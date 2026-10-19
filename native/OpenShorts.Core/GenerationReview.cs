using System.Text.Json.Nodes;
namespace OpenShorts.Core;

public sealed record GenerationProgress(string State,string Stage,double? Overall,double? Elapsed,string? Error,IReadOnlyList<GenerationStage> Stages,IReadOnlyList<string> Diagnostics,bool CanCancel)
{
    public bool Terminal=>State is "completed" or "failed" or "cancelled";
    public static GenerationProgress Parse(JsonObject data)
    {
        string state=data["state"]?.ToString() ?? "idle";
        if(state is not ("idle" or "preparing" or "running" or "cancel_requested" or "cancelled" or "failed" or "completed"))throw new IOException("Unsupported generation state.");
        double? overall=Number(data["overall"]);
        if(overall is <0 or >100 || state!="completed")overall=null;
        return new(state,data["stage"]?.ToString() ?? "Preparing source",overall,Number(data["elapsed_seconds"]),data["error"]?.ToString(),
            (data["stages"]?.AsArray() ?? []).Select(s=>new GenerationStage(s!["title"]!.ToString(),s["state"]!.ToString(),StagePercent(s["percent"]),Number(s["completed_count"]),Number(s["total_count"]),Number(s["elapsed_seconds"]),s["cache_reuse"]?.GetValue<bool>()==true,s["retry"]?.GetValue<bool>()==true)).ToArray(),
            (data["diagnostics"]?.AsArray() ?? []).Select(s=>s!.ToString()).ToArray(),data["can_cancel"]?.GetValue<bool>()==true);
    }
    private static double? StagePercent(JsonNode? value){var n=Number(value);return n is >=0 and <=100?n:null;}
    public static double? Number(JsonNode? value)=>double.TryParse(value?.ToString(),System.Globalization.NumberStyles.Float,System.Globalization.CultureInfo.InvariantCulture,out var n)&&double.IsFinite(n)?n:null;
}
public sealed record GenerationStage(string Title,string State,double? Percent=null,double? Completed=null,double? Total=null,double? Elapsed=null,bool Cache=false,bool Retry=false)
{
    public string Icon=>State=="completed"?"circle-check":State=="active"?"audio-lines":"circle";
    public string Color=>State=="completed"?"#22C55E":State=="active"?"#00D8EF":State=="failed"?"#FB526E":"#66839B";
    public string PercentLabel=>Percent is double n?$"{n:0}%":State=="active"?"Working…":"—";
    public double ProgressValue=>Percent ?? 0;
    public string Description=>Elapsed is double seconds?$"{(Total is >0?$"{Completed:0}/{Total:0} · ":"")}{seconds:0.0}s{(Cache?" · cached":"")}{(Retry?" · retry":"")}":Title switch {"Preparing source"=>"Validating the source video", "Transcribing audio"=>"Converting speech to text", "Analyzing content with Gemini"=>"Finding key moments and story structure", "Selecting clip candidates"=>"Choosing engaging segments", "Rendering selected clips"=>"Framing, captions and audio", _=>"Checking generated outputs"};
    public string Label=>State switch {"completed"=>"Completed", "active"=>"In progress", "failed"=>"Failed", "reported"=>"Reported by engine",_=>"Pending"};
}
public sealed record ReviewRecord(int Index,string Title,double Start,double End,double Duration,double? Score,string Status,string VideoUrl,string Explanation,string Tags,string Hook,string Resolution,string Format,string Caption,string Framing,string Audio,string Metrics)
{
    public bool Ready=>Status=="ready" && VideoUrl.StartsWith("/videos/",StringComparison.Ordinal);
    public string ScoreLabel=>Score is double n?$"{n:0}/100":"Unscored";
    public string DurationLabel=>TimeSpan.FromSeconds(Math.Max(0,Duration)).ToString(@"mm\:ss");
    public static ReviewRecord Parse(JsonObject c)
    {
        string S(string key)=>c[key]?.ToString() ?? "";
        double N(string key)=>GenerationProgress.Number(c[key]) ?? 0;
        var score=GenerationProgress.Number(c["score"]);if(score is <0 or >100)score=null;
        return new(c["index"]!.GetValue<int>(),S("title"),N("start"),N("end"),N("duration"),score,S("status"),S("video_url"),S("explanation"),string.Join(" · ",(c["tags"]?.AsArray() ?? []).Select(t=>t!.ToString())),S("hook"),S("resolution"),S("format"),S("caption_preset"),S("framing"),S("audio"),string.Join(" · ",(c["metrics"]?.AsObject() ?? []).Select(p=>$"{p.Key}: {p.Value}")));
    }
}
