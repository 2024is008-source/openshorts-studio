using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.Logging;
using Microsoft.Win32;
using OpenShorts.Core;
using OpenShorts.EngineBridge;

namespace OpenShorts.Desktop;

public partial class MainViewModel : ObservableObject
{
    private readonly IEngineBridge engine;
    private readonly IUserStorage storage;
    private readonly ILogger<MainViewModel> logger;
    public MediaPreview Preview { get; }
    private JsonObject? editor;
    private ClipItem? editingClip;
    private bool sourcePreview;
    private string? editorSourcePath;
    private readonly Dictionary<string,(double Start,double End,string Text)> captionBaseline=[];
    private string? jobId;
    public string? ActiveJobId => jobId;
    private bool editorRunning;
    private CancellationTokenSource operation = new();
    public ObservableCollection<string> Navigation { get; } = new(["Home","Projects","AI Clipper","Video Editor","Creative Studio","Publish","Templates","Settings","Account"]);
    public string[] PrimaryNav { get; } = ["Home","Projects","AI Clipper","Video Editor","Templates","Creative Studio","Publish"];
    public string[] BottomNav { get; } = ["Settings","Account"];
    public ObservableCollection<ProjectItem> Projects { get; } = [];
    public ObservableCollection<ClipItem> Clips { get; } = [];
    public ObservableCollection<TemplateItem> Templates { get; } = [];
    public ObservableCollection<SegmentRow> Segments { get; } = [];
    public ObservableCollection<CaptionRow> Captions { get; } = [];
    public string[] Encoders { get; } = ["auto","x264","nvenc"];
    public string[] Presets { get; } = ["quiet","balanced","performance"];
    public string[] CropModes { get; } = ["preserve","crop","contain"];
    public string[] CaptionPresets { get; } = ["clean-minimal","bold-creator","dynamic-highlight","podcast","cinematic","openshorts-dynamic","creator-bold","clean-podcast","minimal","green-pop","teal-reveal","paper-focus"];
    public string[] CaptionPositions { get; } = ["top","middle","bottom"];
    [ObservableProperty] private string route = "Home";
    [ObservableProperty] private string status = "Starting the local engine...";
    [ObservableProperty] private string error = "";
    [ObservableProperty] private bool busy;
    [ObservableProperty] private string importedFile = "";
    [ObservableProperty] private bool acknowledged;
    [ObservableProperty] private ProjectItem? selectedProject;
    [ObservableProperty] private ClipItem? selectedClip;
    [ObservableProperty] private SegmentRow? selectedSegment;
    [ObservableProperty] private TemplateItem? selectedTemplate;
    [ObservableProperty] private string encoder = "auto";
    [ObservableProperty] private string preset = "balanced";
    [ObservableProperty] private string credentialStatus = "";
    [ObservableProperty] private string hardware = "Hardware detection has not run yet.";
    [ObservableProperty] private string cropMode = "preserve";
    [ObservableProperty] private double cropX = .5;
    [ObservableProperty] private double cropY = .5;
    [ObservableProperty] private bool captionsEnabled = true;
    [ObservableProperty] private string captionPreset = "clean-minimal";
    [ObservableProperty] private string captionPosition = "bottom";
    [ObservableProperty] private double seekSeconds;
    [ObservableProperty] private double durationSeconds;
    [ObservableProperty] private double progress;
    [ObservableProperty] private bool progressUnknown = true;
    [ObservableProperty] private string editorSummary = "Open a generated clip to edit its saved timeline.";
    [ObservableProperty] private bool hasInputError;
    [ObservableProperty] private bool cancellationAvailable;
    public string PendingCredential { private get; set; } = "";
    public string Library => storage.Library;
    public bool IsHome => Route == "Home";
    public bool IsProjects => Route == "Projects";
    public bool IsClipper => Route == "AI Clipper";
    public bool IsEditor => Route == "Video Editor";
    public bool IsPublishing => Route == "Publish";
    public bool IsCreative => Route == "Creative Studio";
    public bool IsTemplates => Route == "Templates";
    public bool IsSettings => Route == "Settings";
    public bool IsAccount => Route == "Account";
    public bool HasEditor => editor is not null;
    public bool CanStart => !Busy && (ImportedFile.Length > 0 || SourceUrl.Length>0) && Acknowledged && engine.IsRunning && !HasInputError;
    public bool CanOpenClip => !Busy && SelectedClip is not null;
    public bool CanOpenProject => !Busy && SelectedProject is not null;
    public bool CanEdit => !Busy && HasEditor && !HasInputError && !EditorStale;
    public bool CanRemoveVideoRange=>CanEdit && SelectedSegment is not null && Segments.Count>1;
    partial void OnSelectedSegmentChanged(SegmentRow? value)=>RemoveSegmentCommand.NotifyCanExecuteChanged();
    public bool CanCancel => Busy && CancellationAvailable;
    public bool CanExport => !Busy && SelectedClip is not null;
    public bool CanImport => !Busy;
    public double TimelineSeconds
    {
        get
        {
            if(!sourcePreview)return SeekSeconds;
            double offset=0;
            foreach(var segment in Segments)
            { if(segment==SelectedSegment && SeekSeconds>=segment.Start && SeekSeconds<=segment.End)return offset+SeekSeconds-segment.Start;offset+=segment.End-segment.Start; }
            return 0;
        }
    }
    partial void OnSeekSecondsChanged(double value)=>OnPropertyChanged(nameof(TimelineSeconds));
    public void SeekTimeline(double value)
    {
        double offset=0,target=value;
        if(sourcePreview)foreach(var segment in Segments)
        { if(value<=offset+segment.End-segment.Start){SelectedSegment=segment;target=segment.Start+value-offset;break;}offset+=segment.End-segment.Start; }
        Preview.Seek(target);SeekSeconds=target;
    }

    public MainViewModel(IEngineBridge engine, IUserStorage storage, MediaPreview preview, ILogger<MainViewModel> logger)
    {
        this.engine=engine; this.storage=storage; Preview=preview; this.logger=logger;
        InitializeEditing();InitializeAutoEdit();PrepareClipperPreview();
        ConfigureStudioViews();
        var settings=storage.LoadSettings(); Encoder=settings.Encoder; Preset=settings.Preset;
        try { PendingCredential=storage.LoadCredential(); CredentialStatus=PendingCredential.Length>0 ? "Gemini key is protected by Windows." : "Add your Gemini key to enable AI analysis."; }
        catch { CredentialStatus="Your saved key could not be decrypted. Enter it again."; }
    }
    partial void OnRouteChanged(string value)
    { foreach (var name in new[]{nameof(IsHome),nameof(IsProjects),nameof(IsClipper),nameof(IsEditor),nameof(IsNotEditor),nameof(IsPublishing),nameof(IsCreative),nameof(IsTemplates),nameof(IsSettings),nameof(IsAccount)}) OnPropertyChanged(name); }
    partial void OnBusyChanged(bool value) {NotifyCommands();NotifyReviewCommands();}
    partial void OnHasInputErrorChanged(bool value)=>NotifyCommands();
    partial void OnCancellationAvailableChanged(bool value) { OnPropertyChanged(nameof(CanCancel));CancelCommand.NotifyCanExecuteChanged(); }
    partial void OnImportedFileChanged(string value) => NotifyCommands();
    partial void OnAcknowledgedChanged(bool value) => NotifyCommands();
    partial void OnSelectedProjectChanged(ProjectItem? value) => NotifyCommands();
    partial void OnSelectedClipChanged(ClipItem? value) => NotifyCommands();
    private void NotifyCommands()
    {
        foreach(var name in new[]{nameof(CanStart),nameof(CanOpenClip),nameof(CanOpenProject),nameof(CanEdit),nameof(CanCancel),nameof(CanExport),nameof(CanImport),nameof(HasEditor)}) OnPropertyChanged(name);
        StartClippingCommand.NotifyCanExecuteChanged(); OpenClipCommand.NotifyCanExecuteChanged(); OpenProjectCommand.NotifyCanExecuteChanged();
        SaveEditorCommand.NotifyCanExecuteChanged(); RenderPreviewCommand.NotifyCanExecuteChanged(); RenderFinalCommand.NotifyCanExecuteChanged();
        CancelCommand.NotifyCanExecuteChanged(); ExportCommand.NotifyCanExecuteChanged(); ImportCommand.NotifyCanExecuteChanged(); ReviewClippingSettingsCommand.NotifyCanExecuteChanged();
        AddSegmentCommand.NotifyCanExecuteChanged(); RemoveSegmentCommand.NotifyCanExecuteChanged(); SplitSegmentCommand.NotifyCanExecuteChanged();
        MoveUpCommand.NotifyCanExecuteChanged(); MoveDownCommand.NotifyCanExecuteChanged();
        UndoEditCommand.NotifyCanExecuteChanged(); RedoEditCommand.NotifyCanExecuteChanged(); LoadFeaturesCommand.NotifyCanExecuteChanged(); ReloadDraftCommand.NotifyCanExecuteChanged();
        RegenerateAutoEffectsCommand.NotifyCanExecuteChanged();RemoveAutoEffectsCommand.NotifyCanExecuteChanged();RemoveSelectedAutoEffectCommand.NotifyCanExecuteChanged();PreviewAutoEffectCommand.NotifyCanExecuteChanged();
        NotifyClipTools();NotifyCreativeCommands();NotifyPublishingCommands();
        RestartEngineCommand.NotifyCanExecuteChanged();RefreshProjectsCommand.NotifyCanExecuteChanged();DetectHardwareCommand.NotifyCanExecuteChanged();
        OpenHomeProjectCommand.NotifyCanExecuteChanged();OpenHomeExportCommand.NotifyCanExecuteChanged();OpenHomeSearchCommand.NotifyCanExecuteChanged();
        NotifyStudioCommands();
        OnPropertyChanged(nameof(CanRenderExport));RenderExportCommand.NotifyCanExecuteChanged();
    }
    private async Task Guard(Func<CancellationToken,Task> action)
    {
        if(Busy) return;
        operation.Dispose(); operation=new(); CancellationAvailable=false; Busy=true; Error="";
        try { await action(operation.Token); }
        catch(OperationCanceledException) { Status="Operation cancelled. Saved files were kept."; }
        catch(Exception e) { Error=e is IOException or ArgumentException ? e.Message : "The operation failed. Check the engine status and retry."; logger.LogError(new EventId(201),e,"Desktop operation failed"); }
        finally { CancellationAvailable=false;Busy=false; ProgressUnknown=true; }
    }
    public Task InitializeAsync() => Guard(async token =>
    {
        await engine.StartAsync(token); Status="Engine online · one processing job at a time";
        await LoadProjects(token);
        var data=await engine.GetAsync("/api/desktop/templates",token);
        Templates.Clear();
        foreach(var row in data["templates"]?.AsArray() ?? []) if(row is JsonObject template)
            Templates.Add(new(template["id"]!.GetValue<string>(),template["name"]!.GetValue<string>(),(JsonObject)template.DeepClone()));
        FilterHome();UpdateHomeHardware(await engine.GetAsync("/api/desktop/capabilities",token));
        NotifyCommands();
    });
    [RelayCommand(CanExecute=nameof(CanImport))] private Task RestartEngine() => Guard(async token => { Preview.Player.Stop(); await engine.RestartAsync(token); Status="Engine restarted. Existing project files were preserved."; await LoadProjects(token); });
    [RelayCommand(CanExecute=nameof(CanImport))] private Task RefreshProjects() => Guard(LoadProjects);
    private async Task LoadProjects(CancellationToken token)
    {
        var data=await engine.GetAsync("/api/desktop/projects",token); Projects.Clear();
        foreach(var item in data["projects"]?.AsArray() ?? [])
        { var id=EngineClient.JobId(item!["job_id"]!.GetValue<string>()); Projects.Add(new(id,item["clips"]!.GetValue<int>(),item["status"]!.GetValue<string>(),DateTimeOffset.FromUnixTimeSeconds((long)item["modified"]!.GetValue<double>()).LocalDateTime)); }
        await LoadHome(token);
    }
    [RelayCommand(CanExecute=nameof(CanImport))] private Task Import(){OpenImportDialog();return Task.CompletedTask;}
    public Task ImportFileAsync(string path)=>Guard(async token=>
    {
        if(!engine.IsRunning)await engine.StartAsync(token);
        var media=await new VideoImportClient(engine).RunAsync("local",path,cancellationToken:token);
        AcceptImportedSource(media,path);
    });
    [RelayCommand(CanExecute=nameof(CanStart))] private Task StartClipping() => Guard(RunGenerationAsync);
    private void SetClips(string id,JsonObject result)
    {
        var selected=SelectedClip?.Index; Clips.Clear(); int i=0;
        foreach(var clip in result["clips"]?.AsArray() ?? [])
        {
            var index=clip!["clip_index"]?.GetValue<int>() ?? i;
            Clips.Add(new(id,index,clip["title"]?.GetValue<string>() ?? $"Clip {index+1}",clip["video_url"]?.GetValue<string>() ?? "",clip["start"]?.GetValue<double>() ?? 0,clip["end"]?.GetValue<double>() ?? 0,clip["ranking_report"]?["overall"]?.ToString() ?? clip["selection_score"]?.ToString() ?? "Unscored")); i++;
        }
        SelectedClip=Clips.FirstOrDefault(c=>c.Index==selected) ?? Clips.FirstOrDefault();LoadInsights(id,result);
    }
    [RelayCommand(CanExecute=nameof(CanOpenProject))] private Task OpenProject() => Guard(async token =>
    {
        var id=EngineClient.JobId(SelectedProject!.JobId); var data=await engine.SendAsync($"/api/desktop/projects/{id}/restore",new(),cancellationToken:token);
        jobId=id; Route="AI Clipper"; await LoadReviewAsync(id,await engine.GetAsync($"/api/desktop/jobs/{id}/review",token),token); Status="Project reopened from this PC.";
    });
    private string EditorRoute => $"/api/clip/{EngineClient.JobId((editingClip ?? SelectedClip)!.JobId)}/{(editingClip ?? SelectedClip)!.Index}/editor";
    [RelayCommand(CanExecute=nameof(CanOpenClip))] private Task OpenClip() => Guard(async token =>
    {
        if(!await FlushDraftAsync(token)) return;
        editingClip=SelectedClip;PreviewImage=null;
        var data=await engine.GetAsync(EditorRoute,token); ApplyEditor(data);
        var media=await engine.GetAsync($"/api/desktop/media/{editingClip!.JobId}/{editingClip.Index}",token);
        if(data["source_available"]?.GetValue<bool>()==true)
        { media=await engine.GetAsync($"/api/desktop/source/{editingClip.JobId}",token);sourcePreview=true;editorSourcePath=storage.ValidateProjectMedia(media["path"]!.GetValue<string>()); }
        else { sourcePreview=false;editorSourcePath=null; }
        Preview.Open(storage.ValidateProjectMedia(media["path"]!.GetValue<string>())); Route="Video Editor";
        pendingPreviewSeek=editor?["ui"]?["playhead"]?.GetValue<double>();
        await LoadEditorMediaCore(token);
    });
    private void ApplyEditor(JsonObject data)
    {
        applyingEdit=true;
        EditorStale=data["stale"]?.GetValue<bool>() ?? false;
        editor=data["project"]!.AsObject(); sourceDuration=data["source_duration"]?.GetValue<double>() ?? 0; var edits=editor["edits"]!.AsObject(); Segments.Clear(); Captions.Clear();captionBaseline.Clear();
        foreach(var row in edits["segments"]!.AsArray()) Segments.Add(new(row!["start"]!.GetValue<double>(),row["end"]!.GetValue<double>()));
        var overrides=edits["caption_overrides"]!.AsObject();
        foreach(var row in data["captions"]?.AsArray() ?? [])
        { var id=row!["id"]!.GetValue<string>();captionBaseline[id]=(row["start"]!.GetValue<double>(),row["end"]!.GetValue<double>(),row["text"]!.GetValue<string>()); var text=overrides[id] ?? row; Captions.Add(new(id,text["start"]!.GetValue<double>(),text["end"]!.GetValue<double>(),text["text"]!.GetValue<string>())); }
        CropMode=edits["crop"]!["mode"]!.GetValue<string>(); CropX=edits["crop"]!["x"]!.GetValue<double>(); CropY=edits["crop"]!["y"]!.GetValue<double>();
        CaptionsEnabled=edits["style"]!["enabled"]!.GetValue<bool>(); CaptionPreset=edits["style"]!["preset"]!.GetValue<string>(); CaptionPosition=edits["style"]!["position"]!.GetValue<string>();
        SelectedTemplate=Templates.FirstOrDefault(t=>t.Id==edits["template"]?["id"]?.GetValue<string>());
        EditorSummary=EditorStale ? "Delivered clip changed - export it or reset the draft before editing" : $"Saved revision {editor["revision"]} · source duration {data["source_duration"]} s";
        LoadCaptionDetails(data,edits);
        var ui=editor["ui"];
        ProjectTitle=ui?["title"]?.GetValue<string>() ?? editingClip?.Title ?? "Untitled project";
        AssetsVisible=ui?["assets_visible"]?.GetValue<bool>() ?? true;InspectorVisible=ui?["inspector_visible"]?.GetValue<bool>() ?? true;
        PreviewRatio=ui?["preview_ratio"]?.GetValue<string>() ?? "9:16";
        SeekSeconds=ui?["playhead"]?.GetValue<double>() ?? 0;
        AssetsPanelWidth=ui?["assets_width"]?.GetValue<double>() ?? 320;InspectorPanelWidth=ui?["inspector_width"]?.GetValue<double>() ?? 360;EditorTimelineHeight=ui?["timeline_height"]?.GetValue<double>() ?? 300;
        SelectedCaption=Captions.FirstOrDefault(c=>c.Id==ui?["caption_id"]?.GetValue<string>()) ?? Captions.FirstOrDefault(c=>Segments.Any(s=>c.Start<s.End && c.End>s.Start)) ?? Captions.FirstOrDefault();
        SelectedSegment=Segments.ElementAtOrDefault(ui?["segment_index"]?.GetValue<int>() ?? 0) ?? Segments.FirstOrDefault(); applyingEdit=false; ResetEditingHistory(); NotifyCommands();
    }
    private JsonObject BuildEdits()
    {
        if(editor is null) throw new IOException("Open a clip first.");
        if(Segments.Any(s=>!double.IsFinite(s.Start)||!double.IsFinite(s.End)) ||
           Captions.Any(c=>!double.IsFinite(c.Start)||!double.IsFinite(c.End)||c.Words.Any(w=>!double.IsFinite(w.Start)||!double.IsFinite(w.End))))
            throw new ArgumentException("Enter finite numeric timestamps before saving.");
        var edits=(JsonObject)editor["edits"]!.DeepClone();
        edits["segments"]=new JsonArray(Segments.Select(s=>(JsonNode)new JsonObject{["start"]=s.Start,["end"]=s.End}).ToArray());
        edits["crop"]=new JsonObject{["mode"]=CropMode,["x"]=CropX,["y"]=CropY};
        if(CustomAudio)edits["audio"]=StudioAudio();else edits.Remove("audio");
        edits["style"]=new JsonObject{["enabled"]=CaptionsEnabled,["preset"]=CaptionPreset,["position"]=CaptionPosition};
        var overrides=new JsonObject();
        foreach(var caption in Captions)
        {
            // Keep original word alignment when the user did not edit a phrase.
            if(captionBaseline.TryGetValue(caption.Id,out var original) && original==(caption.Start,caption.End,caption.Text))continue;
            overrides[caption.Id]=new JsonObject{["start"]=caption.Start,["end"]=caption.End,["text"]=caption.Text};
        }
        AddWordOverrides(overrides);
        edits["caption_overrides"]=overrides;
        if(CustomCaptionStyle) edits["style"]!["appearance"]=Appearance();
        if(SelectedTemplate is not null && edits["template"]?["id"]?.GetValue<string>()!=SelectedTemplate.Id)
        { edits["template"]=SelectedTemplate.Definition.DeepClone(); edits.Remove("template_content"); }
        if(SelectedTemplate is null) { edits.Remove("template"); edits.Remove("template_content"); }
        if(SelectedTemplate is not null)
        {
            var content=edits["template_content"] as JsonObject ?? new JsonObject();
            content["headline"]=new JsonObject{["text"]=TemplateHeadline,["start"]=HeadlineStart,["end"]=HeadlineEnd};
            edits["template_content"]=content;
        }
        AddAutoEdit(edits);
        return edits;
    }
    private async Task Save(CancellationToken token)
    {
        if(SaveConflict) throw new IOException("Reload the latest draft to resolve the revision conflict. Local edits remain in memory.");
        try
        {
            var saved=await engine.SendAsync(EditorRoute,new JsonObject{["revision"]=editor!["revision"]!.DeepClone(),["edits"]=BuildEdits(),["ui"]=new JsonObject{["title"]=ProjectTitle,["assets_visible"]=AssetsVisible,["inspector_visible"]=InspectorVisible,["preview_ratio"]=PreviewRatio,["playhead"]=Math.Max(0,IsEditor?SeekSeconds:editorPlayheadBeforeReview),["segment_index"]=Math.Max(0,Segments.IndexOf(SelectedSegment!)),["caption_id"]=SelectedCaption?.Id ?? "",["assets_width"]=AssetsPanelWidth,["inspector_width"]=InspectorPanelWidth,["timeline_height"]=EditorTimelineHeight}},true,token);
            editor=saved["project"]!.AsObject(); IsDirty=false;AutosaveStatus="Saved";
            applyingEdit=true;
            try{LoadAutoEdit(editor["edits"]!.AsObject());}
            finally{applyingEdit=false;}
            checkpoint=BuildEdits().ToJsonString();
            EditorSummary=$"Saved revision {editor["revision"]} · preview updates after Render preview";
            Status="Timeline, captions and crop saved.";
        }
        catch(EngineRequestException e) when(e.StatusCode==409)
        { SaveConflict=true; AutosaveStatus="Conflict — local edits retained. Reload latest draft to continue.";throw; }
    }
    [RelayCommand(CanExecute=nameof(CanEdit))] private Task SaveEditor() => Guard(Save);
    [RelayCommand(CanExecute=nameof(CanEdit))] private Task RenderPreview() => Render("preview");
    [RelayCommand(CanExecute=nameof(CanEdit))] private Task RenderFinal() => Render("final");
    private Task Render(string mode) => Guard(token=>RenderCore(mode,token));
    private async Task RenderCore(string mode,CancellationToken token,JsonObject? output=null)
    {
        await Save(token); editorRunning=true;
        try
        {
            var request=new JsonObject{["revision"]=editor!["revision"]!.DeepClone(),["mode"]=mode};if(output is not null)request["output"]=output.DeepClone();
            await engine.SendAsync(EditorRoute+"/run",request,cancellationToken:token);
            CancellationAvailable=true;
            while(true)
            {
                var state=await engine.GetAsync(EditorRoute,token); editor=state["project"]!.AsObject();
                var phase=editor["status"]!.GetValue<string>(); Progress=Math.Clamp(editor["progress"]?.GetValue<double>() ?? 0,0,100); ProgressUnknown=false;
                Status=editor["stage"]?.GetValue<string>() ?? phase;
                if(phase is not ("queued" or "rendering"))
                {
                    if(phase is "failed" or "interrupted") throw new IOException(editor["error"]?.GetValue<string>() ?? "Rendering did not finish.");
                    if(phase=="cancelled")throw new OperationCanceledException("Render cancelled.");
                    if(editor["result"]?["new_video_url"] is JsonValue value)
                    {
                        var url=value.GetValue<string>(); var path=Path.Combine(storage.Library,"output",url.Replace("/videos/","").Replace('/',Path.DirectorySeparatorChar));
                        Preview.Open(storage.ValidateProjectMedia(path)); sourcePreview=false;
                        if(mode=="final") { editingClip=editingClip! with { VideoUrl=url };SelectedClip=editingClip; }
                    }
                    Status=phase; break;
                }
                await Task.Delay(750,token);
            }
        }
        finally { editorRunning=false; }
    }
    [RelayCommand(CanExecute=nameof(CanCancel))] private async Task Cancel()
    {
        try
        {
            if(reviewExportRoute is not null){reviewCancelRequested=true;await engine.SendAsync(reviewExportRoute+"/cancel",new());}
            else if(exportCopying)operation.Cancel();
            else if(editorRunning) await engine.SendAsync(EditorRoute+"/cancel",new());
            else if(jobId is not null){await engine.SendAsync($"/api/desktop/jobs/{EngineClient.JobId(jobId)}/cancel",new());GenerationState="cancel_requested";CancellationAvailable=false;}
            else operation.Cancel();
            Status="Cancellation requested. Waiting for worker cleanup...";
        }
        catch(Exception) { Error="Cancellation could not be confirmed. Check the current worker state before retrying."; }
    }
    [RelayCommand(CanExecute=nameof(CanEdit))] private void AddSegment() => EditTogether(()=> { var row=new SegmentRow(SelectedSegment?.Start ?? 0,SelectedSegment?.End ?? 1); Segments.Add(row);SelectedSegment=row; });
    [RelayCommand(CanExecute=nameof(CanRemoveVideoRange))] private void RemoveSegment() { if(SelectedSegment is not null && Segments.Count>1) Segments.Remove(SelectedSegment); }
    [RelayCommand(CanExecute=nameof(CanEdit))] private void SplitSegment() => EditTogether(()=>
    {
        if(SelectedSegment is null) return;
        var row=SelectedSegment; double cut=SeekSeconds;
        if(!sourcePreview)
        {
            double offset=0;
            foreach(var segment in Segments)
            { if(SeekSeconds<=offset+segment.End-segment.Start) { cut=segment.Start+SeekSeconds-offset;break; } offset+=segment.End-segment.Start; }
        }
        if(cut-row.Start<.5 || row.End-cut<.5) { Error="Each split range must be at least 0.5 seconds."; return; }
        var end=row.End;row.End=cut;Segments.Insert(Segments.IndexOf(row)+1,new(cut,end));
    });
    [RelayCommand(CanExecute=nameof(CanEdit))] private void MoveUp() { if(SelectedSegment is { } row && Segments.IndexOf(row)>0) Segments.Move(Segments.IndexOf(row),Segments.IndexOf(row)-1); }
    [RelayCommand(CanExecute=nameof(CanEdit))] private void MoveDown() { if(SelectedSegment is { } row && Segments.IndexOf(row)<Segments.Count-1) Segments.Move(Segments.IndexOf(row),Segments.IndexOf(row)+1); }
    [RelayCommand] private void PlayPause()
    {
        if(Preview.Player.IsPlaying){Preview.Player.SetPause(true);return;}
        if(sourcePreview && Segments.Count>0 && Preview.Player.Time/1000d>=Segments[^1].End)
        {SelectedSegment=Segments[0];Preview.Seek(SelectedSegment.Start);}
        Preview.Player.SetPause(false);
    }
    [RelayCommand] private void Seek() => Preview.Seek(SeekSeconds);
    [RelayCommand(CanExecute=nameof(CanExport))] private Task Export()
    {
        if(!HasEditor){Error="Open this clip in the editor before exporting its timeline.";return Task.CompletedTask;}
        ExportName=$"OpenShorts-clip-{SelectedClip!.Index+1}.mp4";
        new ExportWindow(this){Owner=Application.Current.MainWindow}.ShowDialog();return Task.CompletedTask;
    }
    [RelayCommand] private void SaveSettings()
    {
        try { storage.SaveSettings(new(Encoder,Preset)); storage.SaveCredential(PendingCredential.Trim()); CredentialStatus="Settings saved. Restart the engine from Home to apply changes."; }
        catch(Exception e) { Error=e.Message; }
    }
    [RelayCommand] private void ClearCredential()
    { try { storage.SaveCredential("");PendingCredential="";CredentialStatus="Saved Gemini key removed. Restart the engine to apply."; } catch(Exception e) { Error=e.Message; } }
    [RelayCommand(CanExecute=nameof(CanImport))] private Task DetectHardware() => Guard(async token=>
    { var data=await engine.GetAsync("/api/desktop/capabilities",token); UpdateHomeHardware(data);Hardware=$"FFmpeg: {data["ffmpeg"]}\nNVENC encode probe: {data["nvenc_initialized"]}\nCPU encoder: {data["libx264_initialized"]}\nAI CUDA: {data["ai_cuda"]}\nLimit: one pipeline job"; });
    public void StopPending() { autosaveTimer.Stop(); operation.Cancel();StopCreativePreview(); }
}
