using System.Text.Json.Nodes;

namespace OpenShorts.Core;

public sealed record AppSettings(string Encoder = "auto", string Preset = "balanced", int Jobs = 1);
public sealed record ProjectItem(string JobId, int Clips, string Status, DateTime Modified);
public sealed record ClipItem(string JobId, int Index, string Title, string VideoUrl, double Start, double End, string Score = "Unscored")
{public double Duration=>Math.Max(0,End-Start);}
public sealed record EngineLaunchOptions(string SourceRoot, string? Library = null);

public interface IUserStorage
{
    string Library { get; }
    string Roaming { get; }
    AppSettings LoadSettings();
    void SaveSettings(AppSettings settings);
    string LoadCredential(string provider = "gemini");
    void SaveCredential(string value, string provider = "gemini");
    void CheckSpace();
    string ValidateProjectMedia(string path);
}

public interface IWorkerProcess : IDisposable
{
    bool HasExited { get; }
    int Id { get; }
}

public interface IWorkerLauncher
{
    IWorkerProcess Start(string executable, IReadOnlyList<string> arguments, string directory, IDictionary<string,string> environment);
}

public interface IEngineBridge : IAsyncDisposable
{
    bool IsRunning { get; }
    Task StartAsync(CancellationToken cancellationToken = default);
    Task RestartAsync(CancellationToken cancellationToken = default);
    Task<JsonObject> GetAsync(string route, CancellationToken cancellationToken = default, IReadOnlyDictionary<string,string>? providerHeaders = null, IReadOnlyDictionary<string,string>? query = null);
    Task<JsonObject> SendAsync(string route, JsonObject body, bool put = false, CancellationToken cancellationToken = default, IReadOnlyDictionary<string,string>? providerHeaders = null);
    Task<JsonObject> FormAsync(string route, IReadOnlyDictionary<string,string> fields, string? file = null, CancellationToken cancellationToken = default, IReadOnlyDictionary<string,string>? images = null);
    Task<JsonObject> CancelScheduledAsync(string jobId, string profile, string providerKey, CancellationToken cancellationToken = default);
    Task<string> UploadAsync(string path, bool acknowledged, string templateId, CancellationToken cancellationToken = default, JsonObject? options = null);
    Task ExportAsync(string route, string destination, CancellationToken cancellationToken = default);
}

// Future remote authority; no local provider fabricates paid entitlements.
public sealed record LicenseStatus(bool Authenticated, IReadOnlySet<string> Entitlements,
    bool DeviceActivated, DateTimeOffset? TrialExpires, DateTimeOffset? OfflineGraceExpires, bool AuthorityVerified);
public interface ISubscriptionProvider
{
    Task<LicenseStatus> LoginAsync(string code, string verifier, CancellationToken cancellationToken);
    Task LogoutAsync(CancellationToken cancellationToken);
    Task<LicenseStatus> GetStatusAsync(CancellationToken cancellationToken);
    Task<LicenseStatus> ActivateDeviceAsync(string publicKey, CancellationToken cancellationToken);
}
