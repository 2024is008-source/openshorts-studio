using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Extensions.DependencyInjection;
using OpenShorts.Core;
using OpenShorts.EngineBridge;
namespace OpenShorts.Desktop;
internal static class TranscriptionLiveTest
{
 internal static async Task RunAsync(MainWindow window,ServiceProvider services,string directory,string video,string sourceRoot)
 {
  var model=services.GetRequiredService<MainViewModel>();var engine=services.GetRequiredService<IEngineBridge>();var store=services.GetRequiredService<IUserStorage>();
  try
  {
   var deadline=DateTime.UtcNow.AddMinutes(15);
   while(model.Busy || !engine.IsRunning){if(model.Error.Length>0 || DateTime.UtcNow>deadline)throw new IOException("Engine startup failed.");await Task.Delay(200);}
   var source=await new VideoImportClient(engine).RunAsync("local",video,_=>{});model.AcceptImportedSource(source,video);
   var env=new Dictionary<string,string>();foreach(var name in new[]{"SYSTEMROOT","WINDIR","PATH","USERPROFILE","LOCALAPPDATA","APPDATA","PROGRAMDATA","PROGRAMFILES","NUMBER_OF_PROCESSORS"})if(Environment.GetEnvironmentVariable(name) is string value)env[name]=value;
   env["PYTHONUTF8"]="1";env["PYTHON_DOTENV_DISABLED"]="1";env["TEMP"]=env["TMP"]=Path.Combine(store.Library,"temp");
   using var worker=services.GetRequiredService<IWorkerLauncher>().Start(Path.Combine(sourceRoot,".venv","Scripts","python.exe"),[Path.Combine(sourceRoot,"tools","check_live_transcription.py"),"--video",video,"--output",directory],sourceRoot,env);
   var captured=new HashSet<string>();
   while(true)
   {
    if(DateTime.UtcNow>deadline)throw new IOException("Local transcription exceeded the diagnostic deadline.");
    JsonObject? data=null;try{if(File.Exists(Path.Combine(directory,"live-progress.json")))data=JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(directory,"live-progress.json")))?.AsObject();}catch(IOException){}
    if(data is not null)
    {
     model.ApplyGenerationProgress(data);window.UpdateLayout();
     var stage=model.GenerationStages.First(s=>s.Title=="Transcribing audio");string key=stage.Percent?.ToString("0") ?? "starting";
     if(captured.Add(key))Capture(window,Path.Combine(directory,"transcription-"+key+".png"));
     if(stage.Percent==100 && stage.State!="completed")throw new IOException("Transcription remains active at 100%.");
    }
    if(worker.HasExited)break;
    await Task.Delay(200);
   }
   var report=JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(directory,"asr-result.json")))!.AsObject();
   if(report["success"]?.GetValue<bool>()!=true)throw new IOException(report["error"]?.ToString() ?? "Local ASR failed.");
   model.ApplyGenerationProgress(JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(directory,"live-progress.json")))!.AsObject());
   Capture(window,Path.Combine(directory,"transcription-complete.png"));report["nativeUiVerified"]=true;report["capturedPercentages"]=new JsonArray(captured.Select(s=>(JsonNode)JsonValue.Create(s)!).ToArray());
   await File.WriteAllTextAsync(Path.Combine(directory,"result.json"),report.ToJsonString());
  }
  catch(Exception error){await File.WriteAllTextAsync(Path.Combine(directory,"result.json"),new JsonObject{["success"]=false,["error"]=error.Message}.ToJsonString());}
  window.Close();
 }
 private static void Capture(MainWindow window,string file)
 {
  window.UpdateLayout();var bitmap=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);bitmap.Render(window);var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(bitmap));using var output=File.Create(file);encoder.Save(output);
 }
}
