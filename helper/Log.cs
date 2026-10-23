using System;
using System.IO;
using System.Text;

namespace TickPlayer;

/// <summary>
/// Plain-text log at %LOCALAPPDATA%\TickPlayer\helper.log. It is recreated on
/// every start so it stays small and only describes the last session, which
/// is what users attach to bug reports.
/// </summary>
internal static class Log
{
    private const long MaxBytes = 2 * 1024 * 1024;
    private static readonly object Gate = new();
    private static StreamWriter _writer;

    public static string FilePath { get; private set; }

    public static void Init(string path)
    {
        lock (Gate)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                _writer = new StreamWriter(path, append: false, new UTF8Encoding(false)) { AutoFlush = true };
                FilePath = path;
            }
            catch (IOException)
            {
                // Another helper (second VLC window) owns the main log.
                var alt = Path.Combine(Path.GetDirectoryName(path),
                    $"helper-{System.Diagnostics.Process.GetCurrentProcess().Id}.log");
                _writer = new StreamWriter(alt, append: false, new UTF8Encoding(false)) { AutoFlush = true };
                FilePath = alt;
            }
        }
    }

    public static void Info(string message) => Write("INFO ", message);

    public static void Warn(string message) => Write("WARN ", message);

    public static void Error(string message, Exception ex = null) =>
        Write("ERROR", ex == null ? message : $"{message}: {ex}");

    private static void Write(string level, string message)
    {
        lock (Gate)
        {
            if (_writer == null || _writer.BaseStream.Length > MaxBytes)
                return;
            _writer.WriteLine($"{DateTime.Now:HH:mm:ss.fff} {level} {message}");
        }
    }
}
