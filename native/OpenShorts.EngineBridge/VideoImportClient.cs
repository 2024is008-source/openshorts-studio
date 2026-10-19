using System.Text.Json.Nodes;
using OpenShorts.Core;

namespace OpenShorts.EngineBridge;

public sealed record ImportedVideo(string Id,string Path,double Duration,int Width,int Height,long Size)
{
    public string Title { get; init; }="";
    public string Platform { get; init; }="Local file";
    public string? Thumbnail { get; init; }
    public string Codec { get; init; }="Unknown";
    public string AudioCodec { get; init; }="";
    public string Format { get; init; }="";
    public double FrameRate { get; init; }
    public string Description=>$"{Width} × {Height} · {TimeSpan.FromSeconds(Duration):hh\\:mm\\:ss} · {Size/1048576d:F1} MB";
    public static ImportedVideo Parse(JsonObject data)
    {
        try
        {
        var media=data["media"]?.AsObject() ?? throw new IOException("Import returned no media reference.");
        var result=new ImportedVideo(EngineClient.JobId(media["import_id"]!.GetValue<string>()),media["path"]!.GetValue<string>(),media["duration"]!.GetValue<double>(),media["width"]!.GetValue<int>(),media["height"]!.GetValue<int>(),media["size"]!.GetValue<long>());
        if(!System.IO.Path.IsPathFullyQualified(result.Path) || !double.IsFinite(result.Duration) || result.Duration<=0 || result.Duration>7200 || result.Width<=0 || result.Width>16384 || result.Height<=0 || result.Height>16384 || result.Size<=0 || result.Size>2L*1024*1024*1024)
            throw new IOException("The import returned invalid media metadata.");
        string Text(string key,string fallback="")=>media[key]?.GetValue<string>() ?? data[key]?.GetValue<string>() ?? fallback;
        return result with {Title=Text("title",System.IO.Path.GetFileName(result.Path)),Platform=Text("platform","Local file"),Thumbnail=Text("thumbnail") is {Length:>0} thumb?thumb:null,Codec=Text("codec","Unknown"),AudioCodec=Text("audio_codec"),Format=Text("format",System.IO.Path.GetExtension(result.Path).TrimStart('.').ToUpperInvariant()),FrameRate=media["fps"]?.GetValue<double>() ?? 0};
        }
        catch(Exception error) when(error is InvalidOperationException or FormatException or NullReferenceException or OverflowException or ArgumentException)
        {throw new IOException("The import returned invalid media metadata.",error);}
    }
}

public sealed class VideoImportClient(IEngineBridge engine)
{
    public async Task<ImportedVideo> RunAsync(string kind,string source,Action<JsonObject>? progress=null,CancellationToken cancellationToken=default,bool acknowledged=false)
    {
        if(kind=="url" && !acknowledged)throw new ArgumentException("Confirm permission to download this source.");
        string id=Guid.NewGuid().ToString("N");bool completed=false;
        try
        {
            var started=await engine.SendAsync("/api/desktop/imports",new(){["kind"]=kind,["source"]=source,["import_id"]=id,["acknowledged"]=acknowledged},cancellationToken:cancellationToken);
            if(started["import_id"]?.GetValue<string>()!=id)throw new IOException("Import identity did not match the submitted source.");
            while(true)
            {
                var state=await engine.GetAsync($"/api/desktop/imports/{id}",cancellationToken);
                progress?.Invoke(state);
                switch(state["state"]?.GetValue<string>())
                {
                    case "completed":var result=ImportedVideo.Parse(state);if(result.Id!=id)throw new IOException("Completed media belongs to another import.");completed=true;return result;
                    case "failed":throw new IOException(state["status"]?.GetValue<string>() ?? "Import failed. Retry the source.");
                    case "cancelled":throw new OperationCanceledException("Import cancelled.",cancellationToken);
                }
                await Task.Delay(300,cancellationToken);
            }
        }
        finally
        {
            if(!completed)
            {
                using var stop=new CancellationTokenSource(TimeSpan.FromSeconds(15));
                try { await engine.SendAsync($"/api/desktop/imports/{id}/cancel",new(),cancellationToken:stop.Token); }
                catch(Exception e) when(e is IOException or HttpRequestException or OperationCanceledException) { }
            }
        }
    }
}
