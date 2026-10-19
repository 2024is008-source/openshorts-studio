using System.Collections.ObjectModel;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using OpenShorts.Core;
namespace OpenShorts.Desktop;
public sealed record ClipperChoice(string Id,string Label)
{public override string ToString()=>Label;}
public sealed record GenerationSettingRow(string Icon,string Label,string Value,string Detail);
public partial class ReviewRow
{
 public string[] TagItems=>Record.Tags.Split(" · ",StringSplitOptions.RemoveEmptyEntries);
 public string Readiness=>Record.Ready?"Rendered MP4":Record.Status=="not_rendered"?"Not rendered":"Media unavailable";
}
public partial class MainViewModel
{
 public ObservableCollection<GenerationSettingRow> GenerationSettingRows {get;}=[];
 public string ReviewReadyLabel=>$"{ReviewRows.Count(r=>r.Record.Ready)} clips ready";
 public string ReviewTotalTime=>TimeSpan.FromSeconds(ReviewRows.Where(r=>r.Record.Ready).Sum(r=>r.Record.Duration)).ToString(@"mm\:ss");
 public string ReviewSavedExports=>$"{reviewHistory.Count(h=>h?["status"]?.ToString()=="completed")} saved";
 public string ReviewSelectionPosition=>ReviewSelected is null?"—":$"{ReviewRows.IndexOf(ReviewSelected)+1} / {ReviewRows.Count}";
 public bool GenerationIdle=>GenerationState=="idle";
 public bool GenerationHasSource=>readySource is not null || GenerationState!="idle";
 public string SelectVideoStep=>GenerationHasSource?"✓":"1";
 public string SettingsStep=>GenerationHasSource?"✓":"2";
 public string GenerationDescription=>GenerationIdle?GenerationHasSource?"Your source is ready. Confirm permission and start AI clipping when you are ready.":"Preview your clipping workspace. Import a video to get started; no AI processing is running.":"Our AI is analyzing your video, finding the best moments, and creating short clips.";
 public string GenerationStepCaption=>GenerationIdle?"Preview · no processing running":"Step 3 of 4 · Generating clips";
 public string GenerationSourceStatus=>GenerationHasSource?"Source ready":"Awaiting video";
 public string GenerationSourceHint=>GenerationHasSource?"Ready for AI analysis":"Import a local video or a video URL";
 private void PrepareClipperPreview()
 {
  ClipperMode="progress";GenerationState="idle";GenerationFailure="";GenerationWarning="";GenerationElapsed="—";GenerationStage=GenerationHasSource?"Ready to start AI clipping":"Import a video to begin";
  GenerationStages.Clear();foreach(var title in new[]{"Preparing source","Transcribing audio","Analyzing content with Gemini","Selecting clip candidates","Rendering selected clips","Validating generated outputs"})GenerationStages.Add(new(title,"not_reported"));
  SetGenerationSettingRows(CaptureGenerationSettings());NotifyReferenceReview();OnPropertyChanged(nameof(GenerationStepsPercent));
  foreach(var name in new[]{nameof(GenerationHasSource),nameof(GenerationSourceStatus),nameof(GenerationSourceHint),nameof(GenerationTitle),nameof(GenerationDescription),nameof(SelectVideoStep),nameof(SettingsStep)})OnPropertyChanged(name);
 }
 public string GenerationStepIcon=>GenerationState=="idle"?"circle":GenerationState=="completed"?"check":GenerationState is "failed" or "cancelled"?"triangle-alert":"audio-lines";
 public double GenerationStepsPercent=>GenerationStages.Count==0?0:100d*GenerationStages.Count(s=>s.State=="completed")/GenerationStages.Count;
 public double GenerationSurfaceHeight=>750+Math.Max(0,GenerationStages.Count-6)*34;
 public string GenerationRingText=>GenerationState=="completed"?"100%":$"{GenerationStepsPercent:0}%";
 public string GenerationRingDetail=>GenerationActive?"STEPS COMPLETE":GenerationState.ToUpperInvariant();
 public string ReviewPlaybackClock=>$@"{TimeSpan.FromSeconds(Math.Max(0,SeekSeconds)):mm\:ss} / {TimeSpan.FromSeconds(Math.Max(0,DurationSeconds)):mm\:ss}";
 public string[] ReviewCaptionStyles=>new[]{"Disabled"}.Concat(CaptionPresets).ToArray();
 public ClipperChoice[] ReviewCaptionChoices=>ReviewCaptionStyles.Select(id=>new ClipperChoice(id,System.Globalization.CultureInfo.InvariantCulture.TextInfo.ToTitleCase(id.Replace('-',' ')))).ToArray();
 public ClipperChoice[] ReviewFramingChoices=>[new("preserve","Keep generated framing"),new("crop","Crop to output"),new("contain","Full video + blurred background")];
 public ClipperChoice[] ReviewEncoderChoices=>[new("auto","Automatic"),new("x264","CPU · H.264"),new("nvenc","NVIDIA NVENC · H.264")];
 public ClipperChoice[] ReviewQualityChoices=>[new("fast","Fast"),new("balanced","Balanced"),new("high","High quality")];
 public string[] ReviewFramingStyles=>["preserve","crop","contain"];
 public string[] ReviewAudioStyles=>["Saved audio","Normalize loudness","Original levels"];
 public string[] ReviewSpeeds=>["0.5×","1×","1.5×","2×"];
 [ObservableProperty] private string reviewCaptionStyle="clean-minimal";
 [ObservableProperty] private string reviewFramingStyle="preserve";
 [ObservableProperty] private string reviewAudioStyle="Saved audio";
 [ObservableProperty] private string reviewSpeed="1×";
 [ObservableProperty] private bool reviewCompletionVisible=true;
 [ObservableProperty] private bool generationDetailsVisible;
 [ObservableProperty] private string systemMemory="Checking memory…";
 [ObservableProperty] private double systemMemoryPercent;
 private DateTime memoryChecked;
 private JsonObject? reviewOptionProject;
 private ReviewRow? reviewOptionRow;
 partial void OnReviewSpeedChanged(string value)=>Preview.Player.SetRate(value switch {"0.5×"=>.5f,"1.5×"=>1.5f,"2×"=>2f,_=>1f});
 private void SetGenerationSettingRows(GenerationSettings s)
 {
  GenerationSettingRows.Clear();
  foreach(var row in new[]{new GenerationSettingRow("clock","Target duration",s.AutoDuration?"Automatic":$"{s.TargetSeconds:0} seconds","Target length for each short clip"),
   new("monitor","Aspect ratio",s.OutputFormat switch {"vertical"=>"9:16 (Vertical)","square"=>"1:1 (Square)",_=>"16:9 (Landscape)"},"Output framing for your selected platform"),
   new("sparkles","Clip mode",s.Mode=="highlights"?"Highlights":"AI clips","Find moments using the selected analysis"),
   new("brain","AI analysis",s.Analysis.StartsWith("adaptive-")?$"Adaptive · {s.Analysis[9..]}":s.Analysis=="hybrid"?"Hybrid analysis":"Transcript analysis",$"Story pacing: {s.Pacing}"),
   new("captions","Captions",s.Captions?s.CaptionPreset:s.SourceHasCaptions?"In source":"Disabled","Use the source language and saved style"),
   new("crop","Framing",s.Framing,"Retained source and framing decisions"),
   new("chart-no-axes-column-increasing","Requested output",s.AutoCount?"Automatic":$"{s.TargetClips} clips",$"Quality: {s.Quality} · Audio: {s.AudioPreset}")})GenerationSettingRows.Add(row);
 }
 private void NotifyReferenceReview()
 {
  foreach(string p in new[]{nameof(ReviewReadyLabel),nameof(ReviewTotalTime),nameof(ReviewSavedExports),nameof(ReviewSelectionPosition),nameof(GenerationRingText),nameof(GenerationRingDetail),nameof(GenerationStepIcon)})OnPropertyChanged(p);
 }
 private async Task LoadReviewOptionsAsync(ReviewRow row)
 {
  reviewOptionProject=null;reviewOptionRow=null;
  if(!row.Record.Ready || reviewJob is null)return;
  string identity=reviewJob;
  try
  {
   var data=await ReadClipperAsync($"/api/clip/{identity}/{row.Record.Index}/editor");
   if(ReviewSelected!=row || reviewJob!=identity)return;
   reviewOptionProject=data["project"]!.AsObject();reviewOptionRow=row;
   var edits=reviewOptionProject["edits"]!;
   ReviewCaptionStyle=edits["style"]?["enabled"]?.GetValue<bool>()==false?"Disabled":edits["style"]?["preset"]?.ToString() ?? "clean-minimal";
   ReviewFramingStyle=edits["crop"]?["mode"]?.ToString() ?? "preserve";ReviewAudioStyle="Saved audio";
  }
  catch{if(ReviewSelected==row)ReviewNotice="Saved style settings are unavailable. Reopen this clip in the editor to inspect it.";}
 }
 [RelayCommand(CanExecute=nameof(CanReviewExport))] private Task ApplyReviewStyles()=>Guard(async token=>
 {
  if(ReviewSelected is not {Record.Ready:true} row || row!=reviewOptionRow || reviewOptionProject is null)throw new IOException("Wait for the selected timeline settings to load, then try again.");
  if(!await FlushDraftAsync(token))return;
  var edits=(JsonObject)reviewOptionProject["edits"]!.DeepClone();edits["style"]!["enabled"]=ReviewCaptionStyle!="Disabled";
  if(ReviewCaptionStyle!="Disabled")edits["style"]!["preset"]=ReviewCaptionStyle;
  edits["crop"]!["mode"]=ReviewFramingStyle;
  if(ReviewAudioStyle!="Saved audio")
  {
   var audio=edits["audio"]?.AsObject() ?? new JsonObject{["volume"]=1,["mute"]=false,["fade"]=0,["normalize"]=false,["target"]=-16,["ceiling"]=-2,["music"]=null};
   audio["normalize"]=ReviewAudioStyle=="Normalize loudness";edits["audio"]=audio.DeepClone();
  }
  string route=$"/api/clip/{reviewJob}/{row.Record.Index}/editor";
  var saved=await engine.SendAsync(route,new JsonObject{["revision"]=reviewOptionProject["revision"]!.DeepClone(),["edits"]=edits},put:true,cancellationToken:token);
  if(editingClip is not null && editingClip.JobId==reviewJob && editingClip.Index==row.Record.Index)ApplyEditor(await engine.GetAsync(route,token));
  ReviewIncludeCaptions=ReviewCaptionStyle!="Disabled";
  ReviewNotice="Rendering updated framing, captions and audio…";Preview.Player.SetPause(true);
  try
  {
   await engine.SendAsync(route+"/run",new JsonObject{["revision"]=saved["project"]!["revision"]!.DeepClone(),["mode"]="preview"},cancellationToken:token);
   reviewExportRoute=route;CancellationAvailable=true;
   while(true)
   {
    var project=(await engine.GetAsync(route,token))["project"]!.AsObject();var state=project["status"]!.ToString();
    Progress=GenerationProgress.Number(project["progress"]) ?? 0;ProgressUnknown=false;Status=project["stage"]?.ToString() ?? "Rendering updated preview";
    if(state is "completed" or "preview_ready")
    {
     if(ReviewSelected==row){Preview.Open(ReviewResultPath(project));sourcePreview=false;ReviewPreviewKind="Updated rendered preview · saved framing, captions and audio";}
     break;
    }
    if(state=="cancelled")throw new OperationCanceledException(token);
    if(state is "failed" or "interrupted" or "draft")throw new IOException(project["error"]?.ToString() ?? "Updated preview could not be rendered.");
    await Task.Delay(500,token);
   }
  }
  finally{reviewExportRoute=null;CancellationAvailable=false;}
  ReviewNotice="Updated preview ready. Export uses these same saved settings.";
  await LoadReviewOptionsAsync(row);
 });
 private string ReviewResultPath(JsonObject project)
 {
  string url=project["result"]?["new_video_url"]?.ToString() ?? throw new IOException("The renderer returned no preview.");
  string prefix=$"/videos/{reviewJob}/";
  if(!url.StartsWith(prefix,StringComparison.Ordinal))throw new IOException("The renderer returned an invalid preview location.");
  string name=Uri.UnescapeDataString(url[prefix.Length..]);
  if(Path.GetFileName(name)!=name || name.Contains('\\') || name.Contains('/') || name is "." or "..")throw new IOException("Invalid preview filename.");
  return storage.ValidateProjectMedia(Path.Combine(storage.Library,"output",reviewJob!,name));
 }
 [RelayCommand] private Task DuplicateReview(ReviewRow? row)=>Guard(async token=>
 {
  if(row is null || !row.Record.Ready)return;
  if(!await FlushDraftAsync(token))return;
  string route=$"/api/clip/{reviewJob}/{row.Record.Index}/editor";
  var project=(await engine.GetAsync(route,token))["project"]!;
  var copy=await engine.SendAsync(route+"/duplicate",new JsonObject{["revision"]=project["revision"]!.DeepClone()},cancellationToken:token);
  int index=copy["clip_index"]!.GetValue<int>();await LoadReviewAsync(reviewJob!,await engine.GetAsync($"/api/desktop/jobs/{reviewJob}/review",token),token);
  ReviewSelected=ReviewRows.First(r=>r.Record.Index==index);await SaveReviewPreferencesAsync();ReviewNotice="Independent timeline created. Source video is shared; large media files were not copied.";
 });
 [RelayCommand] private void PreviousReview(){if(ReviewRows.Count>0)ReviewSelected=ReviewRows[Math.Max(0,ReviewRows.IndexOf(ReviewSelected!)-1)];}
 [RelayCommand] private void NextReview(){if(ReviewRows.Count>0)ReviewSelected=ReviewRows[Math.Min(ReviewRows.Count-1,ReviewRows.IndexOf(ReviewSelected!)+1)];}
 [RelayCommand] private void SortReview(string? sort){if(sort is not null && ReviewSorts.Contains(sort))ReviewSort=sort;}
 [RelayCommand] private void DismissReviewCompletion()=>ReviewCompletionVisible=false;
 [RelayCommand] private void ToggleGenerationDetails()
 {
  var body=new System.Windows.Controls.TextBox{Text=string.Join(Environment.NewLine,GenerationDiagnostics),IsReadOnly=true,TextWrapping=System.Windows.TextWrapping.Wrap,VerticalScrollBarVisibility=System.Windows.Controls.ScrollBarVisibility.Auto,Background=System.Windows.Media.Brushes.Transparent,Foreground=System.Windows.Media.Brushes.LightSteelBlue};
  new System.Windows.Window{Title="Generation details",Owner=System.Windows.Application.Current.MainWindow,Width=640,Height=420,WindowStartupLocation=System.Windows.WindowStartupLocation.CenterOwner,Background=(System.Windows.Media.Brush)System.Windows.Application.Current.FindResource("Panel"),Content=body}.ShowDialog();
 }
 private void RefreshReferenceMemory()
 {
  OnPropertyChanged(nameof(ReviewPlaybackClock));
  if(DateTime.UtcNow-memoryChecked<TimeSpan.FromSeconds(3))return;memoryChecked=DateTime.UtcNow;
  var memory=new MemoryStatus{Length=(uint)Marshal.SizeOf<MemoryStatus>()};
  if(GlobalMemoryStatusEx(ref memory)){SystemMemoryPercent=memory.Load;SystemMemory=$"{(memory.TotalPhysical-memory.AvailablePhysical)/1073741824d:F1} GB / {memory.TotalPhysical/1073741824d:F1} GB";}
 }
 [StructLayout(LayoutKind.Sequential)] private struct MemoryStatus {public uint Length,Load;public ulong TotalPhysical,AvailablePhysical,TotalPage,AvailablePage,TotalVirtual,AvailableVirtual,AvailableExtended;}
 [DllImport("kernel32.dll")] [return:MarshalAs(UnmanagedType.Bool)] private static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);
}
