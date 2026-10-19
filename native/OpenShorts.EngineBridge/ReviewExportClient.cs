using System.Text.Json.Nodes;
using OpenShorts.Core;
namespace OpenShorts.EngineBridge;

/// <summary>Sequential native exports through the existing saved timeline contract.</summary>
public sealed class ReviewExportClient(IEngineBridge engine)
{
    public async Task<string> ExportAsync(string job,int index,JsonObject output,bool captions,string destination,Action<double,string> progress,Action<string?> activeRoute,CancellationToken token)
    {
        string route=$"/api/clip/{EngineClient.JobId(job)}/{index}/editor";
        var data=await engine.GetAsync(route,token);
        if(data["stale"]?.GetValue<bool>()==true)throw new IOException("The saved timeline changed. Open the editor and resolve it before export.");
        var project=data["project"]!.AsObject();
        if(project["edits"]!["style"]!["enabled"]!.GetValue<bool>()!=captions)
        {
            var edits=(JsonObject)project["edits"]!.DeepClone();edits["style"]!["enabled"]=captions;
            var saved=await engine.SendAsync(route,new JsonObject{["revision"]=project["revision"]!.DeepClone(),["edits"]=edits},put:true,cancellationToken:token);
            project=saved["project"]?.AsObject() ?? saved;
        }
        // Preserve revision conflict protection: never retry a conflicting save/run automatically.
        try
        {
            await engine.SendAsync(route+"/run",new JsonObject{["revision"]=project["revision"]!.DeepClone(),["mode"]="final",["output"]=output.DeepClone()},cancellationToken:token);
            activeRoute(route);
            while(true)
            {
                data=await engine.GetAsync(route,token);project=data["project"]!.AsObject();
                string state=project["status"]?.ToString() ?? "unknown";
                progress(GenerationProgress.Number(project["progress"]) ?? 0,project["stage"]?.ToString() ?? "Rendering saved timeline");
                if(state=="completed")break;
                if(state=="cancelled")throw new OperationCanceledException(token);
                if(state is "failed" or "interrupted" or "draft")throw new IOException("Timeline export failed. Open the editor to inspect the saved project.");
                await Task.Delay(1000,token);
            }
            string url=project["result"]?["new_video_url"]?.ToString() ?? throw new IOException("Export produced no validated media reference.");
            progress(100,"Saving validated MP4");activeRoute(null);
            string staging=destination+"."+Guid.NewGuid().ToString("N")+".review-partial";
            try{await engine.ExportAsync(url,staging,token);File.Move(staging,destination,false);}
            finally{File.Delete(staging);}
            return url;
        }
        finally {activeRoute(null);}
    }
    public static string VersionedPath(string folder,string name)
    {
        if(!Directory.Exists(folder))throw new ArgumentException("Choose an existing export folder.");
        if(string.IsNullOrWhiteSpace(name)||Path.GetFileName(name)!=name||name.IndexOfAny(Path.GetInvalidFileNameChars())>=0)throw new ArgumentException("Enter a file name without a folder path.");
        string stem=Path.GetFileNameWithoutExtension(name);if(stem.Length==0)throw new ArgumentException("Enter a file name.");
        for(int i=0;i<10000;i++){string path=Path.Combine(folder,stem+(i==0?"":$" ({i+1})")+".mp4");if(!File.Exists(path))return path;}
        throw new IOException("Choose another export file name.");
    }
}
