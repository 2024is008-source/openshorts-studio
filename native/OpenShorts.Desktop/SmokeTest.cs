using System.Diagnostics;
using System.Text.Json;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Extensions.DependencyInjection;
using OpenShorts.Core;
namespace OpenShorts.Desktop;
internal static class SmokeTest
{
    public static async Task RunAsync(MainWindow window,ServiceProvider services,string directory)
    {
        Directory.CreateDirectory(directory);
        object report;
        try
        {
            var model=services.GetRequiredService<MainViewModel>();var engine=services.GetRequiredService<IEngineBridge>();
            var deadline=DateTime.UtcNow.AddMinutes(3);
            while(!engine.IsRunning || model.Busy)
            { if(DateTime.UtcNow>deadline || model.Error.Length>0) throw new IOException("Native startup failed: "+model.Error);await Task.Delay(200); }
            var config=await engine.GetAsync("/api/config");
            if(config["desktopMode"]?.GetValue<bool>()!=true) throw new IOException("Desktop guard was not enabled.");
            var projects=await engine.GetAsync("/api/desktop/projects");
            var source=Path.Combine(directory,"playback.mp4");
            var ffmpeg=new ProcessStartInfo("ffmpeg"){UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true};
            foreach(var arg in new[]{"-y","-v","error","-f","lavfi","-i","testsrc2=s=320x180:r=30:d=5","-f","lavfi","-i","sine=frequency=440:duration=5","-c:v","libx264","-threads","1","-pix_fmt","yuv420p","-c:a","aac","-shortest",source}) ffmpeg.ArgumentList.Add(arg);
            using(var process=Process.Start(ffmpeg)!) { var error=process.StandardError.ReadToEndAsync();await process.WaitForExitAsync();if(process.ExitCode!=0) throw new IOException("Playback fixture generation failed.");await error; }
            await model.ImportFileAsync(source);
            if(model.Error.Length>0) throw new IOException(model.Error);
            model.Route="Video Editor";
            deadline=DateTime.UtcNow.AddSeconds(15);
            while(model.Preview.Player.Time<=0 || model.Preview.Player.VoutCount==0)
            { if(DateTime.UtcNow>deadline) throw new IOException("H.264 video did not decode.");await Task.Delay(100); }
            model.Preview.Seek(2);
            await Task.Delay(500);
            long seek=model.Preview.Player.Time;
            uint videoOutputs=model.Preview.Player.VoutCount;
            if(seek<1500 || seek>3500) throw new IOException("Playback seek did not reach the expected interval.");
            var storage=services.GetRequiredService<IUserStorage>();
            var projectDirectory=Path.Combine(storage.Library,"output","native-smoke-job");Directory.CreateDirectory(projectDirectory);
            File.Copy(source,Path.Combine(projectDirectory,"example_clip_1.mp4"),true);
            var metadata=new { source_video="example_clip_1.mp4", output_format="horizontal",
                shorts=new[]{new { start=0d,end=5d,title="Native smoke project",video_url="/videos/native-smoke-job/example_clip_1.mp4" }},
                transcript=new { segments=new[]{new { start=0d,end=3d,text="Native video editor smoke test",words=new[]{new { word=" Native",start=0d,end=.5 },new { word=" video",start=.5,end=1d },new {word=" editor",start=1d,end=1.5},new {word=" smoke",start=1.5,end=2d},new {word=" test",start=2d,end=3d}}}}}};
            await File.WriteAllTextAsync(Path.Combine(projectDirectory,"example_metadata.json"),JsonSerializer.Serialize(metadata));
            await engine.RestartAsync();await model.RefreshProjectsCommand.ExecuteAsync(null);
            model.SelectedProject=model.Projects.Single(p=>p.JobId=="native-smoke-job");await model.OpenProjectCommand.ExecuteAsync(null);await model.OpenClipCommand.ExecuteAsync(null);
            if(!model.HasEditor || model.Captions.Count==0) throw new IOException("Native editor could not restore the real project.");
            if(model.EditorMediaFiles.Count==0)throw new IOException("Native media browser did not load the retained source.");
            await model.ImportEditorMediaAsync(source);
            if(model.EditorMediaFiles.Count<2)throw new IOException("Project media import did not persist in the local library.");
            var movedCaption=model.Captions[0];double originalCaptionStart=movedCaption.Start;
            model.BeginEditingGesture();model.MoveCaption(movedCaption,.1);model.EndEditingGesture();
            if(movedCaption.Start<=originalCaptionStart)throw new IOException("Timeline caption drag did not update its source timestamp.");
            model.UndoEditCommand.Execute(null);
            if(model.Captions[0].Start!=originalCaptionStart)throw new IOException("Caption drag undo did not restore source timing.");
            await model.SaveEditorCommand.ExecuteAsync(null);
            var unchanged=await engine.GetAsync("/api/clip/native-smoke-job/0/editor");
            if(unchanged["project"]!["edits"]!["caption_overrides"]!.AsObject().Count!=0) throw new IOException("An unchanged caption lost its original word alignment.");
            model.Segments[0].Start=double.NaN;
            if(!model.IsDirty || !model.AutosaveStatus.Contains("invalid"))throw new IOException("Invalid numeric edit was not handled safely.");
            model.Segments[0].Start=0;
            model.SelectedSegment=model.Segments[0];model.SeekSeconds=2;
            model.SplitSegmentCommand.Execute(null);
            if(model.Segments.Count!=2)throw new IOException("Split did not create a second segment.");
            model.UndoEditCommand.Execute(null);
            if(model.Segments.Count!=1 || model.Segments[0].End!=5)throw new IOException("Undo did not restore the whole split gesture.");
            model.RedoEditCommand.Execute(null);
            if(model.Segments.Count!=2)throw new IOException("Redo did not restore split.");
            model.UndoEditCommand.Execute(null);
            model.BeginEditingGesture();model.TrimSegment(model.Segments[0],true,.4);model.TrimSegment(model.Segments[0],true,.5);model.EndEditingGesture();
            if(model.Segments[0].Start!=.5)throw new IOException("Trim gesture did not use source timestamps.");
            model.UndoEditCommand.Execute(null);
            if(model.Segments[0].Start!=0)throw new IOException("Trim gesture was not a single undo operation.");
            model.SeekSeconds=2;model.SplitSegmentCommand.Execute(null);
            model.SelectedSegment=model.Segments[1];model.MoveUpCommand.Execute(null);
            if(model.Segments[0].Start!=2)throw new IOException("Segment reorder failed.");
            model.RemoveSegmentCommand.Execute(null);
            if(model.Segments.Count!=1)throw new IOException("Segment delete failed.");
            model.UndoEditCommand.Execute(null);model.UndoEditCommand.Execute(null);model.UndoEditCommand.Execute(null);
            if(model.Segments.Count!=1 || model.Segments[0].End!=5)throw new IOException("Compound editing history was not restored.");
            var caption=model.Captions[0];
            if(!caption.WordEditingSupported)throw new IOException("Aligned word inspector was not enabled.");
            caption.Words[0].Emphasis=true;caption.Words[0].Start=.05;
            model.CustomCaptionStyle=true;model.CaptionSize=64;model.CaptionAnimation="pop";
            await model.SaveEditorCommand.ExecuteAsync(null);
            var wordSaved=await engine.GetAsync("/api/clip/native-smoke-job/0/editor");
            if(wordSaved["project"]!["edits"]!["caption_overrides"]![caption.Id]!["words"]![0]!["emphasis"]!.GetValue<bool>()!=true)throw new IOException("Word emphasis did not persist.");
            // The next save must refuse an externally advanced revision.
            await engine.SendAsync("/api/clip/native-smoke-job/0/editor",new System.Text.Json.Nodes.JsonObject{["revision"]=wordSaved["project"]!["revision"]!.DeepClone(),["edits"]=wordSaved["project"]!["edits"]!.DeepClone()},true);
            await model.SaveEditorCommand.ExecuteAsync(null);
            if(!model.SaveConflict)throw new IOException("Revision conflict was not retained in the native workspace.");
            // Local content is identical here, so clear dirty solely for this automated reload (no dialog).
            model.IsDirty=false;await model.ReloadDraftCommand.ExecuteAsync(null);
            if(model.SaveConflict)throw new IOException("Reload did not resolve the conflict.");
            await model.LoadFeaturesCommand.ExecuteAsync(null);
            if(model.Waveform.Length!=600)throw new IOException("The real audio waveform did not load.");
            model.Segments[0].Start=.5;model.Segments[0].End=3.5;model.CropMode="contain";
            model.AutoPreview=true;model.Captions[0].Text="Native video editor verification";
            if(model.Captions[0].WordEditingSupported)throw new IOException("A rewritten phrase incorrectly retained word editing.");
            deadline=DateTime.UtcNow.AddSeconds(60);
            while(model.IsDirty || model.Busy){if(DateTime.UtcNow>deadline)throw new IOException("Debounced autosave did not finish: "+model.Error);await Task.Delay(100);}
            System.Text.Json.Nodes.JsonObject automaticPreview;
            do
            {
                automaticPreview=await engine.GetAsync("/api/clip/native-smoke-job/0/editor");
                if(automaticPreview["project"]!["status"]!.GetValue<string>()=="preview_ready" && !model.Busy)break;
                if(model.Error.Length>0 || DateTime.UtcNow>deadline)throw new IOException("Automatic rendered preview did not finish: "+model.Error);
                await Task.Delay(100);
            }while(true);
            model.AutoPreview=false;
            if(model.Error.Length>0) throw new IOException(model.Error);
            var saved=await engine.GetAsync("/api/clip/native-smoke-job/0/editor");
            if(saved["project"]!["revision"]!.GetValue<int>()<1) throw new IOException("Draft revision was not persisted.");
            await model.RenderPreviewCommand.ExecuteAsync(null);
            if(model.Error.Length>0) throw new IOException(model.Error);
            await model.RenderFinalCommand.ExecuteAsync(null);
            if(model.Error.Length>0) throw new IOException(model.Error);
            await engine.ExportAsync(model.SelectedClip!.VideoUrl,Path.Combine(directory,"native-export.mp4"));
            await engine.RestartAsync();
            var reopened=await engine.GetAsync("/api/clip/native-smoke-job/0/editor");
            if(reopened["project"]!["edits"]!["crop"]!["mode"]!.GetValue<string>()!="contain") throw new IOException("Saved crop did not survive restart.");
            await model.LoadFeaturesCommand.ExecuteAsync(null);
            await model.RecheckQualityCommand.ExecuteAsync(null);
            await model.LoadQualityCommand.ExecuteAsync(null);
            if(model.QualityRows.Count==0)throw new IOException("Native quality report did not load.");
            await model.RecheckQualityCommand.ExecuteAsync(null);
            await model.LoadRankingCommand.ExecuteAsync(null);
            await model.RescoreRankingCommand.ExecuteAsync(null);
            if(model.Error.Length>0)throw new IOException(model.Error);
            model.SelectedTemplate=model.Templates.First();
            await model.SaveCustomTemplateCommand.ExecuteAsync(null);
            if(model.SelectedTemplate?.Id.StartsWith("custom-",StringComparison.Ordinal)!=true)throw new IOException("Custom template was not persisted.");
            await model.SaveEditorCommand.ExecuteAsync(null);
            await model.ApplyTemplateToProjectCommand.ExecuteAsync(null);
            if(model.Error.Length>0)throw new IOException(model.Error);
            model.SelectedTemplate=null;await model.SaveEditorCommand.ExecuteAsync(null);
            model.ProjectTitle="Native editor workspace verification";model.PreviewRatio="1:1";model.AssetsVisible=false;model.SeekSeconds=1.25;
            await model.SaveEditorCommand.ExecuteAsync(null);
            var workspace=await engine.GetAsync("/api/clip/native-smoke-job/0/editor");
            if(workspace["project"]?["ui"]?["title"]?.GetValue<string>()!=model.ProjectTitle || workspace["project"]?["ui"]?["assets_visible"]?.GetValue<bool>()!=false)throw new IOException("Editor workspace preferences did not save with the checked revision.");
            model.AssetsVisible=true;model.PreviewRatio="9:16";
            model.CustomAudio=true;model.ExportAudioVolume=.5;model.ExportAudioFade=.2;model.ExportAudioNormalize=false;
            model.ExportFolder=directory;model.ExportName="editor-cpu-1080.mp4";model.ExportEncoder="x264";model.ExportQuality="fast";
            await model.RenderExportCommand.ExecuteAsync(null);
            if(model.Error.Length>0 || !File.Exists(model.LastExportPath))throw new IOException("Native CPU export dialog workflow failed: "+model.Error);
            var hardware=await engine.GetAsync("/api/desktop/capabilities");
            if(hardware["nvenc_initialized"]?.GetValue<bool>()==true)
            {
                var musicPath=Path.Combine(directory,"music.wav");var musicStart=new ProcessStartInfo("ffmpeg"){UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true};
                foreach(var arg in new[]{"-nostdin","-y","-v","error","-f","lavfi","-i","sine=frequency=220:duration=3","-c:a","pcm_s16le",musicPath})musicStart.ArgumentList.Add(arg);
                using(var musicProcess=Process.Start(musicStart)!){var musicError=musicProcess.StandardError.ReadToEndAsync();await musicProcess.WaitForExitAsync();await musicError;if(musicProcess.ExitCode!=0)throw new IOException("Music fixture failed.");}
                await model.ImportEditorMediaAsync(musicPath);model.UseSelectedMusicCommand.Execute(null);
                if(model.MusicFile.Length==0)throw new IOException("Imported music did not attach to the real audio mix.");
                model.ExportName="editor-nvenc-1080.mp4";model.ExportEncoder="nvenc";
                await model.RenderExportCommand.ExecuteAsync(null);
                if(model.Error.Length>0 || !File.Exists(model.LastExportPath))throw new IOException("Native NVENC export workflow failed: "+model.Error);
            }
            await model.LoadFeaturesCommand.ExecuteAsync(null);
            if(model.TimelineFrames.Count!=8)throw new IOException("Sampled video filmstrip did not load.");
            var exportWindow=new ExportWindow(model){Owner=window};exportWindow.Show();await Task.Delay(150);
            var exportBitmap=new RenderTargetBitmap((int)exportWindow.ActualWidth,(int)exportWindow.ActualHeight,96,96,PixelFormats.Pbgra32);exportBitmap.Render(exportWindow);var exportImage=new PngBitmapEncoder();exportImage.Frames.Add(BitmapFrame.Create(exportBitmap));using(var file=File.Create(Path.Combine(directory,"wpf-export.png")))exportImage.Save(file);exportWindow.Close();
            foreach(var route in new[]{"AI Clipper","Creative Studio","Publish","Templates"})
            {
                model.Route=route;await Task.Delay(150);
                var screen=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);screen.Render(window);
                var png=new PngBitmapEncoder();png.Frames.Add(BitmapFrame.Create(screen));using var file=File.Create(Path.Combine(directory,"wpf-"+route.Replace(" ","-").ToLowerInvariant()+".png"));png.Save(file);
            }
            model.Route="Video Editor";await Task.Delay(200);
            var view=(LibVLCSharp.WPF.VideoView)window.FindName("VideoView");
            if(window.FindName("PreviewOverlay") is not System.Windows.FrameworkElement overlay || overlay.DataContext!=model || overlay.ActualWidth<=0 || System.Windows.PresentationSource.FromVisual(overlay) is null)throw new IOException("LibVLC foreground overlay did not inherit the editor state.");
            model.Preview.Player.TakeSnapshot(0,Path.Combine(directory,"decoded-preview.png"),0,0);
            var editorBitmap=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);editorBitmap.Render(window);
            var editorEncoder=new PngBitmapEncoder();editorEncoder.Frames.Add(BitmapFrame.Create(editorBitmap));using(var image=File.Create(Path.Combine(directory,"wpf-editor.png")))editorEncoder.Save(image);
            window.Width=1366;window.Height=768;await Task.Delay(200);
            var laptop=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);laptop.Render(window);var laptopEncoder=new PngBitmapEncoder();laptopEncoder.Frames.Add(BitmapFrame.Create(laptop));using(var image=File.Create(Path.Combine(directory,"wpf-editor-laptop.png")))laptopEncoder.Save(image);
            window.Width=1600;window.Height=1000;
            await model.RefreshProjectsCommand.ExecuteAsync(null);
            if(model.Error.Length>0 || model.RecentProjects.Count==0 || model.RecentExports.Count==0 || model.HomeHero is null)throw new IOException("Dashboard could not load real library media.");
            model.HomeSearch="native-smoke-job";
            await Task.Delay(150);
            if(window.FindName("HomeSearchPopup") is not System.Windows.Controls.Primitives.Popup { IsOpen:true,Child:System.Windows.FrameworkElement { DataContext:MainViewModel } })throw new IOException("Dashboard search popup did not bind to the native workspace.");
            if(model.HomeSearchResults.Count==0 || model.RecentProjects.Count!=1)throw new IOException("Dashboard project search failed.");
            model.HomeSearch="unmatched-query-404";
            if(!model.HomeSearchEmpty || model.RecentProjects.Count!=0)throw new IOException("Dashboard empty search was not honest.");
            model.HomeSearch="";
            model.SelectHomePresetCommand.Execute("1");
            if(model.OutputFormat!="vertical" || !model.HomeExportPreset.StartsWith("TikTok"))throw new IOException("Dashboard preset did not configure generation.");
            await model.OpenHomeProjectCommand.ExecuteAsync(model.RecentProjects.First());
            if(!model.IsClipper)throw new IOException("Dashboard project card did not reopen the project.");
            await model.OpenHomeExportCommand.ExecuteAsync(model.RecentExports.First());
            if(!model.IsEditor || model.Error.Length>0)throw new IOException("Dashboard export did not reopen the editor.");
            model.Route="Home";await Task.Delay(200);
            var bitmap=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);bitmap.Render(window);
            var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(bitmap));using(var image=File.Create(Path.Combine(directory,"wpf-shell.png"))) encoder.Save(image);
            window.Width=1120;window.Height=760;await Task.Delay(200);
            var compact=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);compact.Render(window);
            var compactEncoder=new PngBitmapEncoder();compactEncoder.Frames.Add(BitmapFrame.Create(compact));using(var image=File.Create(Path.Combine(directory,"wpf-home-compact.png")))compactEncoder.Save(image);
            report=new { success=true,synthetic=true,nativeMediaImport=true,captionDragging=true,workspacePreferences=true,cpuExport1080=true,nvencExport1080=hardware["nvenc_initialized"]?.GetValue<bool>()==true,libVlcForegroundOverlay=true,sampledFilmstrip=true,nativeExportDialog=true,audioGainAndFades=true,musicStem=hardware["nvenc_initialized"]?.GetValue<bool>()==true,nativeWpf=true,authenticatedApi=true,projectLibrary=true,h264VideoOutput=videoOutputs,seekMilliseconds=seek,nativeCustomTemplates=true,nativeTemplateBatch=true,nativeQualityReports=true,nativeRanking=true,nativeTimelineSave=true,invalidTimestampProtection=true,debouncedAutosave=true,automaticRenderedPreview=true,undoRedo=true,trimGesture=true,reorderDelete=true,alignedWordEdit=true,customCaptionStyle=true,revisionConflict=true,realWaveform=true,captionRendering=true,previewRender=true,finalRender=true,validatedExport=true,projectRestartRestore=true,navigation=model.Navigation,unpaidRequestsOnly=true };
        }
        catch(Exception error) { report=new { success=false,error=error.Message };Environment.ExitCode=1; }
        await File.WriteAllTextAsync(Path.Combine(directory,"result.json"),JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}));
        window.Close();
    }
}
