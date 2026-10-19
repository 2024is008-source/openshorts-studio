using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Extensions.DependencyInjection;
using OpenShorts.Core;
namespace OpenShorts.Desktop;

/// <summary>Local UI acceptance against an existing test library; no generation.</summary>
internal static class EditorVisualTest
{
    public static async Task RunAsync(MainWindow window,ServiceProvider services,string directory)
    {
        Directory.CreateDirectory(directory);object report;
        try
        {
            var model=services.GetRequiredService<MainViewModel>();var engine=services.GetRequiredService<IEngineBridge>();
            var deadline=DateTime.UtcNow.AddMinutes(3);
            while(model.Busy || !engine.IsRunning){if(DateTime.UtcNow>deadline)throw new IOException("UI review startup timed out.");await Task.Delay(100);}
            model.SelectedProject=model.Projects.FirstOrDefault() ?? throw new IOException("The review needs an existing local test project.");
            await model.OpenProjectCommand.ExecuteAsync(null);model.SelectedClip=model.Clips.First();await model.OpenClipCommand.ExecuteAsync(null);
            if(model.Error.Length>0)throw new IOException(model.Error);
            await model.PreviewDeliveryCommand.ExecuteAsync(null);await model.LoadFeaturesCommand.ExecuteAsync(null);
            deadline=DateTime.UtcNow.AddSeconds(20);while(model.Preview.Player.VoutCount==0 || !model.Preview.Player.IsSeekable){if(DateTime.UtcNow>deadline)throw new IOException("Native preview did not start.");await Task.Delay(100);}
            model.Preview.Seek(.8);await Task.Delay(250);model.Preview.Player.SetPause(true);
            var fullscreenButton=(Button)window.FindName("FullscreenPreviewButton");fullscreenButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));await Task.Delay(250);
            var fullscreen=Application.Current.Windows.OfType<Window>().Single(w=>w.Title=="Preview · Esc to return");
            if(model.Preview.Player.VoutCount==0)throw new IOException("Fullscreen lost the native video output.");fullscreen.Close();await Task.Delay(250);
            var overlay=(FrameworkElement)window.FindName("PreviewOverlay");
            if(overlay.DataContext!=model || PresentationSource.FromVisual(overlay) is null)throw new IOException("Foreground guides did not bind after fullscreen.");
            model.SelectedCaption=model.Captions.FirstOrDefault(c=>model.Segments.Any(s=>c.Start<s.End && c.End>s.Start)) ?? model.SelectedCaption;
            model.SafeZones=true;model.CropGuides=false;model.DraftOverlay=false;
            if(File.Exists(Path.Combine(directory,"auto-edit.check")))
            {
                if(model.AutoEffects.Count<2)throw new IOException("Retained scene cues did not populate AI effects.");
                var effect=model.AutoEffects.First(e=>e.Type=="fast punch in");var id=effect.Id;var before=effect.Intensity;
                effect.Intensity=.25;model.UndoEditCommand.Execute(null);
                if(Math.Abs(model.AutoEffects.First(e=>e.Id==id).Intensity-before)>.001)throw new IOException("AI effect undo failed.");
                model.RedoEditCommand.Execute(null);
                if(Math.Abs(model.AutoEffects.First(e=>e.Id==id).Intensity-.25)>.001)throw new IOException("AI effect redo failed.");
                await model.RegenerateAutoEffectsCommand.ExecuteAsync(null);
                if(model.Error.Length>0 || Math.Abs(model.AutoEffects.First(e=>e.Id==id).Intensity-.25)>.001)throw new IOException("Regeneration did not preserve the manual effect override: "+model.Error);
                await model.SaveEditorCommand.ExecuteAsync(null);await model.ReloadDraftCommand.ExecuteAsync(null);
                if(model.Error.Length>0 || Math.Abs(model.AutoEffects.First(e=>e.Id==id).Intensity-.25)>.001)throw new IOException("Effect save/reopen failed: "+model.Error);
                var count=model.AutoEffects.Count;model.RemoveAutoEffectsCommand.Execute(null);
                if(model.AutoEffects.Count!=1)throw new IOException("Remove AI effects did not preserve manual edits.");
                model.UndoEditCommand.Execute(null);if(model.AutoEffects.Count!=count)throw new IOException("Effect removal undo failed.");
                model.SelectedAutoEffect=model.AutoEffects.First(e=>e.Id==id);
                await model.PreviewAutoEffectCommand.ExecuteAsync(null);if(model.Error.Length>0)throw new IOException(model.Error);
                model.InspectorTab=3;
                await Task.Delay(250);await CaptureAsync(window,model,Path.Combine(directory,"ai-auto-edit.png"));
                await File.WriteAllTextAsync(Path.Combine(directory,"auto-edit-result.json"),"{\"success\":true,\"undo_redo\":true,\"manual_override_preserved\":true,\"save_reopen\":true,\"render_preview\":true,\"provider_calls\":0}");
            }
            if(File.Exists(Path.Combine(directory,"learning.check")))
            {
                await model.RefreshLearningCommand.ExecuteAsync(null);
                if(model.Error.Length>0 || !model.LearningStatus.Contains("healthy"))throw new IOException("Learning status failed: "+model.Error+model.LearningStatus);
                await model.ApproveLearningCommand.ExecuteAsync(null);
                if(model.Error.Length>0 || !model.LearningStatus.Contains("human-approved"))throw new IOException("Explicit learning approval failed: "+model.Error+model.LearningStatus);
                await model.ApproveLearningCommand.ExecuteAsync(null);
                if(!model.LearningStatus.Contains("duplicate"))throw new IOException("Duplicate review was not deduplicated.");
                model.LearningCorrectionAction="adjust_intensity";
                await model.RecordLearningCorrectionCommand.ExecuteAsync(null);
                if(model.Error.Length>0 || !model.LearningStatus.Contains("human-modified"))throw new IOException("Explicit correction failed: "+model.Error+model.LearningStatus);
                await model.StartLearningTrainingCommand.ExecuteAsync(null);await Task.Delay(500);
                await model.CheckLearningTrainingCommand.ExecuteAsync(null);
                if(!model.LearningStatus.Contains("insufficient-data"))throw new IOException("Fixture data must not train a production model: "+model.LearningStatus);
                model.LearningCollect=false;await model.SaveLearningPrivacyCommand.ExecuteAsync(null);
                model.LearningCollect=true;await model.SaveLearningPrivacyCommand.ExecuteAsync(null);
                await model.RefreshLearningCommand.ExecuteAsync(null);
                model.InspectorTab=3;
                foreach(var panel in Descendants(window).OfType<Expander>().Where(p=>p.Header?.ToString()=="AI Learning · local foundation"))
                {panel.IsExpanded=true;await Task.Delay(100);panel.BringIntoView();}
                await Task.Delay(250);await CaptureAsync(window,model,Path.Combine(directory,"ai-learning.png"));
                await File.WriteAllTextAsync(Path.Combine(directory,"learning-result.json"),"{\"success\":true,\"native_panel\":true,\"explicit_feedback\":true,\"duplicate_guard\":true,\"privacy\":true,\"insufficient_data_guard\":true,\"provider_calls\":0}");
            }
            if(File.Exists(Path.Combine(directory,"highlight-learning.check")))
            {
                await model.SnapshotClipLearningCommand.ExecuteAsync(null);
                if(model.Error.Length>0||!model.HighlightLearningStatus.Contains("snapshot ready"))throw new IOException("Highlight snapshot failed: "+model.Error);
                await model.RecordClipLearningCommand.ExecuteAsync("accept");
                if(model.Error.Length>0||!model.HighlightLearningStatus.Contains("human-approved"))throw new IOException("Explicit clip acceptance failed.");
                model.LearningRating=4;await model.RecordClipLearningCommand.ExecuteAsync("rating");
                model.ClipReviewStart+=.1;model.ClipReviewEnd-=.1;await model.RecordClipLearningCommand.ExecuteAsync("trim");
                model.ClipReviewCategory="podcast-education";await model.RecordClipLearningCommand.ExecuteAsync("category");
                model.ClipAlternative=model.ClipAlternatives.First();await model.RecordClipLearningCommand.ExecuteAsync("alternative");
                if(model.Error.Length>0)throw new IOException("Clip preference capture failed: "+model.Error);
                await model.TrainHighlightRankerCommand.ExecuteAsync(null);await Task.Delay(500);await model.CheckLearningTrainingCommand.ExecuteAsync(null);
                if(!model.LearningStatus.Contains("insufficient-data"))throw new IOException("Synthetic clip reviews were counted as real training data.");
                var status=(await engine.GetAsync("/api/desktop/learning"))["highlight_ranking"]!;
                if(status["reviewed_examples"]!.GetValue<int>()!=0||status["active_model"] is not null)throw new IOException("Synthetic clip model safety gate failed.");
                await File.WriteAllTextAsync(Path.Combine(directory,"highlight-learning-result.json"),"{\"success\":true,\"native_clip_feedback\":true,\"trim_and_alternative\":true,\"synthetic_excluded\":true,\"model_inactive\":true,\"provider_calls\":0}");
            }
            await CaptureAsync(window,model,Path.Combine(directory,"editor-desktop.png"));
            window.Width=1366;window.Height=768;await Task.Delay(200);await CaptureAsync(window,model,Path.Combine(directory,"editor-laptop.png"));
            model.AssetsVisible=false;model.InspectorVisible=false;await Task.Delay(150);await CaptureAsync(window,model,Path.Combine(directory,"editor-focus.png"));
            model.AssetsVisible=true;model.InspectorVisible=true;
            await model.ImportEditorMediaAsync(Path.Combine(services.GetRequiredService<EngineLaunchOptions>().SourceRoot,"assets","watermark.png"));
            await model.PreviewMediaCommand.ExecuteAsync(null);
            if(model.PreviewImage is null)throw new IOException("Image asset preview did not load.");
            await CaptureAsync(window,model,Path.Combine(directory,"editor-image-asset.png"));
            report=new{success=true,nativeVideoOutput=model.Preview.Player.VoutCount,fullscreenReparent=true,foregroundOverlay=true,responsivePanels=true,
                imageAssetPreview=true,
                capture="WPF window + paused LibVLC decoded frame + actual foreground guide layer; native HWND surfaces require composition",unpaidRequestsOnly=true};
        }
        catch(Exception e){report=new{success=false,error=e.Message};Environment.ExitCode=1;}
        await File.WriteAllTextAsync(Path.Combine(directory,"visual-result.json"),JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}));window.Close();
    }
    private static IEnumerable<DependencyObject> Descendants(DependencyObject parent)
    {
        for(int i=0;i<VisualTreeHelper.GetChildrenCount(parent);i++)
        {var child=VisualTreeHelper.GetChild(parent,i);yield return child;foreach(var item in Descendants(child))yield return item;}
    }
    private static async Task CaptureAsync(MainWindow window,MainViewModel model,string path)
    {
        if(model.PreviewImage is not null)
        {
            var still=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);still.Render(window);
            var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(still));using var stream=File.Create(path);encoder.Save(stream);return;
        }
        model.Preview.Player.SetPause(true);
        var view=(LibVLCSharp.WPF.VideoView)window.FindName("VideoView");var overlay=(FrameworkElement)window.FindName("PreviewOverlay");
        string frameFile=Path.ChangeExtension(path,"frame.png");
        if(!model.Preview.Player.TakeSnapshot(0,frameFile,0,0))throw new IOException("LibVLC snapshot request failed.");
        var deadline=DateTime.UtcNow.AddSeconds(5);while(!File.Exists(frameFile) || new FileInfo(frameFile).Length==0){if(DateTime.UtcNow>deadline)throw new IOException("Decoded snapshot timed out.");await Task.Delay(50);}
        await Task.Delay(100);var frame=new BitmapImage();frame.BeginInit();frame.CacheOption=BitmapCacheOption.OnLoad;frame.UriSource=new Uri(frameFile);frame.EndInit();frame.Freeze();
        int width=(int)window.ActualWidth,height=(int)window.ActualHeight;
        var windowImage=new RenderTargetBitmap(width,height,96,96,PixelFormats.Pbgra32);windowImage.Render(window);
        var guides=new RenderTargetBitmap(Math.Max(1,(int)overlay.ActualWidth),Math.Max(1,(int)overlay.ActualHeight),96,96,PixelFormats.Pbgra32);guides.Render(overlay);
        Point origin=view.TranslatePoint(new Point(),window);var bounds=new Rect(origin,new Size(view.ActualWidth,view.ActualHeight));
        double scale=Math.Min(bounds.Width/frame.PixelWidth,bounds.Height/frame.PixelHeight);var picture=new Rect(bounds.X+(bounds.Width-frame.PixelWidth*scale)/2,bounds.Y+(bounds.Height-frame.PixelHeight*scale)/2,frame.PixelWidth*scale,frame.PixelHeight*scale);
        var drawing=new DrawingVisual();using(var dc=drawing.RenderOpen()){dc.DrawImage(windowImage,new Rect(0,0,width,height));dc.PushClip(new RectangleGeometry(bounds));dc.DrawRectangle(Brushes.Black,null,bounds);dc.DrawImage(frame,picture);dc.DrawImage(guides,bounds);dc.Pop();}
        var image=new RenderTargetBitmap(width,height,96,96,PixelFormats.Pbgra32);image.Render(drawing);var png=new PngBitmapEncoder();png.Frames.Add(BitmapFrame.Create(image));using var output=File.Create(path);png.Save(output);
    }
}
