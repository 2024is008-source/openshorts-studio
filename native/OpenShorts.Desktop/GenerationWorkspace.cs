using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using OpenShorts.Core;
using OpenShorts.EngineBridge;

namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    public string[] OutputFormats { get; }=["vertical","horizontal","square"];
    public string[] GenerationModes { get; }=["clips","highlights"];
    public string[] AnalysisModes { get; }=["transcript","hybrid","adaptive-economy","adaptive-balanced","adaptive-quality"];
    public string[] AnalysisCategories {get;}=["auto","podcast","podcast-motivation","podcast-education","podcast-comedy","challenge","challenge-competition","challenge-survival","challenge-experiment","challenge-general","sports_highlights","cricket","football","general"];
    public string[] GenerationCaptionPresets=>new[]{"auto"}.Concat(CaptionPresets).Distinct().ToArray();
    public string[] QualityModes { get; }=["standard","studio"];
    public string[] FramingPresets { get; }=["auto","balanced","subject","editorial"];
    public string[] PacingModes { get; }=["fast","balanced","emotional","educational"];
    public string[] AudioPresets { get; }=["natural","dialogue","original"];
    [ObservableProperty] private bool sourceHasCaptions;
    [ObservableProperty] private bool automaticClipDuration;
    [ObservableProperty] private bool automaticClipCount;
    [ObservableProperty] private double? minimumClipSeconds;
    [ObservableProperty] private double? maximumClipSeconds;
    [ObservableProperty] private string sourceUrl="";
    [ObservableProperty] private string outputFormat="vertical";
    [ObservableProperty] private string generationMode="clips";
    [ObservableProperty] private string analysisMode="adaptive-balanced";
    [ObservableProperty] private string analysisCategory="auto";
    [ObservableProperty] private string analysisPrompt="";
    [ObservableProperty] private double summarySeconds=60;
    [ObservableProperty] private int targetClipCount=5;
    [ObservableProperty] private double targetClipSeconds=30;
    [ObservableProperty] private bool generateCaptions=true;
    [ObservableProperty] private string generationCaptionPreset="auto";
    [ObservableProperty] private string generationQuality="standard";
    [ObservableProperty] private string generationFraming="auto";
    [ObservableProperty] private string generationPacing="balanced";
    [ObservableProperty] private bool trimSilence;
    [ObservableProperty] private string generationAudio="natural";
    [ObservableProperty] private double audioLufs=-16;
    [ObservableProperty] private double audioPeak=-2;
    [ObservableProperty] private double audioFade;
    [ObservableProperty] private bool audioNoise;
    [ObservableProperty] private bool autoHook;
    public ObservableCollection<string> ProcessingLog { get; }=[];
    public ObservableCollection<ClipInsight> ClipInsights { get; }=[];
    public string ClipCountLabel=>Clips.Count==1?"1 clip in this project":$"{Clips.Count} clips in this project";
    [RelayCommand] private void ClearTemplate()=>SelectedTemplate=null;
    partial void OnSourceUrlChanged(string value)=>NotifyCommands();
    internal GenerationSettings CaptureGenerationSettings()=>new GenerationSettings{SourceHasCaptions=SourceHasCaptions,AutoDuration=AutomaticClipDuration,AutoCount=AutomaticClipCount,MinimumSeconds=MinimumClipSeconds,MaximumSeconds=MaximumClipSeconds,OutputFormat=OutputFormat,Mode=GenerationMode,Analysis=AnalysisMode,SummarySeconds=SummarySeconds,
        AnalysisCategory=AnalysisCategory,AnalysisPrompt=AnalysisPrompt,
        TargetClips=TargetClipCount,TargetSeconds=TargetClipSeconds,Captions=GenerateCaptions,CaptionPreset=GenerationCaptionPreset,Quality=GenerationQuality,
        Framing=GenerationFraming,Pacing=GenerationPacing,TrimSilence=TrimSilence,AudioPreset=GenerationAudio,AudioTarget=AudioLufs,AudioPeak=AudioPeak,
        AudioFade=AudioFade,AudioNoise=AudioNoise,AutoHook=AutoHook};
    partial void OnGenerateCaptionsChanged(bool value){if(value)SourceHasCaptions=false;}
    partial void OnSourceHasCaptionsChanged(bool value){if(value)GenerateCaptions=false;}
    partial void OnGenerationModeChanged(string value){if(value=="highlights"){AutomaticClipDuration=false;if(!AnalysisMode.StartsWith("adaptive-"))AnalysisMode="hybrid";}}
    private JsonObject GenerationFields()=>CaptureGenerationSettings().ToFields();
    internal void ApplyGenerationSettings(GenerationSettings s)
    {
        s.ToFields();SourceHasCaptions=s.SourceHasCaptions;AutomaticClipDuration=s.AutoDuration;AutomaticClipCount=s.AutoCount;MinimumClipSeconds=s.MinimumSeconds;MaximumClipSeconds=s.MaximumSeconds;
        OutputFormat=s.OutputFormat;GenerationMode=s.Mode;AnalysisMode=s.Mode=="highlights"&&!s.Analysis.StartsWith("adaptive-")?"hybrid":s.Analysis;SummarySeconds=s.SummarySeconds;
        AnalysisCategory=s.AnalysisCategory;AnalysisPrompt=s.AnalysisPrompt;
        TargetClipCount=s.TargetClips;TargetClipSeconds=s.TargetSeconds;GenerateCaptions=s.Captions;GenerationCaptionPreset=s.CaptionPreset;
        GenerationQuality=s.Quality;GenerationFraming=s.Framing;GenerationPacing=s.Pacing;TrimSilence=s.TrimSilence;
        GenerationAudio=s.AudioPreset;AudioLufs=s.AudioTarget;AudioPeak=s.AudioPeak;AudioFade=s.AudioFade;AudioNoise=s.AudioNoise;AutoHook=s.AutoHook;
    }
    private async Task<string> SubmitGeneration(CancellationToken token)
    {
        var fields=GenerationFields();
        if(string.IsNullOrWhiteSpace(SourceUrl))return await engine.UploadAsync(ImportedFile,Acknowledged,GenerationTemplateId,token,fields);
        if(!Uri.TryCreate(SourceUrl,UriKind.Absolute,out var url) || url.Scheme is not ("https" or "http"))throw new ArgumentException("Enter an HTTP or HTTPS source URL.");
        fields["url"]=url.AbsoluteUri;fields["acknowledged"]=Acknowledged;
        fields["video_template"]=GenerationTemplateId;
        return EngineClient.JobId((await engine.SendAsync("/api/process",fields,cancellationToken:token))["job_id"]!.GetValue<string>());
    }
    private void UpdateProcessingLog(JsonObject data)
    {
        ProcessingLog.Clear();foreach(var line in (data["logs"]?.AsArray() ?? []).TakeLast(200))ProcessingLog.Add(line!.GetValue<string>());
    }
    private void LoadInsights(string id,JsonObject result)
    {
        ClipInsights.Clear();int i=0;
        foreach(var node in result["clips"]?.AsArray() ?? [])
        {
            var index=node!["clip_index"]?.GetValue<int>() ?? i++;
            var score=node["ranking_report"]?["overall"]?.ToString() ?? node["selection_score"]?.ToString() ?? "—";
            ClipInsights.Add(new(index,node["title"]?.GetValue<string>() ?? $"Clip {index+1}",score,node["selection_origin"]?.ToString() ?? "Retained selection"));
        }
        OnPropertyChanged(nameof(ClipCountLabel));
    }
}
public sealed record ClipInsight(int Index,string Title,string Score,string Origin);
