using System;
using System.Diagnostics;
using System.Drawing.Imaging;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace TickPlayer;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length >= 4 && args[0] == "--test-thumbnails")
            return TestThumbnails(args[1], args[2], args[3]);
        if (args.Length >= 1 && args[0] == "--version")
        {
            Console.WriteLine(Application.ProductVersion);
            return 0;
        }

        var sessionPath = ArgValue(args, "--session");
        if (sessionPath == null)
            return 2; // started by hand; nothing to do

        Log.Init(Paths.LogFile);
        Log.Info($"TickPlayer helper {Application.ProductVersion} ({(Environment.Is64BitProcess ? 64 : 32)}-bit) " +
                 $"on Windows {Environment.OSVersion.Version}, .NET {Environment.Version}");
        AppDomain.CurrentDomain.UnhandledException += (_, e) => Log.Error("Unhandled exception", e.ExceptionObject as Exception);
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, e) =>
        {
            Log.Error("Unhandled UI exception", e.Exception);
            Application.Exit();
        };

        try
        {
            return Run(sessionPath);
        }
        catch (Exception ex)
        {
            Log.Error("Fatal error", ex);
            return 1;
        }
    }

    private static int Run(string sessionPath)
    {
        Log.Info("Session file: " + sessionPath);
        var session = new SessionFile(sessionPath);
        SessionFile.DeleteStale(Path.GetDirectoryName(sessionPath));

        SessionFile.State state = null;
        for (var i = 0; i < 30 && state == null; i++)
        {
            state = session.Read();
            if (state == null)
                Thread.Sleep(100);
        }
        if (state == null || !state.Active)
        {
            Log.Warn("No active session; the extension was turned off or the file is unreadable");
            return 1;
        }

        using var vlc = VlcTarget.Find(state.Title, state.Name);
        if (vlc == null)
        {
            Log.Error("VLC is not running");
            return 1;
        }
        Log.Info($"VLC process {vlc.ProcessId} ({(vlc.Is32Bit ? 32 : 64)}-bit): {vlc.ExePath}");
        if (vlc.Is32Bit == Environment.Is64BitProcess)
        {
            Log.Error("This helper's bitness does not match VLC. The extension should start " +
                      (vlc.Is32Bit ? "TickPlayerHelper-x86.exe" : "TickPlayerHelper.exe"));
            return 1;
        }

        // One helper per VLC window. When the extension is switched off and
        // on quickly, give the previous helper a moment to exit.
        using var mutex = new Mutex(false, $@"Local\TickPlayerHelper-{vlc.ProcessId}");
        try
        {
            if (!mutex.WaitOne(3000))
            {
                Log.Warn("Another helper is already running for this VLC");
                return 0;
            }
        }
        catch (AbandonedMutexException)
        {
        }

        try
        {
            LibVlc.Load(vlc.InstallDir);
            Log.Info("libVLC " + LibVlc.Version());
            ThumbnailCache.Prune();

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new HelperApp(vlc, session, state));
        }
        finally
        {
            session.Delete();
            mutex.ReleaseMutex();
        }
        Log.Info("Stopped");
        return 0;
    }

    private static string ArgValue(string[] args, string name)
    {
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == name)
                return args[i + 1];
        }
        return null;
    }

    /// <summary>
    /// Developer and CI check: TickPlayerHelper.exe --test-thumbnails &lt;VLC folder&gt; &lt;media URI&gt; &lt;output folder&gt;
    /// grabs frames at a few times, saves them as PNGs and writes timings to report.txt.
    /// Exits with 1 if the media can't be opened or any frame is missing.
    /// </summary>
    private static int TestThumbnails(string vlcDir, string mrl, string outDir)
    {
        Directory.CreateDirectory(outDir);
        var report = new StringBuilder();
        var passed = false;
        try
        {
            LibVlc.Load(vlcDir);
            report.AppendLine("libVLC " + LibVlc.Version());
            var instance = FrameGrabber.CreateInstance();
            using (var grabber = new FrameGrabber(instance, mrl, 320, 180))
            {
                var sw = Stopwatch.StartNew();
                var ok = grabber.Open(15000, out var error);
                report.AppendLine($"open: {(ok ? "ok" : error)} in {sw.ElapsedMilliseconds} ms, length {grabber.LengthMs} ms, {grabber.FormatInfo}");
                if (ok)
                {
                    long total = 0, worst = 0;
                    var missing = 0;
                    const int n = 20;
                    for (var i = 0; i < n; i++)
                    {
                        var t = Thumbnailer.SlotTimeMs(grabber.LengthMs, n, i);
                        sw.Restart();
                        using var bmp = grabber.Grab(t, 8000);
                        total += sw.ElapsedMilliseconds;
                        worst = Math.Max(worst, sw.ElapsedMilliseconds);
                        report.AppendLine($"  {TimeSpan.FromMilliseconds(t):hh\\:mm\\:ss\\.fff}: {(bmp == null ? "no frame" : $"{bmp.Width}x{bmp.Height}")} in {sw.ElapsedMilliseconds} ms");
                        if (bmp == null)
                            missing++;
                        bmp?.Save(Path.Combine(outDir, $"{i:D2}.png"), ImageFormat.Png);
                    }
                    report.AppendLine($"average {total / n} ms, worst {worst} ms, missing {missing}");
                    passed = missing == 0;
                }
            }
            LibVlc.libvlc_release(instance);
        }
        catch (Exception ex)
        {
            report.AppendLine("error: " + ex);
        }
        File.WriteAllText(Path.Combine(outDir, "report.txt"), report.ToString());
        return passed ? 0 : 1;
    }
}
