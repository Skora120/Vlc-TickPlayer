using System;
using System.IO;

namespace TickPlayer;

internal static class Paths
{
    /// <summary>%LOCALAPPDATA%\TickPlayer: log and thumbnail cache.</summary>
    public static string DataDir =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TickPlayer");

    public static string LogFile => Path.Combine(DataDir, "helper.log");
}
