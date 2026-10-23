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
/// Produces seekbar thumbnails for the current video on a background thread.
/// The video is split into slots (at most <see cref="MaxSlots"/>, at least
/// <see cref="MinSlotMs"/> apart). The slot under the mouse is generated first;
/// in idle time a coarse-to-fine subset is generated so most of the bar is
/// covered quickly. Everything is cached on disk.
/// </summary>
internal sealed class Thumbnailer : IDisposable
{
    public const int MaxSlots = 400;
    private const long MinSlotMs = 2000;
    private const int BackgroundSlots = 120;   // slots generated without hovering
    private const int GrabTimeoutMs = 8000;
    private const int SlowGrabMs = 700;        // average above this switches to keyframe seeking

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
    private int _prioritySlot = -1;
    private bool _disposed;

    private sealed class Job
    {
        public string Uri;
        public long LengthMs;
        public byte[][] Thumbs;
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

    /// <summary>Incremented whenever a thumbnail is added; lets the UI notice new images.</summary>
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
            _prioritySlot = -1;
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

    /// <summary>
    /// Returns the thumbnail for <paramref name="slot"/> if it exists, otherwise
    /// the nearest one, and asks for the exact slot to be generated next.
    /// Null if nothing is ready. The caller owns the returned bitmap.
    /// </summary>
    public Bitmap GetNearest(int slot, out int shownSlot)
    {
        byte[] jpeg = null;
        shownSlot = -1;
        lock (_gate)
        {
            var thumbs = _job?.Thumbs;
            if (thumbs == null)
                return null;
            slot = Math.Max(0, Math.Min(slot, thumbs.Length - 1));
            if (thumbs[slot] == null && _prioritySlot != slot)
            {
                _prioritySlot = slot;
                _wake.Set();
            }
            for (var d = 0; d < thumbs.Length && jpeg == null; d++)
            {
                if (slot - d >= 0 && thumbs[slot - d] is { Length: > 0 })
                    (jpeg, shownSlot) = (thumbs[slot - d], slot - d);
                else if (slot + d < thumbs.Length && thumbs[slot + d] is { Length: > 0 })
                    (jpeg, shownSlot) = (thumbs[slot + d], slot + d);
            }
        }
        if (jpeg == null)
            return null;
        try
        {
            using var ms = new MemoryStream(jpeg);
            using var img = Image.FromStream(ms);
            return new Bitmap(img);
        }
        catch (ArgumentException)
        {
            // A damaged cache file; drop it so the slot is generated again.
            lock (_gate)
            {
                if (_job?.Thumbs is { } thumbs && shownSlot < thumbs.Length && thumbs[shownSlot] == jpeg)
                    thumbs[shownSlot] = null;
            }
            shownSlot = -1;
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
            int version, slot;
            Job job;
            lock (_gate)
            {
                if (_disposed)
                    break;
                uri = _requestedUri;
                version = _requestedVersion;
                job = _job;
                slot = job == null ? -1 : NextSlot(job);
                if (slot == _prioritySlot)
                    _prioritySlot = -1;
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

            if (grabber == null || job == null || slot < 0)
            {
                _wake.WaitOne(1000);
                continue;
            }

            var sw = Stopwatch.StartNew();
            using var bmp = grabber.Grab(SlotTimeMs(job, slot), GrabTimeoutMs);
            grabTimes.Add(sw.ElapsedMilliseconds);
            var jpeg = bmp == null ? null : Encode(bmp);

            lock (_gate)
            {
                if (_job != job)
                    continue;
                // An empty array marks a failed slot so it is not retried forever.
                job.Thumbs[slot] = jpeg ?? Array.Empty<byte>();
                if (jpeg != null)
                    Version++;
            }
            if (jpeg != null)
                job.Cache?.Save(slot, jpeg);
            else
                Log.Warn($"No frame for slot {slot} at {SlotTimeMs(job, slot)} ms");

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

    /// <summary>The hovered slot if it is missing, else the next background slot. Call under _gate.</summary>
    private int NextSlot(Job job)
    {
        if (_prioritySlot >= 0 && _prioritySlot < job.Thumbs.Length && job.Thumbs[_prioritySlot] == null)
            return _prioritySlot;
        foreach (var s in job.BackgroundOrder)
        {
            if (job.Thumbs[s] == null)
                return s;
        }
        return -1;
    }

    public static long SlotTimeMs(long lengthMs, int slotCount, int slot) =>
        (long)((slot + 0.5) * lengthMs / slotCount);

    private static long SlotTimeMs(Job job, int slot) => SlotTimeMs(job.LengthMs, job.Thumbs.Length, slot);

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
