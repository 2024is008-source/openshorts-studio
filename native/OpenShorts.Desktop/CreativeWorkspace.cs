using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;

namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    [ObservableProperty] private string creativeTab="Thumbnails";
    [ObservableProperty] private string thumbnailSource="";
    [ObservableProperty] private string thumbnailSession="";
    [ObservableProperty] private string thumbnailTitle="";
    [ObservableProperty] private string thumbnailPrompt="";
    [ObservableProperty] private string thumbnailFace="";
    [ObservableProperty] private string thumbnailBackground="";
    [ObservableProperty] private string titleRefinement="";
    [ObservableProperty] private int thumbnailCount=2;
    [ObservableProperty] private string creativeStatus="Select a source or enter a title. AI actions use your configured providers.";
    [ObservableProperty] private string? selectedThumbnail;
    public ObservableCollection<string> ThumbnailTitles { get; }=[];
    public ObservableCollection<string> ThumbnailImages { get; }=[];
    [ObservableProperty] private bool providerActionsAuthorized;
    [ObservableProperty] private string productUrl="";
    [ObservableProperty] private string productDescription="";
    [ObservableProperty] private string actorDescription="";
    [ObservableProperty] private string voiceId="";
    [ObservableProperty] private VoiceOption? selectedVoice;
    [ObservableProperty] private string selectedActorUrl="";
    public ObservableCollection<VoiceOption> Voices { get; }=[];
    partial void OnSelectedVoiceChanged(VoiceOption? value){if(value is not null)VoiceId=value.Id;}
    [ObservableProperty] private string ugcMode="lowcost";
    [ObservableProperty] private ScriptRow? selectedScript;
    [ObservableProperty] private string ugcNarration="";
    [ObservableProperty] private string ugcResult="";
    [ObservableProperty] private string targetLanguage="es";
    public string[] UgcModes { get; }=["lowcost","premium"];
    public string[] DubLanguages { get; }=["en","es","fr","de","it","pt","pl","hi","ja","ko","zh","ar","ru","tr","nl","sv","id","fil","ms","vi","th","uk","el","cs","fi","ro","da","bg","hr","sk","ta"];
    public ObservableCollection<ScriptRow> UgcScripts { get; }=[];
    private MediaPreview? creativePreview;
    public MediaPreview CreativePreview=>creativePreview ??= new();
    private string? ugcVideoUrl;
    public string PendingElevenLabs { private get; set; }="";
    public string PendingFal { private get; set; }="";
    public string PendingUploadPost { private get; set; }="";
    private bool CanCreativeAction=>!Busy && ProviderActionsAuthorized;
    partial void OnProviderActionsAuthorizedChanged(bool value){NotifyCreativeCommands();NotifyPublishingCommands();NotifyClipTools();}
    partial void OnSelectedScriptChanged(ScriptRow? value)=>UgcNarration=value?.Definition["full_narration"]?.ToString() ?? "";
    [RelayCommand] private void SaveProviderCredentials()
    {
        try
        {
            // Empty password fields preserve existing secrets; explicit Clear removes them.
            if(PendingElevenLabs.Length>0)storage.SaveCredential(PendingElevenLabs.Trim(),"elevenlabs");
            if(PendingFal.Length>0)storage.SaveCredential(PendingFal.Trim(),"fal");
            if(PendingUploadPost.Length>0)storage.SaveCredential(PendingUploadPost.Trim(),"uploadpost");
            PendingElevenLabs=PendingFal=PendingUploadPost="";CredentialStatus="Provider credentials protected with Windows DPAPI.";
        }
        catch(Exception){Error="Provider credentials could not be saved.";}
    }
    [RelayCommand] private void ClearProviderCredentials()
    {try{foreach(var provider in new[]{"elevenlabs","fal","uploadpost"})storage.SaveCredential("",provider);CredentialStatus="Additional provider credentials removed.";}catch{Error="Provider credentials could not be removed.";}}
    private Dictionary<string,string> ProviderHeaders(params string[] providers)
    {
        var headers=new Dictionary<string,string>();foreach(var p in providers)
        {var key=storage.LoadCredential(p);if(key.Length==0)throw new IOException($"Add your {p} key in Settings first.");headers[p=="fal"?"X-Fal-Key":p=="elevenlabs"?"X-ElevenLabs-Key":"X-Upload-Post-Key"]=key;}
        return headers;
    }
    [RelayCommand(CanExecute=nameof(CanImport))] private void BrowseThumbnailSource()
    {var dialog=new OpenFileDialog{Filter="Video|*.mp4;*.mov;*.mkv;*.webm"};if(dialog.ShowDialog()==true)ThumbnailSource=dialog.FileName;}
    private static string? PickImage(){var dialog=new OpenFileDialog{Filter="Images|*.png;*.jpg;*.jpeg;*.webp"};return dialog.ShowDialog()==true?dialog.FileName:null;}
    [RelayCommand(CanExecute=nameof(CanImport))] private void ChooseThumbnailFace(){if(PickImage() is string path)ThumbnailFace=path;}
    [RelayCommand(CanExecute=nameof(CanImport))] private void ChooseThumbnailBackground(){if(PickImage() is string path)ThumbnailBackground=path;}
    [RelayCommand] private void ClearThumbnailReferences(){ThumbnailFace="";ThumbnailBackground="";}
    [RelayCommand(CanExecute=nameof(CanCreativeAction))] private Task RefineThumbnailTitles()=>Guard(async token=>
    {
        if(ThumbnailSession.Length==0 || string.IsNullOrWhiteSpace(TitleRefinement))throw new ArgumentException("Analyze a video and enter title feedback first.");
        var data=await engine.SendAsync("/api/thumbnail/titles",new JsonObject{["session_id"]=ThumbnailSession,["message"]=TitleRefinement},cancellationToken:token);
        ThumbnailTitles.Clear();foreach(var title in data["titles"]?.AsArray() ?? [])ThumbnailTitles.Add(title!.ToString());ThumbnailTitle=ThumbnailTitles.FirstOrDefault() ?? ThumbnailTitle;
    });
    [RelayCommand(CanExecute=nameof(CanCreativeAction))] private Task AnalyzeThumbnail()=>Guard(async token=>
    {
        if(!File.Exists(ThumbnailSource))throw new IOException("Choose a video for thumbnail analysis.");
        var data=await engine.FormAsync("/api/thumbnail/analyze",new Dictionary<string,string>(),ThumbnailSource,token);
        ThumbnailSession=data["session_id"]!.GetValue<string>();ThumbnailTitles.Clear();foreach(var title in data["titles"]?.AsArray() ?? [])ThumbnailTitles.Add(title!.ToString());
        ThumbnailTitle=ThumbnailTitles.FirstOrDefault() ?? "";CreativeStatus="Titles ready. Choose a title and generate images.";
    });
    [RelayCommand(CanExecute=nameof(CanCreativeAction))] private Task GenerateThumbnails()=>Guard(async token=>
    {
        if(string.IsNullOrWhiteSpace(ThumbnailTitle))throw new ArgumentException("Enter a thumbnail title.");
        if(ThumbnailCount<1 || ThumbnailCount>6)throw new ArgumentException("Choose one to six thumbnails.");
        if(ThumbnailSession.Length==0)
        {var session=await engine.SendAsync("/api/thumbnail/titles",new JsonObject{["title"]=ThumbnailTitle},cancellationToken:token);ThumbnailSession=session["session_id"]!.GetValue<string>();}
        var images=new Dictionary<string,string>();if(ThumbnailFace.Length>0)images["face"]=ThumbnailFace;if(ThumbnailBackground.Length>0)images["background"]=ThumbnailBackground;
        var data=await engine.FormAsync("/api/thumbnail/generate",new Dictionary<string,string>{["session_id"]=ThumbnailSession,["title"]=ThumbnailTitle,["extra_prompt"]=ThumbnailPrompt,["count"]=ThumbnailCount.ToString(),["burn_text"]="true"},cancellationToken:token,images:images);
        ThumbnailImages.Clear();foreach(var row in data["thumbnails"]?.AsArray() ?? [])
        {
            var url=row is JsonObject ? row["url"]?.GetValue<string>() : row?.GetValue<string>();if(url is null)continue;
            if(!url.StartsWith("/thumbnails/",StringComparison.Ordinal))continue;
            var relative=Uri.UnescapeDataString(url[12..]);
            ThumbnailImages.Add(storage.ValidateProjectMedia(Path.Combine(storage.Library,"output","thumbnails",relative.Replace('/',Path.DirectorySeparatorChar))));
        }
        SelectedThumbnail=ThumbnailImages.FirstOrDefault();CreativeStatus=$"{ThumbnailImages.Count} generated images available.";
    });
    [RelayCommand(CanExecute=nameof(CanImport))] private void SaveThumbnail()
    {
        try
        {if(SelectedThumbnail is null)return;var dialog=new SaveFileDialog{Filter="PNG image|*.png",FileName="OpenShorts-thumbnail.png"};
        if(dialog.ShowDialog()==true)File.Copy(storage.ValidateProjectMedia(SelectedThumbnail),dialog.FileName,true);}
        catch{Error="The selected thumbnail could not be saved.";}
    }
    [RelayCommand(CanExecute=nameof(CanCreativeAction))] private Task AnalyzeProduct()=>Guard(async token=>
    {
        var data=await engine.SendAsync("/api/saasshorts/analyze",new JsonObject{["url"]=ProductUrl,["description"]=ProductDescription,["num_scripts"]=3,["style"]="ugc",["language"]="en",["actor_gender"]="female"},cancellationToken:token);
        UgcScripts.Clear();int i=0;foreach(var row in data["scripts"]?.AsArray() ?? [])if(row is JsonObject script)UgcScripts.Add(new($"Script {++i}",(JsonObject)script.DeepClone()));
        SelectedScript=UgcScripts.FirstOrDefault();CreativeStatus="Scripts ready. Review the narration before generating.";
    });
    [RelayCommand(CanExecute=nameof(CanImport))] private Task LoadVoices()=>Guard(async token=>
    {
        var key=storage.LoadCredential("elevenlabs");
        var data=await engine.GetAsync("/api/saasshorts/voices",token,key.Length==0?null:new Dictionary<string,string>{["X-ElevenLabs-Key"]=key});
        Voices.Clear();foreach(var row in data["voices"]?.AsArray() ?? [])Voices.Add(new(row!["voice_id"]!.ToString(),row["name"]!.ToString()));SelectedVoice=Voices.FirstOrDefault();
    });
    [RelayCommand(CanExecute=nameof(CanImport))] private Task UploadActor()=>Guard(async token=>
    {
        if(PickImage() is not string path)return;
        if(new FileInfo(path).Length>25L*1024*1024)throw new IOException("Actor images must be below 25 MB.");
        var data=await engine.FormAsync("/api/saasshorts/actor-upload",new Dictionary<string,string>(),path,token);SelectedActorUrl=data["url"]!.GetValue<string>();CreativeStatus="Actor reference uploaded to this local workspace.";
    });
    [RelayCommand(CanExecute=nameof(CanCreativeAction))] private Task GenerateUgc()=>Guard(async token=>
    {
        if(SelectedScript is null)throw new IOException("Generate and select a script first.");
        var headers=ProviderHeaders("fal","elevenlabs");var script=(JsonObject)SelectedScript.Definition.DeepClone();script["full_narration"]=UgcNarration;
        var data=await engine.SendAsync("/api/saasshorts/generate",new JsonObject{["script"]=script,["actor_description"]=ActorDescription,["selected_actor_url"]=SelectedActorUrl.Length>0?SelectedActorUrl:null,["voice_id"]=VoiceId.Length>0?VoiceId:null,["video_mode"]=UgcMode,["share_to_gallery"]=false},cancellationToken:token,providerHeaders:headers);
        var id=OpenShorts.EngineBridge.EngineClient.JobId(data["job_id"]!.GetValue<string>());
        while(true)
        {
            var state=await engine.GetAsync($"/api/saasshorts/status/{id}",token);CreativeStatus=state["logs"]?.AsArray().LastOrDefault()?.ToString() ?? state["status"]!.ToString();
            if(state["status"]!.ToString() is "completed" or "failed")
            {
                UgcResult=Pretty(state["result"]);if(state["status"]!.ToString()=="failed")throw new IOException("UGC generation failed. Check provider configuration.");
                ugcVideoUrl=state["result"]?["video_url"]?.GetValue<string>();
                if(ugcVideoUrl is not null && ugcVideoUrl.StartsWith($"/videos/saas_{id}/",StringComparison.Ordinal))
                    CreativePreview.Open(storage.ValidateProjectMedia(Path.Combine(storage.Library,"output",Uri.UnescapeDataString(ugcVideoUrl[8..]).Replace('/',Path.DirectorySeparatorChar))));
                break;
            }
            await Task.Delay(1500,token);
        }
    });
    [RelayCommand(CanExecute=nameof(CanCreativeAction))] private Task DubClip()=>Guard(async token=>
    {
        if(!HasEditor)throw new IOException("Open a clip in the editor first.");
        if(!await FlushDraftAsync(token))return;
        var body=ClipRequest();body["target_language"]=TargetLanguage;
        var data=await engine.SendAsync("/api/translate",body,cancellationToken:token,providerHeaders:ProviderHeaders("elevenlabs"));
        await OpenToolPreview(data,token);
        if(data["new_video_url"] is JsonValue url){editingClip=CurrentClip with{VideoUrl=url.GetValue<string>()};SelectedClip=editingClip;}
        ApplyEditor(await engine.GetAsync(EditorRoute,token));UgcResult=Pretty(data);CreativeStatus="Dubbed clip ready in the editor. Review the translated audio before exporting.";Route="Video Editor";
    });
    [RelayCommand(CanExecute=nameof(CanImport))] private Task ExportUgc()=>Guard(async token=>
    {
        if(ugcVideoUrl is null)throw new IOException("Generate a product video first.");
        var dialog=new SaveFileDialog{Filter="MP4 video|*.mp4",FileName="OpenShorts-product-video.mp4"};
        if(dialog.ShowDialog()==true)await engine.ExportAsync(ugcVideoUrl,dialog.FileName,token);
    });
    public void PauseCreativePlayback(){if(creativePreview is not null)creativePreview.Player.SetPause(true);}
    [RelayCommand] private void PlayCreativeVideo()=>CreativePreview.Player.SetPause(CreativePreview.Player.IsPlaying);
    private void StopCreativePreview(){creativePreview?.Dispose();creativePreview=null;}
    private void NotifyCreativeCommands()
    {foreach(var c in new IRelayCommand[]{AnalyzeThumbnailCommand,GenerateThumbnailsCommand,AnalyzeProductCommand,GenerateUgcCommand,DubClipCommand,BrowseThumbnailSourceCommand,SaveThumbnailCommand,ExportUgcCommand,LoadVoicesCommand,UploadActorCommand,ChooseThumbnailFaceCommand,ChooseThumbnailBackgroundCommand,RefineThumbnailTitlesCommand})c.NotifyCanExecuteChanged();}
}
public sealed record ScriptRow(string Name,JsonObject Definition);
public sealed record VoiceOption(string Id,string Name);
