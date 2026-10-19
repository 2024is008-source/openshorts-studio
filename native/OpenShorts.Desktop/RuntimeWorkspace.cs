using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using System.Text.Json.Nodes;

namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    [ObservableProperty] private string modelAvailability="Refresh runtime status to inspect the speech model. Downloads start only when requested.";
    [ObservableProperty] private string optionalRendererStatus="Optional renderer is not started. Native editor export uses FFmpeg.";
    private void ApplyRuntime(JsonObject model,JsonObject renderer)
    {
        ModelAvailability=$"Whisper small: {model["state"]} · {model["downloaded_bytes"]}/{model["total_bytes"]} bytes · {model["error_code"]}";
        OptionalRendererStatus=$"Optional renderer: {renderer["state"]} · installed {renderer["installed"]} · configured {renderer["configured"]} · running {renderer["running"]} · ready {renderer["ready"]} · {renderer["error_code"]}";
    }
    private async Task RefreshRuntimeAsync(CancellationToken token)
    { ApplyRuntime(await engine.GetAsync("/api/desktop/models/whisper",token),await engine.GetAsync("/api/desktop/renderer",token)); }
    [RelayCommand] private Task RefreshRuntime()=>Guard(RefreshRuntimeAsync);
    [RelayCommand] private Task DownloadSpeechModel()=>Guard(async token=>
    {
        if(System.Windows.MessageBox.Show("Download the pinned Whisper small speech model (about 486 MB) to your library? Existing partial files can resume. Internet and free disk space are required.","Prepare local speech model",System.Windows.MessageBoxButton.YesNo,System.Windows.MessageBoxImage.Question)!=System.Windows.MessageBoxResult.Yes)return;
        await engine.SendAsync("/api/desktop/models/whisper/prepare",new JsonObject{["acknowledged"]=true},cancellationToken:token);
        await RefreshRuntimeAsync(token);Status="Model preparation started. Refresh status to check progress. A ready model is used by the next transcription.";
    });
    [RelayCommand] private Task CancelSpeechModel()=>Guard(async token=>{await engine.SendAsync("/api/desktop/models/whisper/cancel",new(),cancellationToken:token);await RefreshRuntimeAsync(token);});
    [RelayCommand] private Task StartOptionalRenderer()=>Guard(async token=>{await engine.SendAsync("/api/desktop/renderer/start",new(),cancellationToken:token);await RefreshRuntimeAsync(token);});
    [RelayCommand] private Task StopOptionalRenderer()=>Guard(async token=>{await engine.SendAsync("/api/desktop/renderer/stop",new(),cancellationToken:token);await RefreshRuntimeAsync(token);});
    [RelayCommand] private Task RestartOptionalRenderer()=>Guard(async token=>{await engine.SendAsync("/api/desktop/renderer/restart",new(),cancellationToken:token);await RefreshRuntimeAsync(token);});
}
