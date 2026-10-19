using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Extensions.DependencyInjection;
using OpenShorts.Core;

namespace OpenShorts.Desktop;

/// <summary>Opt-in real-media acceptance using the commands bound to the native UI.</summary>
internal static class IntegrationTest
{
    public static async Task RunAsync(MainWindow window,ServiceProvider services,string directory,string video)
    {
        Directory.CreateDirectory(directory);
        var model=services.GetRequiredService<MainViewModel>();var engine=services.GetRequiredService<IEngineBridge>();
        var report=new JsonObject{["success"]=false,["synthetic"]=false,["freshAiAnalysis"]=false,["manualUiAcceptance"]=false};
        try
        {
            var deadline=DateTime.UtcNow.AddMinutes(3);
            while(!engine.IsRunning || model.Busy)
            {if(DateTime.UtcNow>deadline || model.Error.Length>0)throw new IOException("Startup failed: "+model.Error);await Task.Delay(200);}
            await model.ImportFileAsync(video);Check(model);
            var playingUntil=DateTime.UtcNow.AddSeconds(20);
            while(model.Preview.Player.VoutCount==0 && DateTime.UtcNow<playingUntil)await Task.Delay(100);
            report["nativePlayback"]=model.Preview.Player.VoutCount>0;
            model.Acknowledged=true;
            await File.WriteAllTextAsync(Path.Combine(directory,"progress.json"),"{\"stage\":\"fresh-ai-generation\"}");
            await model.StartClippingCommand.ExecuteAsync(null);Check(model);
            if(model.ActiveJobId is string generatedId)
            {
                var state=await engine.GetAsync($"/api/status/{generatedId}");
                // Private diagnostic artifact: redact the configured secret even if a dependency logs it.
                var diagnostic=state.ToJsonString(new JsonSerializerOptions{WriteIndented=true});
                var credential=services.GetRequiredService<IUserStorage>().LoadCredential();
                if(credential.Length>0)diagnostic=diagnostic.Replace(credential,"[redacted]",StringComparison.Ordinal);
                await File.WriteAllTextAsync(Path.Combine(directory,"engine-status.json"),diagnostic);
                if(state["status"]?.GetValue<string>()!="completed")throw new IOException("Fresh generation did not complete; see the redacted engine-status.json.");
            }
            if(model.Clips.Count==0)throw new IOException("AI generation produced no clips.");
            report["freshAiAnalysis"]=true;report["clipCount"]=model.Clips.Count;
            if(model.Clips.Any(c=>!double.IsFinite(c.Start)||!double.IsFinite(c.End)||c.Start<0||c.End<=c.Start))throw new IOException("Invalid clip boundaries.");
            report["clipSelections"]=new JsonArray(model.Clips.Select(c=>(JsonNode)new JsonObject{["index"]=c.Index,["start"]=c.Start,["end"]=c.End}).ToArray());
            model.SelectedClip=model.Clips[0];await model.OpenClipCommand.ExecuteAsync(null);Check(model);
            if(model.Captions.Count==0)throw new IOException("No timed captions were generated for the selected clip.");
            report["timedCaptionCount"]=model.Captions.Count;
            var clip=model.SelectedClip!;var route=$"/api/clip/{clip.JobId}/{clip.Index}/editor";
            await model.SaveEditorCommand.ExecuteAsync(null);Check(model);
            var saved=await engine.GetAsync(route);var edits=saved["project"]!["edits"]!.DeepClone();
            await model.RenderFinalCommand.ExecuteAsync(null);Check(model);
            await engine.ExportAsync(model.SelectedClip!.VideoUrl,Path.Combine(directory,"user-video-export.mp4"));
            var probe=await Probe(Path.Combine(directory,"user-video-export.mp4"));
            var streams=probe["streams"]!.AsArray();var v=streams.First(s=>s!["codec_type"]!.GetValue<string>()=="video")!;
            if(v["width"]!.GetValue<int>()!=1080 || v["height"]!.GetValue<int>()!=1920)throw new IOException("Export is not 1080x1920.");
            if(!streams.Any(s=>s!["codec_type"]!.GetValue<string>()=="audio"))throw new IOException("Export has no audio stream.");
            report["exportProbe"]=probe;report["export1080x1920"]=true;
            await engine.RestartAsync();var reopened=await engine.GetAsync(route);
            // Final rendering may update origin/status, but user edit decisions must survive.
            if(!JsonNode.DeepEquals(edits,reopened["project"]!["edits"]))throw new IOException("Saved edits changed across restart.");
            report["savedProjectReopened"]=true;report["jobId"]=clip.JobId;report["success"]=true;
            report["humanReviewRequired"]="Semantic subtitle accuracy, story selection, framing and audio listening require review of the real export.";
        }
        catch(Exception e){report["error"]=e is IOException?e.Message:"Native integration failed; inspect isolated engine logs.";Environment.ExitCode=1;}
        await File.WriteAllTextAsync(Path.Combine(directory,"result.json"),report.ToJsonString(new JsonSerializerOptions{WriteIndented=true}));
        window.Close();
    }
    private static void Check(MainViewModel model)
    {if(model.Error.Length>0)throw new IOException(model.Error);}
    private static async Task<JsonObject> Probe(string path)
    {
        var start=new ProcessStartInfo("ffprobe"){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
        foreach(var arg in new[]{"-v","error","-show_streams","-show_format","-of","json",path})start.ArgumentList.Add(arg);
        using var process=Process.Start(start)!;var output=process.StandardOutput.ReadToEndAsync();var error=process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();await error;if(process.ExitCode!=0)throw new IOException("Export probe failed.");
        return JsonNode.Parse(await output)!.AsObject();
    }
}
