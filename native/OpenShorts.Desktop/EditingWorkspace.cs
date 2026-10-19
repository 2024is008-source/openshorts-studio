using System.Collections.Specialized;
using System.ComponentModel;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace OpenShorts.Desktop;

public partial class MainViewModel
{
    private readonly DispatcherTimer autosaveTimer=new() { Interval=TimeSpan.FromSeconds(2) };
    private bool applyingEdit;
    private double sourceDuration;
    private string? checkpoint;
    private readonly List<string> undo=[];
    private readonly List<string> redo=[];
    private readonly Dictionary<string,string> wordBaseline=[];
    private readonly HashSet<INotifyPropertyChanged> watched=[];
    [ObservableProperty] private bool isDirty;
    [ObservableProperty] private bool saveConflict;
    [ObservableProperty] private bool editorStale;
    partial void OnEditorStaleChanged(bool value)=>NotifyCommands();
    [ObservableProperty] private string autosaveStatus="Autosave ready";
    [ObservableProperty] private CaptionRow? selectedCaption;
    [ObservableProperty] private bool customCaptionStyle;
    [ObservableProperty] private bool autoPreview;
    [ObservableProperty] private string captionFont="Arial";
    [ObservableProperty] private double captionSize=52;
    [ObservableProperty] private string captionColor="#FFFFFF";
    [ObservableProperty] private string highlightColor="#00FF88";
    [ObservableProperty] private string outlineColor="#000000";
    [ObservableProperty] private double outlineWidth=2;
    [ObservableProperty] private double captionShadow=1;
    [ObservableProperty] private string captionAnimation="none";
    [ObservableProperty] private string captionBackground="#000000";
    [ObservableProperty] private double captionBackgroundOpacity;
    [ObservableProperty] private int captionMaxLines=2;
    [ObservableProperty] private int captionMaxWords=6;
    [ObservableProperty] private double captionSyncOffset;
    [ObservableProperty] private double captionMinPhrase=.45;
    [ObservableProperty] private double captionLineSpacing=1.25;
    [ObservableProperty] private double captionBaseOpacity=1;
    [ObservableProperty] private bool captionUppercase;
    [ObservableProperty] private double timelineZoom=1;
    [ObservableProperty] private bool snapEnabled=true;
    [ObservableProperty] private double[] waveform=[];
    [ObservableProperty] private double[] sceneBoundaries=[];
    [ObservableProperty] private string featureStatus="Load waveform / scenes for the current cuts";
    public string[] CaptionFonts { get; }=["Arial","Anton","Verdana","Impact","Georgia","Courier New","Helvetica","Noto Serif"];
    public string[] CaptionAnimations { get; }=["none","fade","pop","glow","box","scale","reveal","bounce"];
    private static readonly HashSet<string> EditProperties=[nameof(CaptionBackground),nameof(CaptionBackgroundOpacity),nameof(CaptionMaxLines),nameof(CaptionMaxWords),nameof(CaptionSyncOffset),nameof(CaptionMinPhrase),nameof(CaptionLineSpacing),nameof(CaptionBaseOpacity),nameof(CaptionUppercase),nameof(TemplateHeadline),nameof(HeadlineStart),nameof(HeadlineEnd),nameof(CropMode),nameof(CropX),nameof(CropY),nameof(CaptionsEnabled),nameof(CaptionPreset),nameof(CaptionPosition),nameof(SelectedTemplate),nameof(CustomCaptionStyle),nameof(CaptionFont),nameof(CaptionSize),nameof(CaptionColor),nameof(HighlightColor),nameof(OutlineColor),nameof(OutlineWidth),nameof(CaptionShadow),nameof(CaptionAnimation)];
    private void InitializeEditing()
    {
        foreach(var property in new[]{nameof(CustomAudio),nameof(ExportAudioVolume),nameof(ExportAudioMute),nameof(ExportAudioFade),nameof(ExportAudioNormalize),nameof(ExportAudioTarget),nameof(ExportAudioCeiling),nameof(MusicFile)})EditProperties.Add(property);
        Segments.CollectionChanged+=RowsChanged; Captions.CollectionChanged+=RowsChanged;
        PropertyChanged+=(_,e)=> { if(e.PropertyName is not null && EditProperties.Contains(e.PropertyName)) EditingChanged(false); };
        autosaveTimer.Tick+=async (_,_)=>
        {
            if(!IsDirty || SaveConflict){autosaveTimer.Stop();return;}
            if(Busy || HasInputError || MouseEditing) return;
            autosaveTimer.Stop(); await Guard(Save);
            AutosaveStatus=IsDirty ? "Autosave paused — correct the edit or save again" : "Autosaved";
            if(!IsDirty && !SaveConflict && AutoPreview)await Render("preview");
        };
    }
    public bool MouseEditing { get; private set; }
    public void BeginEditingGesture() { MouseEditing=true; }
    public void EndEditingGesture() { MouseEditing=false;EditingChanged(true); }
    private void EditTogether(Action action)
    { BeginEditingGesture();try{action();}finally{EndEditingGesture();} }
    private void RowsChanged(object? sender,NotifyCollectionChangedEventArgs e)
    {
        foreach(var row in watched) row.PropertyChanged-=RowEdited;
        watched.Clear();
        foreach(var row in Segments.Cast<INotifyPropertyChanged>().Concat(Captions).Concat(Captions.SelectMany(c=>c.Words)))
            if(watched.Add(row)) row.PropertyChanged+=RowEdited;
        EditingChanged(true);
        RemoveSegmentCommand.NotifyCanExecuteChanged();
    }
    private void RowEdited(object? sender,PropertyChangedEventArgs e)
    { if(e.PropertyName!=nameof(CaptionRow.WordEditingSupported)) EditingChanged(sender is SegmentRow); }
    private void EditingChanged(bool cuts)
    {
        if(applyingEdit || editor is null) return;
        if(MouseEditing)return;
        string next;
        try{next=BuildEdits().ToJsonString();}
        catch(ArgumentException){IsDirty=true;autosaveTimer.Stop();AutosaveStatus="Correct invalid timestamps before saving";return;}
        if(checkpoint==next)
        {if(IsDirty && !SaveConflict){AutosaveStatus="Unsaved changes · autosave in 2 seconds";autosaveTimer.Start();}return;}
        if(checkpoint is not null){undo.Add(checkpoint);if(undo.Count>100)undo.RemoveAt(0);}
        redo.Clear();checkpoint=next;IsDirty=true;
        if(cuts){Waveform=[];SceneBoundaries=[];TimelineFrames.Clear();FeatureStatus="Cuts changed — reload waveform / scenes";UseSourcePreview();}
        OnPropertyChanged(nameof(TimelineSeconds));
        AutosaveStatus=SaveConflict ? "Conflict — autosave paused" : "Unsaved changes · autosave in 2 seconds";
        autosaveTimer.Stop();if(!SaveConflict)autosaveTimer.Start();
        UndoEditCommand.NotifyCanExecuteChanged();RedoEditCommand.NotifyCanExecuteChanged();
    }
    private void ResetEditingHistory()
    {
        undo.Clear();redo.Clear();checkpoint=BuildEdits().ToJsonString();IsDirty=false;SaveConflict=false;
        Waveform=[];SceneBoundaries=[];TimelineFrames.Clear();AutosaveStatus="Saved";autosaveTimer.Stop();
        RowsChanged(this,new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
    }
    private JsonObject Appearance()=>new(){["font_name"]=CaptionFont,["font_size"]=CaptionSize,["font_color"]=CaptionColor,["highlight_color"]=HighlightColor,["border_color"]=OutlineColor,["border_width"]=OutlineWidth,["shadow"]=CaptionShadow,["effect"]=CaptionAnimation,
        ["bg_color"]=CaptionBackground,["bg_opacity"]=CaptionBackgroundOpacity,["max_lines"]=CaptionMaxLines,["max_words"]=CaptionMaxWords,["sync_offset"]=CaptionSyncOffset,["min_phrase_duration"]=CaptionMinPhrase,["line_spacing"]=CaptionLineSpacing,["base_opacity"]=CaptionBaseOpacity,["uppercase"]=CaptionUppercase};
    private void LoadAppearance(JsonObject edits)
    {
        LoadAutoEdit(edits);
        LoadStudioAudio(edits);
        TemplateHeadline=edits["template_content"]?["headline"]?["text"]?.GetValue<string>() ?? "";
        HeadlineStart=edits["template_content"]?["headline"]?["start"]?.GetValue<double>() ?? 0;
        HeadlineEnd=edits["template_content"]?["headline"]?["end"]?.GetValue<double>() ?? 3;
        var a=edits["style"]?["appearance"];CustomCaptionStyle=a is not null;
        CaptionFont=a?["font_name"]?.GetValue<string>() ?? "Arial";CaptionSize=a?["font_size"]?.GetValue<double>() ?? 52;
        CaptionColor=a?["font_color"]?.GetValue<string>() ?? "#FFFFFF";HighlightColor=a?["highlight_color"]?.GetValue<string>() ?? "#00FF88";
        OutlineColor=a?["border_color"]?.GetValue<string>() ?? "#000000";OutlineWidth=a?["border_width"]?.GetValue<double>() ?? 2;
        CaptionShadow=a?["shadow"]?.GetValue<double>() ?? 1;CaptionAnimation=a?["effect"]?.GetValue<string>() ?? "none";
        CaptionBackground=a?["bg_color"]?.GetValue<string>() ?? "#000000";CaptionBackgroundOpacity=a?["bg_opacity"]?.GetValue<double>() ?? 0;
        CaptionMaxLines=a?["max_lines"]?.GetValue<int>() ?? 2;CaptionMaxWords=a?["max_words"]?.GetValue<int>() ?? 6;CaptionSyncOffset=a?["sync_offset"]?.GetValue<double>() ?? 0;
        CaptionMinPhrase=a?["min_phrase_duration"]?.GetValue<double>() ?? .45;CaptionLineSpacing=a?["line_spacing"]?.GetValue<double>() ?? 1.25;CaptionBaseOpacity=a?["base_opacity"]?.GetValue<double>() ?? 1;CaptionUppercase=a?["uppercase"]?.GetValue<bool>() ?? false;
    }
    private static JsonArray WordJson(CaptionRow c)=>new(c.Words.Select(w=>(JsonNode)new JsonObject{["word"]=w.Word,["start"]=w.Start,["end"]=w.End,["emphasis"]=w.Emphasis}).ToArray());
    private void LoadCaptionDetails(JsonObject data,JsonObject edits)
    {
        wordBaseline.Clear();
        foreach(var c in Captions)
        {
            var original=data["captions"]!.AsArray().First(r=>r!["id"]!.GetValue<string>()==c.Id)!;
            c.OriginalText=original["text"]!.GetValue<string>();
            var saved=edits["caption_overrides"]?[c.Id]?["words"];
            foreach(var word in original["words"]?.AsArray() ?? [])
                c.Words.Add(new(word!["word"]!.GetValue<string>(),word["start"]!.GetValue<double>(),word["end"]!.GetValue<double>(),word["emphasis"]?.GetValue<bool>() ?? false,word["aligned"]?.GetValue<bool>() ?? false));
            wordBaseline[c.Id]=WordJson(c).ToJsonString();
            if(saved is JsonArray words)for(int i=0;i<Math.Min(words.Count,c.Words.Count);i++)
            {c.Words[i].Start=words[i]!["start"]!.GetValue<double>();c.Words[i].End=words[i]!["end"]!.GetValue<double>();c.Words[i].Emphasis=words[i]!["emphasis"]!.GetValue<bool>();}
        }
        SelectedCaption=Captions.FirstOrDefault();LoadAppearance(edits);
    }
    private void AddWordOverrides(JsonObject overrides)
    {
        foreach(var c in Captions)
            if(c.WordEditingSupported && wordBaseline.TryGetValue(c.Id,out var baseline) && WordJson(c).ToJsonString()!=baseline)
                overrides[c.Id]=new JsonObject{["start"]=c.Start,["end"]=c.End,["text"]=c.Text,["words"]=WordJson(c)};
    }
    private bool CanUndoEdit=>CanEdit && undo.Count>0;
    private bool CanRedoEdit=>CanEdit && redo.Count>0;
    [RelayCommand(CanExecute=nameof(CanUndoEdit))] private void UndoEdit()=>RestoreHistory(undo,redo);
    [RelayCommand(CanExecute=nameof(CanRedoEdit))] private void RedoEdit()=>RestoreHistory(redo,undo);
    private void RestoreHistory(List<string> from,List<string> to)
    {
        if(from.Count==0 || checkpoint is null)return;
        to.Add(checkpoint);var value=from[^1];from.RemoveAt(from.Count-1);
        applyingEdit=true;
        try
        {
            var edits=JsonNode.Parse(value)!.AsObject();
            Segments.Clear();foreach(var row in edits["segments"]!.AsArray())Segments.Add(new(row!["start"]!.GetValue<double>(),row["end"]!.GetValue<double>()));
            foreach(var c in Captions)
            {
                var baseline=captionBaseline[c.Id];var o=edits["caption_overrides"]?[c.Id];
                c.Start=o?["start"]?.GetValue<double>() ?? baseline.Start;c.End=o?["end"]?.GetValue<double>() ?? baseline.End;c.Text=o?["text"]?.GetValue<string>() ?? baseline.Text;
                var words=o?["words"] as JsonArray ?? JsonNode.Parse(wordBaseline[c.Id])!.AsArray();
                for(int i=0;i<c.Words.Count;i++){c.Words[i].Start=words[i]!["start"]!.GetValue<double>();c.Words[i].End=words[i]!["end"]!.GetValue<double>();c.Words[i].Emphasis=words[i]!["emphasis"]!.GetValue<bool>();}
            }
            CropMode=edits["crop"]!["mode"]!.GetValue<string>();CropX=edits["crop"]!["x"]!.GetValue<double>();CropY=edits["crop"]!["y"]!.GetValue<double>();
            CaptionsEnabled=edits["style"]!["enabled"]!.GetValue<bool>();CaptionPreset=edits["style"]!["preset"]!.GetValue<string>();CaptionPosition=edits["style"]!["position"]!.GetValue<string>();LoadAppearance(edits);
            SelectedTemplate=Templates.FirstOrDefault(t=>t.Id==edits["template"]?["id"]?.GetValue<string>());
            FeatureStatus="History changed — reload waveform / scenes";
            checkpoint=value;SelectedSegment=Segments.FirstOrDefault();Waveform=[];SceneBoundaries=[];TimelineFrames.Clear();
        }
        finally{applyingEdit=false;}
        UseSourcePreview();
        IsDirty=true;autosaveTimer.Stop();if(!SaveConflict)autosaveTimer.Start();AutosaveStatus="Unsaved history change";NotifyCommands();
    }
    [RelayCommand(CanExecute=nameof(CanEdit))] private Task LoadFeatures()=>Guard(async token=>
    {
        await Save(token);var data=await engine.SendAsync(EditorRoute+"/features",new JsonObject{["revision"]=editor!["revision"]!.DeepClone()},cancellationToken:token);
        Waveform=data["waveform"]!.AsArray().Select(x=>x!.GetValue<double>()).ToArray();SceneBoundaries=data["scene_boundaries"]!.AsArray().Select(x=>x!.GetValue<double>()).ToArray();
        TimelineFrames.Clear();var converter=new MediaThumbnailConverter();
        foreach(var frame in data["thumbnails"]?.AsArray() ?? [])
            if(converter.Convert(storage.ValidateProjectMedia(frame!["path"]!.GetValue<string>()),typeof(System.Windows.Media.ImageSource),null!,System.Globalization.CultureInfo.InvariantCulture) is System.Windows.Media.ImageSource image)
                TimelineFrames.Add(new(frame["time"]!.GetValue<double>(),image));
        FeatureStatus=data["scene_method"]!.GetValue<string>();
    });
    [RelayCommand(CanExecute=nameof(CanEdit))] private Task ReloadDraft()=>Guard(async token=>
    {
        if(IsDirty && MessageBox.Show("Reload replaces unsaved local edits with the latest saved draft.","Reload latest draft?",MessageBoxButton.YesNo)!=MessageBoxResult.Yes)return;
        ApplyEditor(await engine.GetAsync(EditorRoute,token));
    });
    public async Task<bool> FlushDraftAsync(CancellationToken token=default)
    {
        if(!IsDirty)return true;
        try{await Save(token);return true;}catch(Exception e){Error=e.Message;return false;}
    }
    public void TrimSegment(SegmentRow row,bool start,double seconds)
    {
        if(!CanEdit)return;
        var candidates=Segments.Where(s=>s!=row).SelectMany(s=>new[]{s.Start,s.End}).Concat(Captions.SelectMany(c=>new[]{c.Start,c.End}));
        double offset=0;var sceneSources=new List<double>();
        foreach(var segment in Segments){sceneSources.AddRange(SceneBoundaries.Where(t=>t>=offset && t<=offset+segment.End-segment.Start).Select(t=>segment.Start+t-offset));offset+=segment.End-segment.Start;}
        candidates=candidates.Concat(sceneSources);
        if(SnapEnabled){var closest=candidates.OrderBy(t=>Math.Abs(t-seconds)).FirstOrDefault(double.NaN);if(Math.Abs(closest-seconds)<.12)seconds=closest;}
        seconds=Math.Round(seconds,3);
        if(start)row.Start=Math.Clamp(seconds,0,Math.Max(0,row.End-.5));
        else row.End=Math.Clamp(seconds,row.Start+.5,Math.Max(row.Start+.5,sourceDuration));
    }
    public void SyncPlayback()
    {
        if(!IsEditor || Busy || !sourcePreview || !Preview.Player.IsPlaying || Segments.Count==0)return;
        var time=Preview.Player.Time/1000d;
        var index=SelectedSegment is null ? -1 : Segments.IndexOf(SelectedSegment);
        if(index<0)index=0;
        var current=Segments[index];
        if(time<current.Start-.15)Preview.Seek(current.Start);
        else if(time>=current.End)
        {if(index+1<Segments.Count){SelectedSegment=Segments[index+1];Preview.Seek(SelectedSegment.Start);}else Preview.Player.Pause();}
    }
    private void UseSourcePreview()
    {
        if(sourcePreview || editorSourcePath is null)return;
        Preview.Open(editorSourcePath);sourcePreview=true;
        EditorSummary="Source playback · render preview to review caption appearance and assembled cuts";
    }
}
