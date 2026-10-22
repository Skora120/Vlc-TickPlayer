using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Threading;

namespace TickPlayer;

/// <summary>
/// A hidden libVLC player that decodes into memory. It is opened paused,
/// and each <see cref="Grab"/> seeks to a time and captures one frame.
/// Not thread-safe: use it from a single worker thread.
/// </summary>
internal sealed class FrameGrabber : IDisposable
{
    private readonly int _maxWidth;
    private readonly int _maxHeight;
    private readonly object _bufferGate = new();
    private readonly AutoResetEvent _frameShown = new(false);

    // Delegates handed to native code must stay referenced.
    private readonly LibVlc.LockCb _lockCb;
    private readonly LibVlc.UnlockCb _unlockCb;
    private readonly LibVlc.DisplayCb _displayCb;
    private readonly LibVlc.FormatCb _formatCb;
    private readonly LibVlc.CleanupCb _cleanupCb;

    private IntPtr _media;
    private IntPtr _player;
    private IntPtr _buffer;
    private int _width;
    private int _height;
    private int _frameCount;

    public long LengthMs { get; private set; }

    /// <summary>Source and output frame sizes, for the log.</summary>
    public string FormatInfo { get; private set; } = "";

    /// <summary>Creates the shared libVLC instance used by all grabbers.</summary>
    public static IntPtr CreateInstance()
    {
        return LibVlc.NewInstance(
            "--ignore-config",          // don't inherit the user's interfaces (e.g. http) or filters
            "--no-plugins-scan",        // use VLC's plugin cache for a fast start
            "--intf=dummy",
            "--no-audio",
            "--no-video-title-show",
            "--no-osd",
            "--no-spu",
            "--no-sub-autodetect-file",
            "--no-stats",
            "--no-media-library",
            "--no-lua",
            "--avcodec-hw=none",        // software decoding: reliable with memory output
            "--quiet");
    }

    /// <param name="fastSeek">
    /// Seek to keyframes instead of exact times. Faster on files with long
    /// keyframe intervals, but VLC's MP4 demuxer can land on the wrong
    /// keyframe, so exact seeking is the default.
    /// </param>
    public FrameGrabber(IntPtr instance, string mrl, int maxWidth, int maxHeight, bool fastSeek = false)
    {
        _maxWidth = maxWidth;
        _maxHeight = maxHeight;
        _lockCb = OnLock;
        _unlockCb = OnUnlock;
        _displayCb = OnDisplay;
        _formatCb = OnFormat;
        _cleanupCb = OnCleanup;

        _media = LibVlc.NewMedia(instance, mrl);
        if (_media == IntPtr.Zero)
            throw new InvalidOperationException("libVLC could not create media: " + LibVlc.LastError());
        LibVlc.AddOption(_media, ":no-audio");
        LibVlc.AddOption(_media, fastSeek ? ":input-fast-seek" : ":no-input-fast-seek");
        LibVlc.AddOption(_media, ":input-repeat=0");

        _player = LibVlc.libvlc_media_player_new_from_media(_media);
        if (_player == IntPtr.Zero)
            throw new InvalidOperationException("libVLC could not create a player: " + LibVlc.LastError());
        LibVlc.libvlc_video_set_format_callbacks(_player, _formatCb, _cleanupCb);
        LibVlc.libvlc_video_set_callbacks(_player, _lockCb, _unlockCb, _displayCb, IntPtr.Zero);
    }

    /// <summary>Starts decoding, waits for the first frame and pauses.</summary>
    public bool Open(int timeoutMs, out string error)
    {
        error = null;
        var before = Volatile.Read(ref _frameCount);
        if (LibVlc.libvlc_media_player_play(_player) != 0)
        {
            error = "play failed: " + LibVlc.LastError();
            return false;
        }

        var sw = Stopwatch.StartNew();
        while (Volatile.Read(ref _frameCount) == before)
        {
            var state = LibVlc.libvlc_media_player_get_state(_player);
            if (state is LibVlc.State.Error or LibVlc.State.Ended or LibVlc.State.Stopped)
            {
                error = $"player stopped before the first frame (state {state})";
                return false;
            }
            if (sw.ElapsedMilliseconds > timeoutMs)
            {
                error = "no video frame within the timeout (audio-only file or unsupported video?)";
                return false;
            }
            _frameShown.WaitOne(50);
        }

        LibVlc.libvlc_media_player_set_pause(_player, 1);
        while (LibVlc.libvlc_media_player_get_state(_player) != LibVlc.State.Paused && sw.ElapsedMilliseconds < timeoutMs)
            Thread.Sleep(10);

        while ((LengthMs = LibVlc.libvlc_media_player_get_length(_player)) <= 0 && sw.ElapsedMilliseconds < timeoutMs)
            Thread.Sleep(20);

        if (LengthMs <= 0)
        {
            error = "media length is unknown";
            return false;
        }
        if (LibVlc.libvlc_media_player_is_seekable(_player) == 0)
        {
            error = "media is not seekable";
            return false;
        }
        return true;
    }

    /// <summary>Seeks to <paramref name="timeMs"/> and returns the decoded frame, or null.</summary>
    public Bitmap Grab(long timeMs, int timeoutMs)
    {
        var state = LibVlc.libvlc_media_player_get_state(_player);
        if (state is LibVlc.State.Ended or LibVlc.State.Stopped or LibVlc.State.Error)
        {
            // Seeking past the last keyframe can end playback; restart it.
            if (!Open(timeoutMs, out _))
                return null;
        }

        // Seeking into the last few seconds can leave the demuxer at end of
        // file, after which later seeks are ignored. Stay clear of the end.
        timeMs = Math.Max(0, Math.Min(timeMs, LengthMs - EndMarginMs));

        // After a seek VLC first shows the old picture again, then the new one
        // once it is decoded. So wait for the picture to change; if it stays
        // the same for a while, the new frame simply looks identical.
        var before = Settle();
        var oldHash = HashFrame();
        LibVlc.libvlc_media_player_set_time(_player, timeMs);

        var sw = Stopwatch.StartNew();
        var seen = before;
        var stepped = false;
        long firstFrameAt = -1;
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            _frameShown.WaitOne(5);
            var now = Volatile.Read(ref _frameCount);
            if (now != seen)
            {
                seen = now;
                if (firstFrameAt < 0)
                    firstFrameAt = sw.ElapsedMilliseconds;
                if (HashFrame() != oldHash)
                    return CopyFrame();
            }
            if (firstFrameAt >= 0 && sw.ElapsedMilliseconds - firstFrameAt > SameFrameWaitMs)
                return CopyFrame();
            if (firstFrameAt < 0 && !stepped && sw.ElapsedMilliseconds > 400)
            {
                // Nothing rendered after the seek: step one frame to force a decode.
                LibVlc.libvlc_media_player_next_frame(_player);
                stepped = true;
            }
        }
        return firstFrameAt >= 0 ? CopyFrame() : null;
    }

    /// <summary>How long to wait for a different picture before accepting an identical one.</summary>
    private const int SameFrameWaitMs = 250;

    private long EndMarginMs => Math.Min(5000, LengthMs / 20);

    /// <summary>Cheap fingerprint of the current picture (a grid of sampled pixels).</summary>
    private long HashFrame()
    {
        lock (_bufferGate)
        {
            if (_buffer == IntPtr.Zero)
                return 0;
            long hash = 17;
            for (var gy = 0; gy < 12; gy++)
            {
                var y = (_height - 1) * gy / 11;
                for (var gx = 0; gx < 16; gx++)
                {
                    var x = (_width - 1) * gx / 15;
                    hash = hash * 31 + Marshal.ReadInt32(_buffer, (y * _width + x) * 4);
                }
            }
            return hash;
        }
    }

    /// <summary>Waits until no frame has been shown for a moment; returns the frame count.</summary>
    private int Settle()
    {
        const int quietMs = 40, maxMs = 250;
        var sw = Stopwatch.StartNew();
        var count = Volatile.Read(ref _frameCount);
        var quietSince = sw.ElapsedMilliseconds;
        while (sw.ElapsedMilliseconds - quietSince < quietMs && sw.ElapsedMilliseconds < maxMs)
        {
            _frameShown.WaitOne(10);
            var now = Volatile.Read(ref _frameCount);
            if (now != count)
            {
                count = now;
                quietSince = sw.ElapsedMilliseconds;
            }
        }
        return count;
    }

    private Bitmap CopyFrame()
    {
        lock (_bufferGate)
        {
            if (_buffer == IntPtr.Zero || _width <= 0 || _height <= 0)
                return null;
            var bmp = new Bitmap(_width, _height, PixelFormat.Format32bppRgb);
            var data = bmp.LockBits(new Rectangle(0, 0, _width, _height), ImageLockMode.WriteOnly, PixelFormat.Format32bppRgb);
            try
            {
                var rowBytes = _width * 4;
                for (var y = 0; y < _height; y++)
                    Native.CopyMemory(data.Scan0 + y * data.Stride, _buffer + y * rowBytes, (IntPtr)rowBytes);
            }
            finally
            {
                bmp.UnlockBits(data);
            }
            return bmp;
        }
    }

    private uint OnFormat(ref IntPtr opaque, IntPtr chroma, ref uint width, ref uint height, IntPtr pitches, IntPtr lines)
    {
        // Scale the source to fit the preview box, keeping its aspect ratio.
        // The sizes passed in include decoder padding (e.g. 1920x1090 for
        // 1080p), so prefer the track's display size when it is known.
        double srcW = Math.Max(1, width), srcH = Math.Max(1, height);
        if (LibVlc.TryGetVideoDisplaySize(_media, out var trackW, out var trackH))
        {
            srcW = trackW;
            srcH = trackH;
        }
        var scale = Math.Min(_maxWidth / srcW, _maxHeight / srcH);
        var w = Math.Max(16, (int)Math.Round(srcW * scale) & ~1);
        var h = Math.Max(16, (int)Math.Round(srcH * scale) & ~1);

        FormatInfo = $"decoded {width}x{height}, display {srcW:0}x{srcH:0}, thumbnail {w}x{h}";
        Marshal.Copy(new[] { (byte)'R', (byte)'V', (byte)'3', (byte)'2' }, 0, chroma, 4);
        width = (uint)w;
        height = (uint)h;
        Marshal.WriteInt32(pitches, w * 4);
        Marshal.WriteInt32(lines, h);

        lock (_bufferGate)
        {
            FreeBuffer();
            _buffer = Marshal.AllocHGlobal(w * h * 4);
            _width = w;
            _height = h;
        }
        return 1;
    }

    private void OnCleanup(IntPtr opaque)
    {
        lock (_bufferGate)
            FreeBuffer();
    }

    // VLC may lock and unlock the picture on different threads, and keeps the
    // last picture locked while paused, so no lock is taken here. Frames are
    // only copied while the player is paused, when nothing writes the buffer.
    private IntPtr OnLock(IntPtr opaque, IntPtr planes)
    {
        Marshal.WriteIntPtr(planes, _buffer);
        return IntPtr.Zero;
    }

    private void OnUnlock(IntPtr opaque, IntPtr picture, IntPtr planes)
    {
    }

    private void OnDisplay(IntPtr opaque, IntPtr picture)
    {
        Interlocked.Increment(ref _frameCount);
        _frameShown.Set();
    }

    private void FreeBuffer()
    {
        if (_buffer != IntPtr.Zero)
        {
            Marshal.FreeHGlobal(_buffer);
            _buffer = IntPtr.Zero;
        }
        _width = _height = 0;
    }

    public void Dispose()
    {
        if (_player != IntPtr.Zero)
        {
            LibVlc.libvlc_media_player_stop(_player);
            LibVlc.libvlc_media_player_release(_player);
            _player = IntPtr.Zero;
        }
        if (_media != IntPtr.Zero)
        {
            LibVlc.libvlc_media_release(_media);
            _media = IntPtr.Zero;
        }
        lock (_bufferGate)
            FreeBuffer();
        _frameShown.Dispose();
    }
}
