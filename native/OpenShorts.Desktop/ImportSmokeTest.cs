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
internal static class ImportSmokeTest
{
    public static async Task RunAsync(MainWindow window,ServiceProvider services,string directory,string? testUrl=null)
    {
        Directory.CreateDirectory(directory);
        try
        {
            var model=services.GetRequiredService<MainViewModel>();var bridge=services.GetRequiredService<IEngineBridge>();var store=services.GetRequiredService<IUserStorage>();
            var deadline=DateTime.UtcNow.AddMinutes(3);
            while(model.Busy || !bridge.IsRunning){if(DateTime.UtcNow>deadline)throw new IOException("Import smoke startup timed out.");await Task.Delay(100);}
            if(model.Error.Length>0)throw new IOException(model.Error);
            string source=Path.Combine(directory,"原始 video.mp4");
            var ff=new ProcessStartInfo("ffmpeg"){UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true};
            foreach(var arg in new[]{"-nostdin","-v","error","-y","-f","lavfi","-i","testsrc2=s=320x180:r=24:d=2","-f","lavfi","-i","sine=frequency=440:duration=2","-c:v","libx264","-threads","1","-pix_fmt","yuv420p","-c:a","aac","-shortest",source})ff.ArgumentList.Add(arg);
            using(var process=Process.Start(ff)!){var error=process.StandardError.ReadToEndAsync();await process.WaitForExitAsync();if(process.ExitCode!=0)throw new IOException(await error);await error;}
            int navigation=0;model.Route="Home";model.PropertyChanged+=(_,e)=>{if(e.PropertyName==nameof(MainViewModel.Route) && model.IsClipper)navigation++;};
            _ = window.Dispatcher.BeginInvoke(()=>model.ImportCommand.Execute(null));
            await Task.Delay(300);
            var dialog=Application.Current.Windows.OfType<ImportVideoWindow>().Single();var workflow=(ImportVideoViewModel)dialog.DataContext;
            if(!workflow.BrowseTab || dialog.Owner!=window)throw new IOException("Import modal did not open in Browse File.");
            Capture(dialog,Path.Combine(directory,"import-browse.png"));
            workflow.UrlTab=true;workflow.Url="https://public.example/fixture.mp4";
            if(workflow.FetchCommand.CanExecute(null))throw new IOException("URL permission confirmation was skipped.");
            workflow.RightsConfirmed=true;if(!workflow.FetchCommand.CanExecute(null))throw new IOException("URL tab did not enable fetch after confirmation.");
            await Task.Delay(100);Capture(dialog,Path.Combine(directory,"import-url.png"));
            workflow.PropertyChanged+=(_,e)=>
            {
                if(e.PropertyName==nameof(ImportVideoViewModel.Busy) && !workflow.Busy && workflow.State=="completed")
                    dialog.Dispatcher.Invoke(()=>Capture(dialog,Path.Combine(directory,"import-validated.png")),System.Windows.Threading.DispatcherPriority.Render);
            };
            await workflow.ImportLocalAsync(source);
            if(workflow.Error.Length>0)throw new IOException(workflow.Error);
            var ready=await ReadyWindow();var settings=(VideoReadyViewModel)ready.DataContext;
            if(settings.Media.FrameRate<=0 || settings.Media.Codec!="h264" || settings.Media.AudioCodec!="aac" || settings.Thumbnail is null)throw new IOException("Video Ready did not receive real metadata.");
            if(navigation!=0 || model.IsClipper)throw new IOException("Import skipped the Video Ready confirmation.");
            if(settings.Framing!="auto" || settings.TemplateId!="auto")throw new IOException("New sources must default to automatic framing and template selection.");
            settings.PlayCommand.Execute(null);
            deadline=DateTime.UtcNow.AddSeconds(15);while(settings.Player is null || settings.Player.VoutCount==0){if(DateTime.UtcNow>deadline)throw new IOException("Video Ready preview did not play.");await Task.Delay(50);}
            settings.Player?.Pause();settings.PreviewActive=false;
            settings.Minimum=5;await settings.OpenCommand.ExecuteAsync(null);
            if(settings.Error.Length==0 || !Application.Current.Windows.OfType<VideoReadyWindow>().Any())throw new IOException("Invalid settings did not keep the modal open.");
            settings.Minimum=null;
            // Exercise the actual WPF commands through a mocked paid boundary.
            using(var categorySettings=new VideoReadyViewModel(new ClipperSmokeBridge(bridge),store,settings.Media,
                new GenerationDraft{SourceId=settings.Media.Id,Settings=settings.Settings with{AnalysisCategory="football"},OutputLocation=Path.Combine(store.Library,"output")},
                "Synthetic credential status",model.CaptionPresets,model.Templates.ToArray(),_=>Task.CompletedTask))
            {
                await categorySettings.DetectCategoryCommand.ExecuteAsync(null);
                if(categorySettings.Settings.AnalysisCategory!="football" || !categorySettings.CategoryExplanation.Contains("education"))throw new IOException("Detection overwrote the manual category or hid its explanation.");
                categorySettings.UseDetectedCategoryCommand.Execute(null);
                if(categorySettings.Settings.AnalysisCategory!="podcast-education")throw new IOException("Explicit category confirmation failed.");
            }
            settings.PrimaryCategory="challenge";settings.Subcategory="experiment";
            if(settings.Settings.AnalysisCategory!="challenge-experiment" || !settings.Subcategories.Contains("survival"))throw new IOException("Category subtype controls lost their contract.");
            settings.Mode="highlights";settings.TargetSeconds=60;settings.Ratio="square";settings.Framing="subject";settings.CaptionPreset="creator-bold";settings.Pacing="emotional";settings.AudioPreset="dialogue";settings.AutoCount=true;
            settings.SelectedTab=0;await Task.Delay(60);Capture(ready,Path.Combine(directory,"video-ready-clips.png"));
            settings.SelectedTab=1;await Task.Delay(60);Capture(ready,Path.Combine(directory,"video-ready-ai.png"));
            settings.SelectedTab=2;await Task.Delay(60);Capture(ready,Path.Combine(directory,"video-ready-output.png"));
            settings.SelectedTab=0;ready.Width=1000;ready.Height=560;await Task.Delay(60);Capture(ready,Path.Combine(directory,"video-ready-1366.png"));
            AssertFooter(ready);
            ready.Width=1100;ready.Height=700;settings.SelectedTab=0;await Task.Delay(60);Capture(ready,Path.Combine(directory,"video-ready-1920.png"));AssertFooter(ready);
            settings.TemplateId="auto";
            if(!settings.Templates.Any(t=>t.Id=="auto") || !settings.Templates.Any(t=>t.Id=="none"))throw new IOException("Automatic and manual template choices are missing.");
            await settings.OpenCommand.ExecuteAsync(null);
            if(settings.Error.Length>0)throw new IOException(settings.Error);
            if(model.GenerationMode!="highlights" || model.OutputFormat!="square" || model.GenerationFraming!="subject" || model.GenerationCaptionPreset!="creator-bold" || model.AnalysisMode!=settings.Analysis || model.AnalysisCategory!="challenge-experiment" || !model.AutomaticClipCount)throw new IOException("AI Clipper settings differ from the saved draft.");
            if(!model.ClipperProcessing || !model.GenerationIdle || model.GenerationActive || navigation!=1 || !model.IsClipper || model.ImportedFile!=source || model.ImportedMediaId is null || model.Acknowledged)throw new IOException("Imported media did not navigate exactly once with analysis disabled.");
            workflow.OpenCommand.Execute(null);if(navigation!=1)throw new IOException("Completed import navigated twice.");
            if(Application.Current.Windows.OfType<ImportVideoWindow>().Any())throw new IOException("Import modal did not close.");
            _ = window.Dispatcher.BeginInvoke(()=>model.ReviewClippingSettingsCommand.Execute(null));
            var reopened=await ReadyWindow();var restored=(VideoReadyViewModel)reopened.DataContext;
            if(restored.TemplateId!="auto" || restored.Ratio!="square" || restored.Mode!="highlights" || restored.CaptionPreset!="creator-bold" || restored.Settings.AnalysisCategory!="challenge-experiment")throw new IOException("Saved settings/category were not restored.");
            reopened.Close();if(!File.Exists(source))throw new IOException("Cancel deleted the original source.");
            string manifest=Path.Combine(store.Library,"uploads","native-imports",model.ImportedMediaId,"manifest.json");
            if(!File.Exists(manifest) || !File.Exists(source))throw new IOException("Imported source or durable reference is missing.");
            deadline=DateTime.UtcNow.AddSeconds(15);while(model.Preview.Player.VoutCount==0){if(DateTime.UtcNow>deadline)throw new IOException("Imported H.264 video did not play.");await Task.Delay(100);}
            var duplicate=await new VideoImportClient(bridge).RunAsync("local",source);if(duplicate.Path!=source)throw new IOException("Local import copied a safe original unnecessarily.");
            string cancelId=Guid.NewGuid().ToString("N");
            await bridge.SendAsync("/api/desktop/imports",new(){["kind"]="local",["source"]=source,["import_id"]=cancelId});
            var cancelled=await bridge.SendAsync($"/api/desktop/imports/{cancelId}/cancel",new());
            if(cancelled["state"]?.GetValue<string>() is not ("cancelled" or "completed"))throw new IOException("Owned cancellation did not settle.");
            string blocked=Guid.NewGuid().ToString("N");
            await bridge.SendAsync("/api/desktop/imports",new(){["kind"]="url",["source"]="http://127.0.0.1/private.mp4",["acknowledged"]=true,["import_id"]=blocked});
            deadline=DateTime.UtcNow.AddSeconds(30);JsonObject rejected;
            do{rejected=await bridge.GetAsync($"/api/desktop/imports/{blocked}");if(DateTime.UtcNow>deadline)throw new IOException("Private URL rejection timed out.");await Task.Delay(100);}while(rejected["state"]?.GetValue<string>()!="failed");
            if(testUrl is not null)
            {
                model.Route="Home";
                _ = window.Dispatcher.BeginInvoke(()=>model.ImportCommand.Execute(null));
                await Task.Delay(300);
                var remoteDialog=Application.Current.Windows.OfType<ImportVideoWindow>().Single();
                var remote=(ImportVideoViewModel)remoteDialog.DataContext;
                remote.UrlTab=true;remote.Url=testUrl;remote.RightsConfirmed=true;
                remote.PropertyChanged+=(_,e)=>
                {
                    if(e.PropertyName==nameof(ImportVideoViewModel.Busy) && !remote.Busy)
                        remoteDialog.Dispatcher.Invoke(()=>Capture(remoteDialog,Path.Combine(directory,"import-remote.png")),System.Windows.Threading.DispatcherPriority.Render);
                };
                await remote.FetchCommand.ExecuteAsync(null);
                if(remote.Error.Length>0)throw new IOException(remote.Error);
                var remoteReady=await ReadyWindow();var remoteSettings=(VideoReadyViewModel)remoteReady.DataContext;
                await remoteSettings.OpenCommand.ExecuteAsync(null);
                if(remoteSettings.Error.Length>0)throw new IOException(remoteSettings.Error);
                if(!model.IsClipper || model.ImportedFile==source || !File.Exists(model.ImportedFile) || model.Acknowledged)
                    throw new IOException("Remote import did not hand off the validated file without starting AI.");
                store.ValidateProjectMedia(model.ImportedFile);
                deadline=DateTime.UtcNow.AddSeconds(15);
                while(model.Preview.Player.VoutCount==0){if(DateTime.UtcNow>deadline)throw new IOException("Downloaded video did not play.");await Task.Delay(100);}
            }
            Capture(window,Path.Combine(directory,"clipper-source.png"));
            File.WriteAllText(Path.Combine(directory,"result.json"),JsonSerializer.Serialize(new{success=true,videoReady=true,threeTabs=true,settingsPersist=true,cancelPreservesSource=true,responsiveFooter=true,remoteDownload=testUrl is not null,nativeModal=true,browseAndUrlTabs=true,actualEngineBridge=true,ffprobeValidated=true,originalPreserved=true,durableImport=true,duplicateWithoutCopy=true,singleNavigation=true,localPlayback=true,ownedCancel=true,privateUrlBlocked=true,noAiRequests=true,categoryDetectionMocked=true,categorySelectionPersist=true}));
            Application.Current.Shutdown(0);
        }
        catch(Exception error){File.WriteAllText(Path.Combine(directory,"error.txt"),error.ToString());Application.Current.Shutdown(1);}
    }
    private static async Task<VideoReadyWindow> ReadyWindow()
    {
        var deadline=DateTime.UtcNow.AddSeconds(30);
        while(true)
        {
            var ready=Application.Current.Windows.OfType<VideoReadyWindow>().FirstOrDefault();
            if(ready is not null && ready.DataContext is VideoReadyViewModel model && !model.Busy)
            {if(model.Error.Length>0)throw new IOException(model.Error);if(model.CanContinue)return ready;}
            if(DateTime.UtcNow>deadline)throw new IOException("Video Ready did not become available.");
            await Task.Delay(50);
        }
    }
    private static void AssertFooter(VideoReadyWindow window)
    {
        foreach(var button in new[]{window.CancelButton,window.ContinueButton})
        {
            var point=button.TransformToAncestor(window).Transform(new System.Windows.Point(0,0));
            if(!button.IsVisible || point.Y+button.ActualHeight>window.ActualHeight || point.X+button.ActualWidth>window.ActualWidth)throw new IOException("Video Ready footer is clipped.");
        }
    }
    private static IEnumerable<T> Children<T>(DependencyObject parent) where T:DependencyObject
    {
        for(int i=0;i<VisualTreeHelper.GetChildrenCount(parent);i++)
        {
            var child=VisualTreeHelper.GetChild(parent,i);if(child is T match)yield return match;
            foreach(var nested in Children<T>(child))yield return nested;
        }
    }
    private static void Capture(FrameworkElement window,string path)
    {
        window.UpdateLayout();var image=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);image.Render(window);
        var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(image));using var output=File.Create(path);encoder.Save(output);
    }
}
