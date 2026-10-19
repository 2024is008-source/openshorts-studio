using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using OpenShorts.Core;

namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    public ObservableCollection<ReportRow> QualityRows { get; }=[];
    public ObservableCollection<ReportRow> RankingRows { get; }=[];
    public ObservableCollection<SceneRow> SceneRows { get; }=[];
    public ObservableCollection<WeightRow> RankingWeights { get; }=new(new[]{("hook",25d),("story",25d),("engagement",20d),("visual",15d),("pacing",10d),("ending",5d)}.Select(x=>new WeightRow(x.Item1,x.Item2)));
    [ObservableProperty] private string qualitySummary="Load a clip report to review export quality.";
    [ObservableProperty] private string hookText="";
    [ObservableProperty] private double hookStart;
    [ObservableProperty] private double hookDuration=3;
    [ObservableProperty] private string hookStyle="classic";
    [ObservableProperty] private string hookPosition="top";
    [ObservableProperty] private string hookSize="M";
    [ObservableProperty] private string hookAnimation="fade";
    [ObservableProperty] private string hookContext="Load a source-backed suggestion or quote the retained speech.";
    [ObservableProperty] private string templateHeadline="";
    [ObservableProperty] private double headlineStart;
    [ObservableProperty] private double headlineEnd=3;
    [ObservableProperty] private string directorSummary="Load the saved director plan for this clip.";
    public string[] HookStyles { get; }=["classic","dark","yellow","red","outline","outline_yellow"];
    public string[] HookPositions { get; }=["top","center","bottom"];
    public string[] HookAnimations { get; }=["none","fade","scale-pop","slide-up","spring","highlight-reveal"];
    public string[] HookSizes { get; }=["S","M","L"];
    private ClipItem CurrentClip=>editingClip ?? SelectedClip ?? throw new IOException("Open a clip first.");
    private string ClipRoute=>$"/api/clip/{CurrentClip.JobId}/{CurrentClip.Index}";
    private JsonObject ClipRequest()=>new(){["job_id"]=CurrentClip.JobId,["clip_index"]=CurrentClip.Index};
    private bool CanUseClipTools=>CanEdit && !SaveConflict;
    private static string Pretty(JsonNode? value)=>value is JsonValue ? value.ToString() : value?.ToJsonString(new JsonSerializerOptions{WriteIndented=true}) ?? "Not available";
    private static void Report(ObservableCollection<ReportRow> rows,JsonNode? data)
    {
        rows.Clear();if(data is JsonObject obj)foreach(var pair in obj)rows.Add(new(pair.Key.Replace('_',' '),Pretty(pair.Value)));
    }
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task LoadQuality()=>Guard(async token=>
    {
        var data=await engine.GetAsync(ClipRoute+"/quality",token);var report=data["quality_report"];
        QualitySummary=report?["status"]?.ToString() ?? "No quality report. Run validation or render final.";Report(QualityRows,report);
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task RecheckQuality()=>Guard(async token=>
    {
        var data=await engine.SendAsync(ClipRoute+"/quality",new JsonObject{["force"]=true},cancellationToken:token);
        QualitySummary=data["quality_report"]?["status"]?.ToString() ?? data["status"]?.ToString() ?? "Validation finished";Report(QualityRows,data["quality_report"] ?? data);
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task LoadRanking()=>Guard(async token=>
    {
        var data=await engine.GetAsync($"/api/jobs/{CurrentClip.JobId}/ranking",token);ApplyRanking(data);
    });
    private void ApplyRanking(JsonObject data)
    {
        var score=data["scores"]?.AsArray().FirstOrDefault(n=>n?["clip_index"]?.GetValue<int>()==CurrentClip.Index);
        Report(RankingRows,score?["ranking_report"]);
    }
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task RescoreRanking()=>Guard(async token=>
    {
        var weights=new JsonObject();foreach(var row in RankingWeights)
        {if(!double.IsFinite(row.Value)||row.Value<0||row.Value>100)throw new ArgumentException("Weights must be between 0 and 100.");weights[row.Name]=row.Value;}
        if(RankingWeights.Sum(w=>w.Value)<=0)throw new ArgumentException("Set at least one positive weight.");
        ApplyRanking(await engine.SendAsync($"/api/jobs/{CurrentClip.JobId}/ranking/rescore",new JsonObject{["weights"]=weights},cancellationToken:token));
        Status="Ranking updated. Scores are advisory; media was preserved.";
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task SuggestHook()=>Guard(async token=>
    {
        var data=await engine.GetAsync(ClipRoute+"/hooks",token);HookContext=data["message"]?.ToString() ?? data["context"]?.ToString() ?? "";
        if(data["suggestion"] is JsonObject h){HookText=h["text"]?.ToString() ?? "";HookStart=h["start"]?.GetValue<double>() ?? 0;HookDuration=(h["end"]?.GetValue<double>() ?? 3)-HookStart;}
    });
    private JsonObject HookRequest(bool remove=false)
    {
        var data=ClipRequest();data["text"]=HookText;data["start_seconds"]=HookStart;data["duration_seconds"]=HookDuration;
        data["style"]=HookStyle;data["position"]=HookPosition;data["size"]=HookSize;data["animation"]=HookAnimation;data["remove"]=remove;return data;
    }
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task PreviewHook()=>Guard(async token=>
    {
        await Save(token);var data=await engine.SendAsync("/api/hook/preview",HookRequest(),cancellationToken:token);await OpenToolPreview(data,token);
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task ApplyHook()=>ApplyClipTool("/api/hook",HookRequest());
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task RemoveHook()=>ApplyClipTool("/api/hook",HookRequest(true));
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task RemoveCaptions()=>ApplyClipTool("/api/subtitle/remove",ClipRequest());
    private Task ApplyClipTool(string route,JsonObject body)=>Guard(async token=>
    {
        await RenderCore("final",token);
        if(editor?["status"]?.ToString()!="completed")throw new IOException("Finish the timeline render before applying this clip operation.");
        var data=await engine.SendAsync(route,body,cancellationToken:token);
        var media=await engine.GetAsync($"/api/desktop/media/{CurrentClip.JobId}/{CurrentClip.Index}",token);
        Preview.Open(storage.ValidateProjectMedia(media["path"]!.GetValue<string>()));sourcePreview=false;
        if(data["new_video_url"] is JsonValue value){editingClip=CurrentClip with{VideoUrl=value.GetValue<string>()};SelectedClip=editingClip;}
        ApplyEditor(await engine.GetAsync(EditorRoute,token));Status="Clip updated. Export this version, or use Reset to delivered clip before further timeline edits.";
    });
    private async Task OpenToolPreview(JsonObject data,CancellationToken token)
    {
        var url=(data["video_url"] ?? data["new_video_url"])?.GetValue<string>() ?? throw new IOException("No preview was returned.");
        // Tool preview URLs may include a cache-busting query; only use the validated local path.
        var path=new Uri("http://127.0.0.1"+url).AbsolutePath;
        if(!path.StartsWith($"/videos/{CurrentClip.JobId}/",StringComparison.Ordinal))throw new IOException("Invalid preview location.");
        path=Uri.UnescapeDataString(path[8..]);
        Preview.Open(storage.ValidateProjectMedia(Path.Combine(storage.Library,"output",path.Replace('/',Path.DirectorySeparatorChar))));sourcePreview=false;
        await Task.CompletedTask;
    }
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task LoadScenes()=>Guard(async token=>
    {
        var data=await engine.GetAsync(ClipRoute+"/scenes",token);SceneRows.Clear();
        foreach(var row in data["scenes"]?.AsArray() ?? [])SceneRows.Add(new(row!["index"]!.GetValue<int>(),row["start"]!.GetValue<double>(),row["end"]!.GetValue<double>(),row["suggested_center"]?.GetValue<double>() ?? .5));
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task ApplySceneCrops()
    {
        var overrides=new JsonObject();foreach(var scene in SceneRows)
        {if(!double.IsFinite(scene.Center)||scene.Center<0||scene.Center>1){Error="Scene centers must be from 0 to 1.";return Task.CompletedTask;}overrides[scene.Index.ToString()]=scene.Center;}
        var body=ClipRequest();body["crop_overrides"]=overrides;body["reapply_captions"]=true;return ApplyClipTool("/api/clip/reframe",body);
    }
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task LoadDirector()=>Guard(async token=>
    {
        var data=await engine.GetAsync(EditorRoute+"/director",token);DirectorSummary=Pretty(data["plan"]);
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task PreviewDirector()=>Guard(async token=>
    {
        var data=await engine.SendAsync(EditorRoute+"/director-preview",new(),cancellationToken:token);await OpenToolPreview(data,token);
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task ExportAll()=>Guard(async token=>
    {
        var dialog=new SaveFileDialog{Filter="ZIP archive|*.zip",FileName="OpenShorts-clips.zip",AddExtension=true};
        if(dialog.ShowDialog()==true)await engine.ExportAsync($"/api/jobs/{CurrentClip.JobId}/download-all",dialog.FileName,token);
    });
    private bool CanPolish=>CanUseClipTools && ProviderActionsAuthorized;
    [RelayCommand(CanExecute=nameof(CanPolish))] private Task AiPolish()=>ApplyClipTool("/api/edit",ClipRequest());
    [RelayCommand(CanExecute=nameof(CanImport))] private Task ResetDeliveredDraft()=>Guard(async token=>
    {
        if(!HasEditor)throw new IOException("Open a clip first.");
        if(System.Windows.MessageBox.Show("Reset the timeline draft to the current delivered clip? This replaces saved draft decisions. The delivered video is kept.","Reset draft",System.Windows.MessageBoxButton.OKCancel)!=System.Windows.MessageBoxResult.OK)return;
        var latest=await engine.GetAsync(EditorRoute,token);
        ApplyEditor(await engine.SendAsync(EditorRoute+"/reset",new JsonObject{["revision"]=latest["project"]!["revision"]!.DeepClone()},cancellationToken:token));
    });
    private void NotifyClipTools()
    {
        foreach(var command in new IRelayCommand[]{LoadQualityCommand,RecheckQualityCommand,LoadRankingCommand,RescoreRankingCommand,SuggestHookCommand,PreviewHookCommand,ApplyHookCommand,RemoveHookCommand,RemoveCaptionsCommand,LoadScenesCommand,ApplySceneCropsCommand,LoadDirectorCommand,PreviewDirectorCommand,ExportAllCommand})command.NotifyCanExecuteChanged();
        AiPolishCommand.NotifyCanExecuteChanged();ResetDeliveredDraftCommand.NotifyCanExecuteChanged();SaveCustomTemplateCommand.NotifyCanExecuteChanged();LoadProjectTemplatesCommand.NotifyCanExecuteChanged();ApplyTemplateToProjectCommand.NotifyCanExecuteChanged();
        OnPropertyChanged(nameof(CanUseClipTools));
    }
}
public sealed record ReportRow(string Name,string Value);
public partial class WeightRow(string name,double value) : ObservableObject
{public string Name { get; }=name;[ObservableProperty]private double value=value;}
public partial class SceneRow(int index,double start,double end,double center) : ObservableObject
{public int Index { get; }=index;public double Start { get; }=start;public double End { get; }=end;[ObservableProperty]private double center=center;}
