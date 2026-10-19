using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using OpenShorts.Core;
using OpenShorts.EngineBridge;

namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    [ObservableProperty] private string importedMediaDescription="";
    public string? ImportedMediaId { get; private set; }
    private ImportedVideo? readySource;
    private string? readyOriginal;
    private string generationTemplateId="auto";
    private string GenerationTemplateId=>SelectedTemplate?.Id ?? generationTemplateId;
    private bool CanReviewClippingSettings=>readySource is not null && !Busy;
    [RelayCommand(CanExecute=nameof(CanReviewClippingSettings))] private void ReviewClippingSettings(){if(readySource is not null)ShowVideoReady(readySource,readyOriginal,true);}
    public void OpenImportDialog(string? initialFile=null)
    {
        if(Busy)return;
        ImportedVideo? pending=null;string? original=null;
        var workflow=new ImportVideoViewModel(engine,storage,(media,path)=>{pending=media;original=path;});
        var dialog=new ImportVideoWindow(workflow){Owner=Application.Current.MainWindow};
        if(initialFile is not null)dialog.Loaded+=async (_,_)=>await workflow.ImportLocalAsync(initialFile);
        dialog.ShowDialog();
        if(pending is not null)ShowVideoReady(pending,original);
    }
    private void ShowVideoReady(ImportedVideo media,string? original,bool keepCurrent=false)
    {
        if(Busy)return;
        bool wasPlaying=Preview.Player.IsPlaying;if(wasPlaying)Preview.Player.Pause();
        var draft=new GenerationDraft{SourceId=media.Id,Settings=CaptureGenerationSettings(),Encoder=storage.LoadSettings().Encoder,OutputLocation=Path.Combine(storage.Library,"output"),TemplateId=GenerationTemplateId};
        var model=new VideoReadyViewModel(engine,storage,media,draft,CredentialStatus,CaptionPresets,Templates.ToArray(),saved=>
        {
            if(saved.TemplateId is not ("auto" or "none" or "") && !Templates.Any(t=>t.Id==saved.TemplateId))throw new IOException("The saved template is unavailable. Choose another template or clear it.");
            AcceptImportedSource(media,original);ApplyGenerationSettings(saved.Settings);
            generationTemplateId=saved.TemplateId;SelectedTemplate=Templates.FirstOrDefault(t=>t.Id==saved.TemplateId);SetGenerationSettingRows(saved.Settings);
            return Task.CompletedTask;
        },keepCurrent);
        var window=new VideoReadyWindow(model){Owner=Application.Current.MainWindow};
        var accepted=window.ShowDialog();
        if(accepted!=true && wasPlaying)Preview.Player.Play();
        if(window.ChangeVideoRequested)OpenImportDialog();
    }
    internal void AcceptImportedSource(ImportedVideo media,string? original)
    {
        string path;
        if(original is not null && string.Equals(Path.GetFullPath(original),Path.GetFullPath(media.Path),StringComparison.OrdinalIgnoreCase))path=Path.GetFullPath(original);
        else path=storage.ValidateProjectMedia(media.Path);
        if(!File.Exists(path))throw new IOException("The imported file was removed. Select it again.");
        ClipperMode="progress";GenerationState="idle";readySource=media;readyOriginal=original;ReviewClippingSettingsCommand.NotifyCanExecuteChanged();
        Preview.Open(path);
        ImportedFile=path;ImportedMediaId=media.Id;ImportedMediaDescription=media.Description;
        SourceUrl="";Acknowledged=false;
        GenerationSourceTitle=media.Title.Length>0?media.Title:Path.GetFileName(path);GenerationSourceDetails=$"{media.Description} · {media.Format}";GenerationThumbnail=media.Thumbnail;
        PrepareClipperPreview();Route="AI Clipper";
        Status="Video imported. Review the settings and confirm permission before starting AI analysis.";
    }
}
