using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Data;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using OpenShorts.EngineBridge;

namespace OpenShorts.Desktop;
public sealed record EditorMedia(string Path,string Name,string Kind,bool Source,int? ClipIndex,double Duration,string? Thumbnail)
{
    public string Detail=>$"{Kind} · {(Kind=="Images"?"Image":Duration>0?TimeSpan.FromSeconds(Math.Min(Duration,86400)).ToString(@"mm\:ss"):"Duration unavailable")}";
}
public sealed record TimelineFrame(double Time,System.Windows.Media.ImageSource Image);
public partial class MainViewModel
{
    public ObservableCollection<TimelineFrame> TimelineFrames { get; }=[];
    public ObservableCollection<EditorMedia> EditorMediaFiles { get; }=[];
    public ICollectionView MediaView=>CollectionViewSource.GetDefaultView(EditorMediaFiles);
    public ICollectionView CaptionView=>CollectionViewSource.GetDefaultView(Captions);
    public string[] MediaFilters { get; }=["All","Videos","Images","Audio"];
    public string[] PreviewRatios { get; }=["9:16","1:1","16:9","Source"];
    [ObservableProperty] private string mediaFilter="All";
    [ObservableProperty] private EditorMedia? selectedMedia;
    [ObservableProperty] private string captionSearch="";
    [ObservableProperty] private string projectTitle="Untitled project";
    [ObservableProperty] private string previewRatio="9:16";
    [ObservableProperty] private bool assetsVisible=true;
    [ObservableProperty] private bool inspectorVisible=true;
    [ObservableProperty] private bool safeZones=true;
    [ObservableProperty] private bool cropGuides;
    [ObservableProperty] private double previewZoom=1;
    [ObservableProperty] private double playbackVolume=80;
    [ObservableProperty] private string playbackClock="00:00 / 00:00";
    [ObservableProperty] private bool draftOverlay;
    [ObservableProperty] private string previewCaption="";
    [ObservableProperty] private string previewHeadline="";
    [ObservableProperty] private int assetTab;
    [ObservableProperty] private int inspectorTab;
    [ObservableProperty] private double timelinePan;
    [ObservableProperty] private string? sourceThumbnail;
    [ObservableProperty] private string? previewImage;
    [ObservableProperty] private bool customAudio;
    [ObservableProperty] private double exportAudioVolume=1;
    [ObservableProperty] private bool exportAudioMute;
    [ObservableProperty] private double exportAudioFade;
    [ObservableProperty] private bool exportAudioNormalize=true;
    [ObservableProperty] private double exportAudioTarget=-16;
    [ObservableProperty] private double exportAudioCeiling=-2;
    [ObservableProperty] private string musicFile="";
    [ObservableProperty] private double assetsPanelWidth=320;
    [ObservableProperty] private double inspectorPanelWidth=360;
    [ObservableProperty] private double editorTimelineHeight=300;
    [ObservableProperty] private double sourceAspect=16d/9;
    private double? pendingPreviewSeek;
    private bool? pendingPlaybackResume;
    public void RestorePreviewAfterSurfaceChange(double seconds,bool playing){pendingPreviewSeek=Math.Max(0,seconds);pendingPlaybackResume=playing;}
    partial void OnSourceAspectChanged(double value)=>OnPropertyChanged(nameof(PreviewAspect));
    private JsonObject StudioAudio()=>new(){["volume"]=ExportAudioVolume,["mute"]=ExportAudioMute,["fade"]=ExportAudioFade,["normalize"]=ExportAudioNormalize,["target"]=ExportAudioTarget,["ceiling"]=ExportAudioCeiling,["music"]=MusicFile.Length>0?MusicFile:null};
    private void LoadStudioAudio(JsonObject edits)
    {
        var audio=edits["audio"];CustomAudio=audio is not null;
        ExportAudioVolume=audio?["volume"]?.GetValue<double>() ?? 1;ExportAudioMute=audio?["mute"]?.GetValue<bool>() ?? false;
        ExportAudioFade=audio?["fade"]?.GetValue<double>() ?? 0;ExportAudioNormalize=audio?["normalize"]?.GetValue<bool>() ?? true;
        ExportAudioTarget=audio?["target"]?.GetValue<double>() ?? -16;ExportAudioCeiling=audio?["ceiling"]?.GetValue<double>() ?? -2;MusicFile=audio?["music"]?.GetValue<string>() ?? "";
    }
    [RelayCommand] private void UseSelectedMusic()
    {
        if(!CanEdit || SelectedMedia?.Kind!="Audio"){Error="Select an imported audio file in Media first.";return;}
        if(Path.GetDirectoryName(SelectedMedia.Path)!=Path.Combine(storage.Library,"output",CurrentClip.JobId,"media")){Error="Music must be imported into this project.";return;}
        EditTogether(()=>{CustomAudio=true;ExportAudioNormalize=true;MusicFile=Path.GetFileName(SelectedMedia.Path);});AssetTab=2;InspectorTab=2;
    }
    [RelayCommand] private void RemoveMusic(){if(CanEdit)EditTogether(()=>MusicFile="");}
    public bool IsNotEditor=>!IsEditor;
    public string PreviewMode=>sourcePreview?"Source preview · render to review final styling":"Rendered / media preview";
    public bool CanAddSource=>CanEdit && SelectedMedia?.Source==true;
    public bool CanPreviewMedia=>!Busy && SelectedMedia is not null;
    partial void OnMediaFilterChanged(string value)=>MediaView.Refresh();
    partial void OnCaptionSearchChanged(string value)=>CaptionView.Refresh();
    partial void OnSelectedMediaChanged(EditorMedia? value)=>NotifyStudioCommands();
    partial void OnPlaybackVolumeChanged(double value)=>Preview.Player.Volume=(int)Math.Clamp(value,0,100);
    partial void OnPreviewRatioChanged(string value)=>OnPropertyChanged(nameof(PreviewAspect));
    public double PreviewAspect=>PreviewRatio switch {"1:1"=>1,"16:9"=>16d/9,"Source"=>SourceAspect,_=>9d/16};
    partial void OnProjectTitleChanged(string value)
    { if(!applyingEdit && editor is not null){IsDirty=true;autosaveTimer.Stop();autosaveTimer.Start();} }
    private void NotifyStudioCommands()
    {
        OnPropertyChanged(nameof(CanAddSource));OnPropertyChanged(nameof(CanPreviewMedia));
        AddSourceRangeCommand.NotifyCanExecuteChanged();PreviewMediaCommand.NotifyCanExecuteChanged();ImportEditorMediaCommand.NotifyCanExecuteChanged();LoadEditorMediaCommand.NotifyCanExecuteChanged();PreviewDeliveryCommand.NotifyCanExecuteChanged();
        CleanThumbnailCacheCommand.NotifyCanExecuteChanged();
    }
    private void ConfigureStudioViews()
    {
        MediaView.Filter=o=>o is EditorMedia m && (MediaFilter=="All" || m.Kind==MediaFilter);
        CaptionView.Filter=o=>o is CaptionRow c && c.Text.Contains(CaptionSearch,StringComparison.OrdinalIgnoreCase);
    }
    private async Task LoadEditorMediaCore(CancellationToken token)
    {
        if(!HasEditor)return;
        var data=await engine.GetAsync($"/api/desktop/assets/{CurrentClip.JobId}",token);
        EditorMediaFiles.Clear();
        foreach(var row in data["assets"]?.AsArray() ?? [])
        {
            string path=storage.ValidateProjectMedia(row!["path"]!.GetValue<string>());
            string? image=null;if(row["thumbnail"]?.GetValue<string>() is string thumb)image=storage.ValidateProjectMedia(thumb);
            EditorMediaFiles.Add(new(path,row["name"]!.GetValue<string>(),row["kind"]!.GetValue<string>(),row["source"]!.GetValue<bool>(),row["clip_index"]?.GetValue<int>(),row["duration"]!.GetValue<double>(),image));
        }
        SelectedMedia=EditorMediaFiles.FirstOrDefault();
        SourceThumbnail=EditorMediaFiles.FirstOrDefault(m=>m.Source)?.Thumbnail;
    }
    [RelayCommand(CanExecute=nameof(CanImport))] private Task LoadEditorMedia()=>Guard(LoadEditorMediaCore);
    [RelayCommand(CanExecute=nameof(CanImport))] private Task CleanThumbnailCache()=>Guard(async token=>
    {var data=await engine.SendAsync("/api/desktop/cache/cleanup",new(),cancellationToken:token);Status=$"Removed {data["files"]} cached thumbnails/features older than 24 hours · {data["bytes"]} bytes · {data["skipped"]} locked files skipped.";});
    [RelayCommand(CanExecute=nameof(CanImport))] private async Task ImportEditorMedia()
    {
        if(!HasEditor){await ImportCommand.ExecuteAsync(null);return;}
        var dialog=new OpenFileDialog{Filter="Media files|*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v;*.mp3;*.wav;*.m4a;*.aac;*.png;*.jpg;*.jpeg;*.webp"};
        if(dialog.ShowDialog()==true)await ImportEditorMediaAsync(dialog.FileName);
    }
    public Task ImportEditorMediaAsync(string path)=>Guard(async token=>
    {
        if(!HasEditor)throw new IOException("Open a clip before importing project assets.");
        var file=new FileInfo(path);
        if(!file.Exists || file.Length>2L*1024*1024*1024 || !new[]{".mp4",".mov",".mkv",".webm",".avi",".m4v",".mp3",".wav",".m4a",".aac",".png",".jpg",".jpeg",".webp"}.Contains(file.Extension.ToLowerInvariant()))throw new IOException("Choose supported media below 2 GB.");
        var delivered=await engine.GetAsync($"/api/desktop/media/{CurrentClip.JobId}/{CurrentClip.Index}",token);
        string projectFolder=Path.Combine(storage.Library,"output",EngineClient.JobId(CurrentClip.JobId));
        storage.ValidateProjectMedia(delivered["path"]!.GetValue<string>());
        string mediaFolder=Path.Combine(projectFolder,"media");Directory.CreateDirectory(mediaFolder);
        if((File.GetAttributes(mediaFolder)&FileAttributes.ReparsePoint)!=0)throw new IOException("Linked media storage is not supported.");
        string target=Path.Combine(mediaFolder,Guid.NewGuid().ToString("N")+file.Extension.ToLowerInvariant());
        try
        {
            await using(var input=File.OpenRead(file.FullName))await using(var output=new FileStream(target,FileMode.CreateNew,FileAccess.Write,FileShare.None,81920,true))await input.CopyToAsync(output,token);
            await LoadEditorMediaCore(token);SelectedMedia=EditorMediaFiles.FirstOrDefault(m=>m.Path==target);
            Status="Media imported into this project. The video timeline uses the retained source; imported assets can be previewed.";
        }
        catch{File.Delete(target);throw;}
    });
    [RelayCommand(CanExecute=nameof(CanPreviewMedia))] private Task PreviewMedia()=>Guard(_=>
    {
        string path=storage.ValidateProjectMedia(SelectedMedia!.Path);
        if(SelectedMedia.Kind=="Images")
        {
            if(new MediaThumbnailConverter().Convert(path,typeof(System.Windows.Media.ImageSource),"1024",System.Globalization.CultureInfo.InvariantCulture) is null)throw new IOException("The image could not be decoded.");
            Preview.Player.SetPause(true);PreviewImage=path;Status="Image asset preview · image layering is not supported by this timeline.";
        }
        else{PreviewImage=null;Preview.Open(path);}
        sourcePreview=SelectedMedia.Source;
        OnPropertyChanged(nameof(PreviewMode));
        return Task.CompletedTask;
    });
    [RelayCommand(CanExecute=nameof(CanAddSource))] private void AddSourceRange()
    { EditTogether(()=>{double start=Math.Min(Math.Max(0,SeekSeconds),Math.Max(0,sourceDuration-.5));var row=new SegmentRow(start,Math.Min(sourceDuration,start+5));Segments.Add(row);SelectedSegment=row;}); }
    [RelayCommand] private void RevealEditorMedia()
    {if(SelectedMedia is not null)Process.Start(new ProcessStartInfo("explorer.exe"){UseShellExecute=true,Arguments="/select,\""+storage.ValidateProjectMedia(SelectedMedia.Path)+"\""});}
    [RelayCommand] private void ApplyCaptionPreset(string? preset)
    { if(preset is not null && CaptionPresets.Contains(preset) && CanEdit)EditTogether(()=>{SelectedTemplate=null;CustomCaptionStyle=false;CaptionPreset=preset;}); }
    [RelayCommand] private void ReturnToTimeline()
    {if(editorSourcePath is not null){PreviewImage=null;sourcePreview=false;UseSourcePreview();OnPropertyChanged(nameof(PreviewMode));}}
    [RelayCommand(CanExecute=nameof(CanImport))] private Task PreviewDelivery()=>Guard(async token=>
    {if(!HasEditor)throw new IOException("Open a clip first.");var media=await engine.GetAsync($"/api/desktop/media/{CurrentClip.JobId}/{CurrentClip.Index}",token);PreviewImage=null;Preview.Open(storage.ValidateProjectMedia(media["path"]!.GetValue<string>()));sourcePreview=false;pendingPreviewSeek=null;OnPropertyChanged(nameof(PreviewMode));});
    [RelayCommand] private void StepForward()
    {if(Preview.Player.IsSeekable){Preview.Player.SetPause(true);Preview.Player.NextFrame();Status="Next decoded frame requested. Reverse frame stepping is unavailable.";}}
    [RelayCommand] private void PreviousPosition()
    {Preview.Player.SetPause(true);Preview.Seek(Math.Max(0,SeekSeconds-.1));Status="Moved back approximately 0.1 seconds; seek precision depends on the decoder.";}
    [RelayCommand] private void ToggleAssets()=>AssetsVisible=!AssetsVisible;
    [RelayCommand] private void ToggleInspector()=>InspectorVisible=!InspectorVisible;
    public void MoveCaption(CaptionRow row,double delta)
    {
        if(!CanEdit || !double.IsFinite(delta))return;
        if(SnapEnabled)
        {
            var boundaries=Segments.SelectMany(s=>new[]{s.Start,s.End}).Concat(Captions.Where(c=>c!=row).SelectMany(c=>new[]{c.Start,c.End}));
            double correction=boundaries.SelectMany(t=>new[]{t-row.Start-delta,t-row.End-delta}).OrderBy(Math.Abs).FirstOrDefault(double.PositiveInfinity);
            if(Math.Abs(correction)<.08)delta+=correction;
        }
        delta=Math.Clamp(delta,-row.Start,sourceDuration-row.End);
        row.Start+=delta;row.End+=delta;
        if(row.WordEditingSupported)foreach(var word in row.Words){word.Start+=delta;word.End+=delta;}
    }
    public void TrimCaption(CaptionRow row,bool start,double time)
    {
        if(!CanEdit || !double.IsFinite(time))return;
        if(start)row.Start=Math.Clamp(time,Math.Max(0,row.End-30),row.WordEditingSupported?Math.Min(row.End-.05,row.Words[0].Start):row.End-.05);
        else row.End=Math.Clamp(time,row.WordEditingSupported?Math.Max(row.Start+.05,row.Words[^1].End):row.Start+.05,Math.Min(sourceDuration,row.Start+30));
    }
    [RelayCommand] private void SelectEditorTool(string? tool)
    {if(tool=="Captions"){AssetTab=1;InspectorTab=0;}else if(tool=="Audio"){AssetTab=2;InspectorTab=2;}else if(tool=="Effects"){AssetTab=3;InspectorTab=4;}else if(tool=="AutoEdit"){AssetTab=3;InspectorTab=3;}else if(tool=="Crop"){InspectorTab=1;CropGuides=true;}else if(tool=="Templates")AssetTab=4;}
    public void UpdateStudioPlayback()
    {
        if(pendingPreviewSeek is double seek && Preview.Player.IsSeekable){Preview.Seek(seek);SeekSeconds=seek;pendingPreviewSeek=null;if(pendingPlaybackResume is bool resume){Preview.Player.SetPause(!resume);pendingPlaybackResume=null;}}
        uint width=0,height=0;if(Preview.Player.Size(0,ref width,ref height) && width>0 && height>0)SourceAspect=width/(double)height;
        PlaybackClock=$"{TimeSpan.FromSeconds(Math.Max(0,SeekSeconds)):mm\\:ss} / {TimeSpan.FromSeconds(Math.Max(0,DurationSeconds)):mm\\:ss}";
        double sourceTime=SeekSeconds;
        if(!sourcePreview){double offset=0;foreach(var s in Segments){if(SeekSeconds<=offset+s.End-s.Start){sourceTime=s.Start+SeekSeconds-offset;break;}offset+=s.End-s.Start;}}
        PreviewCaption=DraftOverlay && sourcePreview?Captions.FirstOrDefault(c=>c.Start<=sourceTime && c.End>sourceTime)?.Text ?? "":"";
        PreviewHeadline=DraftOverlay && sourcePreview && TimelineSeconds>=HeadlineStart && TimelineSeconds<HeadlineEnd?TemplateHeadline:"";
    }
    public async Task<bool> PersistWorkspaceAsync()
    {if(!HasEditor || SaveConflict)return !IsDirty;if(Busy)return false;await Guard(Save);return Error.Length==0 && !IsDirty;}
}
