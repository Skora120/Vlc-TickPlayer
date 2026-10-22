using System;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;

namespace TickPlayer;

/// <summary>
/// Main loop: about 60 times a second, checks whether the mouse is over the
/// VLC seek bar and shows or hides the preview.
/// </summary>
internal sealed class HelperApp : ApplicationContext
{
    // Preview size at 100% display scaling; scaled per monitor.
    private const int BoxWidth = 256;
    private const int BoxHeight = 144;
    private const int TickMs = 15;
    private const int SessionPollTicks = 16;

    private readonly VlcTarget _vlc;
    private readonly SessionFile _session;
    private readonly SeekbarLocator _locator = new();
    private readonly Thumbnailer _thumbs;
    private readonly PreviewWindow _preview = new();
    private readonly Timer _timer;

    private int _ticks;
    private string _uri;
    private string _shownKey; // which frame the preview shows: "slot N" or "exact P"
    private Size _imageSize;
    private int _tooltipClearance;

    public HelperApp(VlcTarget vlc, SessionFile session, SessionFile.State initial)
    {
        _vlc = vlc;
        _session = session;

        // Generate thumbnails sharp enough for the monitor VLC is on.
        Native.GetCursorPos(out var pt);
        var scale = Math.Max(1.0, Math.Min(2.0, Native.ScaleAt(pt)));
        _thumbs = new Thumbnailer((int)(BoxWidth * scale), (int)(BoxHeight * scale));

        Apply(initial);
        _timer = new Timer { Interval = TickMs };
        _timer.Tick += (_, _) => Tick();
        _timer.Start();
    }

    private void Tick()
    {
        try
        {
            if (_vlc.HasExited)
            {
                Log.Info("VLC exited");
                ExitThread();
                return;
            }

            if (++_ticks % SessionPollTicks == 0)
            {
                var state = _session.Read();
                if (state != null && !state.Active)
                {
                    Log.Info("Turned off in VLC");
                    ExitThread();
                    return;
                }
                if (state != null)
                    Apply(state);
            }

            UpdatePreview();
        }
        catch (Exception ex)
        {
            Log.Error("Update failed", ex);
            _preview.HidePreview();
        }
    }

    private void Apply(SessionFile.State state)
    {
        if (state.Uri == _uri)
            return;
        _uri = state.Uri;
        Log.Info("Media: " + (string.IsNullOrEmpty(_uri) ? "(none)" : _uri));
        _thumbs.SetMedia(_uri);
        _shownKey = null;
    }

    private void UpdatePreview()
    {
        Native.GetCursorPos(out var pt);
        var root = Native.GetAncestor(Native.WindowFromPoint(pt), Native.GA_ROOT);
        if (string.IsNullOrEmpty(_uri) || !_vlc.Owns(root) || Native.IsIconic(root) ||
            !_locator.TryGet(root, out var bar) ||
            pt.X < bar.Left || pt.X >= bar.Right || pt.Y < bar.Top - 2 || pt.Y > bar.Bottom + 2)
        {
            if (_preview.IsShown)
                _thumbs.CancelExact();
            _preview.HidePreview();
            return;
        }

        if (!_thumbs.TryGetMedia(out _, out var slotCount))
        {
            if (_thumbs.Problem != null)
            {
                _preview.HidePreview();
                return;
            }
            ShowLoading(pt, bar);
            return;
        }

        // Ask for the exact frame VLC would jump to, and meanwhile show
        // whichever finished frame is closest: the last exact one or a slot.
        var position = ClickPosition(pt.X, bar);
        _thumbs.RequestExact(position);
        var slot = _thumbs.NearestSlot(Math.Min(slotCount - 1, (int)(position * slotCount)));
        string key = null;
        if (slot >= 0)
            key = "slot " + slot;
        if (_thumbs.TryGetExact(out var exactPosition) &&
            (slot < 0 || Math.Abs(exactPosition - position) <= Math.Abs(Thumbnailer.SlotPosition(slot, slotCount) - position)))
        {
            key = "exact " + exactPosition;
        }

        if (key == null)
        {
            ShowLoading(pt, bar);
            return;
        }
        if (key != _shownKey)
        {
            var bmp = key.StartsWith("exact") ? _thumbs.LoadExact() : _thumbs.LoadSlot(slot);
            if (bmp != null)
            {
                _shownKey = key;
                _imageSize = bmp.Size;
                _preview.SetImage(bmp);
            }
        }
        if (_shownKey == null)
        {
            ShowLoading(pt, bar);
            return;
        }

        var scale = Native.ScaleAt(pt);
        var fit = Math.Min(BoxWidth * scale / _imageSize.Width, BoxHeight * scale / _imageSize.Height);
        Place(pt, bar, scale, (int)Math.Round(_imageSize.Width * fit), (int)Math.Round(_imageSize.Height * fit));
    }

    /// <summary>
    /// The position (0..1) VLC seeks to when the seek bar is clicked at
    /// screen x, as computed by SeekSlider::getValueFromXPos: the slider runs
    /// from 0 to 10000 and the handle length is subtracted. VLC asks the style
    /// for that length without passing the widget, so it gets the native
    /// Windows metric: 11 px at 100% scaling, where the bar is 18 px tall.
    /// </summary>
    private static double ClickPosition(int x, Native.RECT bar)
    {
        const int sliderMax = 10000;
        var handle = (int)Math.Round(11.0 * bar.Height / 18.0);
        var pos = x - bar.Left - handle / 2;
        var span = bar.Width - handle;
        if (span <= 0 || pos <= 0)
            return 0;
        if (pos >= span)
            return 1;
        // QStyle::sliderValueFromPosition rounds to the nearest slider step.
        var value = (2L * sliderMax * pos + span) / (2L * span);
        return value / (double)sliderMax;
    }

    private void ShowLoading(Native.POINT pt, Native.RECT bar)
    {
        var scale = Native.ScaleAt(pt);
        _shownKey = null;
        _preview.SetLoading();
        Place(pt, bar, scale, (int)(BoxWidth * scale), (int)(BoxWidth * scale * 9 / 16));
    }

    /// <summary>Positions a w x h preview centred above the cursor, clear of VLC's time tooltip.</summary>
    private void Place(Native.POINT pt, Native.RECT bar, double scale, int w, int h)
    {
        // VLC shows its own time tooltip just above the bar; sit above it.
        var tooltip = _vlc.VisibleTooltips().FirstOrDefault(t =>
            t.Bottom <= bar.Top + 6 * scale && t.Bottom >= bar.Top - 70 * scale &&
            t.Left - 20 <= pt.X && pt.X <= t.Right + 20);
        if (tooltip.Height > 0 && bar.Top - tooltip.Top != _tooltipClearance)
        {
            _tooltipClearance = bar.Top - tooltip.Top;
            Log.Info($"VLC time tooltip {tooltip}, {_tooltipClearance} px above the bar");
        }
        var clearance = (_tooltipClearance > 0 ? _tooltipClearance : (int)(56 * scale)) + (int)(4 * scale);

        var monitor = Native.MonitorBoundsAt(pt);
        var margin = (int)(4 * scale);
        var x = Math.Max(monitor.Left + margin, Math.Min(pt.X - w / 2, monitor.Right - margin - w));
        var y = bar.Top - clearance - h;
        if (y < monitor.Top + margin)
            y = bar.Bottom + clearance; // no room above: show below the bar

        _preview.ShowAt(new Rectangle(x, y, w, h));
    }

    protected override void ExitThreadCore()
    {
        _timer.Stop();
        _preview.HidePreview();
        _locator.Dispose();
        _thumbs.Dispose();
        _preview.Dispose();
        base.ExitThreadCore();
    }
}
