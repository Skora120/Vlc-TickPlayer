using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;

namespace TickPlayer;

/// <summary>The VLC process this helper serves.</summary>
internal sealed class VlcTarget : IDisposable
{
    private IntPtr _handle;

    private VlcTarget(uint pid, IntPtr handle, string exePath, bool is32Bit)
    {
        ProcessId = pid;
        _handle = handle;
        ExePath = exePath;
        Is32Bit = is32Bit;
    }

    public uint ProcessId { get; }

    public string ExePath { get; }

    public string InstallDir => Path.GetDirectoryName(ExePath);

    public bool Is32Bit { get; }

    public bool HasExited => Native.WaitForSingleObject(_handle, 0) == Native.WAIT_OBJECT_0;

    /// <summary>
    /// Picks the VLC instance that started this helper. The extension cannot
    /// pass VLC's process id, so: a single running VLC wins; with several,
    /// the one whose window title shows the current media, then the one in
    /// the foreground, then the newest.
    /// </summary>
    public static VlcTarget Find(params string[] titleHints)
    {
        var candidates = new List<(uint Pid, string Title)>();
        Native.EnumWindows((hwnd, _) =>
        {
            if (Native.IsWindowVisible(hwnd) && Native.TitleOf(hwnd).EndsWith("VLC media player", StringComparison.Ordinal))
                candidates.Add((Native.ProcessIdOf(hwnd), Native.TitleOf(hwnd)));
            return true;
        }, IntPtr.Zero);

        var pids = Process.GetProcessesByName("vlc").Select(p => (uint)p.Id).ToList();
        if (pids.Count == 0)
            return null;

        uint chosen;
        if (pids.Count == 1)
        {
            chosen = pids[0];
        }
        else
        {
            var hints = titleHints.Where(h => !string.IsNullOrWhiteSpace(h)).ToList();
            var byTitle = candidates.FirstOrDefault(c => pids.Contains(c.Pid) && hints.Any(h => c.Title.StartsWith(h + " - ", StringComparison.Ordinal)));
            var foreground = Native.ProcessIdOf(Native.GetForegroundWindow());
            if (byTitle.Pid != 0)
                chosen = byTitle.Pid;
            else if (pids.Contains(foreground))
                chosen = foreground;
            else
                chosen = pids.OrderByDescending(StartTime).First();
            Log.Info($"{pids.Count} VLC processes running; chose {chosen}");
        }
        return ForProcess(chosen);
    }

    /// <summary>A specific VLC process, or null if it can't be opened.</summary>
    public static VlcTarget ForProcess(uint chosen)
    {
        var handle = Native.OpenProcess(Native.PROCESS_QUERY_LIMITED_INFORMATION | Native.SYNCHRONIZE, false, chosen);
        if (handle == IntPtr.Zero)
            return null;
        var sb = new StringBuilder(1024);
        var size = sb.Capacity;
        if (!Native.QueryFullProcessImageName(handle, 0, sb, ref size))
        {
            Native.CloseHandle(handle);
            return null;
        }
        Native.IsWow64Process(handle, out var wow64);
        var is32Bit = wow64 || !Environment.Is64BitOperatingSystem;
        return new VlcTarget(chosen, handle, sb.ToString(), is32Bit);
    }

    private static DateTime StartTime(uint pid)
    {
        try
        {
            return Process.GetProcessById((int)pid).StartTime;
        }
        catch (Exception)
        {
            return DateTime.MinValue;
        }
    }

    public bool Owns(IntPtr hwnd) => hwnd != IntPtr.Zero && Native.ProcessIdOf(hwnd) == ProcessId;

    /// <summary>VLC's visible tooltip windows (the time tooltip over the seek bar, among others).</summary>
    public IEnumerable<Native.RECT> VisibleTooltips()
    {
        var result = new List<Native.RECT>();
        Native.EnumWindows((hwnd, _) =>
        {
            if (Native.IsWindowVisible(hwnd) && Owns(hwnd) &&
                Native.ClassNameOf(hwnd).IndexOf("ToolTip", StringComparison.OrdinalIgnoreCase) >= 0 &&
                Native.GetWindowRect(hwnd, out var r))
            {
                result.Add(r);
            }
            return true;
        }, IntPtr.Zero);
        return result;
    }

    public void Dispose()
    {
        if (_handle != IntPtr.Zero)
        {
            Native.CloseHandle(_handle);
            _handle = IntPtr.Zero;
        }
    }
}
