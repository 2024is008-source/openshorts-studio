using System.Text.Json.Serialization;
using System.Globalization;
using System.Text.Json.Nodes;
namespace OpenShorts.Core;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record GenerationSettings
{
    public bool SourceHasCaptions { get; init; }
    public bool AutoDuration { get; init; }
    public bool AutoCount { get; init; }
    public double? MinimumSeconds { get; init; }
    public double? MaximumSeconds { get; init; }
    public string HighlightStrategy { get; init; }="auto";
    public string OutputFormat { get; init; }="vertical";
    public string Mode { get; init; }="clips";
    public string Analysis { get; init; }="transcript";
    public string AnalysisCategory { get; init; }="auto";
    public string AnalysisPrompt { get; init; }="";
    public double SummarySeconds { get; init; }=60;
    public int TargetClips { get; init; }=5;
    public double TargetSeconds { get; init; }=30;
    public string CaptionPreset { get; init; }="clean-minimal";
    public bool Captions { get; init; }=true;
    public string Quality { get; init; }="standard";
    public string Framing { get; init; }="auto";
    public string Pacing { get; init; }="balanced";
    public bool TrimSilence { get; init; }
    public string AudioPreset { get; init; }="natural";
    public double AudioTarget { get; init; }=-16;
    public double AudioPeak { get; init; }=-2;
    public double AudioFade { get; init; }
    public bool AudioNoise { get; init; }
    public bool AutoHook { get; init; }
    public JsonObject ToFields()
    {
        static void Choice(string value,string[] choices){if(!choices.Contains(value))throw new ArgumentException("Choose a supported generation option.");}
        static void Range(double value,double low,double high){if(!double.IsFinite(value)||value<low||value>high)throw new ArgumentException($"Generation value must be between {low} and {high}.");}
        if(SourceHasCaptions && Captions)throw new ArgumentException("Disable new captions when the source already has captions.");
        Choice(HighlightStrategy,["auto"]);
        Choice(OutputFormat,["vertical","horizontal","square"]);Choice(Mode,["clips","highlights"]);Choice(Analysis,["transcript","hybrid","adaptive-economy","adaptive-balanced","adaptive-quality"]);
        VideoCategories.Parse(AnalysisCategory);
        if(AnalysisPrompt.Length>500)throw new ArgumentException("Keep the analysis prompt within 500 characters.");
        Choice(Quality,["standard","studio"]);Choice(Framing,["auto","balanced","subject","editorial"]);Choice(Pacing,["fast","balanced","emotional","educational"]);
        Choice(AudioPreset,["natural","dialogue","original"]);
        Choice(CaptionPreset,["auto","clean-minimal","bold-creator","dynamic-highlight","podcast","cinematic","openshorts-dynamic","creator-bold","clean-podcast","minimal","green-pop","teal-reveal","paper-focus"]);
        Range(SummarySeconds,30,180);Range(TargetClips,1,12);Range(TargetSeconds,10,150);Range(AudioTarget,-24,-12);Range(AudioPeak,-6,-1);Range(AudioFade,0,2);
        string N(double v)=>v.ToString(CultureInfo.InvariantCulture);
        string B(bool v)=>v?"true":"false";
        if(MinimumSeconds is double minimum)Range(minimum,5,175);
        if(MaximumSeconds is double maximum)Range(maximum,10,180);
        if(MinimumSeconds is double lo && MaximumSeconds is double hi && hi<lo+5)throw new ArgumentException("Maximum duration must be at least 5 seconds above minimum.");
        if(!AutoDuration && (MinimumSeconds is double low && TargetSeconds<low || MaximumSeconds is double high && TargetSeconds>high))throw new ArgumentException("The duration band must contain the target length.");
        if(Mode=="highlights" && AutoDuration)throw new ArgumentException("Highlight summaries require a target duration.");
        var fields=new JsonObject(){["output_format"]=OutputFormat,["generation_mode"]=Mode,["analysis_mode"]=Analysis,["summary_seconds"]=N(SummarySeconds),
            ["analysis_category"]=AnalysisCategory,["analysis_prompt"]=AnalysisPrompt,
            ["target_clips"]=N(TargetClips),["clip_target_seconds"]=N(TargetSeconds),["caption_preset"]=CaptionPreset,["captions"]=B(Captions),
            ["quality_preset"]=Quality,["framing_preset"]=Framing,["pacing_mode"]=Pacing,["trim_silence"]=B(TrimSilence),
            ["audio_preset"]=AudioPreset,["audio_target_lufs"]=N(AudioTarget),["audio_true_peak"]=N(AudioPeak),["audio_fade_seconds"]=N(AudioFade),
            ["audio_noise_reduction"]=B(AudioNoise),["auto_hook"]=B(AutoHook)};
        if(AutoDuration)fields.Remove("clip_target_seconds");
        if(AutoCount)fields.Remove("target_clips");
        if(MinimumSeconds is double min)fields["clip_min_seconds"]=N(min);
        if(MaximumSeconds is double max)fields["clip_max_seconds"]=N(max);
        return fields;
    }
}
