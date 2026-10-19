using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Text.Json.Nodes;
using System.Windows.Data;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using OpenShorts.Core;
using OpenShorts.EngineBridge;
namespace OpenShorts.Desktop;

public sealed partial class ReviewRow(ReviewRecord record) : ObservableObject
{
    public ReviewRecord Record {get;}=record;
    public int Rank {get;set;}
    [ObservableProperty] private bool marked;
    [ObservableProperty] private string? thumbnail;
    [ObservableProperty] private string exportState="";
    [ObservableProperty] private double exportProgress;
}
public partial class MainViewModel
{
    [ObservableProperty] private string clipperMode="progress";
    [ObservableProperty] private string generationState="idle";
    [ObservableProperty] private string generationStage="Import a video to begin";
    [ObservableProperty] private string generationElapsed="Not recorded";
    [ObservableProperty] private string generationFailure="";
    [ObservableProperty] private string generationSourceTitle="No source selected";
    [ObservableProperty] private string generationSourceDetails="";
    [ObservableProperty] private string? generationThumbnail;
    [ObservableProperty] private string generationSettingsSummary="";
    [ObservableProperty] private ReviewRow? reviewSelected;
    [ObservableProperty] private string reviewSort="Score";
    [ObservableProperty] private string reviewTag="All tags";
    [ObservableProperty] private string reviewNotice="";
    [ObservableProperty] private string generationWarning="";
    [ObservableProperty] private string reviewPreviewKind="Choose a clip to preview";
    [ObservableProperty] private bool reviewIncludeCaptions=true;
    [ObservableProperty] private int reviewVolume=80;
    private int reviewRevision;
    private JsonArray reviewHistory=[];
    private bool restoringReview;
    private bool reviewSaveConflict;
    private string? reviewExportRoute;
    private bool reviewCancelRequested;
    private CancellationTokenSource? reviewPreviewCancellation;
    private readonly SemaphoreSlim reviewSaveLock=new(1,1);
    private string? reviewJob;
    private double editorPlayheadBeforeReview;
    partial void OnRouteChanging(string value){if(IsEditor && value!="Video Editor")editorPlayheadBeforeReview=SeekSeconds;}
    public ObservableCollection<GenerationStage> GenerationStages {get;}=[];
    public ObservableCollection<string> GenerationDiagnostics {get;}=[];
    public ObservableCollection<ReviewRow> ReviewRows {get;}=[];
    public ObservableCollection<string> ReviewTags {get;}=["All tags"];
    public string[] ReviewSorts {get;}=["Score","Shortest","Longest","Source position"];
    public ICollectionView ReviewView=>CollectionViewSource.GetDefaultView(ReviewRows);
    public bool ClipperSettings=>ClipperMode=="settings";
    public bool ClipperProcessing=>ClipperMode is "progress" or "settings";
    public bool ClipperReview=>ClipperMode=="review";
    public bool GenerationActive=>GenerationState is "preparing" or "running" or "cancel_requested";
    public bool GenerationCanReturn=>!Busy;
    public bool GenerationHasFailure=>GenerationFailure.Length>0;
    public string GenerationTitle=>GenerationState switch {"idle"=>GenerationHasSource?"Video Ready":"AI Clipper Preview","failed"=>"Generation failed","cancelled"=>"Generation cancelled","cancel_requested"=>"Cancelling generation",_=>"Generating Clips"};
    public string GenerationActivity=>$"{GenerationState} · {GenerationStage}";
    public string ReviewCount=>$"{ReviewRows.Count(r=>r.Record.Ready)} clips ready · {ReviewRows.Count(r=>!r.Record.Ready)} unavailable / not rendered";
    public bool CanReviewExport=>!Busy && ReviewRows.Any(r=>r.Record.Ready);
    public string GenerationWorkflow=>ClipperReview && GenerationState!="completed"?"✓ Select video    ━    ✓ Settings    ━    Generation stopped    ━    Saved clips":ClipperReview?"✓ Select video    ━    ✓ Settings    ━    ✓ Generating    ━    4 Review":GenerationState is "failed" or "cancelled"?"✓ Select video    ━    ✓ Settings    ━    Generation stopped    ━    Review pending":"✓ Select video    ━    ✓ Settings    ━    3 Generating    ━    Review pending";
    partial void OnClipperModeChanged(string value){foreach(string p in new[]{nameof(ClipperSettings),nameof(ClipperProcessing),nameof(ClipperReview),nameof(GenerationWorkflow),nameof(GenerationIdle),nameof(GenerationDescription),nameof(GenerationStepCaption),nameof(GenerationHasSource),nameof(GenerationSourceStatus),nameof(GenerationSourceHint),nameof(SelectVideoStep),nameof(SettingsStep)})OnPropertyChanged(p);}
    partial void OnGenerationStateChanged(string value){NotifyReferenceReview();foreach(string p in new[]{nameof(GenerationActive),nameof(GenerationTitle),nameof(GenerationActivity),nameof(GenerationWorkflow),nameof(GenerationIdle),nameof(GenerationDescription),nameof(GenerationStepCaption),nameof(GenerationHasSource),nameof(GenerationSourceStatus),nameof(GenerationSourceHint),nameof(SelectVideoStep),nameof(SettingsStep)})OnPropertyChanged(p);}
    partial void OnGenerationStageChanged(string value)=>OnPropertyChanged(nameof(GenerationActivity));
    partial void OnGenerationFailureChanged(string value)=>OnPropertyChanged(nameof(GenerationHasFailure));
    partial void OnReviewVolumeChanged(int value)=>Preview.Player.Volume=Math.Clamp(value,0,100);
    partial void OnReviewSortChanged(string value){RefreshReviewView();QueueReviewSave();}
    partial void OnReviewTagChanged(string value){RefreshReviewView();QueueReviewSave();}
    partial void OnReviewSelectedChanged(ReviewRow? value)
    {
        OnPropertyChanged(nameof(ReviewSeekMinimum));OnPropertyChanged(nameof(ReviewSeekMaximum));
        NotifyReferenceReview();if(value is null)return;
        _=LoadReviewOptionsAsync(value);
        SelectedClip=new(reviewJob!,value.Record.Index,value.Record.Title,value.Record.VideoUrl,value.Record.Start,value.Record.End,value.Record.ScoreLabel);
        ExportName=$"OpenShorts-clip-{value.Record.Index+1}.mp4";
        if(!restoringReview){QueueReviewSave();_=PreviewReviewAsync(value);}
    }
    private void NotifyReviewCommands()
    {
        OnPropertyChanged(nameof(CanReviewExport));OnPropertyChanged(nameof(GenerationCanReturn));
        ExportReviewSelectedCommand.NotifyCanExecuteChanged();ExportReviewAllCommand.NotifyCanExecuteChanged();RetryReviewExportsCommand.NotifyCanExecuteChanged();ApplyReviewStylesCommand.NotifyCanExecuteChanged();ReturnGenerationSettingsCommand.NotifyCanExecuteChanged();
    }
    private void RefreshReviewView()
    {
        var view=ReviewView;view.Filter=o=>o is ReviewRow row && (ReviewTag=="All tags" || row.Record.Tags.Split(" · ").Contains(ReviewTag));
        view.SortDescriptions.Clear();
        view.SortDescriptions.Add(ReviewSort switch {"Shortest"=>new("Record.Duration",ListSortDirection.Ascending),"Longest"=>new("Record.Duration",ListSortDirection.Descending),"Source position"=>new("Record.Start",ListSortDirection.Ascending),_=>new("Record.Score",ListSortDirection.Descending)});
    }
    private async Task<JsonObject> ReadClipperAsync(string route,CancellationToken token=default)
    {
        using var bounded=CancellationTokenSource.CreateLinkedTokenSource(token);bounded.CancelAfter(TimeSpan.FromSeconds(30));
        try{return await engine.GetAsync(route,bounded.Token);}
        catch(OperationCanceledException) when(!token.IsCancellationRequested){throw new IOException("The engine did not respond. Reopen Projects to recover saved work.");}
    }
    private async Task RunGenerationAsync(CancellationToken token)
    {
        if(!await FlushDraftAsync(token))return;
        reviewPreviewCancellation?.Cancel();jobId=null;reviewJob=null;ReviewSelected=null;ReviewRows.Clear();Clips.Clear();OnPropertyChanged(nameof(ReviewCount));ClipperMode="progress";GenerationState="preparing";GenerationFailure="";GenerationElapsed="Starting…";
        GenerationStage="Submitting source";GenerationStages.Clear();GenerationDiagnostics.Clear();Preview.Player.SetPause(true);
        GenerationSourceTitle=readySource?.Title is {Length:>0} title?title:Path.GetFileName(ImportedFile);
        GenerationSourceDetails=readySource is not null?$"{readySource.Description} · {readySource.Format}":"Source metadata unavailable";GenerationThumbnail=readySource?.Thumbnail;
        var settings=CaptureGenerationSettings();SetGenerationSettingRows(settings);
        GenerationSettingsSummary=$"DURATION\n{(settings.AutoDuration?"Automatic":$"{settings.TargetSeconds:0} seconds")}\n\nASPECT RATIO\n{settings.OutputFormat}\n\nGENERATION / ANALYSIS\n{settings.Mode} · {settings.Analysis}\n\nSTORY / FRAMING\n{settings.Pacing} · {settings.Framing}\n\nCAPTIONS\n{(settings.Captions?settings.CaptionPreset:settings.SourceHasCaptions?"Already in source":"Disabled")}\n\nQUALITY / AUDIO\n{settings.Quality} · {settings.AudioPreset}\n\nCLIP COUNT\n{(settings.AutoCount?"Automatic":settings.TargetClips.ToString())}";
        try
        {
            Status="Submitting video for AI analysis…";jobId=await SubmitGeneration(token);
            while(true)
            {
                var data=await ReadClipperAsync($"/api/desktop/jobs/{jobId}/progress",token);ApplyGenerationProgress(data);
                if(GenerationState is "completed" or "failed" or "cancelled")break;
                await Task.Delay(1500,token);
            }
            var review=await engine.GetAsync($"/api/desktop/jobs/{jobId}/review",token);
            if((review["clips"]?.AsArray() ?? []).Count>0)await LoadReviewAsync(jobId,review,token,GenerationState=="completed");
            if(GenerationState=="completed" && !ReviewRows.Any(r=>r.Record.Ready))
            {ClipperMode="progress";GenerationState="failed";GenerationFailure="The worker completed without an available validated clip. Reopen the project after checking media storage.";}
            await LoadProjects(token);
        }
        catch(OperationCanceledException){GenerationState="cancelled";throw;}
        catch(Exception failure){if(App.DiagnosticDirectory is not null)File.WriteAllText(Path.Combine(App.DiagnosticDirectory,"generation-transition-error.txt"),failure.ToString());GenerationState="failed";GenerationFailure="The engine connection or job submission failed. Reopen Projects to recover completed work before starting another paid analysis.";throw new IOException(GenerationFailure);}
        finally{CancellationAvailable=false;}
    }
    internal void ApplyGenerationProgress(JsonObject data)
    {
        var snapshot=GenerationProgress.Parse(data);GenerationState=snapshot.State;GenerationStage=snapshot.Stage;
        GenerationWarning=data["analysis"]?["warning"]?.GetValue<string>() ?? "";
        if(data["category"] is JsonObject category)
            GenerationWarning+=$" Category: {category["primary_category"]} / {category["subcategory"]} · {category["source"]} · {category["classification_method"]} · review required: {category["review_required"]} · editing profile: {category["active_editing_profile"]}.";
        if(snapshot.Stage=="Analyzing content with Gemini" && data["analysis_chapter"] is JsonObject chapter)
            GenerationStage+=chapter["completed"] is not null?$" · {chapter["completed"]}/{chapter["total"]} chapters complete":$" · chapter {chapter["current"]}/{chapter["total"]}";
        GenerationFailure=snapshot.Error ?? "";GenerationElapsed=snapshot.Elapsed is double e?TimeSpan.FromSeconds(e).ToString(@"hh\:mm\:ss"):"Not recorded";
        ProgressUnknown=snapshot.Overall is null;Progress=snapshot.Overall ?? 0;CancellationAvailable=snapshot.CanCancel;
        if(!GenerationStages.SequenceEqual(snapshot.Stages)){GenerationStages.Clear();foreach(var stage in snapshot.Stages)GenerationStages.Add(stage);}
        NotifyReferenceReview();OnPropertyChanged(nameof(GenerationStepsPercent));OnPropertyChanged(nameof(GenerationSurfaceHeight));
        if(!GenerationDiagnostics.SequenceEqual(snapshot.Diagnostics)){GenerationDiagnostics.Clear();foreach(var line in snapshot.Diagnostics)GenerationDiagnostics.Add(line);}
        Status=GenerationFailure.Length>0?GenerationFailure:$"{GenerationState} · {GenerationStage}";
    }
    private async Task LoadReviewAsync(string identity,JsonObject data,CancellationToken token,bool show=true)
    {
        reviewPreviewCancellation?.Cancel();restoringReview=true;reviewSaveConflict=false;reviewJob=identity;jobId=identity;
        try
        {
            var preferences=data["preferences"]?.AsObject() ?? new();reviewRevision=preferences["revision"]?.GetValue<int>() ?? 0;
            reviewHistory=(JsonArray)(preferences["history"]?.DeepClone() ?? new JsonArray());
            var selected=(preferences["selected"]?.AsArray() ?? []).Select(n=>n!.GetValue<int>()).ToHashSet();
            ReviewSelected=null;ReviewRows.Clear();Clips.Clear();ReviewTags.Clear();ReviewTags.Add("All tags");
            var records=(data["clips"]?.AsArray() ?? []).Select(n=>ReviewRecord.Parse(n!.AsObject())).OrderByDescending(r=>r.Score ?? -1).ToArray();
            int rank=0;foreach(var record in records)
            {
                var row=new ReviewRow(record){Rank=++rank,Marked=selected.Contains(record.Index)};
                row.PropertyChanged+=(_,e)=>{if(e.PropertyName==nameof(ReviewRow.Marked))QueueReviewSave();};ReviewRows.Add(row);
                foreach(string tag in record.Tags.Split(" · ",StringSplitOptions.RemoveEmptyEntries))if(!ReviewTags.Contains(tag))ReviewTags.Add(tag);
                if(record.Ready)Clips.Add(new(identity,record.Index,record.Title,record.VideoUrl,record.Start,record.End,record.ScoreLabel));
            }
            ReviewSort=preferences["sort"]?.ToString() ?? "Score";ReviewTag=preferences["tag"]?.ToString() ?? "All tags";if(!ReviewTags.Contains(ReviewTag))ReviewTag="All tags";
            GenerationSourceTitle=data["source_title"]?.ToString() ?? "Imported video";
            if(data["progress"] is JsonObject progress)ApplyGenerationProgress(progress);
            ReviewNotice=GenerationWarning.Length>0?GenerationWarning:ReviewCount;OnPropertyChanged(nameof(ReviewCount));RefreshReviewView();
            ReviewSelected=ReviewRows.FirstOrDefault(r=>r.Record.Index==preferences["active"]?.GetValue<int>()) ?? ReviewRows.FirstOrDefault(r=>r.Record.Ready && selected.Contains(r.Record.Index)) ?? ReviewRows.FirstOrDefault(r=>r.Record.Ready) ?? ReviewRows.FirstOrDefault();
            if(show)ClipperMode="review";ReviewCompletionVisible=true;NotifyReviewCommands();NotifyReferenceReview();
        }
        finally{restoringReview=false;}
        if(show && ReviewSelected is not null)await PreviewReviewAsync(ReviewSelected);
        _=LoadReviewThumbnailsAsync(identity,ReviewRows.ToArray());
    }
    private async Task LoadReviewThumbnailsAsync(string identity,ReviewRow[] rows)
    {
        foreach(var row in rows.Where(r=>r.Record.Ready))
        {
            if(reviewJob!=identity || !ClipperReview)return;
            try{var data=await ReadClipperAsync($"/api/desktop/jobs/{identity}/clips/{row.Record.Index}/thumbnail");if(data["path"]?.ToString() is {Length:>0} path)row.Thumbnail=storage.ValidateProjectMedia(path);}
            catch{ /* A thumbnail is optional; never replace a valid clip with a placeholder record. */ }
        }
    }
    private async Task PreviewReviewAsync(ReviewRow row)
    {
        if(!IsClipper || !ClipperReview || Busy && reviewExportRoute is not null)return;
        reviewPreviewCancellation?.Cancel();reviewPreviewCancellation?.Dispose();reviewPreviewCancellation=new();var token=reviewPreviewCancellation.Token;
        Preview.Player.SetPause(true);ReviewPreviewKind="Loading preview…";
        try
        {
            var route=row.Record.Ready?$"/api/desktop/media/{reviewJob}/{row.Record.Index}":$"/api/desktop/source/{reviewJob}";
            var data=await engine.GetAsync(route,token);string path=storage.ValidateProjectMedia(data["path"]!.ToString());
            bool updatedPreview=false;
            if(row.Record.Ready)
            {
                var project=(await engine.GetAsync($"/api/clip/{reviewJob}/{row.Record.Index}/editor",token))["project"]!.AsObject();
                if(project["status"]?.ToString() is "completed" or "preview_ready" && project["result"]?["mode"]?.ToString()=="preview" && JsonNode.DeepEquals(project["result"]?["revision"],project["revision"]))
                {path=ReviewResultPath(project);updatedPreview=true;}
            }
            if(token.IsCancellationRequested || ReviewSelected!=row || !IsClipper)return;
            Preview.Open(path);sourcePreview=false;Preview.Player.Volume=ReviewVolume;
            ReviewPreviewKind=updatedPreview?"Updated rendered preview · saved framing, captions and audio":row.Record.Ready?"Rendered MP4 · includes its saved rendered captions":"Source segment only · framing and captions are not rendered";
            if(!row.Record.Ready)
            {
                for(int i=0;i<40 && !Preview.Player.IsSeekable;i++)await Task.Delay(50,token);
                if(ReviewSelected==row)Preview.Seek(row.Record.Start);
            }
        }
        catch(OperationCanceledException){}
        catch{if(ReviewSelected==row){Preview.Player.Stop();ReviewPreviewKind="Preview media is missing or unavailable. Reimport the source to recover it.";}}
    }
    internal void UpdateReviewPlayback()
    {
        RefreshReferenceMemory();
        OnPropertyChanged(nameof(ReviewSeekMaximum));
        if(IsClipper && ClipperReview && ReviewSelected is {Record.Ready:false} row && Preview.Player.Time/1000d>=row.Record.End)Preview.Player.SetPause(true);
    }
    internal void PauseReviewRequests(){reviewPreviewCancellation?.Cancel();}
    private async void QueueReviewSave()=>await SaveReviewPreferencesAsync();
    private async Task SaveReviewPreferencesAsync()
    {
        if(restoringReview || reviewSaveConflict || reviewJob is null)return;
        string identity=reviewJob;
        await reviewSaveLock.WaitAsync();
        try
        {
            if(reviewJob!=identity || reviewSaveConflict)return;
            var state=new JsonObject{["revision"]=reviewRevision,["selected"]=new JsonArray(ReviewRows.Where(r=>r.Marked).Select(r=>(JsonNode?)JsonValue.Create(r.Record.Index)).ToArray()),["active"]=ReviewSelected is null?null:JsonValue.Create(ReviewSelected.Record.Index),["sort"]=ReviewSort,["tag"]=ReviewTag,["history"]=reviewHistory.DeepClone()};
            var saved=await engine.SendAsync($"/api/desktop/jobs/{identity}/review",state,put:true);if(reviewJob==identity)reviewRevision=saved["revision"]!.GetValue<int>();
        }
        catch{reviewSaveConflict=true;ReviewNotice="Review preferences could not be saved or changed elsewhere. Reopen the project before saving more changes.";}
        finally{reviewSaveLock.Release();}
    }
    public double ReviewSeekMinimum=>ReviewSelected is {Record.Ready:false} row?row.Record.Start:0;
    public double ReviewSeekMaximum=>ReviewSelected is {Record.Ready:false} row?row.Record.End:DurationSeconds;
    [RelayCommand] private void ReviewPlayPause()
    {
        if(ReviewSelected is {Record.Ready:false} row && (Preview.Player.Time/1000d<row.Record.Start || Preview.Player.Time/1000d>=row.Record.End))Preview.Seek(row.Record.Start);
        PlayPause();
    }
    [RelayCommand] private void RunGenerationBackground()=>Route="Home";
    [RelayCommand(CanExecute=nameof(GenerationCanReturn))] private void ReturnGenerationSettings()=>ClipperMode="progress";
    [RelayCommand] private void ShowSavedGenerationClips(){if(ReviewRows.Count>0)ClipperMode="review";}
    [RelayCommand] private async Task PreviewReview(ReviewRow? row){if(row is null)return;if(ReviewSelected==row)await PreviewReviewAsync(row);else ReviewSelected=row;}
    [RelayCommand] private async Task EditReview(ReviewRow? row)
    {if(Busy || row is null || !row.Record.Ready)return;ReviewSelected=row;await OpenClipCommand.ExecuteAsync(null);}
    [RelayCommand] private void CopyReviewTitle(ReviewRow? row)
    {
        if(row is null)return;
        try{System.Windows.Clipboard.SetText(row.Record.Title);ReviewNotice="Clip title copied.";}
        catch{ReviewNotice="The clipboard is unavailable. Try again.";}
    }
    [RelayCommand] private void CopyReviewHook(ReviewRow? row)
    {
        if(row is null || string.IsNullOrWhiteSpace(row.Record.Hook))return;
        try{System.Windows.Clipboard.SetText(row.Record.Hook);ReviewNotice="Generated hook copied.";}
        catch{ReviewNotice="The clipboard is unavailable. Try again.";}
    }
    [RelayCommand] private async Task ReloadReview()
    {if(Busy || reviewJob is null)return;await Guard(async token=>await LoadReviewAsync(reviewJob,await engine.GetAsync($"/api/desktop/jobs/{reviewJob}/review",token),token));}
    [RelayCommand] private async Task ExportReviewOne(ReviewRow? row)
    {if(row is not null && row.Record.Ready && !Busy){ReviewSelected=row;await ExportReviewBatchAsync([row]);}}
    [RelayCommand(CanExecute=nameof(CanReviewExport))] private Task ExportReviewSelected()=>ExportReviewBatchAsync(ReviewRows.Where(r=>r.Record.Ready && r.Marked).DefaultIfEmpty(ReviewSelected!).Where(r=>r is not null && r.Record.Ready).ToArray());
    [RelayCommand(CanExecute=nameof(CanReviewExport))] private Task ExportReviewAll()=>ExportReviewBatchAsync(ReviewRows.Where(r=>r.Record.Ready).ToArray());
    [RelayCommand(CanExecute=nameof(CanReviewExport))] private Task RetryReviewExports()=>ExportReviewBatchAsync(ReviewRows.Where(r=>r.Record.Ready && r.ExportState.StartsWith("Failed")).ToArray());
    private Task ExportReviewBatchAsync(ReviewRow[] rows)=>Guard(async token=>
    {
        if(rows.Length==0){ReviewNotice="Select one or more available clips.";return;}
        if(!await FlushDraftAsync(token))return;
        int index=Array.IndexOf(ExportSizes,ExportSize);int[][] sizes=[[1080,1920],[1080,1080],[1920,1080],[720,1280],[1280,720]];
        if(index<0)throw new ArgumentException("Choose a supported export size.");
        var options=new JsonObject{["encoder"]=ExportEncoder,["quality"]=ExportQuality};
        if(index<sizes.Length)options["size"]=new JsonArray(sizes[index].Select(n=>(JsonNode?)JsonValue.Create(n)).ToArray());
        if(ExportFrameRate!="Source")options["fps"]=int.Parse(ExportFrameRate,System.Globalization.CultureInfo.InvariantCulture);
        string folder=ExportFolder,name=ExportName;bool captions=ReviewIncludeCaptions;reviewCancelRequested=false;
        var exporter=new ReviewExportClient(engine);int done=0,failed=0;
        foreach(var row in rows)row.ExportState="Queued";
        foreach(var row in rows)
        {
            if(reviewCancelRequested || token.IsCancellationRequested)break;
            row.ExportState="Rendering";Preview.Player.SetPause(true);
            try
            {
                string fileName=rows.Length==1?name:$"{Path.GetFileNameWithoutExtension(name)}-{row.Record.Index+1}.mp4";
                string destination=ReviewExportClient.VersionedPath(folder,fileName);
                await exporter.ExportAsync(reviewJob!,row.Record.Index,options,captions,destination,(value,label)=>{row.ExportProgress=value;Progress=Math.Clamp(value,0,100);ProgressUnknown=false;Status=$"Clip {row.Record.Index+1} · {label}";},route=>{reviewExportRoute=route;CancellationAvailable=route is not null;},token);
                row.ExportState="Exported · "+Path.GetFileName(destination);LastExportPath=destination;done++;
                reviewHistory.Add(new JsonObject{["index"]=row.Record.Index,["status"]="completed",["name"]=Path.GetFileName(destination),["at"]=DateTimeOffset.UtcNow.ToString("O")});
            }
            catch(OperationCanceledException){row.ExportState="Cancelled";reviewCancelRequested=true;}
            catch{row.ExportState="Failed · inspect saved timeline or reload conflicting revision";failed++;reviewHistory.Add(new JsonObject{["index"]=row.Record.Index,["status"]="failed",["name"]="",["at"]=DateTimeOffset.UtcNow.ToString("O")});}
        }
        foreach(var row in rows.Where(r=>r.ExportState=="Queued"))row.ExportState="Cancelled before export";
        while(reviewHistory.Count>500)reviewHistory.RemoveAt(0);await SaveReviewPreferencesAsync();
        ReviewNotice=$"Export finished · {done} saved · {failed} failed"+(reviewCancelRequested?" · cancelled":"");Status=ReviewNotice;
        await LoadProjects(token);
        var exportStates=ReviewRows.ToDictionary(r=>r.Record.Index,r=>(r.ExportState,r.ExportProgress));
        string notice=ReviewNotice;
        if(editor is not null && editingClip is not null && rows.Any(r=>r.Record.Index==editingClip.Index && editingClip.JobId==reviewJob))
            ApplyEditor(await engine.GetAsync(EditorRoute,token));
        await LoadReviewAsync(reviewJob!,await engine.GetAsync($"/api/desktop/jobs/{reviewJob}/review",token),token);
        foreach(var row in ReviewRows)if(exportStates.TryGetValue(row.Record.Index,out var state)){row.ExportState=state.ExportState;row.ExportProgress=state.ExportProgress;}
        ExportName=name;ReviewNotice=notice;Status=notice;
    });
}
