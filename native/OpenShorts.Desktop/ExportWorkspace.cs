using System.Diagnostics;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    public string[] ExportSizes { get; }=["1080 × 1920 · Portrait","1080 × 1080 · Square","1920 × 1080 · Landscape","720 × 1280 · Portrait","1280 × 720 · Landscape","Current clip size"];
    public string[] ExportFrameRates { get; }=["Source","24","25","30","50","60"];
    public string[] ExportQualityPresets { get; }=["fast","balanced","high"];
    [ObservableProperty] private string exportName="OpenShorts-clip.mp4";
    [ObservableProperty] private string exportFolder=Environment.GetFolderPath(Environment.SpecialFolder.MyVideos);
    [ObservableProperty] private string exportSize="1080 × 1920 · Portrait";
    [ObservableProperty] private string exportFrameRate="Source";
    [ObservableProperty] private string exportEncoder="auto";
    [ObservableProperty] private string exportQuality="balanced";
    [ObservableProperty] private string lastExportPath="";
    private bool exportCopying;
    public bool CanRenderExport=>CanEdit && !SaveConflict;
    public bool CanOpenExport=>File.Exists(LastExportPath);
    partial void OnLastExportPathChanged(string value){OnPropertyChanged(nameof(CanOpenExport));OpenExportedFileCommand.NotifyCanExecuteChanged();OpenExportFolderCommand.NotifyCanExecuteChanged();}
    [RelayCommand] private void BrowseExportFolder()
    {var dialog=new OpenFolderDialog{Title="Choose export folder"};if(dialog.ShowDialog()==true)ExportFolder=dialog.FolderName;}
    [RelayCommand(CanExecute=nameof(CanRenderExport))] private Task RenderExport()=>Guard(async token=>
    {
        if(string.IsNullOrWhiteSpace(ExportName) || Path.GetFileName(ExportName)!=ExportName || ExportName.IndexOfAny(Path.GetInvalidFileNameChars())>=0)throw new ArgumentException("Enter a valid file name without a folder path.");
        if(!Directory.Exists(ExportFolder))throw new IOException("Choose an existing export folder.");
        string destination=Path.Combine(Path.GetFullPath(ExportFolder),Path.ChangeExtension(ExportName,".mp4"));
        if(File.Exists(destination) && System.Windows.MessageBox.Show("Replace the existing MP4?", "Export",System.Windows.MessageBoxButton.YesNo)!=System.Windows.MessageBoxResult.Yes)return;
        int index=Array.IndexOf(ExportSizes,ExportSize);
        int[][] sizes=[[1080,1920],[1080,1080],[1920,1080],[720,1280],[1280,720]];
        if(index<0)throw new ArgumentException("Choose a supported export size.");
        var output=new JsonObject{["encoder"]=ExportEncoder,["quality"]=ExportQuality};
        if(index<sizes.Length)output["size"]=new JsonArray(sizes[index].Select(n=>(JsonNode?)JsonValue.Create(n)).ToArray());
        if(ExportFrameRate!="Source")output["fps"]=int.Parse(ExportFrameRate,System.Globalization.CultureInfo.InvariantCulture);
        await RenderCore("final",token,output);
        if(editor?["status"]?.ToString()!="completed")throw new IOException("The final render did not complete. No file was exported.");
        exportCopying=true;CancellationAvailable=true;ProgressUnknown=true;Status="Saving validated MP4…";
        try{await engine.ExportAsync(CurrentClip.VideoUrl,destination,token);LastExportPath=destination;Status="Export complete · "+Path.GetFileName(destination);}
        finally{exportCopying=false;}
        await LoadProjects(token);
    });
    [RelayCommand(CanExecute=nameof(CanOpenExport))] private void OpenExportedFile()=>Process.Start(new ProcessStartInfo(LastExportPath){UseShellExecute=true});
    [RelayCommand(CanExecute=nameof(CanOpenExport))] private void OpenExportFolder()=>Process.Start(new ProcessStartInfo("explorer.exe"){UseShellExecute=true,Arguments="/select,\""+LastExportPath+"\""});
}
