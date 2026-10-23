using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace TickPlayer;

/// <summary>
/// The small text file the Lua extension writes to talk to the helper:
/// key=value lines (UTF-8) ending with "end=1". The extension rewrites it
/// whenever the media changes and sets active=0 when it is turned off.
/// </summary>
internal sealed class SessionFile
{
    private readonly string _path;
    private DateTime _missingSince = DateTime.MaxValue;

    public SessionFile(string path) => _path = path;

    public string Path => _path;

    public sealed class State
    {
        public bool Active;
        public string Uri = "";
        public string Name = "";
        public string Title = "";
    }

    /// <summary>
    /// Reads the file. Returns null if it is mid-write (no end marker yet).
    /// A file that stays missing for two seconds reads as inactive.
    /// </summary>
    public State Read()
    {
        string text;
        try
        {
            using var fs = new FileStream(_path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            using var reader = new StreamReader(fs, Encoding.UTF8);
            text = reader.ReadToEnd();
            _missingSince = DateTime.MaxValue;
        }
        catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException)
        {
            if (_missingSince == DateTime.MaxValue)
                _missingSince = DateTime.UtcNow;
            return DateTime.UtcNow - _missingSince > TimeSpan.FromSeconds(2) ? new State { Active = false } : null;
        }
        catch (IOException)
        {
            return null;
        }

        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in text.Split('\n'))
        {
            var eq = line.IndexOf('=');
            if (eq > 0)
                values[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).TrimEnd('\r');
        }
        if (!values.TryGetValue("end", out var end) || end != "1")
            return null;

        return new State
        {
            Active = values.TryGetValue("active", out var a) && a == "1",
            Uri = values.TryGetValue("uri", out var u) ? u : "",
            Name = values.TryGetValue("name", out var n) ? n : "",
            Title = values.TryGetValue("title", out var t) ? t : "",
        };
    }

    public void Delete()
    {
        try
        {
            File.Delete(_path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }

    /// <summary>Removes session files left behind by crashes.</summary>
    public static void DeleteStale(string directory)
    {
        try
        {
            foreach (var file in Directory.GetFiles(directory, "session-*.txt"))
            {
                if (DateTime.UtcNow - File.GetLastWriteTimeUtc(file) > TimeSpan.FromDays(2))
                    File.Delete(file);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }
}
