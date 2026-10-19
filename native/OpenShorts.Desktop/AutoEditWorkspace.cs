using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace OpenShorts.Desktop;

public partial class AutoEffectRow : ObservableObject
{
    public JsonObject Definition { get; }
    public string Id=>Definition["id"]!.GetValue<string>();
    public string Type=>Definition["type"]!.GetValue<string>().Replace('_',' ');
    public string Reason=>Definition["reason"]!.GetValue<string>();
    [ObservableProperty] private double start;
    [ObservableProperty] private double end;
    [ObservableProperty] private double intensity;
    [ObservableProperty] private bool enabled;
    public AutoEffectRow(JsonObject value)
    { Definition=(JsonObject)value.DeepClone();start=value["start"]!.GetValue<double>();end=value["end"]!.GetValue<double>();intensity=value["intensity"]!.GetValue<double>();enabled=value["enabled"]!.GetValue<bool>(); }
    public JsonObject Export()
    {
        if(!double.IsFinite(Start)||!double.IsFinite(End)||!double.IsFinite(Intensity)||Start<0||End<=Start||Intensity<0||Intensity>1)
            throw new ArgumentException("Effect timing and intensity must be finite and within range.");
        var result=(JsonObject)Definition.DeepClone();result["start"]=Start;result["end"]=End;result["duration"]=End-Start;result["intensity"]=Intensity;result["enabled"]=Enabled;return result;
    }
}

public partial class MainViewModel
{
    public ObservableCollection<AutoEffectRow> AutoEffects {get;}=[];
    public string[] AutoEditProfiles {get;}=["minimal","balanced","dynamic","cinematic","custom"];
    [ObservableProperty] private bool autoEditEnabled=true;
    [ObservableProperty] private string autoEditProfile="balanced";
    [ObservableProperty] private bool autoZoom=true;
    [ObservableProperty] private bool autoTracking=true;
    [ObservableProperty] private bool autoTransitions=true;
    [ObservableProperty] private bool autoText=true;
    [ObservableProperty] private bool autoAudio;
    [ObservableProperty] private AutoEffectRow? selectedAutoEffect;
    [ObservableProperty] private string autoEditStatus="Use retained scene analysis. No additional provider requests.";
    [ObservableProperty] private int autoMaxEffects=5;
    [ObservableProperty] private double autoCameraGap=5;
    [ObservableProperty] private double autoMaxZoom=1.1;
    [ObservableProperty] private double autoMaxShake=.002;
    [ObservableProperty] private double autoMinDuration=.35;
    [ObservableProperty] private double autoMaxDuration=5;
    [ObservableProperty] private double autoMotionSensitivity=.75;
    private JsonObject? autoEditState;
    private void InitializeAutoEdit()
    {
        foreach(var name in new[]{nameof(AutoEditEnabled),nameof(AutoEditProfile),nameof(AutoZoom),nameof(AutoTracking),nameof(AutoTransitions),nameof(AutoText),nameof(AutoAudio),nameof(AutoMaxEffects),nameof(AutoCameraGap),nameof(AutoMaxZoom),nameof(AutoMaxShake),nameof(AutoMinDuration),nameof(AutoMaxDuration),nameof(AutoMotionSensitivity)})EditProperties.Add(name);
    }
    partial void OnAutoEditProfileChanged(string value)
    {
        if(applyingEdit||value=="custom")return;
        EditTogether(()=>
        {
            (AutoMaxEffects,AutoCameraGap,AutoMaxZoom,AutoMaxShake,AutoMinDuration,AutoMaxDuration,AutoMotionSensitivity)=value switch
            {
                "minimal"=>(2,8d,1.04,0d,.6,5d,.85),
                "dynamic"=>(8,3d,1.14,.004,.25,4d,.7),
                "cinematic"=>(4,7d,1.07,0d,.8,6d,.8),
                _=>(5,5d,1.10,.002,.35,5d,.75)
            };
        });
    }
    private void LoadAutoEdit(JsonObject edits)
    {
        foreach(var row in AutoEffects)row.PropertyChanged-=AutoEffectChanged;
        AutoEffects.Clear();autoEditState=edits["auto_edit"]?.DeepClone() as JsonObject;
        var value=autoEditState;
        AutoEditEnabled=value?["enabled"]?.GetValue<bool>() ?? true;AutoEditProfile=value?["profile"]?.GetValue<string>() ?? "balanced";
        AutoZoom=value?["zoom"]?.GetValue<bool>() ?? true;AutoTracking=value?["tracking"]?.GetValue<bool>() ?? true;
        AutoTransitions=value?["transitions"]?.GetValue<bool>() ?? true;AutoText=value?["text"]?.GetValue<bool>() ?? true;AutoAudio=value?["audio"]?.GetValue<bool>() ?? false;
        AutoMaxEffects=value?["limits"]?["max_effects"]?.GetValue<int>() ?? 5;AutoCameraGap=value?["limits"]?["camera_gap"]?.GetValue<double>() ?? 5;
        AutoMaxZoom=value?["limits"]?["max_zoom"]?.GetValue<double>() ?? 1.1;AutoMaxShake=value?["limits"]?["max_shake"]?.GetValue<double>() ?? .002;
        AutoMinDuration=value?["limits"]?["min_duration"]?.GetValue<double>() ?? .35;AutoMaxDuration=value?["limits"]?["max_duration"]?.GetValue<double>() ?? 5;
        AutoMotionSensitivity=value?["limits"]?["motion_sensitivity"]?.GetValue<double>() ?? .75;
        foreach(var item in value?["effects"]?.AsArray() ?? [])
            if(item is JsonObject effect){var row=new AutoEffectRow(effect);row.PropertyChanged+=AutoEffectChanged;AutoEffects.Add(row);}
        SelectedAutoEffect=AutoEffects.FirstOrDefault();
        AutoEditStatus=$"{AutoEffects.Count} effect decisions · {value?["scenes"]?.AsArray().Count ?? 0} retained scenes";
        var skipped=value?["skipped"]?.AsArray().FirstOrDefault()?["reason"]?.GetValue<string>();
        if(skipped is not null)AutoEditStatus+=$" · {skipped}";
    }
    private void AutoEffectChanged(object? sender,PropertyChangedEventArgs e)
    {
        if(applyingEdit)return;
        if(sender is AutoEffectRow row)row.Definition["origin"]="manual";
        EditingChanged(false);
    }
    private void AddAutoEdit(JsonObject edits)
    {
        var value=autoEditState is null?new JsonObject{["version"]=1,["scenes"]=new JsonArray(),["skipped"]=new JsonArray(),["source_segments"]=new JsonArray()}:(JsonObject)autoEditState.DeepClone();
        value["enabled"]=AutoEditEnabled;value["profile"]=AutoEditProfile;value["zoom"]=AutoZoom;value["tracking"]=AutoTracking;
        value["transitions"]=AutoTransitions;value["text"]=AutoText;value["audio"]=AutoAudio;
        value["limits"]=new JsonObject{["max_effects"]=AutoMaxEffects,["camera_gap"]=AutoCameraGap,["max_zoom"]=AutoMaxZoom,["max_shake"]=AutoMaxShake,["min_duration"]=AutoMinDuration,["max_duration"]=AutoMaxDuration,["motion_sensitivity"]=AutoMotionSensitivity};
        value["effects"]=new JsonArray(AutoEffects.Select(e=>(JsonNode)e.Export()).ToArray());edits["auto_edit"]=value;
    }
    [RelayCommand(CanExecute=nameof(CanEdit))]
    private Task RegenerateAutoEffects()=>Guard(async token=>
    {
        await Save(token);
        var reply=await engine.SendAsync(EditorRoute+"/auto-edit",new JsonObject{["revision"]=editor!["revision"]!.DeepClone(),["settings"]=BuildEdits()["auto_edit"]!.DeepClone()},cancellationToken:token);
        EditTogether(()=>
        {
            applyingEdit=true;
            try{LoadAutoEdit(new JsonObject{["auto_edit"]=reply["auto_edit"]!.DeepClone()});}
            finally{applyingEdit=false;}
        });
        AutoEditStatus+=" · Reused analysis; no Gemini call or transcription.";
    });
    [RelayCommand(CanExecute=nameof(CanEdit))]
    private void RemoveAutoEffects()=>EditTogether(()=>
    {
        foreach(var row in AutoEffects.Where(e=>e.Definition["origin"]?.GetValue<string>()=="ai").ToArray())AutoEffects.Remove(row);
        SelectedAutoEffect=AutoEffects.FirstOrDefault();AutoEditStatus="AI effects removed. Manual effect edits kept.";
    });
    [RelayCommand(CanExecute=nameof(CanEdit))]
    private void RemoveSelectedAutoEffect()
    { if(SelectedAutoEffect is null)return;EditTogether(()=>{AutoEffects.Remove(SelectedAutoEffect);SelectedAutoEffect=AutoEffects.FirstOrDefault();}); }
    [RelayCommand(CanExecute=nameof(CanEdit))]
    private async Task PreviewAutoEffect()
    {
        if(SelectedAutoEffect is null)return;var at=SelectedAutoEffect.Start;
        await Render("preview");if(string.IsNullOrEmpty(Error))SeekTimeline(at);
    }
}
