using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using OpenShorts.Core;

namespace OpenShorts.EngineBridge;

public sealed class EngineClient(IUserStorage storage, IWorkerLauncher launcher, EngineLaunchOptions options, ILogger<EngineClient> logger) : IEngineBridge
{
    private HttpClient? client;
    private IWorkerProcess? worker;
    private string? ready;
    private readonly SemaphoreSlim lifecycle = new(1,1);
    public bool IsRunning => worker is { HasExited: false } && client is not null;
    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        await lifecycle.WaitAsync(cancellationToken);
        try
        {
            if (IsRunning) return;
            Stop(); storage.CheckSpace();
            var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(48));
            ready = Path.Combine(storage.Library, "temp", "wpf-ready-" + Guid.NewGuid().ToString("N"));
            var env = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            foreach (var name in new[] { "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "USERPROFILE", "USERNAME", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE" })
                if (Environment.GetEnvironmentVariable(name) is { } value) env[name] = value;
            env["OPENSHORTS_DESKTOP"] = "1"; env["PYTHONUTF8"] = "1"; env["PYTHON_DOTENV_DISABLED"] = "1";
            env["OPENSHORTS_LIBRARY"] = storage.Library; env["OPENSHORTS_ROAMING"] = storage.Roaming;
            env["OPENSHORTS_LOCAL_TOKEN"] = token; env["OPENSHORTS_READY_FILE"] = ready;
            var frozen = Path.Combine(AppContext.BaseDirectory, "engine", "OpenShorts.Engine.exe");
            if (File.Exists(frozen)) worker = launcher.Start(frozen, ["--native-backend"], storage.Library, env);
            else
            {
                var python = Path.Combine(options.SourceRoot, ".venv", "Scripts", "python.exe");
                var entry = Path.Combine(options.SourceRoot, "desktop_entry.py");
                if (!File.Exists(python) || !File.Exists(entry)) throw new IOException("The Python engine is missing. Use --source-root for development or repair the installation.");
                worker = launcher.Start(python, [entry, "--native-backend"], storage.Library, env);
            }
            logger.LogInformation(new EventId(100), "Engine starting");
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken); timeout.CancelAfter(TimeSpan.FromMinutes(3));
            while (true)
            {
                timeout.Token.ThrowIfCancellationRequested();
                if (worker.HasExited) throw new IOException("The Python worker stopped during startup. Check the engine dependencies and restart.");
                string? readiness=null;
                // Windows may observe the file between create and writer close.
                try { if(File.Exists(ready)) readiness=await File.ReadAllTextAsync(ready,timeout.Token); }
                catch(IOException) { }
                if (int.TryParse(readiness, out var port) && port is > 0 and < 65536)
                {
                    var http = new HttpClient(new SocketsHttpHandler { UseProxy = false, AllowAutoRedirect = false }) { BaseAddress = new Uri($"http://127.0.0.1:{port}/"), Timeout = Timeout.InfiniteTimeSpan };
                    http.DefaultRequestHeaders.Add("X-OpenShorts-Session", token);
                    try
                    {
                        using var probe = CancellationTokenSource.CreateLinkedTokenSource(timeout.Token); probe.CancelAfter(500);
                        using var response = await http.GetAsync("health", probe.Token);
                        if (response.IsSuccessStatusCode) { client = http; break; }
                    }
                    catch (Exception e) when (e is HttpRequestException or OperationCanceledException) { }
                    http.Dispose();
                }
                await Task.Delay(200, timeout.Token);
            }
            try { NativeContract.Validate(await GetAsync("/api/desktop/contract",timeout.Token)); }
            catch(EngineRequestException e) when(e.StatusCode==404)
            { throw new IOException("The Python worker is missing the native integration contract. Use a matched source export or repair the engine installation.",e); }
            logger.LogInformation(new EventId(101), "Engine ready");
        }
        catch { Stop(); throw; }
        finally { lifecycle.Release(); }
    }
    public async Task RestartAsync(CancellationToken cancellationToken = default)
    {
        await lifecycle.WaitAsync(cancellationToken); try { Stop(); } finally { lifecycle.Release(); }
        await StartAsync(cancellationToken);
    }
    public static string ValidateRoute(string route)
    {
        if (!(route.StartsWith("/api/",StringComparison.Ordinal) || route.StartsWith("/videos/",StringComparison.Ordinal)) || route.Any(char.IsControl) || route.IndexOfAny(['?', '#', '\\', ':'])>=0)
            throw new ArgumentException("Invalid engine route.");
        var decoded=Uri.UnescapeDataString(route);
        if(decoded.Contains('%') || decoded.Contains('\\') || decoded.Any(char.IsControl) || decoded.Split('/').Any(part=>part is "." or ".."))
            throw new ArgumentException("Invalid engine route.");
        return string.Join('/',decoded.TrimStart('/').Split('/').Select(Uri.EscapeDataString));
    }
    public static string JobId(string value) => Regex.IsMatch(value, @"^[A-Za-z0-9_-]{1,128}$") ? value : throw new ArgumentException("Invalid project identity.");
    private HttpClient Connected => IsRunning ? client! : throw new IOException("The processing engine is offline. Restart it from Home.");
    public async Task<JsonObject> GetAsync(string route, CancellationToken cancellationToken = default, IReadOnlyDictionary<string,string>? providerHeaders = null, IReadOnlyDictionary<string,string>? query = null)
    {
        var target=ValidateRoute(route);
        if(query is {Count:>0})
        {
            if(query.Keys.Any(k=>k is not ("user" or "platforms" or "platform" or "limit" or "cursor" or "since" or "until")))throw new ArgumentException("Unsupported query parameter.");
            target+="?"+string.Join("&",query.Select(p=>Uri.EscapeDataString(p.Key)+"="+Uri.EscapeDataString(p.Value)));
        }
        using var request = new HttpRequestMessage(HttpMethod.Get,target);
        AddProviderHeaders(request,providerHeaders);
        return await JsonAsync(request, cancellationToken);
    }
    public async Task<JsonObject> SendAsync(string route, JsonObject body, bool put = false, CancellationToken cancellationToken = default, IReadOnlyDictionary<string,string>? providerHeaders = null)
    {
        using var request = new HttpRequestMessage(put ? HttpMethod.Put : HttpMethod.Post, ValidateRoute(route));
        AddProviderHeaders(request,providerHeaders);
        request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        return await JsonAsync(request, cancellationToken);
    }
    private static void AddProviderHeaders(HttpRequestMessage request,IReadOnlyDictionary<string,string>? providerHeaders)
    {
        foreach(var header in providerHeaders ?? new Dictionary<string,string>())
        {
            if(header.Key is not ("X-ElevenLabs-Key" or "X-Fal-Key" or "X-Upload-Post-Key"))throw new ArgumentException("Unsupported provider header.");
            request.Headers.Add(header.Key,header.Value);
        }
    }
    public async Task<JsonObject> CancelScheduledAsync(string jobId,string profile,string providerKey,CancellationToken cancellationToken=default)
    {
        using var request=new HttpRequestMessage(HttpMethod.Delete,ValidateRoute($"/api/social/scheduled/{JobId(jobId)}")+"?user="+Uri.EscapeDataString(profile));
        AddProviderHeaders(request,new Dictionary<string,string>{["X-Upload-Post-Key"]=providerKey});return await JsonAsync(request,cancellationToken);
    }
    public async Task<JsonObject> FormAsync(string route,IReadOnlyDictionary<string,string> fields,string? file=null,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? images=null)
    {
        if(route is not ("/api/thumbnail/analyze" or "/api/thumbnail/generate" or "/api/thumbnail/upload" or "/api/saasshorts/actor-upload"))throw new ArgumentException("Unsupported form operation.");
        using var request=new HttpRequestMessage(HttpMethod.Post,ValidateRoute(route));using var content=new MultipartFormDataContent();
        foreach(var field in fields)content.Add(new StringContent(field.Value),field.Key);
        if(file is not null)
        {
            var info=new FileInfo(file);if(!info.Exists || info.Length>2L*1024*1024*1024)throw new IOException("Choose an existing file below 2 GB.");
            content.Add(new StreamContent(File.OpenRead(info.FullName)),"file",info.Name);
        }
        foreach(var image in images ?? new Dictionary<string,string>())
        {
            if(route!="/api/thumbnail/generate" || image.Key is not ("face" or "background"))throw new ArgumentException("Unsupported reference image field.");
            var info=new FileInfo(image.Value);
            if(!info.Exists || info.Length>25L*1024*1024 || !new[]{".png",".jpg",".jpeg",".webp"}.Contains(info.Extension.ToLowerInvariant()))throw new IOException("Choose a supported image below 25 MB.");
            content.Add(new StreamContent(File.OpenRead(info.FullName)),image.Key,info.Name);
        }
        request.Content=content;return await JsonAsync(request,cancellationToken);
    }
    private async Task<JsonObject> JsonAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken); timeout.CancelAfter(TimeSpan.FromMinutes(30));
        using var response = await Connected.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
        const int limit = 8 * 1024 * 1024;
        if (response.Content.Headers.ContentLength > limit) throw new IOException("Engine response exceeds the safety limit.");
        using var stream = await response.Content.ReadAsStreamAsync(timeout.Token);
        using var buffer = new MemoryStream(); var bytes = new byte[16384]; int count;
        while ((count = await stream.ReadAsync(bytes, timeout.Token)) > 0)
        { if (buffer.Length + count > limit) throw new IOException("Engine response exceeds the safety limit."); await buffer.WriteAsync(bytes.AsMemory(0,count), timeout.Token); }
        JsonObject data;
        try { data = JsonNode.Parse(buffer.ToArray(), documentOptions: new JsonDocumentOptions { MaxDepth = 64 }) as JsonObject ?? throw new JsonException(); }
        catch (JsonException) { throw new IOException("The engine returned an invalid response."); }
        if (!response.IsSuccessStatusCode)
        {
            var detail = data["detail"] is JsonValue v && v.TryGetValue<string>(out var message) ? message : $"Engine request failed ({(int)response.StatusCode}).";
            throw new EngineRequestException((int)response.StatusCode,detail.Length <= 1000 ? detail : "The engine rejected this request.");
        }
        return data;
    }
    public async Task<string> UploadAsync(string path, bool acknowledged, string templateId, CancellationToken cancellationToken = default, JsonObject? options = null)
    {
        if (!acknowledged) throw new ArgumentException("Confirm that you have permission to use this video.");
        var file = new FileInfo(path);
        if (!file.Exists || file.Length == 0 || file.Length > 2L * 1024 * 1024 * 1024) throw new IOException("Choose a video between 1 byte and 2 GB.");
        if (!new[] { ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v" }.Contains(file.Extension.ToLowerInvariant())) throw new IOException("Unsupported video format.");
        using var request = new HttpRequestMessage(HttpMethod.Post, "api/process");
        using var multipart = new MultipartFormDataContent();
        var stream = new StreamContent(File.OpenRead(file.FullName)); stream.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        multipart.Add(stream, "file", file.Name); multipart.Add(new StringContent("true"), "acknowledged");
        var fields=options ?? new JsonObject{["output_format"]="vertical",["captions"]="true"};
        var allowed=new GenerationSettings().ToFields().Select(f=>f.Key).ToHashSet(StringComparer.Ordinal);
        foreach(var field in fields)
        {
            if(!allowed.Contains(field.Key) || field.Value is not JsonValue value || !value.TryGetValue<string>(out var text))throw new ArgumentException("Invalid generation field.");
            multipart.Add(new StringContent(text),field.Key);
        }
        if (!string.IsNullOrEmpty(templateId)) multipart.Add(new StringContent(templateId), "video_template");
        request.Content = multipart;
        var result = await JsonAsync(request, cancellationToken);
        return JobId(result["job_id"]?.GetValue<string>() ?? throw new IOException("The engine returned no job identity."));
    }
    public async Task ExportAsync(string route, string destination, CancellationToken cancellationToken = default)
    {
        using var response = await Connected.GetAsync(ValidateRoute(route), HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if (!response.IsSuccessStatusCode) throw new IOException("Export was rejected by the engine. Check the quality report.");
        var target = Path.GetFullPath(destination); var temporary = target + "." + Guid.NewGuid().ToString("N") + ".partial";
        var available = new DriveInfo(Path.GetPathRoot(target)!).AvailableFreeSpace;
        if (available < Math.Max(response.Content.Headers.ContentLength ?? 0, 256L * 1024 * 1024)) throw new IOException("The export drive has too little free space.");
        try
        {
            await using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, 65536, true))
                await response.Content.CopyToAsync(stream, cancellationToken);
            File.Move(temporary, target, true);
        }
        finally { File.Delete(temporary); }
    }
    private void Stop()
    {
        client?.Dispose(); client = null; worker?.Dispose(); worker = null;
        if (ready is not null) File.Delete(ready);
        logger.LogInformation(new EventId(102), "Engine stopped");
    }
    public async ValueTask DisposeAsync()
    { await lifecycle.WaitAsync(); try { Stop(); } finally { lifecycle.Release(); } }
}
