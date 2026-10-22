using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace TickPlayer;

/// <summary>
/// The floating thumbnail. A borderless, topmost tool window that never takes
/// focus and lets the mouse pass through, so VLC keeps behaving normally.
/// </summary>
internal sealed class PreviewWindow : Form
{
    private Bitmap _image;
    private bool _loading;
    private bool _shown;
    private Rectangle _bounds;

    public PreviewWindow()
    {
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.Manual;
        BackColor = Color.FromArgb(24, 24, 24);
        ForeColor = Color.FromArgb(200, 200, 200);
        DoubleBuffered = true;
        Text = "TickPlayer preview";
        _ = Handle; // create the window now, hidden
    }

    public bool IsShown => _shown;

    protected override bool ShowWithoutActivation => true;

    protected override CreateParams CreateParams
    {
        get
        {
            var cp = base.CreateParams;
            cp.ExStyle |= Native.WS_EX_TOOLWINDOW | Native.WS_EX_NOACTIVATE | Native.WS_EX_TOPMOST;
            return cp;
        }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        // Small rounded corners on Windows 11 (ignored on Windows 10).
        var corner = Native.DWMWCP_ROUNDSMALL;
        Native.DwmSetWindowAttribute(Handle, Native.DWMWA_WINDOW_CORNER_PREFERENCE, ref corner, Marshal.SizeOf(typeof(int)));
    }

    protected override void WndProc(ref Message m)
    {
        switch (m.Msg)
        {
            case Native.WM_NCHITTEST:
                m.Result = (IntPtr)Native.HTTRANSPARENT;
                return;
            case Native.WM_MOUSEACTIVATE:
                m.Result = (IntPtr)Native.MA_NOACTIVATE;
                return;
            case Native.WM_DPICHANGED:
                // Bounds are always set explicitly in physical pixels.
                m.Result = IntPtr.Zero;
                return;
        }
        base.WndProc(ref m);
    }

    /// <summary>Displays <paramref name="image"/>, taking ownership of it.</summary>
    public void SetImage(Bitmap image)
    {
        if (ReferenceEquals(image, _image))
            return;
        _image?.Dispose();
        _image = image;
        _loading = false;
        Invalidate();
    }

    /// <summary>Displays a "loading" placeholder until an image is set.</summary>
    public void SetLoading()
    {
        if (_loading)
            return;
        _image?.Dispose();
        _image = null;
        _loading = true;
        Invalidate();
    }

    public void ShowAt(Rectangle bounds)
    {
        if (!_shown || bounds != _bounds)
        {
            _bounds = bounds;
            Native.SetWindowPos(Handle, Native.HWND_TOPMOST, bounds.X, bounds.Y, bounds.Width, bounds.Height,
                Native.SWP_NOACTIVATE | Native.SWP_SHOWWINDOW | Native.SWP_NOOWNERZORDER);
            _shown = true;
        }
    }

    public void HidePreview()
    {
        if (!_shown)
            return;
        Native.ShowWindow(Handle, Native.SW_HIDE);
        _shown = false;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        var client = ClientRectangle;
        if (_image != null)
        {
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            g.DrawImage(_image, client);
        }
        else if (_loading)
        {
            using var font = new Font("Segoe UI", Math.Max(8f, client.Height / 10f), GraphicsUnit.Pixel);
            TextRenderer.DrawText(g, "Loading preview…", font, client, ForeColor,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }
        using var border = new Pen(Color.FromArgb(110, 110, 110));
        g.DrawRectangle(border, 0, 0, client.Width - 1, client.Height - 1);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
            _image?.Dispose();
        base.Dispose(disposing);
    }
}
