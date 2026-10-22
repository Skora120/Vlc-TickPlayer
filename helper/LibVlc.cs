using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace TickPlayer;

/// <summary>
/// Minimal libVLC 3 bindings. The helper loads libvlc.dll from the user's own
/// VLC installation, so anything VLC can play can be thumbnailed, with no
/// FFmpeg download.
/// </summary>
internal static class LibVlc
{
    private const string Dll = "libvlc.dll";

    public enum State
    {
        NothingSpecial = 0,
        Opening = 1,
        Buffering = 2,
        Playing = 3,
        Paused = 4,
        Stopped = 5,
        Ended = 6,
        Error = 7,
    }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate IntPtr LockCb(IntPtr opaque, IntPtr planes);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate void UnlockCb(IntPtr opaque, IntPtr picture, IntPtr planes);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate void DisplayCb(IntPtr opaque, IntPtr picture);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate uint FormatCb(ref IntPtr opaque, IntPtr chroma, ref uint width, ref uint height, IntPtr pitches, IntPtr lines);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate void CleanupCb(IntPtr opaque);

    // libvlc_new keeps pointers into argv for the lifetime of the instance in
    // some code paths, so the strings are never freed.
    private static readonly List<IntPtr> KeepAlive = new();

    /// <summary>Loads libvlc.dll (and libvlccore.dll next to it) from a VLC install folder.</summary>
    public static void Load(string vlcDir)
    {
        var path = Path.Combine(vlcDir, Dll);
        if (!File.Exists(path))
            throw new FileNotFoundException("libvlc.dll not found in the VLC folder", path);
        Native.SetDllDirectory(vlcDir);
        var handle = Native.LoadLibraryEx(path, IntPtr.Zero, Native.LOAD_WITH_ALTERED_SEARCH_PATH);
        if (handle == IntPtr.Zero)
            throw new DllNotFoundException($"Could not load {path} (Win32 error {Marshal.GetLastWin32Error()}). " +
                                           "Is the helper the same bitness as VLC?");
    }

    public static string Version() => FromUtf8(libvlc_get_version());

    public static string LastError() => FromUtf8(libvlc_errmsg());

    public static IntPtr NewInstance(params string[] args)
    {
        var argv = new IntPtr[args.Length];
        for (var i = 0; i < args.Length; i++)
        {
            var bytes = Utf8(args[i]);
            argv[i] = Marshal.AllocHGlobal(bytes.Length);
            Marshal.Copy(bytes, 0, argv[i], bytes.Length);
            KeepAlive.Add(argv[i]);
        }
        return libvlc_new(argv.Length, argv);
    }

    public static IntPtr NewMedia(IntPtr instance, string mrl) => libvlc_media_new_location(instance, Utf8(mrl));

    public static void AddOption(IntPtr media, string option) => libvlc_media_add_option(media, Utf8(option));

    public static byte[] Utf8(string s) => Encoding.UTF8.GetBytes(s + "\0");

    /// <summary>
    /// Display size of the first video track (width and height with the
    /// sample aspect ratio and rotation applied), or false if unknown.
    /// </summary>
    public static bool TryGetVideoDisplaySize(IntPtr media, out double width, out double height)
    {
        width = height = 0;
        var count = libvlc_media_tracks_get(media, out var tracks);
        if (count == 0 || tracks == IntPtr.Zero)
            return false;
        try
        {
            for (var i = 0; i < count; i++)
            {
                // libvlc_media_track_t: i_codec, i_original_fourcc, i_id, i_type,
                // i_profile, i_level (6 x 4 bytes), then the union pointer.
                var track = Marshal.ReadIntPtr(tracks, i * IntPtr.Size);
                if (Marshal.ReadInt32(track, 12) != 1) // libvlc_track_video
                    continue;
                var video = Marshal.ReadIntPtr(track, 24);
                if (video == IntPtr.Zero)
                    continue;
                // libvlc_video_track_t: i_height, i_width, i_sar_num, i_sar_den,
                // i_frame_rate_num, i_frame_rate_den, i_orientation.
                var h = (uint)Marshal.ReadInt32(video, 0);
                var w = (uint)Marshal.ReadInt32(video, 4);
                var sarNum = (uint)Marshal.ReadInt32(video, 8);
                var sarDen = (uint)Marshal.ReadInt32(video, 12);
                var orientation = Marshal.ReadInt32(video, 24);
                if (w == 0 || h == 0)
                    continue;
                width = sarNum > 0 && sarDen > 0 ? w * (double)sarNum / sarDen : w;
                height = h;
                if (orientation >= 4) // transposed orientations swap the axes
                    (width, height) = (height, width);
                return true;
            }
            return false;
        }
        finally
        {
            libvlc_media_tracks_release(tracks, count);
        }
    }

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern uint libvlc_media_tracks_get(IntPtr media, out IntPtr tracks);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void libvlc_media_tracks_release(IntPtr tracks, uint count);

    private static string FromUtf8(IntPtr p)
    {
        if (p == IntPtr.Zero)
            return "";
        var len = 0;
        while (Marshal.ReadByte(p, len) != 0)
            len++;
        var bytes = new byte[len];
        Marshal.Copy(p, bytes, 0, len);
        return Encoding.UTF8.GetString(bytes);
    }

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern IntPtr libvlc_new(int argc, IntPtr[] argv);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_release(IntPtr instance);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern IntPtr libvlc_get_version();

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern IntPtr libvlc_errmsg();

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern IntPtr libvlc_media_new_location(IntPtr instance, byte[] mrl);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void libvlc_media_add_option(IntPtr media, byte[] option);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_media_release(IntPtr media);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr libvlc_media_player_new_from_media(IntPtr media);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_media_player_release(IntPtr player);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern int libvlc_media_player_play(IntPtr player);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_media_player_stop(IntPtr player);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_media_player_set_pause(IntPtr player, int pause);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern long libvlc_media_player_get_length(IntPtr player);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern long libvlc_media_player_get_time(IntPtr player);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_media_player_set_time(IntPtr player, long timeMs);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern State libvlc_media_player_get_state(IntPtr player);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern int libvlc_media_player_is_seekable(IntPtr player);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_media_player_next_frame(IntPtr player);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_video_set_callbacks(IntPtr player, LockCb lockCb, UnlockCb unlockCb, DisplayCb displayCb, IntPtr opaque);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    public static extern void libvlc_video_set_format_callbacks(IntPtr player, FormatCb setup, CleanupCb cleanup);
}
