using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Extensions.DependencyInjection;
using OpenShorts.Core;
using OpenShorts.EngineBridge;
namespace OpenShorts.Desktop;

/// <summary>Explicit diagnostic mode: mock paid jobs, real recovered media and FFmpeg exports.</summary>
internal sealed class ClipperSmokeBridge(IEngineBridge inner) : IEngineBridge
{
    public string Outcome="completed";public bool FailSecondExport;public string Job="review-smoke";private bool submitted,cancelled;private int polls;
    public bool IsRunning=>inner.IsRunning;
    public Task StartAsync(CancellationToken t=default)=>inner.StartAsync(t);
    public Task RestartAsync(CancellationToken t=default)=>inner.RestartAsync(t);
    public Task<string> UploadAsync(string p,bool acknowledged,string template,CancellationToken cancellationToken=default,JsonObject? options=null)
    {if(!acknowledged)throw new IOException("Permission is required.");submitted=true;cancelled=false;polls=0;return Task.FromResult(Job);}
    private JsonObject Progress()=>new(){["state"]=cancelled?"cancelled":polls<3?"running":Outcome,["stage"]=polls<2?"Transcribing audio":"Analyzing content with Gemini",["overall"]=!cancelled && polls>=3 && Outcome=="completed"?100:null,["elapsed_seconds"]=polls,["can_cancel"]=!cancelled && polls<3,["error"]=Outcome=="failed"&&polls>=3?"Gemini quota or rate limit reached. Check your provider allowance before retrying.":null,["stages"]=new JsonArray(new JsonObject{["title"]="Preparing source",["state"]="completed",["percent"]=100},new JsonObject{["title"]="Transcribing audio",["state"]="active",["percent"]=50},new JsonObject{["title"]="Analyzing content with Gemini",["state"]="not_reported"},new JsonObject{["title"]="Selecting clip candidates",["state"]="not_reported"},new JsonObject{["title"]="Rendering selected clips",["state"]="not_reported"},new JsonObject{["title"]="Validating generated outputs",["state"]="not_reported"})};
    public async Task<JsonObject> GetAsync(string route,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? providerHeaders=null,IReadOnlyDictionary<string,string>? query=null)
    {
        if(submitted && route.EndsWith("/progress")){if(Outcome=="crash")throw new IOException("Simulated worker disconnect");polls++;return Progress();}
        var data=await inner.GetAsync(route,cancellationToken,providerHeaders,query);
        if(submitted && route.EndsWith("/review"))
        {
            var analysis=data["progress"]?["analysis"]?.DeepClone();
            data["progress"]=Progress();if(analysis is not null)data["progress"]!["analysis"]=analysis;
            data["state"]=Progress()["state"]!.DeepClone();
        }
        return data;
    }
    public Task<JsonObject> SendAsync(string route,JsonObject body,bool put=false,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? providerHeaders=null)
    {
        if(route.StartsWith("/api/desktop/imports/") && route.EndsWith("/category"))
            return Task.FromResult(new JsonObject{["primary_category"]="podcast",["subcategory"]="education",["confidence"]=.9,["classification_method"]="text",["review_required"]=false,["explanation"]="Synthetic grounded source interval 0–1s"});
        if(route==$"/api/desktop/jobs/{Job}/cancel"){cancelled=true;return Task.FromResult(new JsonObject{["status"]="cancelling"});}
        if(FailSecondExport && route.EndsWith("/1/editor/run"))throw new IOException("Simulated per-item failure");
        return inner.SendAsync(route,body,put,cancellationToken,providerHeaders);
    }
    public Task<JsonObject> FormAsync(string r,IReadOnlyDictionary<string,string> f,string? file=null,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? images=null)=>inner.FormAsync(r,f,file,cancellationToken,images);
    public Task<JsonObject> CancelScheduledAsync(string j,string p,string k,CancellationToken cancellationToken=default)=>inner.CancelScheduledAsync(j,p,k,cancellationToken);
    public Task ExportAsync(string r,string d,CancellationToken cancellationToken=default)=>inner.ExportAsync(r,d,cancellationToken);
    public ValueTask DisposeAsync()=>inner.DisposeAsync();
}
internal static class ClipperSmokeTest
{
    public static async Task RunAsync(MainWindow window,ServiceProvider services,string directory)
    {
        object report;
        try
        {
            var model=services.GetRequiredService<MainViewModel>();var bridge=(ClipperSmokeBridge)services.GetRequiredService<IEngineBridge>();var store=services.GetRequiredService<IUserStorage>();
            await Until(()=>!model.Busy && bridge.IsRunning);
            model.Route="AI Clipper";
            if(!model.ClipperProcessing || model.GenerationActive || model.GenerationHasSource)throw new IOException("Initial clipping preview is not idle.");
            await Capture(window,model,Path.Combine(directory,"idle-preview.png"),false);
            var source=await new VideoImportClient(bridge).RunAsync("local",Path.Combine(store.Library,"output","review-smoke","example_clip_1.mp4"),progress:p=>File.WriteAllText(Path.Combine(directory,"import-status.json"),p.ToJsonString()));model.AcceptImportedSource(source,null);model.Acknowledged=true;model.Route="AI Clipper";
            if(!model.ClipperProcessing || model.GenerationActive || !model.GenerationHasSource)throw new IOException("Import did not enter the ready processing page without starting AI.");
            await Capture(window,model,Path.Combine(directory,"imported-ready.png"),false);
            var running=model.StartClippingCommand.ExecuteAsync(null);await Until(()=>model.GenerationState=="running");
            if(!model.ClipperProcessing || !model.ProgressUnknown || !model.CancellationAvailable)throw new IOException("Real job presentation did not enter indeterminate processing.");
            await Capture(window,model,Path.Combine(directory,"generating.png"),false);window.ClipperWorkspace.AssertProcessingFits();
            double originalWidth=window.Width,originalHeight=window.Height;
            window.Width=1366;window.Height=768;await Capture(window,model,Path.Combine(directory,"generating-laptop.png"),false);window.ClipperWorkspace.AssertProcessingFits();
            window.MinWidth=800;window.MinHeight=500;window.Width=910;window.Height=510;await Capture(window,model,Path.Combine(directory,"generating-compact.png"),false);window.ClipperWorkspace.AssertProcessingFits();window.Width=originalWidth;window.Height=originalHeight;
            model.RunGenerationBackgroundCommand.Execute(null);if(!model.GenerationActive || model.IsClipper)throw new IOException("Background navigation lost the job.");
            model.NavigateHomeCommand.Execute("AI Clipper");await running;
            if(!model.ClipperReview || model.ReviewRows.Count!=3 || model.ReviewRows.Count(r=>r.Record.Ready)!=2 || model.ReviewSelected is null)throw new IOException($"Completed review mapping failed: mode={model.ClipperMode}, state={model.GenerationState}, rows={model.ReviewRows.Count}, ready={model.ReviewRows.Count(r=>r.Record.Ready)}, selected={model.ReviewSelected?.Record.Index}, error={model.Error}");
            if(File.Exists(Path.Combine(directory,"fallback-analysis.check")))
            {
                if(!model.GenerationWarning.Contains("fallback"))throw new IOException("Completed fallback generation hid its missing visual analysis.");
                await File.WriteAllTextAsync(Path.Combine(directory,"analysis-warning-result.json"),"{\"success\":true,\"fallback_warning_visible\":true}");
            }
            await Until(()=>model.Preview.Player.IsSeekable && model.Preview.Player.VoutCount>0);model.Preview.Player.SetPause(true);
            window.OpenClipperFullscreen();await Task.Delay(300);var fullscreen=Application.Current.Windows.OfType<Window>().Single(w=>w.Title=="Preview · Esc to return");
            if(model.Preview.Player.VoutCount==0)throw new IOException("Fullscreen lost native playback.");fullscreen.Close();await Task.Delay(300);
            await Capture(window,model,Path.Combine(directory,"review-desktop.png"),true);
            window.Width=1366;window.Height=768;await Capture(window,model,Path.Combine(directory,"review-laptop.png"),true);
            window.MinWidth=800;window.MinHeight=500;window.Width=910;window.Height=510;await Capture(window,model,Path.Combine(directory,"review-150-percent-layout.png"),true);
            var workspace=(ClipperWorkspaceView)window.FindName("ClipperWorkspace");var tabs=(System.Windows.Controls.TabControl)workspace.FindName("PreviewTabs");tabs.SelectedIndex=1;
            await Capture(window,model,Path.Combine(directory,"review-compact-export.png"),false);tabs.SelectedIndex=0;
            window.Width=1500;window.Height=900;
            await model.PreviewReviewCommand.ExecuteAsync(model.ReviewRows.Single(r=>r.Record.Index==1));
            if(model.SelectedClip?.Index!=1)throw new IOException("Selected preview identity changed.");
            await model.EditReviewCommand.ExecuteAsync(model.ReviewSelected);if(!model.IsEditor || model.Segments.Count==0)throw new IOException("Edit did not load saved timeline.");
            model.NavigateHomeCommand.Execute("AI Clipper");model.ExportFolder=directory;model.ExportName="review-export.mp4";model.ExportEncoder="x264";model.ExportQuality="fast";model.ExportFrameRate="24";model.ReviewIncludeCaptions=false;bridge.FailSecondExport=true;
            await model.ExportReviewAllCommand.ExecuteAsync(null);
            if(model.ReviewRows.Count(r=>r.ExportState.StartsWith("Exported"))!=1 || model.ReviewRows.Count(r=>r.ExportState.StartsWith("Failed"))!=1)throw new IOException("Batch partial success was not preserved.");
            if(model.ExportName!="review-export.mp4")throw new IOException("Results refresh changed the chosen export filename.");
            bridge.FailSecondExport=false;await model.RetryReviewExportsCommand.ExecuteAsync(null);
            if(model.ReviewRows.Count(r=>r.ExportState.StartsWith("Exported"))!=2)throw new IOException("Retry did not export the failed item.");
            await Capture(window,model,Path.Combine(directory,"review-exported.png"),true);
            await model.ReloadReviewCommand.ExecuteAsync(null);if(model.ReviewRows.Count!=3)throw new IOException("Reload duplicated records.");
            await model.PreviewReviewCommand.ExecuteAsync(model.ReviewRows.First(r=>r.Record.Ready));await Task.Delay(150);
            model.ReviewCaptionStyle="podcast";model.ReviewFramingStyle="contain";model.ReviewAudioStyle="Normalize loudness";
            await model.ApplyReviewStylesCommand.ExecuteAsync(null);
            var styled=(await bridge.GetAsync($"/api/clip/review-smoke/{model.ReviewSelected!.Record.Index}/editor"))["project"]!;
            if(styled["edits"]!["style"]!["preset"]!.ToString()!="podcast" || styled["edits"]!["crop"]!["mode"]!.ToString()!="contain" || styled["edits"]!["audio"]!["normalize"]!.GetValue<bool>()!=true)throw new IOException("Inline style controls did not save the actual timeline.");
            if(model.Error.Length>0 || styled["result"]?["mode"]?.ToString()!="preview" || !model.ReviewPreviewKind.StartsWith("Updated rendered preview"))throw new IOException("Style application did not render and open a fresh preview: "+model.Error);
            await Until(()=>model.Preview.Player.VoutCount>0);await Task.Delay(300);window.UpdateLayout();
            if(Math.Abs(window.ClipperWorkspace.PlayerHost.ActualWidth/window.ClipperWorkspace.PlayerHost.ActualHeight-model.SourceAspect)>.02)throw new IOException("Native review player does not retain the decoded video aspect.");
            await Capture(window,model,Path.Combine(directory,"full-video-blurred-preview.png"),true);
            await model.PreviewReviewCommand.ExecuteAsync(model.ReviewSelected);
            if(!model.ReviewPreviewKind.StartsWith("Updated rendered preview"))throw new IOException("Preview action reverted to the old delivered MP4.");
            int beforeDuplicate=model.ReviewRows.Count;await model.DuplicateReviewCommand.ExecuteAsync(model.ReviewSelected);
            if(model.ReviewRows.Count!=beforeDuplicate+1 || !model.ReviewSelected!.Record.Title.EndsWith("(copy)"))throw new IOException("The duplicate action did not create a separate clip configuration.");
            if(LucideIcon.Failures.Count>0)throw new IOException("Invalid bundled icon assets: "+string.Join(", ",LucideIcon.Failures));
            int selected=model.ReviewSelected!.Record.Index;await bridge.RestartAsync();await model.RefreshProjectsCommand.ExecuteAsync(null);
            model.SelectedProject=model.Projects.Single(p=>p.JobId=="review-smoke");await model.OpenProjectCommand.ExecuteAsync(null);
            var recovered=await bridge.GetAsync("/api/desktop/jobs/review-smoke/review");
            if(model.ReviewSelected?.Record.Index!=selected || recovered["preferences"]!["history"]!.AsArray().Count<3)throw new IOException("Worker restart lost completed clips, selection or export history.");
            model.ClipperMode="settings";bridge.Outcome="completed";
            running=model.StartClippingCommand.ExecuteAsync(null);await Until(()=>model.CancellationAvailable);await model.CancelCommand.ExecuteAsync(null);await running;
            if(model.GenerationState!="cancelled" || model.ClipperReview)throw new IOException("Cancelled generation was presented as completed.");
            bridge.Outcome="failed";await model.StartClippingCommand.ExecuteAsync(null);
            if(!model.GenerationHasFailure || model.ClipperReview)throw new IOException("Gemini error presentation failed.");
            await Capture(window,model,Path.Combine(directory,"generation-failed.png"),false);
            bridge.Outcome="crash";await model.StartClippingCommand.ExecuteAsync(null);if(model.GenerationState!="failed" || !model.GenerationHasFailure)throw new IOException("Worker disconnect was not recoverable.");
            report=new{success=true,paidRequests=0,progress="mock provider job statuses",realMedia=true,backgroundNavigation=true,cancellation=true,partialResults=true,nativePlayback=true,editorTimeline=true,real1080x1920BatchExports=true,perItemRetry=true,preferenceRecovery=true,inlineStyleEditing=true,updatedRenderedPreview=true,previewAspectVerified=true,independentDuplicate=true,lucideIcons=true,fittedProgressWithoutScrollbars=true,idlePreview=true,directImportToProcessingPage=true,dimensions=new[]{"desktop","1366×768","910×510 effective layout"},capture="WPF capture composed with a decoded native LibVLC snapshot"};
        }
        catch(Exception e){report=new{success=false,error=e.ToString()};Environment.ExitCode=1;}
        await File.WriteAllTextAsync(Path.Combine(directory,"clipper-result.json"),JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}));
        if(services.GetRequiredService<MainViewModel>().HasEditor)await services.GetRequiredService<MainViewModel>().PersistWorkspaceAsync();window.Close();
    }
    private static async Task Until(Func<bool> predicate)
    {var end=DateTime.UtcNow.AddMinutes(3);while(!predicate()){if(DateTime.UtcNow>end)throw new IOException("Native review condition timed out.");await Task.Delay(100);}}
    private static async Task Capture(MainWindow window,MainViewModel model,string path,bool video)
    {
        await Task.Delay(300);window.UpdateLayout();var drawing=new DrawingVisual();int w=(int)window.ActualWidth,h=(int)window.ActualHeight;
        var ui=new RenderTargetBitmap(w,h,96,96,PixelFormats.Pbgra32);ui.Render(window);
        using(var dc=drawing.RenderOpen())
        {
            dc.DrawImage(ui,new Rect(0,0,w,h));
            if(video)
            {
                string frameFile=path+".frame.png";
                if(model.Preview.Player.TakeSnapshot(0,frameFile,0,0))
                {
                    await Until(()=>File.Exists(frameFile)&&new FileInfo(frameFile).Length>0);await Task.Delay(50);
                    var bitmap=new BitmapImage();bitmap.BeginInit();bitmap.CacheOption=BitmapCacheOption.OnLoad;bitmap.UriSource=new Uri(frameFile);bitmap.EndInit();bitmap.Freeze();
                    var view=(FrameworkElement)window.FindName("VideoView");var origin=view.TranslatePoint(new Point(),window);var bounds=new Rect(origin,new Size(view.ActualWidth,view.ActualHeight));double scale=Math.Min(bounds.Width/bitmap.PixelWidth,bounds.Height/bitmap.PixelHeight);
                    dc.PushClip(new RectangleGeometry(bounds));dc.DrawRectangle(Brushes.Black,null,bounds);dc.DrawImage(bitmap,new Rect(bounds.X+(bounds.Width-bitmap.PixelWidth*scale)/2,bounds.Y+(bounds.Height-bitmap.PixelHeight*scale)/2,bitmap.PixelWidth*scale,bitmap.PixelHeight*scale));dc.Pop();
                }
            }
        }
        var image=new RenderTargetBitmap(w,h,96,96,PixelFormats.Pbgra32);image.Render(drawing);var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(image));using var output=File.Create(path);encoder.Save(output);
    }
}
