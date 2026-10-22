using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Threading;

namespace TickPlayer;

/// <summary>
/// Produces seek bar previews for the current video on a background thread.
///
/// The frame for the exact position under the mouse is always made first
/// (see <see cref="RequestExact"/>), so the preview shows what VLC jumps to
/// when that spot is clicked. While it is being made, the nearest slot is
/// shown: the video is split into slots (at most <see cref="MaxSlots"/>, at
/// least <see cref="MinSlotMs"/> apart), and in idle time a coarse-to-fine
/// subset of them is generated so the whole bar has a rough preview quickly.
/// Exact frames also fill their slot. Slots are cached on disk.
/// </summary>
internal sealed class Thumbnailer : IDisposable
{
    public const int MaxSlots = 400;
    private const long MinSlotMs = 2000;
    private const int BackgroundSlots = 120;   // slots generated without hovering
    private const int GrabTimeoutMs = 8000;
    private const int SlowGrabMs = 1500;       // average above this switches to keyframe seeking

    private readonly int _boxWidth;
    private readonly int _boxHeight;
    private readonly object _gate = new();
    private readonly AutoResetEvent _wake = new(false);
    private readonly Thread _worker;
    private readonly ImageCodecInfo _jpegCodec;
    private readonly EncoderParameters _jpegParams;

    // Guarded by _gate.
    private string _requestedUri;
    private int _requestedVersion;
    private Job _job;
    private double _exactWanted = -1;   // position to make an exact frame for, or -1
    private double _exactDone = -1;     // last position attempted
    private byte[] _exactJpeg;
    private double _exactPosition = -1; // position of _exactJpeg
    private bool _disposed;

    private sealed class Job
    {
        public string Uri;
        public long LengthMs;
        public byte[][] Thumbs; // null: not made yet; empty: failed
        public ThumbnailCache Cache;
        public int[] BackgroundOrder;
    }

    public Thumbnailer(int boxWidth, int boxHeight)
    {
        _boxWidth = boxWidth;
        _boxHeight = boxHeight;
        _jpegCodec = ImageCodecInfo.GetImageEncoders().First(c => c.MimeType == "image/jpeg");
        _jpegParams = new EncoderParameters(1) { Param = { [0] = new EncoderParameter(Encoder.Quality, 85L) } };
        _worker = new Thread(WorkerLoop) { IsBackground = true, Name = "Thumbnailer", Priority = ThreadPriority.BelowNormal };
        _worker.Start();
    }

    /// <summary>Incremented whenever a frame is added; lets the UI notice new images.</summary>
    public int Version { get; private set; }

    /// <summary>Why previews are unavailable for the current media, or null.</summary>
    public string Problem { get; private set; }

    public void SetMedia(string uri)
    {
        lock (_gate)
        {
            if (uri == _requestedUri)
                return;
            _requestedUri = uri;
            _requestedVersion++;
            _job = null;
            _exactWanted = _exactDone = _exactPosition = -1;
            _exactJpeg = null;
            Problem = null;
        }
        _wake.Set();
    }

    /// <summary>Length and slot count of the current media, once it has been opened.</summary>
    public bool TryGetMedia(out long lengthMs, out int slotCount)
    {
        lock (_gate)
        {
            lengthMs = _job?.LengthMs ?? 0;
            slotCount = _job?.Thumbs.Length ?? 0;
            return _job != null;
        }
    }

    public static double SlotPosition(int slot, int slotCount) => (slot + 0.5) / slotCount;

    /// <summary>Asks for the frame at exactly this position (0..1) to be made next.</summary>
    public void RequestExact(double position)
    {
        lock (_gate)
        {
            if (position == _exactWanted)
                return;
            _exactWanted = position;
        }
        _wake.Set();
    }

    /// <summary>Stops making exact frames (the mouse left the seek bar).</summary>
    public void CancelExact()
    {
        lock (_gate)
            _exactWanted = -1;
    }

    /// <summary>Position of the latest exact frame, if there is one.</summary>
    public bool TryGetExact(out double position)
    {
        lock (_gate)
        {
            position = _exactPosition;
            return _exactJpeg != null;
        }
    }

    /// <summary>The finished slot nearest to <paramref name="slot"/>, or -1 if none.</summary>
    public int NearestSlot(int slot)
    {
        lock (_gate)
        {
            var thumbs = _job?.Thumbs;
            if (thumbs == null)
                return -1;
            slot = Math.Max(0, Math.Min(slot, thumbs.Length - 1));
            for (var d = 0; d < thumbs.Length; d++)
            {
                if (slot - d >= 0 && thumbs[slot - d] is { Length: > 0 })
                    return slot - d;
                if (slot + d < thumbs.Length && thumbs[slot + d] is { Length: > 0 })
                    return slot + d;
            }
            return -1;
        }
    }

    /// <summary>Decodes a finished slot's image. The caller owns the bitmap.</summary>
    public Bitmap LoadSlot(int slot)
    {
        byte[] jpeg;
        lock (_gate)
            jpeg = _job?.Thumbs is { } t && slot >= 0 && slot < t.Length ? t[slot] : null;
        var bmp = Decode(jpeg);
        if (bmp == null && jpeg is { Length: > 0 })
        {
            // A damaged cache file; drop it so the slot is made again.
            lock (_gate)
            {
                if (_job?.Thumbs is { } t && slot < t.Length && t[slot] == jpeg)
                    t[slot] = null;
            }
        }
        return bmp;
    }

    /// <summary>Decodes the latest exact frame. The caller owns the bitmap.</summary>
    public Bitmap LoadExact()
    {
        byte[] jpeg;
        lock (_gate)
            jpeg = _exactJpeg;
        return Decode(jpeg);
    }

    private static Bitmap Decode(byte[] jpeg)
    {
        if (jpeg is not { Length: > 0 })
            return null;
        try
        {
            using var ms = new MemoryStream(jpeg);
            using var img = Image.FromStream(ms);
            return new Bitmap(img);
        }
        catch (ArgumentException)
        {
            return null;
        }
    }

    private void WorkerLoop()
    {
        IntPtr instance;
        try
        {
            instance = FrameGrabber.CreateInstance();
            if (instance == IntPtr.Zero)
                throw new InvalidOperationException(LibVlc.LastError());
        }
        catch (Exception ex)
        {
            Log.Error("libVLC could not start", ex);
            Problem = "libVLC could not start";
            return;
        }

        FrameGrabber grabber = null;
        var openedVersion = -1;
        var grabTimes = new List<long>();
        var fastSeek = false;

        while (true)
        {
            string uri;
            int version, slot = -1;
            double exact = -1;
            Job job;
            lock (_gate)
            {
                if (_disposed)
                    break;
                uri = _requestedUri;
                version = _requestedVersion;
                job = _job;
                if (job != null)
                {
                    if (_exactWanted >= 0 && _exactWanted != _exactDone)
                        exact = _exactWanted;
                    else
                        slot = NextBackgroundSlot(job);
                }
            }

            if (version != openedVersion)
            {
                grabber?.Dispose();
                grabber = null;
                openedVersion = version;
                grabTimes.Clear();
                fastSeek = false;
                if (!string.IsNullOrEmpty(uri))
                    grabber = OpenMedia(instance, uri, version, fastSeek);
                continue;
            }

            if (grabber == null || job == null || (exact < 0 && slot < 0))
            {
                _wake.WaitOne(1000);
                continue;
            }

            var position = exact >= 0 ? exact : SlotPosition(slot, job.Thumbs.Length);
            var sw = Stopwatch.StartNew();
            using var bmp = grabber.Grab(position, GrabTimeoutMs);
            grabTimes.Add(sw.ElapsedMilliseconds);
            var jpeg = bmp == null ? null : Encode(bmp);

            var cacheSlot = -1;
            lock (_gate)
            {
                if (_job != job)
                    continue;
                if (exact >= 0)
                {
                    _exactDone = exact;
                    if (jpeg != null)
                    {
                        _exactJpeg = jpeg;
                        _exactPosition = exact;
                        Version++;
                        // Use it as its slot's preview too, if that slot is still empty.
                        var s = Math.Min(job.Thumbs.Length - 1, (int)(exact * job.Thumbs.Length));
                        if (job.Thumbs[s] is not { Length: > 0 })
                            job.Thumbs[cacheSlot = s] = jpeg;
                    }
                }
                else
                {
                    // An empty array marks a failed slot so it is not retried forever.
                    job.Thumbs[slot] = jpeg ?? Array.Empty<byte>();
                    if (jpeg != null)
                    {
                        Version++;
                        cacheSlot = slot;
                    }
                }
            }
            if (cacheSlot >= 0)
                job.Cache?.Save(cacheSlot, jpeg);
            if (jpeg == null)
                Log.Warn($"No frame at position {position:0.0000}");

            if (!fastSeek && grabTimes.Count == 8 && grabTimes.Average() > SlowGrabMs)
            {
                Log.Info($"Exact seeking is slow ({grabTimes.Average():0} ms per frame); switching to keyframe seeking");
                fastSeek = true;
                grabber.Dispose();
                grabber = OpenMedia(instance, uri, version, fastSeek);
            }
        }

        grabber?.Dispose();
        LibVlc.libvlc_release(instance);
    }

    private FrameGrabber OpenMedia(IntPtr instance, string uri, int version, bool fastSeek)
    {
        if (!uri.StartsWith("file:", StringComparison.OrdinalIgnoreCase))
        {
            Problem = "previews are only available for local files";
            Log.Info($"Not a local file, previews disabled: {uri}");
            return null;
        }

        var sw = Stopwatch.StartNew();
        FrameGrabber grabber = null;
        try
        {
            grabber = new FrameGrabber(instance, uri, _boxWidth, _boxHeight, fastSeek);
            if (!grabber.Open(15000, out var error))
            {
                Problem = error;
                Log.Warn($"Cannot preview {uri}: {error}");
                grabber.Dispose();
                return null;
            }
        }
        catch (Exception ex)
        {
            Problem = ex.Message;
            Log.Error($"Cannot open {uri}", ex);
            grabber?.Dispose();
            return null;
        }

        var length = grabber.LengthMs;
        var count = (int)Math.Max(1, Math.Min(MaxSlots, length / MinSlotMs));
        var job = new Job
        {
            Uri = uri,
            LengthMs = length,
            Thumbs = new byte[count][],
            Cache = ThumbnailCache.Open(uri, length, count, _boxWidth, _boxHeight),
            BackgroundOrder = CoarseToFine(count).Take(BackgroundSlots).ToArray(),
        };
        var cached = 0;
        if (job.Cache != null)
        {
            for (var i = 0; i < count; i++)
            {
                job.Thumbs[i] = job.Cache.Load(i);
                if (job.Thumbs[i] != null)
                    cached++;
            }
        }
        Log.Info($"Opened in {sw.ElapsedMilliseconds} ms: length {length} ms, {count} slots, {cached} cached, {grabber.FormatInfo}" +
                 (fastSeek ? ", keyframe seeking" : ""));

        lock (_gate)
        {
            if (version != _requestedVersion)
            {
                grabber.Dispose();
                return null;
            }
            _job = job;
            Version++;
        }
        return grabber;
    }

    /// <summary>The next background slot still to make, or -1. Call under _gate.</summary>
    private static int NextBackgroundSlot(Job job)
    {
        foreach (var s in job.BackgroundOrder)
        {
            if (job.Thumbs[s] == null)
                return s;
        }
        return -1;
    }

    /// <summary>Slot indices ordered so that early entries spread evenly over the whole video.</summary>
    private static IEnumerable<int> CoarseToFine(int count)
    {
        var seen = new bool[count];
        for (var k = 0; k < count * 8; k++)
        {
            // Van der Corput sequence: 0, 1/2, 1/4, 3/4, 1/8, ...
            double v = 0, denom = 1;
            for (var n = k; n > 0; n >>= 1)
            {
                denom *= 2;
                v += (n & 1) / denom;
            }
            var slot = (int)(v * count);
            if (!seen[slot])
            {
                seen[slot] = true;
                yield return slot;
            }
        }
        for (var i = 0; i < count; i++)
        {
            if (!seen[i])
                yield return i;
        }
    }

    private byte[] Encode(Bitmap bmp)
    {
        using var ms = new MemoryStream();
        bmp.Save(ms, _jpegCodec, _jpegParams);
        return ms.ToArray();
    }

    public void Dispose()
    {
        lock (_gate)
            _disposed = true;
        _wake.Set();
        _worker.Join(3000);
    }
}
