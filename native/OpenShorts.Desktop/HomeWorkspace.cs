using System.IO;
using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using OpenShorts.EngineBridge;

namespace OpenShorts.Desktop;

public sealed record HomeProject(string JobId,string Title,int Clips,DateTime Modified,long Size,string? Thumbnail)
{
    public string Detail=>$"{Clips} clips  ·  {HomeDisplay.Bytes(Size)}";
    public string Updated=>$"Modified {Modified:MMM d, h:mm tt}";
    public string DisplayTitle=>Title.Contains(JobId,StringComparison.OrdinalIgnoreCase)?"Video project":Title;
}
public sealed record HomeExport(string JobId,int Index,string Title,double Duration,string Format,string Resolution,long Size,DateTime Modified)
{
    public string Length=>Duration>0 && double.IsFinite(Duration)?TimeSpan.FromSeconds(Math.Clamp(Duration,0,864000)).ToString(Duration>=3600?@"hh\:mm\:ss":@"mm\:ss"):"—";
    public string DisplayTitle=>Title.Contains(JobId,StringComparison.OrdinalIgnoreCase) || Title.StartsWith("subtitled_",StringComparison.OrdinalIgnoreCase)?$"Clip {Index+1:00} · rendered video":Title;
    public string FileSize=>HomeDisplay.Bytes(Size);
    public string Exported=>Modified.ToString("g");
}
public sealed record HomeSearchResult(string Title,string Detail,string Route,string? JobId=null,string? TemplateId=null);
internal static class HomeDisplay
{
    public static string Bytes(long bytes)=>bytes>=1024L*1024*1024?$"{bytes/(1024d*1024*1024):F1} GB":$"{bytes/(1024d*1024):F1} MB";
}
public partial class MainViewModel
{
    private readonly List<HomeProject> homeLibrary=[];
    public ObservableCollection<HomeProject> RecentProjects { get; }=[];
    public ObservableCollection<HomeExport> RecentExports { get; }=[];
    public ObservableCollection<HomeSearchResult> HomeSearchResults { get; }=[];
    [ObservableProperty] private string homeSearch="";
    [ObservableProperty] private string homeGpuFeatures="Detecting capabilities…";
    [ObservableProperty] private string homeGpuStatus="Detecting hardware…";
    [ObservableProperty] private string homeGpuDetail="Checking the local rendering engine";
    [ObservableProperty] private string homeRenderStatus="Checking encoders…";
    [ObservableProperty] private string homeStorage="Checking library storage…";
    [ObservableProperty] private string? homeHero;
    [ObservableProperty] private string homeLibrarySummary="Your local projects will appear here";
    [ObservableProperty] private bool homeHasProjects;
    [ObservableProperty] private bool homeHasExports;
    [ObservableProperty] private bool homeGpuEnabled;
    [ObservableProperty] private string homeStoragePath="Checking…";
    [ObservableProperty] private string homeStorageUsed="—";
    [ObservableProperty] private string homeStorageFree="—";
    [ObservableProperty] private string homeStorageTotal="—";
    [ObservableProperty] private double homeStorageBar=0;
    [ObservableProperty] private string homeBenchmarkResult="";
    [ObservableProperty] private bool homeBenchmarkAvailable;
    [ObservableProperty] private string homeExportPreset="YouTube Shorts · 1080 × 1920";
    public string[] HomeProcessingModes=>Presets.Select(p=>char.ToUpperInvariant(p[0])+p[1..]).ToArray();
    public string HomeProcessingMode { get=>char.ToUpperInvariant(Preset[0])+Preset[1..];set=>Preset=value.ToLowerInvariant(); }
    partial void OnPresetChanged(string value)=>OnPropertyChanged(nameof(HomeProcessingMode));
    public string[] HomeExportPresets { get; }=["YouTube Shorts · 1080 × 1920","TikTok · 1080 × 1920","Instagram Reels · 1080 × 1920","Custom · choose in AI Clipper"];
    public bool HomeSearchVisible=>HomeSearch.Trim().Length>0;
    public bool HomeSearchEmpty=>HomeSearchVisible && HomeSearchResults.Count==0;
    partial void OnHomeSearchChanged(string value)=>FilterHome();
    partial void OnHomeExportPresetChanged(string value)
    {
        if(!value.StartsWith("Custom",StringComparison.Ordinal))OutputFormat="vertical";
        Status=value.StartsWith("Custom",StringComparison.Ordinal)?"Choose output format and quality in AI Clipper.":$"{value} selected for new clips. Existing clips keep their saved framing.";
    }
    private async Task LoadHome(CancellationToken token)
    {
        var data=await engine.GetAsync("/api/desktop/home",token);
        homeLibrary.Clear();
        foreach(var row in data["projects"]?.AsArray() ?? [])
        {
            string? image=null;
            if(row?["thumbnail"]?.GetValue<string>() is string path)
                try { image=storage.ValidateProjectMedia(path); } catch(IOException) { }
            homeLibrary.Add(new(EngineClient.JobId(row!["job_id"]!.GetValue<string>()),row["title"]!.GetValue<string>(),row["clips"]!.GetValue<int>(),
                DateTimeOffset.FromUnixTimeSeconds((long)row["modified"]!.GetValue<double>()).LocalDateTime,row["size"]!.GetValue<long>(),image));
        }
        RecentExports.Clear();
        foreach(var row in data["exports"]?.AsArray() ?? [])
            RecentExports.Add(new(EngineClient.JobId(row!["job_id"]!.GetValue<string>()),row["clip_index"]!.GetValue<int>(),row["title"]!.GetValue<string>(),
                row["duration"]!.GetValue<double>(),row["format"]!.GetValue<string>(),row["resolution"]!.GetValue<string>(),row["size"]!.GetValue<long>(),DateTimeOffset.FromUnixTimeSeconds((long)row["modified"]!.GetValue<double>()).LocalDateTime));
        HomeHasProjects=homeLibrary.Count>0;HomeHasExports=RecentExports.Count>0;
        HomeHero=homeLibrary.FirstOrDefault(p=>p.Thumbnail is not null)?.Thumbnail;
        HomeLibrarySummary=$"{data["project_count"]} projects  ·  {data["export_count"]} rendered clips";
        HomeStorage=data["free_bytes"] is JsonValue free?$"{HomeDisplay.Bytes(free.GetValue<long>())} free in library drive":"Storage unavailable";
        try {
            var drv=new DriveInfo(Path.GetPathRoot(storage.Library)!);
            long tot=drv.TotalSize,avail=drv.AvailableFreeSpace,used=tot-avail;
            HomeStorageFree=HomeDisplay.Bytes(avail)+" free";
            HomeStorageUsed=HomeDisplay.Bytes(used)+" used";
            HomeStorageTotal=HomeDisplay.Bytes(tot);
            HomeStorageBar=tot>0?Math.Clamp((double)used/tot,0,1):0;
        } catch { HomeStorageFree=HomeStorage;HomeStorageUsed="—";HomeStorageTotal="—"; }
        HomeStoragePath=storage.Library;
        FilterHome();
    }
    private void FilterHome()
    {
        string query=HomeSearch.Trim();
        bool Matches(string text)=>text.Contains(query,StringComparison.OrdinalIgnoreCase);
        RecentProjects.Clear();foreach(var project in homeLibrary.Where(p=>Matches(p.Title)||Matches(p.JobId)).Take(3))RecentProjects.Add(project);
        HomeSearchResults.Clear();
        if(query.Length>0)
        {
            foreach(var project in homeLibrary.Where(p=>Matches(p.Title)||Matches(p.JobId)).Take(6))
                HomeSearchResults.Add(new(project.Title,project.Detail,"Projects",project.JobId));
            foreach(var template in Templates.Where(t=>Matches(t.Name)).Take(4))
                HomeSearchResults.Add(new(template.Name,"Template · open in template library","Templates",TemplateId:template.Id));
            foreach(var routeName in Navigation.Where(Matches).Take(4))HomeSearchResults.Add(new(routeName,"Workspace",""+routeName));
        }
        OnPropertyChanged(nameof(HomeSearchVisible));OnPropertyChanged(nameof(HomeSearchEmpty));
    }
    private void UpdateHomeHardware(JsonObject data)
    {
        bool nvenc=data["nvenc_initialized"]?.GetValue<bool>()==true;
        bool libx264=data["libx264_initialized"]?.GetValue<bool>()==true;
        string? cudaDevice=data["ai_cuda"]?["devices"]?.AsArray().FirstOrDefault()?.GetValue<string>();
        HomeGpuDetail=cudaDevice is {Length:>0}
            ? cudaDevice
            : nvenc
                ? "NVIDIA GPU detected — NVENC encoder active"
                : "No GPU encoder detected — CPU fallback in use";
        HomeGpuFeatures=(nvenc?"NVENC":"CPU encode")+(cudaDevice is {Length:>0}?" · CUDA · GPU Inference":"");
        HomeGpuEnabled=nvenc;
        HomeGpuStatus=nvenc?"NVENC · GPU encode":"CPU encode";
        HomeRenderStatus=nvenc
            ? "NVENC encode ready"+(libx264?"; CPU fallback available":"")+(cudaDevice is {Length:>0}?"; CUDA AI inference active":"")+"."
            : libx264
                ? "CPU encoder (x264) ready. Import a video to begin."
                : "No encoder available — check Settings and reinstall FFmpeg.";
    }
    [RelayCommand] private void NavigateHome(string? page)
    {
        if(page=="Video Editor" && ClipperReview && ReviewSelected?.Record.Ready==true)
        {if(!Busy)_=OpenClipCommand.ExecuteAsync(null);return;}
        if(page is not null && Navigation.Contains(page)){HomeSearch="";Route=page;}
    }
    [RelayCommand(CanExecute=nameof(CanImport))] private async Task OpenHomeProject(HomeProject? project)
    {
        if(project is null || !await FlushDraftAsync())return;
        SelectedProject=Projects.FirstOrDefault(p=>p.JobId==project.JobId);
        if(SelectedProject is not null)await OpenProjectCommand.ExecuteAsync(null);
    }
    [RelayCommand(CanExecute=nameof(CanImport))] private async Task OpenHomeExport(HomeExport? item)
    {
        if(item is null || !await FlushDraftAsync())return;
        SelectedProject=Projects.FirstOrDefault(p=>p.JobId==item.JobId);
        if(SelectedProject is null)return;
        await OpenProjectCommand.ExecuteAsync(null);
        SelectedClip=Clips.FirstOrDefault(c=>c.Index==item.Index);
        if(SelectedClip is not null)await OpenClipCommand.ExecuteAsync(null);
    }
    [RelayCommand(CanExecute=nameof(CanImport))] private async Task OpenHomeSearch(HomeSearchResult? item)
    {
        if(item is null)return;
        HomeSearch="";
        if(item.JobId is not null)await OpenHomeProject(homeLibrary.FirstOrDefault(p=>p.JobId==item.JobId));
        else { if(item.TemplateId is not null)SelectedTemplate=Templates.FirstOrDefault(t=>t.Id==item.TemplateId);Route=item.Route; }
    }
    [RelayCommand] private void OpenLibraryFolder()
    { try{System.Diagnostics.Process.Start("explorer.exe",storage.Library);}catch{Status="Cannot open library folder.";} }
    [RelayCommand] private void RunBenchmark()
    { HomeBenchmarkResult="";Status="Hardware benchmark is not available in this build. Use Detect Hardware to probe capabilities."; }
    [RelayCommand] private void SelectHomePreset(string? preset)
    { if(int.TryParse(preset,out int i) && i>=0 && i<HomeExportPresets.Length){HomeExportPreset=HomeExportPresets[i];if(i==3)Route="AI Clipper";} }
}
