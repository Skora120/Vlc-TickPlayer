using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Windows.Automation;

namespace TickPlayer;

/// <summary>
/// Finds VLC's seek bar with Windows UI Automation. VLC's Qt interface
/// exposes its sliders to accessibility tools; the seek bar is the widest
/// one in the window (the other is the volume slider). Lookups take tens of
/// milliseconds, so they run on a background thread and are cached per
/// window until the window moves, resizes, or the entry gets old.
/// </summary>
internal sealed class SeekbarLocator : IDisposable
{
    private const long RefreshMs = 2000;

    private readonly object _gate = new();
    private readonly Dictionary<IntPtr, Entry> _entries = new();
    private readonly BlockingCollection<IntPtr> _queue = new();
    private readonly Thread _worker;
    private readonly Stopwatch _clock = Stopwatch.StartNew();

    private sealed class Entry
    {
        public Native.RECT WindowRect;
        public Native.RECT? Seekbar;
        public long CheckedAt;
        public bool Pending;
        public string LastLogged;
    }

    public SeekbarLocator()
    {
        _worker = new Thread(WorkerLoop) { IsBackground = true, Name = "SeekbarLocator" };
        _worker.Start();
    }

    /// <summary>
    /// Returns the cached seek bar rectangle (screen pixels) for a top-level
    /// VLC window, scheduling a refresh when needed. False while unknown.
    /// </summary>
    public bool TryGet(IntPtr hwnd, out Native.RECT seekbar)
    {
        seekbar = default;
        if (!Native.GetWindowRect(hwnd, out var rect))
            return false;

        lock (_gate)
        {
            if (!_entries.TryGetValue(hwnd, out var entry))
                _entries[hwnd] = entry = new Entry { CheckedAt = long.MinValue / 2 };

            var moved = !entry.WindowRect.SameAs(rect);
            if (!entry.Pending && (moved || _clock.ElapsedMilliseconds - entry.CheckedAt > RefreshMs))
            {
                entry.Pending = true;
                _queue.Add(hwnd);
            }
            if (moved || entry.Seekbar == null)
                return false;
            seekbar = entry.Seekbar.Value;
            return true;
        }
    }

    private void WorkerLoop()
    {
        foreach (var hwnd in _queue.GetConsumingEnumerable())
        {
            Native.GetWindowRect(hwnd, out var rectBefore);
            var found = Find(hwnd, out var detail);
            Native.GetWindowRect(hwnd, out var rectAfter);

            lock (_gate)
            {
                if (!_entries.TryGetValue(hwnd, out var entry))
                    continue;
                entry.Pending = false;
                entry.CheckedAt = _clock.ElapsedMilliseconds;
                // If the window moved during the lookup, the result is stale; retry next tick.
                entry.WindowRect = rectBefore.SameAs(rectAfter) ? rectAfter : default;
                entry.Seekbar = found;
                if (detail != entry.LastLogged)
                {
                    Log.Info($"Window 0x{hwnd.ToInt64():x} {rectAfter}: {detail}");
                    entry.LastLogged = detail;
                }
                if (!Native.IsWindow(hwnd))
                    _entries.Remove(hwnd);
            }
        }
    }

    private static Native.RECT? Find(IntPtr hwnd, out string detail)
    {
        try
        {
            var root = AutomationElement.FromHandle(hwnd);
            var sliders = root.FindAll(TreeScope.Descendants,
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Slider));

            Native.RECT? best = null;
            var count = 0;
            foreach (AutomationElement slider in sliders)
            {
                count++;
                var r = slider.Current.BoundingRectangle;
                if (r.IsEmpty || double.IsInfinity(r.Width) || slider.Current.IsOffscreen)
                    continue;
                // A seek bar is long and thin.
                if (r.Width < 100 || r.Width < r.Height * 4)
                    continue;
                if (best == null || r.Width > best.Value.Width)
                {
                    best = new Native.RECT
                    {
                        Left = (int)Math.Round(r.Left),
                        Top = (int)Math.Round(r.Top),
                        Right = (int)Math.Round(r.Right),
                        Bottom = (int)Math.Round(r.Bottom),
                    };
                }
            }
            detail = best == null ? $"no seek bar ({count} sliders)" : $"seek bar {best} ({count} sliders)";
            return best;
        }
        catch (Exception ex) when (ex is ElementNotAvailableException or InvalidOperationException or ArgumentException or System.Runtime.InteropServices.COMException)
        {
            detail = "UI Automation failed: " + ex.Message;
            return null;
        }
    }

    public void Dispose()
    {
        _queue.CompleteAdding();
        _worker.Join(1000);
    }
}
