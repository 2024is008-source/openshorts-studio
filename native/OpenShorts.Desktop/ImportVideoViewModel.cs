using System.Text.Json.Nodes;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using OpenShorts.Core;
using OpenShorts.EngineBridge;

namespace OpenShorts.Desktop;
public partial class ImportVideoViewModel(IEngineBridge engine,IUserStorage storage,Action<ImportedVideo,string?> accept) : ObservableObject
{
    [ObservableProperty] private string url="";
    [ObservableProperty] private bool rightsConfirmed;
    [ObservableProperty] private bool busy;
    [ObservableProperty] private bool urlTab;
    [ObservableProperty] private string title="No video selected";
    [ObservableProperty] private string details="Choose a file or paste a supported public video URL.";
    [ObservableProperty] private string status="Ready to import";
    [ObservableProperty] private string error="";
    [ObservableProperty] private string? thumbnail;
    [ObservableProperty] private string state="ready";
    [ObservableProperty] private double percentage;
    [ObservableProperty] private bool progressUnknown=true;
    [ObservableProperty] private string bytesDescription="";
    private CancellationTokenSource? cancellation;
    private ImportedVideo? result;
    private string? local;
    private bool opened;
    public event Action? Opened;
    public bool CanInteract=>!Busy;
    public bool CanFetch=>!Busy && RightsConfirmed && !string.IsNullOrWhiteSpace(Url);
    public bool CanOpen=>!Busy && result is not null && !opened;
    public bool HasPreview=>State!="ready";
    public bool BrowseTab=>!UrlTab;
    public bool ShowDropTarget=>BrowseTab && !HasPreview;
    public string ProgressLabel=>ProgressUnknown?"":$"{Percentage:F0}%";
    partial void OnPercentageChanged(double value)=>OnPropertyChanged(nameof(ProgressLabel));
    partial void OnProgressUnknownChanged(bool value)=>OnPropertyChanged(nameof(ProgressLabel));
    public string MetadataStage=>State is "ready"?"Waiting for a source":State is "validating" or "metadata"?"Reading source information…":"Source information retrieved";
    public string DownloadStage=>State is "downloading"?"Downloading and saving to local storage…":State is "completed"?"Validated source retained locally":local is not null?"Original media is preserved":"Waiting for video metadata";
    public string OpenStage=>opened?"AI Clipper opened":result is not null?"Validated source is ready":"Settings open after validation";
    partial void OnUrlChanged(string value)=>FetchCommand.NotifyCanExecuteChanged();
    partial void OnRightsConfirmedChanged(bool value)=>FetchCommand.NotifyCanExecuteChanged();
    partial void OnUrlTabChanged(bool value){OnPropertyChanged(nameof(BrowseTab));OnPropertyChanged(nameof(ShowDropTarget));}
    partial void OnBusyChanged(bool value)
    {
        OnPropertyChanged(nameof(CanInteract));OnPropertyChanged(nameof(CanFetch));OnPropertyChanged(nameof(CanOpen));
        FetchCommand.NotifyCanExecuteChanged();BrowseCommand.NotifyCanExecuteChanged();OpenCommand.NotifyCanExecuteChanged();
    }
    partial void OnStateChanged(string value)
    { foreach(var name in new[]{nameof(HasPreview),nameof(ShowDropTarget),nameof(MetadataStage),nameof(DownloadStage),nameof(OpenStage)})OnPropertyChanged(name); }
    [RelayCommand] private void Paste()
    {try{if(Clipboard.ContainsText())Url=Clipboard.GetText().Trim();}catch{Error="Clipboard is unavailable. Paste the URL into the field.";}}
    [RelayCommand] private void Clear()=>Url="";
    [RelayCommand] private void Cancel(){Status="Cancelling import and cleaning incomplete files…";cancellation?.Cancel();}
    [RelayCommand(CanExecute=nameof(CanInteract))] private async Task Browse()
    {
        var picker=new OpenFileDialog{Filter="Video files|*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v",CheckFileExists=true};
        if(picker.ShowDialog()==true)await ImportLocalAsync(picker.FileName);
    }
    [RelayCommand(CanExecute=nameof(CanFetch))] private Task Fetch()=>RunAsync("url",Url);
    public Task ImportLocalAsync(string path){UrlTab=false;return RunAsync("local",path);}
    internal async Task RunAsync(string kind,string source)
    {
        if(Busy)return;
        Busy=true;Error="";result=null;opened=false;local=kind=="local"?source:null;
        cancellation?.Dispose();cancellation=new();State="validating";Status="Validating source…";ProgressUnknown=true;Percentage=0;Thumbnail=null;Title=kind=="local"?System.IO.Path.GetFileName(source):"Video URL";Details=kind=="local"?"Local file":"Public video";BytesDescription="";
        try
        {
            if(!engine.IsRunning)await engine.StartAsync(cancellation.Token);
            result=await new VideoImportClient(engine).RunAsync(kind,source,Update,cancellation.Token,kind=="url" && RightsConfirmed);
            Details=result.Description;State="completed";Status="Opening clipping settings…";
        }
        catch(OperationCanceledException){ProgressUnknown=false;State="cancelled";Status="Import cancelled. Original and completed files were preserved.";}
        catch(Exception error) when(error is IOException or ArgumentException or System.Net.Http.HttpRequestException)
        {State="failed";ProgressUnknown=false;Error=error.Message;Status=error.Message;}
        finally {Busy=false;}
        if(result is not null)Open();
    }
    private void Update(JsonObject data)
    {
        State=data["state"]?.GetValue<string>() ?? "validating";
        Status=data["status"]?.GetValue<string>() ?? "Importing…";
        Title=data["title"]?.GetValue<string>() ?? "Video source";
        var platform=data["platform"]?.GetValue<string>() ?? "Video";
        double.TryParse(data["duration"]?.ToString(),out var duration);
        Details=platform+(duration>0?$" · {TimeSpan.FromSeconds(duration):hh\\:mm\\:ss}":"");
        if(data["width"] is not null && data["height"] is not null)Details+=$" · {data["width"]} × {data["height"]}";
        if(data["thumbnail"]?.GetValue<string>() is string path)
            try{Thumbnail=storage.ValidateProjectMedia(path);}catch(IOException){ }
        if(data["thumbnail_warning"] is not null && Thumbnail is null)Details+=" · Thumbnail unavailable";
        long.TryParse(data["downloaded"]?.ToString(),out long downloaded);long.TryParse(data["total"]?.ToString(),out long total);
        ProgressUnknown=total<=0;
        Percentage=total>0?Math.Clamp(downloaded*100d/total,0,100):0;
        BytesDescription=downloaded>0?$"{downloaded/1048576d:F1} MB"+(total>0?$" / {total/1048576d:F1} MB":" downloaded"):"";
    }
    [RelayCommand(CanExecute=nameof(CanOpen))] private void Open()
    {
        if(!CanOpen)return;
        try{accept(result!,local);opened=true;OnPropertyChanged(nameof(OpenStage));OpenCommand.NotifyCanExecuteChanged();Opened?.Invoke();}
        catch(Exception error) when(error is IOException or ArgumentException)
        {Error=error.Message;Status="Media retained. "+error.Message;}
    }
}
