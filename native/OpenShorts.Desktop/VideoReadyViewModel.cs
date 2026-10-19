using System.Text.Json;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using OpenShorts.Core;
using OpenShorts.EngineBridge;

namespace OpenShorts.Desktop;
public partial class VideoReadyViewModel : ObservableObject, IDisposable
{
    private readonly IEngineBridge engine;
    private readonly IUserStorage storage;
    private readonly Func<GenerationDraft,Task> accept;
    private readonly bool keepCurrent;
    private GenerationDraft draft;
    private JsonObject captionStyles=new();
    private MediaPreview? preview;
    private bool loaded,completed,inputInvalid,selectionError;
    [ObservableProperty] private string categoryExplanation="Auto Detect uses bounded source evidence and configured Gemini on import. It may use API quota; the full video is never sent for classification.";
    private string? detectedCategory;
    public ReadyOption[] CategoryOptions {get;}=[new("auto","Auto Detect"),new("podcast","Podcast"),new("challenge","Challenge"),new("sports_highlights","Sports Highlights"),new("general","General")];
    public string PrimaryCategory
    {
        get=>VideoCategories.Parse(Settings.AnalysisCategory).Primary;
        set {if(value is not null)Change(Settings with{AnalysisCategory=VideoCategories.Id(value,"auto")});}
    }
    public string[] Subcategories=>VideoCategories.Registry.TryGetValue(PrimaryCategory,out var subs)?subs:["auto"];
    public string Subcategory
    {
        get=>VideoCategories.Parse(Settings.AnalysisCategory).Subcategory;
        set {if(value is not null && Subcategories.Contains(value))Change(Settings with{AnalysisCategory=VideoCategories.Id(PrimaryCategory,value)});}
    }
    [ObservableProperty] private bool busy;
    [ObservableProperty] private string error="";
    [ObservableProperty] private int selectedTab;
    [ObservableProperty] private bool previewActive;
    public ImportedVideo Media { get; }
    public IReadOnlyList<TemplateItem> Templates { get; }
    public string CredentialStatus { get; }
    public string[] CaptionPresets { get; }
    public ReadyOption[] FramingPresets { get; }=[new("auto","Automatic · Subject and Scene"),new("subject","Focus on Dominant Subject"),new("balanced","Balanced · Preserve Groups"),new("editorial","Editorial · Detail and Context")];
    public ReadyOption[] PacingModes { get; }=[new("fast","Fast"),new("balanced","Balanced"),new("emotional","Emotional"),new("educational","Educational")];
    public ReadyOption[] AudioPresets { get; }=[new("natural","Natural"),new("dialogue","Clear Dialogue"),new("original","Original · No Mastering")];
    public ReadyOption[] QualityModes { get; }=[new("standard","Standard"),new("studio","High Quality · Studio")];
    public bool CanContinue=>loaded && !Busy && !completed && !inputInvalid;
    public bool CanEdit=>!Busy;
    public bool IsClips=>Mode=="clips";
    public bool IsSummary=>!IsClips;
    public bool CanSetTarget=>!AutoDuration;
    public bool CanCustomizeAudio=>AudioPreset!="original";
    public bool ShowThumbnail=>!PreviewActive;
    public LibVLCSharp.Shared.MediaPlayer? Player=>preview?.Player;
    public string Title=>string.IsNullOrWhiteSpace(Media.Title)?Path.GetFileName(Media.Path):Media.Title;
    public string? Thumbnail { get; }
    public string SourceInfo=>$"{Media.Platform} · {TimeSpan.FromSeconds(Media.Duration):hh\\:mm\\:ss} · {Media.Width} × {Media.Height}";
    public string FileInfo=>$"{Media.Size/1048576d:F1} MB · {Media.Format} · "+(Media.FrameRate>0?$"{Media.FrameRate:F2} FPS":"Frame rate unavailable");
    public string CodecInfo=>$"{Media.Codec} / "+(Media.AudioCodec.Length>0?Media.AudioCodec:"No audio stream");
    public string OutputLocation=>draft.OutputLocation;
    public string EncoderInfo=>$"{draft.Encoder} · H.264 / AAC in MP4 · CPU fallback";
    public string OutputDescription=>Ratio switch {"square"=>"Square output · MP4 / H.264 / AAC","horizontal"=>"Landscape output · MP4 / H.264 / AAC",_=>"Portrait output · MP4 / H.264 / AAC"};
    private JsonObject? CaptionStyle=>captionStyles[CaptionPreset] as JsonObject;
    public System.Windows.Media.FontFamily CaptionFont=>CaptionStyle?["font_name"]?.GetValue<string>() is "Anton"?new(new Uri("pack://application:,,,/"),"./Assets/Fonts/#Anton"):new(CaptionStyle?["font_name"]?.GetValue<string>() ?? "Arial");
    public System.Windows.Media.Brush CaptionColor=>(System.Windows.Media.Brush)new System.Windows.Media.BrushConverter().ConvertFromString(CaptionStyle?["highlight_color"]?.GetValue<string>() ?? "#FFFFFF")!;
    public System.Windows.Media.Brush CaptionBaseColor=>(System.Windows.Media.Brush)new System.Windows.Media.BrushConverter().ConvertFromString(CaptionStyle?["font_color"]?.GetValue<string>() ?? "#FFFFFF")!;
    public double CaptionSize=>Math.Clamp((CaptionStyle?["font_size"]?.GetValue<double>() ?? 52)*.35,18,36);
    public string CaptionSample=>CaptionStyle?["uppercase"]?.GetValue<bool>() is true?"YOUR NEXT STORY":"Your next story";
    public string CaptionEffect=>"Preset effect: "+(CaptionStyle?["effect"]?.GetValue<string>() ?? "none")+" · Static style sample; preview animation in Video Editor.";
    public GenerationSettings Settings=>draft.Settings;
    private void Change(GenerationSettings value)
    {
        draft=draft with{Settings=value};
        if(selectionError && !inputInvalid)
        {try{draft.Validate(Media.Duration);Error="";selectionError=false;}catch(ArgumentException e){Error=e.Message;}}
        OnPropertyChanged((string?)null);
    }
    public string Mode {get=>Settings.Mode;set=>Change(Settings with{Mode=value,Analysis=value=="highlights"&&!Settings.Analysis.StartsWith("adaptive-")?"hybrid":Settings.Analysis,AutoDuration=value=="highlights"?false:Settings.AutoDuration});}
    public string Analysis {get=>Settings.Analysis;set=>Change(Settings with{Analysis=value});}
    public string Ratio {get=>Settings.OutputFormat;set=>Change(Settings with{OutputFormat=value});}
    public string Pacing {get=>Settings.Pacing;set=>Change(Settings with{Pacing=value});}
    public string Framing {get=>Settings.Framing;set=>Change(Settings with{Framing=value});}
    public string Quality {get=>Settings.Quality;set=>Change(Settings with{Quality=value});}
    public bool AutoDuration {get=>Settings.AutoDuration;set=>Change(Settings with{AutoDuration=value});}
    public bool AutoCount {get=>Settings.AutoCount;set=>Change(Settings with{AutoCount=value});}
    public int Count {get=>Settings.TargetClips;set=>Change(Settings with{TargetClips=value});}
    public string DurationSelection {get=>AutoDuration?"auto":TargetSeconds is 15 or 30 or 60?TargetSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture):"custom";set=>Duration(value);}
    public double TargetSeconds {get=>IsSummary?Settings.SummarySeconds:Settings.TargetSeconds;set=>Change(IsSummary?Settings with{SummarySeconds=value}:Settings with{TargetSeconds=value});}
    public double? Minimum {get=>Settings.MinimumSeconds;set=>Change(Settings with{MinimumSeconds=value});}
    public double? Maximum {get=>Settings.MaximumSeconds;set=>Change(Settings with{MaximumSeconds=value});}
    public bool Captions {get=>Settings.Captions;set=>Change(Settings with{Captions=value,SourceHasCaptions=value?false:Settings.SourceHasCaptions});}
    public string CaptionPreset {get=>Settings.CaptionPreset;set=>Change(Settings with{CaptionPreset=value});}
    public bool ExistingCaptions {get=>Settings.SourceHasCaptions;set=>Change(Settings with{SourceHasCaptions=value,Captions=value?false:Settings.Captions});}
    public bool AutoHook {get=>Settings.AutoHook;set=>Change(Settings with{AutoHook=value});}
    public bool TrimSilence {get=>Settings.TrimSilence;set=>Change(Settings with{TrimSilence=value});}
    public string AudioPreset {get=>Settings.AudioPreset;set=>Change(Settings with{AudioPreset=value});}
    public double AudioTarget {get=>Settings.AudioTarget;set=>Change(Settings with{AudioTarget=value});}
    public double AudioPeak {get=>Settings.AudioPeak;set=>Change(Settings with{AudioPeak=value});}
    public double AudioFade {get=>Settings.AudioFade;set=>Change(Settings with{AudioFade=value});}
    public bool AudioNoise {get=>Settings.AudioNoise;set=>Change(Settings with{AudioNoise=value});}
    public string TemplateId {get=>draft.TemplateId;set{draft=draft with{TemplateId=value ?? ""};OnPropertyChanged();}}
    public event Action? Accepted;
    public event Action? ChangeRequested;
    public VideoReadyViewModel(IEngineBridge engine,IUserStorage storage,ImportedVideo media,GenerationDraft draft,string credentialStatus,string[] captions,IReadOnlyList<TemplateItem> templates,Func<GenerationDraft,Task> accept,bool keepCurrent=false)
    {
        this.keepCurrent=keepCurrent;this.engine=engine;this.storage=storage;Media=media;this.draft=draft;this.accept=accept;CredentialStatus=credentialStatus;CaptionPresets=new[]{"auto"}.Concat(captions).Distinct().ToArray();Templates=new[]{new TemplateItem("auto","Automatic · choose from story",new()),new TemplateItem("none","None · captions only",new())}.Concat(templates).ToArray();
        if(media.Thumbnail is string path)try{Thumbnail=storage.ValidateProjectMedia(path);}catch(IOException){}
    }
    public async Task LoadAsync()
    {
        Busy=true;Error="";
        try
        {
            var response=await engine.GetAsync($"/api/desktop/imports/{Media.Id}/settings");
            captionStyles=(await engine.GetAsync("/api/desktop/caption-presets"))["presets"]?.AsObject() ?? throw new IOException("Caption styles are unavailable.");
            if(response["draft"] is JsonObject saved)
            {
                var restored=saved.Deserialize<GenerationDraft>() ?? throw new IOException("Saved settings are invalid.");restored.Validate(Media.Duration);
                draft=keepCurrent?draft with{Revision=restored.Revision}:restored with{Encoder=draft.Encoder,OutputLocation=draft.OutputLocation};
            }
            draft.Validate(Media.Duration);loaded=true;OnPropertyChanged((string?)null);
            if(!keepCurrent && PrimaryCategory=="auto")await DetectCategoryCore();
        }
        catch(Exception e) when(e is IOException or ArgumentException or JsonException or System.Net.Http.HttpRequestException or OperationCanceledException){Error=e.Message;}
        finally{Busy=false;OpenCommand.NotifyCanExecuteChanged();}
    }
    partial void OnBusyChanged(bool value){OnPropertyChanged(nameof(CanContinue));OnPropertyChanged(nameof(CanEdit));OpenCommand.NotifyCanExecuteChanged();}
    partial void OnPreviewActiveChanged(bool value)=>OnPropertyChanged(nameof(ShowThumbnail));
    public void SetInputInvalid(bool value)
    {
        inputInvalid=value;
        if(value)Error="Correct the highlighted numeric field before continuing.";
        else if(Error=="Correct the highlighted numeric field before continuing.")Error="";
        OnPropertyChanged(nameof(CanContinue));OpenCommand.NotifyCanExecuteChanged();
    }
    [RelayCommand] private void Duration(string value)
    {
        if(value=="custom"){AutoDuration=false;return;}
        if(value=="auto"){if(IsClips)AutoDuration=true;return;}
        AutoDuration=false;TargetSeconds=double.Parse(value,System.Globalization.CultureInfo.InvariantCulture);
    }
    [RelayCommand] private void ClearBand(){Minimum=null;Maximum=null;}
    [RelayCommand] private void ClearTemplate()=>TemplateId="none";
    [RelayCommand] private void AutoVisuals(){Framing="auto";TemplateId="auto";}
    [RelayCommand] private async Task DetectCategory()
    {
        if(Busy)return;
        Busy=true;
        try{await DetectCategoryCore();}
        finally{Busy=false;}
    }
    private async Task DetectCategoryCore()
    {
        CategoryExplanation="Detecting video category from available source evidence…";
        try
        {
            using var timeout=new CancellationTokenSource(TimeSpan.FromMinutes(4));
            var result=await engine.SendAsync($"/api/desktop/imports/{Media.Id}/category",new(),cancellationToken:timeout.Token);
            var primary=result["primary_category"]!.GetValue<string>();var sub=result["subcategory"]!.GetValue<string>();
            detectedCategory=VideoCategories.Id(primary,sub);
            CategoryExplanation=$"Suggested: {primary} / {sub} · {result["classification_method"]} · model estimate {result["confidence"]} (uncalibrated) · review required: {result["review_required"]}. {result["explanation"]}. Current selection is preserved. Use the suggestion or choose an override.";
        }
        catch(Exception e) when(e is IOException or ArgumentException or JsonException or System.Net.Http.HttpRequestException or OperationCanceledException)
        {CategoryExplanation="Category detection unavailable. Choose a category manually or keep the conservative automatic fallback.";}
    }
    [RelayCommand] private void UseDetectedCategory()
    {
        if(detectedCategory is not null)Change(Settings with{AnalysisCategory=detectedCategory});
    }
    [RelayCommand] private void ChangeVideo(){if(!Busy)ChangeRequested?.Invoke();}
    [RelayCommand] private void Play()
    {
        try
        {
            if(preview is null){preview=new();OnPropertyChanged(nameof(Player));preview.Open(Media.Path);PreviewActive=true;}
            else if(preview.Player.IsPlaying)preview.Player.Pause();else preview.Player.Play();
        }
        catch(IOException e){Error=e.Message;}
    }
    [RelayCommand(CanExecute=nameof(CanContinue))] private async Task Open()
    {
        Busy=true;Error="";
        try
        {
            draft.Validate(Media.Duration);
            if(!System.IO.File.Exists(Media.Path))throw new IOException("The source was removed. Change the video and retry.");
            var response=await engine.SendAsync($"/api/desktop/imports/{Media.Id}/settings",JsonSerializer.SerializeToNode(draft)!.AsObject(),put:true);
            draft=response["draft"]!.Deserialize<GenerationDraft>()!;
            await accept(draft);completed=true;Accepted?.Invoke();
        }
        catch(ArgumentException e){selectionError=true;Error=e.Message;}
        catch(Exception e) when(e is IOException or JsonException or System.Net.Http.HttpRequestException or OperationCanceledException){Error=e.Message;}
        finally{Busy=false;}
    }
    public void Dispose(){preview?.Dispose();preview=null;}
}

public sealed record ReadyOption(string Value,string Label){public override string ToString()=>Label;}
