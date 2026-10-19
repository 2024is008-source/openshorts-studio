using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    [ObservableProperty] private string templateName="My studio style";
    [ObservableProperty] private string templatePrimary="#00D9EC";
    [ObservableProperty] private string templateSecondary="#FFE500";
    [ObservableProperty] private string templateText="#FFFFFF";
    [ObservableProperty] private string templateFont="Arial";
    [ObservableProperty] private double templateFontSize=58;
    [ObservableProperty] private string templateLogo="OpenShorts";
    [ObservableProperty] private bool templateLogoEnabled;
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task SaveCustomTemplate()=>Guard(async token=>
    {
        if(SelectedTemplate is null)throw new ArgumentException("Select a starter template first.");
        var template=(JsonObject)SelectedTemplate.Definition.DeepClone();template["name"]=TemplateName;
        template["colors"]!["primary"]=TemplatePrimary;template["colors"]!["secondary"]=TemplateSecondary;template["colors"]!["text"]=TemplateText;
        template["fonts"]!["family"]=TemplateFont;template["fonts"]!["caption_size"]=TemplateFontSize;
        template["logo"]!["enabled"]=TemplateLogoEnabled;template["logo"]!["text"]=TemplateLogo;
        var data=await engine.SendAsync(EditorRoute+"/templates",new JsonObject{["template"]=template},cancellationToken:token);
        var saved=data["template"]!.AsObject();var item=new TemplateItem(saved["id"]!.GetValue<string>(),saved["name"]!.GetValue<string>(),(JsonObject)saved.DeepClone());
        Templates.Add(item);SelectedTemplate=item;Status="Custom style saved to this project. Save draft and render to apply.";
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task LoadProjectTemplates()=>Guard(async token=>
    {
        var data=await engine.GetAsync(EditorRoute+"/templates",token);var selected=SelectedTemplate?.Id;
        Templates.Clear();foreach(var row in data["templates"]!.AsArray())
        {var t=row!.AsObject();Templates.Add(new(t["id"]!.GetValue<string>(),t["name"]!.GetValue<string>(),(JsonObject)t.DeepClone()));}
        SelectedTemplate=Templates.FirstOrDefault(t=>t.Id==selected);Status="Project templates loaded.";
    });
    [RelayCommand(CanExecute=nameof(CanUseClipTools))] private Task ApplyTemplateToProject()=>Guard(async token=>
    {
        if(SelectedTemplate is null)throw new ArgumentException("Choose a template first.");
        var template=SelectedTemplate.Definition.DeepClone();await Save(token);var revisions=new JsonObject();
        var clips=Clips.Where(c=>c.JobId==CurrentClip.JobId).ToArray();
        if(clips.Length is <1 or >12)throw new IOException("Batch styling supports one to twelve clips in the current project.");
        foreach(var clip in clips)
        {
            var data=await engine.GetAsync($"/api/clip/{clip.JobId}/{clip.Index}/editor",token);
            if(data["stale"]?.GetValue<bool>()==true)throw new IOException("A clip draft is stale. Resolve it before applying a batch style.");
            revisions[clip.Index.ToString()]=data["project"]!["revision"]!.DeepClone();
        }
        await engine.SendAsync(EditorRoute+"/template-batch",new JsonObject{["template"]=template,["clips"]=revisions},cancellationToken:token);
        ApplyEditor(await engine.GetAsync(EditorRoute,token));Status="Template applied to saved clip drafts. Render each final to produce its styled video.";
    });
}
