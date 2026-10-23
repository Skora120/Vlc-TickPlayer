using System;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace TickPlayer;

/// <summary>
/// Disk cache of generated thumbnails, one folder per video under
/// %LOCALAPPDATA%\TickPlayer\thumbs, so reopening a video is instant.
/// </summary>
internal sealed class ThumbnailCache
{
    private const long MaxTotalBytes = 300L * 1024 * 1024;
    private static readonly TimeSpan MaxAge = TimeSpan.FromDays(60);

    private readonly string _dir;

    private ThumbnailCache(string dir) => _dir = dir;

    public static string Root => Path.Combine(Paths.DataDir, "thumbs");

    /// <summary>
    /// Opens the cache folder for a local video. Returns null for anything
    /// that is not a local file. A folder made with different settings is
    /// cleared.
    /// </summary>
    public static ThumbnailCache Open(string uri, long lengthMs, int slotCount, int boxWidth, int boxHeight)
    {
        try
        {
            var u = new Uri(uri);
            if (!u.IsFile)
                return null;
            var file = new FileInfo(u.LocalPath);
            if (!file.Exists)
                return null;

            var identity = $"{file.FullName.ToLowerInvariant()}|{file.Length}|{file.LastWriteTimeUtc.Ticks}";
            var dir = Path.Combine(Root, Hash(identity));
            var info = $"v1 {boxWidth}x{boxHeight} {slotCount} {lengthMs}";
            var infoPath = Path.Combine(dir, "info.txt");

            if (Directory.Exists(dir) && (!File.Exists(infoPath) || File.ReadAllText(infoPath) != info))
                Directory.Delete(dir, recursive: true);
            if (!Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
                File.WriteAllText(infoPath, info);
            }
            Directory.SetLastWriteTimeUtc(dir, DateTime.UtcNow);
            return new ThumbnailCache(dir);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or UriFormatException or ArgumentException or NotSupportedException)
        {
            Log.Warn("Thumbnail cache unavailable: " + ex.Message);
            return null;
        }
    }

    public byte[] Load(int slot)
    {
        try
        {
            var path = SlotPath(slot);
            return File.Exists(path) ? File.ReadAllBytes(path) : null;
        }
        catch (IOException)
        {
            return null;
        }
    }

    public void Save(int slot, byte[] jpeg)
    {
        try
        {
            File.WriteAllBytes(SlotPath(slot), jpeg);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // A full disk or similar only costs the cache, not the preview.
        }
    }

    /// <summary>Deletes old cache folders and keeps the total size bounded.</summary>
    public static void Prune()
    {
        try
        {
            if (!Directory.Exists(Root))
                return;
            var dirs = new DirectoryInfo(Root).GetDirectories()
                .OrderByDescending(d => d.LastWriteTimeUtc)
                .ToList();
            long total = 0;
            foreach (var d in dirs)
            {
                total += d.GetFiles().Sum(f => f.Length);
                if (total > MaxTotalBytes || DateTime.UtcNow - d.LastWriteTimeUtc > MaxAge)
                    d.Delete(recursive: true);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Log.Warn("Cache pruning failed: " + ex.Message);
        }
    }

    private string SlotPath(int slot) => Path.Combine(_dir, $"{slot:D3}.jpg");

    private static string Hash(string s)
    {
        using var sha = SHA1.Create();
        var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(s));
        return string.Concat(bytes.Take(8).Select(b => b.ToString("x2")));
    }
}
