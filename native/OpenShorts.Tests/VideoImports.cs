using System.Text.Json.Nodes;
using OpenShorts.Core;
using OpenShorts.EngineBridge;
using Xunit;
namespace OpenShorts.Tests;
public sealed class VideoImports
{
    private static JsonObject Complete()=>new(){["state"]="completed",["media"]=new JsonObject{["import_id"]="fixture",["path"]=Path.Combine(Path.GetTempPath(),"video.mp4"),["duration"]=1d,["width"]=320,["height"]=180,["size"]=1024L}};
    [Fact]public void CompletedSchemaIsValidated()
    {Assert.Equal(320,ImportedVideo.Parse(Complete()).Width);var data=Complete();data["media"]!["duration"]=double.PositiveInfinity;Assert.Throws<IOException>(()=>ImportedVideo.Parse(data));Assert.Throws<IOException>(()=>ImportedVideo.Parse(new()));}
    [Fact]public async Task UnknownTotalsAreDeliveredAsUnknown()
    {
        var bridge=new Fake();var observations=new List<JsonObject>();
        var result=await new VideoImportClient(bridge).RunAsync("local",Path.Combine(Path.GetTempPath(),"video.mp4"),observations.Add);
        Assert.Equal(2,observations.Count);Assert.Null(observations[0]["total"]);Assert.Equal(1024,result.Size);Assert.Equal(0,bridge.CancelCount);
    }
    [Fact]public async Task CancellationUsesKnownJobIdentityAndExistingBridge()
    {
        using var cancel=new CancellationTokenSource();var bridge=new Fake{CancelOnStart=cancel};
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>new VideoImportClient(bridge).RunAsync("local","source.mp4",cancellationToken:cancel.Token));
        Assert.Equal(1,bridge.CancelCount);Assert.EndsWith("/"+bridge.Id+"/cancel",bridge.CancelRoute);
    }
    [Fact]public async Task UrlRequiresPermissionBeforeStarting()
    {var bridge=new Fake();await Assert.ThrowsAsync<ArgumentException>(()=>new VideoImportClient(bridge).RunAsync("url","https://public.example/a.mp4"));Assert.Null(bridge.Id);}
    private sealed class Fake : IEngineBridge
    {
        public string? Id;public int CancelCount;public string? CancelRoute;public CancellationTokenSource? CancelOnStart;private int polls;
        public bool IsRunning=>true;
        public Task<JsonObject> SendAsync(string route,JsonObject body,bool put=false,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? providerHeaders=null)
        {if(route.EndsWith("/cancel")){CancelCount++;CancelRoute=route;return Task.FromResult(new JsonObject());}Id=body["import_id"]!.GetValue<string>();CancelOnStart?.Cancel();return Task.FromResult(new JsonObject{["import_id"]=Id});}
        public Task<JsonObject> GetAsync(string route,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? providerHeaders=null,IReadOnlyDictionary<string,string>? query=null)
        {cancellationToken.ThrowIfCancellationRequested();var completed=Complete();completed["media"]!["import_id"]=Id;return Task.FromResult(polls++==0?new JsonObject{["state"]="downloading",["downloaded"]=20L}:completed);}
        public Task StartAsync(CancellationToken t=default)=>Task.CompletedTask;
        public Task RestartAsync(CancellationToken t=default)=>Task.CompletedTask;
        public ValueTask DisposeAsync()=>ValueTask.CompletedTask;
        public Task<JsonObject> FormAsync(string r,IReadOnlyDictionary<string,string> f,string? file=null,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? images=null)=>throw new NotSupportedException();
        public Task<JsonObject> CancelScheduledAsync(string j,string p,string k,CancellationToken cancellationToken=default)=>throw new NotSupportedException();
        public Task<string> UploadAsync(string p,bool a,string t,CancellationToken cancellationToken=default,JsonObject? options=null)=>throw new NotSupportedException();
        public Task ExportAsync(string r,string d,CancellationToken cancellationToken=default)=>throw new NotSupportedException();
    }
}
