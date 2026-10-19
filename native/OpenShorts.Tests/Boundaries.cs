using System.Diagnostics;
using System.Text;
using Microsoft.Extensions.Logging.Abstractions;
using OpenShorts.Core;
using OpenShorts.EngineBridge;
using OpenShorts.Infrastructure;
using Xunit;

namespace OpenShorts.Tests;

public sealed class Boundaries : IDisposable
{
    private readonly string directory=Path.Combine(Path.GetTempPath(),"openshorts-wpf-tests-"+Guid.NewGuid().ToString("N"));
    private UserStorage Storage => new(Path.Combine(directory,"library"),Path.Combine(directory,"profile"));
    [Theory]
    [InlineData("http://evil.example/api/config")][InlineData("/api/../secret")][InlineData("/videos/a/%2e%2e/secret")][InlineData("//evil.example/api/config")][InlineData("/api/a\\b")]
    public void RoutesRejectCrossOriginAndTraversal(string route) => Assert.Throws<ArgumentException>(()=>EngineClient.ValidateRoute(route));
    [Fact] public void MediaRoutesSupportUnicodeNamesWithoutAllowingDoubleEncoding()
    { Assert.Equal("videos/job/r%C3%A9sum%C3%A9%20clip.mp4",EngineClient.ValidateRoute("/videos/job/résumé clip.mp4"));Assert.Throws<ArgumentException>(()=>EngineClient.ValidateRoute("/videos/job/%252e%252e/secret")); }
    [Fact] public void RoutesAndJobIdsAreCanonical()
    { Assert.Equal("api/clip/job-1/0/editor",EngineClient.ValidateRoute("/api/clip/job-1/0/editor"));Assert.Throws<ArgumentException>(()=>EngineClient.JobId("../project")); }
    [Fact] public void SettingsAreCompatibleAndBounded()
    { var store=Storage;store.SaveSettings(new("nvenc","quiet",999));Assert.Equal(new AppSettings("nvenc","quiet",1),store.LoadSettings());Assert.Throws<ArgumentException>(()=>store.SaveSettings(new("auto & calc","quiet"))); }
    [Fact] public void CredentialsAreDpapiCiphertext()
    { var store=Storage;store.SaveCredential("test-secret");Assert.Equal("test-secret",store.LoadCredential());Assert.DoesNotContain("test-secret",Encoding.UTF8.GetString(File.ReadAllBytes(Path.Combine(store.Roaming,"credentials.dpapi"))));store.SaveCredential("");Assert.Equal("",store.LoadCredential()); }
    [Fact] public void SameFileLockExcludesAnotherInstance()
    { var store=Storage;using(var first=new InstanceLock(store.Roaming)) Assert.Throws<IOException>(()=>new InstanceLock(store.Roaming));using var next=new InstanceLock(store.Roaming); }
    [Fact] public void ProjectPathsStayInsideLibrary()
    { var store=Storage;var path=Path.Combine(store.Library,"output","clip.mp4");File.WriteAllText(path,"video");Assert.Equal(path,store.ValidateProjectMedia(path));var other=Path.Combine(directory,"private.mp4");File.WriteAllText(other,"private");Assert.Throws<IOException>(()=>store.ValidateProjectMedia(other)); }
    [Theory][InlineData("simple")][InlineData("has spaces")][InlineData("C:\\folder with spaces\\")][InlineData("quote\"inside")]
    public void ArgumentsAreQuotedWithoutShellExpansion(string value)
    { var result=WindowsWorkerLauncher.QuoteArgument(value);Assert.StartsWith("\"",result);Assert.EndsWith("\"",result);Assert.Throws<ArgumentException>(()=>WindowsWorkerLauncher.QuoteArgument("a\0b")); }
    [Fact] public async Task JobObjectKillsRealChildAndGrandchild()
    {
        var store=Storage;var marker=Path.Combine(directory,"grandchild.pid");
        var script=Path.Combine(directory,"child.ps1");
        File.WriteAllText(script,"$p = Start-Process -FilePath $env:ComSpec -ArgumentList '/c ping -n 120 127.0.0.1 > nul' -WindowStyle Hidden -PassThru\n$p.Id | Set-Content -LiteralPath '"+marker.Replace("'","''")+"'\nStart-Sleep -Seconds 120");
        var env=Environment.GetEnvironmentVariables().Cast<System.Collections.DictionaryEntry>().ToDictionary(x=>(string)x.Key,x=>(string)x.Value!);
        var launcher=new WindowsWorkerLauncher();
        using var child=launcher.Start(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe"),["-NoProfile","-ExecutionPolicy","Bypass","-File",script],directory,env);
        var deadline=DateTime.UtcNow.AddSeconds(20);while(!File.Exists(marker) && DateTime.UtcNow<deadline) await Task.Delay(50);
        Assert.True(File.Exists(marker));var pid=int.Parse(File.ReadAllText(marker));using var grandchild=Process.GetProcessById(pid);
        child.Dispose();Assert.True(child.HasExited);Assert.True(grandchild.WaitForExit(5000));
    }
    [Fact] public async Task RealNativeBridgeStartsAndRestarts()
    {
        var root=Environment.GetEnvironmentVariable("OPENSHORTS_TEST_ROOT");
        if(root is null) return; // opt-in integration requires the existing Python environment.
        var store=Storage;using var marker=new InstanceLock(store.Roaming);
        var launcher=new RecordingLauncher();
        await using var bridge=new EngineClient(store,launcher,new(root),NullLogger<EngineClient>.Instance);
        await bridge.StartAsync();Assert.True(bridge.IsRunning);
        Assert.True((await bridge.GetAsync("/api/config"))["desktopMode"]!.GetValue<bool>());
        Assert.NotNull((await bridge.GetAsync("/api/desktop/projects"))["projects"]);
        Assert.NotNull((await bridge.GetAsync("/api/desktop/templates"))["templates"]);
        Assert.Equal(Environment.GetEnvironmentVariable("USERNAME"),launcher.Environment["USERNAME"]);
        var launchToken=launcher.Environment["OPENSHORTS_LOCAL_TOKEN"];
        var port=await File.ReadAllTextAsync(launcher.Environment["OPENSHORTS_READY_FILE"]);
        using var http=new HttpClient(new SocketsHttpHandler{UseProxy=false}){BaseAddress=new Uri($"http://127.0.0.1:{port}/")};
        Assert.Equal(System.Net.HttpStatusCode.Forbidden,(await http.GetAsync("api/config")).StatusCode);
        using var foreign=new HttpRequestMessage(HttpMethod.Get,"api/config");
        foreign.Headers.Add("X-OpenShorts-Session",launchToken);foreign.Headers.Add("Origin","https://evil.example");
        Assert.Equal(System.Net.HttpStatusCode.Forbidden,(await http.SendAsync(foreign)).StatusCode);
        await bridge.RestartAsync();Assert.True(bridge.IsRunning);
        Assert.NotEqual(launchToken,launcher.Environment["OPENSHORTS_LOCAL_TOKEN"]);
        Assert.False(launcher.Environment.ContainsKey("GEMINI_API_KEY"));
    }
    [Fact] public async Task DpapiInteroperatesWithExistingPythonStore()
    {
        var root=Environment.GetEnvironmentVariable("OPENSHORTS_TEST_ROOT");if(root is null)return;
        var store=Storage;store.SaveCredential("dotnet-test-key");
        var start=new ProcessStartInfo(Path.Combine(root,".venv","Scripts","python.exe")){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=root,RedirectStandardError=true};
        foreach(var arg in new[]{"-X","utf8","-c","from desktop.credentials import CredentialStore; import sys; s=CredentialStore(sys.argv[1]); assert s.load()=='dotnet-test-key'; s.save('python-test-key')",store.Roaming})start.ArgumentList.Add(arg);
        using var process=Process.Start(start)!;var error=process.StandardError.ReadToEndAsync();await process.WaitForExitAsync();Assert.Equal(0,process.ExitCode);await error;
        Assert.Equal("python-test-key",store.LoadCredential());
    }
    private sealed class RecordingLauncher : IWorkerLauncher
    {
        public Dictionary<string,string> Environment { get; private set; }=[];
        public IWorkerProcess Start(string executable,IReadOnlyList<string> arguments,string directory,IDictionary<string,string> environment)
        { Environment=new(environment);return new WindowsWorkerLauncher().Start(executable,arguments,directory,environment); }
    }
    public void Dispose() { if(Directory.Exists(directory)) Directory.Delete(directory,true); }
}
