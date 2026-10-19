using System.Text.Json.Nodes;
using OpenShorts.Core;
using OpenShorts.EngineBridge;
using Xunit;
namespace OpenShorts.Tests;
public class GenerationReviewTests
{
 [Fact] public void FailedAnalysisStageIsExplicit()
 {var stage=new GenerationStage("Analyzing content with Gemini","failed",87.5);Assert.Equal("Failed",stage.Label);Assert.Equal("#FB526E",stage.Color);Assert.Equal("88%",stage.PercentLabel);}
 [Theory][InlineData("preparing")][InlineData("running")][InlineData("cancel_requested")][InlineData("failed")][InlineData("cancelled")]
 public void NonterminalPercentIsNeverManufactured(string state)
 {var p=GenerationProgress.Parse(new(){["state"]=state,["overall"]=68});Assert.Null(p.Overall);}
 [Fact] public void CompletedUsesBackendState()
 {var p=GenerationProgress.Parse(new(){["state"]="completed",["overall"]=100});Assert.True(p.Terminal);Assert.Equal(100,p.Overall);Assert.Throws<IOException>(()=>GenerationProgress.Parse(new(){["state"]="made-up"}));}
 [Fact] public void MeasuredStagePercentageIsValidatedIndependentlyOfOverall()
 {var p=GenerationProgress.Parse(new(){["state"]="running",["stages"]=new JsonArray(new JsonObject{["title"]="Transcribing audio",["state"]="active",["percent"]=50},new JsonObject{["title"]="AI analysis",["state"]="active",["percent"]=101})});Assert.Null(p.Overall);Assert.Equal("50%",p.Stages[0].PercentLabel);Assert.Null(p.Stages[1].Percent);Assert.Equal("Working…",p.Stages[1].PercentLabel);}
 [Fact] public void OptionalScoreAndMissingOutputAreHonest()
 {var row=ReviewRecord.Parse(new(){["index"]=7,["title"]="Saved title",["status"]="unavailable",["score"]=150,["start"]=1,["end"]=3,["duration"]=2});Assert.False(row.Ready);Assert.Equal("Unscored",row.ScoreLabel);Assert.Equal("00:02",row.DurationLabel);}
 [Fact] public void ExportVersionsInsteadOfOverwriting()
 {var folder=Path.Combine(Path.GetTempPath(),Guid.NewGuid().ToString());Directory.CreateDirectory(folder);try{File.WriteAllText(Path.Combine(folder,"video.mp4"),"kept");Assert.EndsWith("video (2).mp4",ReviewExportClient.VersionedPath(folder,"video.mp4"));Assert.Throws<ArgumentException>(()=>ReviewExportClient.VersionedPath(folder,"../file.mp4"));}finally{Directory.Delete(folder,true);}}
 [Fact] public async Task ExistingTimelineRevisionCaptionsAndValidatedUrlAreReused()
 {var bridge=new ReviewBridge();var folder=Path.Combine(Path.GetTempPath(),Guid.NewGuid().ToString());Directory.CreateDirectory(folder);try{var client=new ReviewExportClient(bridge);string target=Path.Combine(folder,"export.mp4");var url=await client.ExportAsync("job",7,new(){["encoder"]="x264"},false,target,(_,_)=>{},_=>{},default);Assert.Equal("/videos/job/final.mp4",url);Assert.Equal("validated",File.ReadAllText(target));Assert.Equal(new[]{"PUT:revision=4:captions=False","RUN:revision=5","COPY:/videos/job/final.mp4"},bridge.Calls);}finally{Directory.Delete(folder,true);}}
 [Fact] public async Task ConflictStopsBeforePaidOrRenderRequests()
 {var bridge=new ReviewBridge{Conflict=true};await Assert.ThrowsAsync<IOException>(()=>new ReviewExportClient(bridge).ExportAsync("job",7,new(),false,"unused",(_,_)=>{},_=>{},default));Assert.Single(bridge.Calls);}
 sealed class ReviewBridge : IEngineBridge
 {
  public List<string> Calls=[];public bool Conflict;bool rendered;int revision=4;public bool IsRunning=>true;
  public Task<JsonObject> GetAsync(string route,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? providerHeaders=null,IReadOnlyDictionary<string,string>? query=null)=>Task.FromResult(new JsonObject{["project"]=new JsonObject{["revision"]=revision,["status"]=rendered?"completed":"draft",["edits"]=new JsonObject{["style"]=new JsonObject{["enabled"]=true}},["result"]=new JsonObject{["new_video_url"]="/videos/job/final.mp4"}}});
  public Task<JsonObject> SendAsync(string route,JsonObject body,bool put=false,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? providerHeaders=null)
  {if(put){Calls.Add($"PUT:revision={body["revision"]}:captions={body["edits"]!["style"]!["enabled"]!.GetValue<bool>()}");if(Conflict)throw new IOException("conflict");revision++;return Task.FromResult(new JsonObject{["project"]=new JsonObject{["revision"]=revision}});}Calls.Add($"RUN:revision={body["revision"]}");rendered=true;return Task.FromResult(new JsonObject());}
  public Task ExportAsync(string route,string destination,CancellationToken token=default){Calls.Add("COPY:"+route);File.WriteAllText(destination,"validated");return Task.CompletedTask;}
  public ValueTask DisposeAsync()=>ValueTask.CompletedTask;
  public Task StartAsync(CancellationToken t=default)=>Task.CompletedTask;public Task RestartAsync(CancellationToken t=default)=>Task.CompletedTask;
  public Task<JsonObject> FormAsync(string r,IReadOnlyDictionary<string,string> f,string? file=null,CancellationToken cancellationToken=default,IReadOnlyDictionary<string,string>? images=null)=>throw new NotSupportedException();
  public Task<JsonObject> CancelScheduledAsync(string j,string p,string k,CancellationToken cancellationToken=default)=>throw new NotSupportedException();
  public Task<string> UploadAsync(string p,bool a,string t,CancellationToken cancellationToken=default,JsonObject? options=null)=>throw new NotSupportedException();
 }
}
