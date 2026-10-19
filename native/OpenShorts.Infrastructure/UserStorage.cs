using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using OpenShorts.Core;

namespace OpenShorts.Infrastructure;

public sealed class UserStorage : IUserStorage
{
    public string Library { get; }
    public string Roaming { get; }
    public UserStorage(string? library = null, string? roaming = null)
    {
        Roaming = roaming ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "OpenShorts");
        Directory.CreateDirectory(Roaming);
        var location = Path.Combine(Roaming, "library-location.json");
        if (library is null && File.Exists(location))
            library = JsonSerializer.Deserialize<string>(File.ReadAllText(location));
        Library = Path.GetFullPath(library ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "OpenShorts"));
        foreach (var name in new[] { "output", "uploads", "temp", "models", "logs" }) Directory.CreateDirectory(Path.Combine(Library, name));
    }
    public AppSettings LoadSettings()
    {
        try
        {
            using var data = JsonDocument.Parse(File.ReadAllText(Path.Combine(Roaming, "settings.json")));
            return Validate(new(data.RootElement.GetProperty("encoder").GetString()!, data.RootElement.GetProperty("preset").GetString()!));
        }
        catch (Exception e) when (e is IOException or JsonException or KeyNotFoundException or ArgumentException) { return new(); }
    }
    public static AppSettings Validate(AppSettings settings)
    {
        if (!new[] { "auto", "x264", "nvenc" }.Contains(settings.Encoder) || !new[] { "quiet", "balanced", "performance" }.Contains(settings.Preset))
            throw new ArgumentException("Unsupported performance setting.");
        return settings with { Jobs = 1 };
    }
    public void SaveSettings(AppSettings settings)
    {
        var value = Validate(settings);
        AtomicWrite("settings.json", JsonSerializer.SerializeToUtf8Bytes(new { encoder = value.Encoder, preset = value.Preset, jobs = 1 }));
    }
    private static string CredentialFile(string provider)=>provider switch
    {"gemini"=>"credentials.dpapi","elevenlabs"=>"elevenlabs.dpapi","fal"=>"fal.dpapi","uploadpost"=>"uploadpost.dpapi",_=>throw new ArgumentException("Unsupported credential provider.")};
    public string LoadCredential(string provider = "gemini")
    {
        var file = Path.Combine(Roaming, CredentialFile(provider));
        return File.Exists(file) ? Encoding.UTF8.GetString(ProtectedData.Unprotect(File.ReadAllBytes(file), null, DataProtectionScope.CurrentUser)) : "";
    }
    public void SaveCredential(string value, string provider = "gemini")
    {
        if (value.Length > 4096 || value.Any(char.IsWhiteSpace)) throw new ArgumentException("Invalid API key format.");
        var name=CredentialFile(provider);
        if (value.Length == 0) { File.Delete(Path.Combine(Roaming, name)); return; }
        AtomicWrite(name, ProtectedData.Protect(Encoding.UTF8.GetBytes(value), null, DataProtectionScope.CurrentUser));
    }
    private void AtomicWrite(string name, byte[] data)
    {
        var target = Path.Combine(Roaming, name);
        var temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllBytes(temporary, data); File.Move(temporary, target, true); }
        finally { File.Delete(temporary); }
    }
    public void CheckSpace()
    {
        if (new DriveInfo(Path.GetPathRoot(Library)!).AvailableFreeSpace < 2L * 1024 * 1024 * 1024)
            throw new IOException("The video library drive needs at least 2 GB of free space. Select another library folder at startup.");
    }
    public string ValidateProjectMedia(string path)
    {
        var full = Path.GetFullPath(path);
        var root = new[]{"output","uploads"}.Select(name=>Path.Combine(Library,name)+Path.DirectorySeparatorChar).FirstOrDefault(p=>full.StartsWith(p,StringComparison.OrdinalIgnoreCase));
        if (root is null || !File.Exists(full)) throw new IOException("Project media is unavailable.");
        if((File.GetAttributes(root.TrimEnd(Path.DirectorySeparatorChar))&FileAttributes.ReparsePoint)!=0)throw new IOException("Linked project storage is not supported.");
        for (var item = full; item.Length >= root.Length; item = Path.GetDirectoryName(item)!)
            if ((File.GetAttributes(item) & FileAttributes.ReparsePoint) != 0) throw new IOException("Linked project media is not supported.");
        return full;
    }
}
