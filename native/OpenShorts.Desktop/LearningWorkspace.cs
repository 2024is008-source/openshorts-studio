using System.Text.Json.Nodes;
using System.Security.Cryptography;
using System.Text;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    [ObservableProperty] private string learningStatus="Local learning · collecting explicit feedback, no trained model active.";
    [ObservableProperty] private string learningDetails="Refresh to check database, reviewed examples and training readiness.";
    [ObservableProperty] private bool learningCollect=true;
    [ObservableProperty] private bool learningRetrieve=true;
    [ObservableProperty] private bool learningInference=false;
    [ObservableProperty] private string highlightLearningStatus="Clip ranking: no evaluated model active.";
    [ObservableProperty] private string learningModelId="";
    [ObservableProperty] private double clipReviewStart;
    [ObservableProperty] private double clipReviewEnd;
    [ObservableProperty] private string clipReviewCategory="general";
    [ObservableProperty] private string clipRejectionReason="poor_story";
    [ObservableProperty] private string? clipAlternative;
    public string[] ClipReviewCategories {get;}=["general","podcast","podcast-motivation","podcast-education","podcast-comedy","challenge","challenge-competition","challenge-survival","challenge-experiment","challenge-general","sports_highlights","cricket","football"];
    public string[] ClipRejectionReasons {get;}=["poor_story","wrong_event","duplicate","bad_boundary","irrelevant","poor_framing","other"];
    public System.Collections.ObjectModel.ObservableCollection<string> ClipAlternatives {get;}=[];
    private readonly Dictionary<string,string> clipAlternativeIds=[];
    private string? clipRankingSnapshot;
    [ObservableProperty] private double learningRating=3;
    public string[] LearningCorrectionActions {get;}=["adjust_intensity","adjust_duration","adjust_timing","replace","remove","caption_style","caption_text","quality"];
    [ObservableProperty] private string learningCorrectionAction="adjust_intensity";
    private JsonObject? learningSnapshot;
    private JsonObject? learningBefore;
    private string? learningCandidate;
    private string learningEffect="";

    [RelayCommand] private Task RefreshLearning()=>Guard(async token=>
    {
        var state=await engine.GetAsync("/api/desktop/learning",token);
        LearningCollect=state["privacy"]?["collect"]?.GetValue<bool>() ?? true;
        LearningRetrieve=state["privacy"]?["retrieval"]?.GetValue<bool>() ?? true;
        LearningInference=state["privacy"]?["inference"]?.GetValue<bool>() ?? false;
        var rank=state["highlight_ranking"];
        HighlightLearningStatus=$"Clip ranker · usable reviewed: {rank?["reviewed_examples"]} · sources: {rank?["independent_sources"]} · active: {rank?["active_model"]?.ToString() ?? "None"}\n{rank?["activation_reason"]}\nEvaluation: {rank?["evaluation"]?.ToJsonString() ?? "Unavailable; no measured ML improvement"}";
        LearningStatus=$"Database: {state["database"]} · Reviewed: {state["reviewed_examples"]} · Model: {state["active_model"]}";
        LearningDetails=$"Data: {state["learning_data"]} · Training: {state["training"]?["status"]} · Retrieval: {(LearningRetrieve?"enabled":"disabled")}\nLast evaluation: {(state["last_evaluation"]?.AsArray().Count>0?"Held-out results available":"None")}\n{state["gemini"]}";
        if(HasEditor && !HasInputError && !EditorStale)
        {
            // Snapshot before an explicit correction; autosave/undo never sends labels.
            var selectedId=SelectedAutoEffect?.Id;
            await Save(token);
            learningSnapshot=await engine.GetAsync(EditorRoute+"/learning",token);
            SelectedAutoEffect=AutoEffects.FirstOrDefault(e=>e.Id==selectedId);
            learningBefore=SelectedAutoEffect?.Export();learningEffect=SelectedAutoEffect?.Id ?? "none";
            var scene=SelectedAutoEffect?.Definition["source_scene"]?.ToString();
            var match=learningSnapshot["candidates"]?.AsArray().FirstOrDefault(n=>n?["effect"]?.ToString()==learningEffect && (scene is null || n?["scene"] is not null));
            learningCandidate=match?["id"]?.ToString();
        }
    });
    [RelayCommand] private Task SaveLearningPrivacy()=>Guard(async token=>
    {
        await engine.SendAsync("/api/desktop/learning/privacy",new JsonObject{["collect"]=LearningCollect,["retrieval"]=LearningRetrieve,["inference"]=LearningInference,["retention_days"]=365,["upload"]=false},true,token);
        LearningStatus="Local privacy preferences saved. Inference requires a separately approved, active model.";
    });
    [RelayCommand] private Task ApproveLearning()=>SendLearning(learningEffect=="none"?"approve_none":"approve");
    [RelayCommand] private Task RejectLearning()=>SendLearning("reject");
    [RelayCommand] private Task RecordLearningCorrection()=>SendLearning(LearningCorrectionAction);
    private Task SendLearning(string action)=>Guard(async token=>
    {
        if(!HasEditor||HasInputError||EditorStale||learningCandidate is null)throw new IOException("Refresh learning with the effect selected before reviewing or correcting it.");
        if((SelectedAutoEffect?.Id ?? "none")!=learningEffect)throw new IOException("Refresh learning after changing the selected effect.");
        var after=SelectedAutoEffect?.Export();
        JsonObject Operational(JsonObject? value)
        {
            var result=new JsonObject();
            foreach(var key in new[]{"type","start","end","duration","intensity","enabled"})if(value?[key] is JsonNode node)result[key]=node.DeepClone();
            return result;
        }
        var before=Operational(learningBefore);var change=Operational(after);
        if(action=="caption_style"){before=new(){["preset"]=editor?["edits"]?["style"]?["preset"]?.ToString() ?? "existing"};change=new(){["preset"]=CaptionPreset};}
        if(action=="caption_text")
        {
            var original=SelectedCaption is null?"":wordBaseline.GetValueOrDefault(SelectedCaption.Id,"");
            var current=SelectedCaption?.Text ?? "";
            string Hash(string text)=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
            before=new(){["text_hash"]=Hash(original),["word_count"]=original.Split(' ',StringSplitOptions.RemoveEmptyEntries).Length};
            change=new(){["text_hash"]=Hash(current),["word_count"]=current.Split(' ',StringSplitOptions.RemoveEmptyEntries).Length};
        }
        // Feedback is append-only and separate from editor undo/autosave history.
        var reply=await engine.SendAsync(EditorRoute+"/learning",new JsonObject{["event"]=Guid.NewGuid().ToString("N"),["candidate"]=learningCandidate,["action"]=action,["before"]=before,["after"]=change,["rating"]=action=="quality"?LearningRating:null},cancellationToken:token);
        LearningStatus=$"Explicit review saved: {reply["status"]}. A saved correction is not automatic model training.";
    });
    [RelayCommand] private Task StartLearningTraining()=>Guard(async token=>
    {await engine.SendAsync("/api/desktop/learning/train",new JsonObject{["epochs"]=100},cancellationToken:token);LearningStatus="CPU training queued; insufficient reviewed data keeps ML disabled. Check training status.";});
    [RelayCommand] private Task CheckLearningTraining()=>Guard(async token=>
    {var state=await engine.GetAsync("/api/desktop/learning/train",token);LearningStatus=$"Training: {state["status"]} · {state["result"]?["status"]}";LearningModelId=state["result"]?["model_id"]?.ToString() ?? LearningModelId;});
    [RelayCommand] private Task CancelLearningTraining()=>Guard(async token=>
    {await engine.SendAsync("/api/desktop/learning/train/cancel",new JsonObject(),cancellationToken:token);LearningStatus="Training cancellation requested.";});
    private string ClipLearningRoute=>EditorRoute.Replace("/editor","/learning-ranking",StringComparison.Ordinal);
    [RelayCommand] private Task SnapshotClipLearning()=>Guard(async token=>
    {
        if(!HasEditor)throw new IOException("Open a clip in the Editor before reviewing its ranking.");
        var state=await engine.GetAsync(ClipLearningRoute,token);clipRankingSnapshot=state["candidate"]?.ToString();
        ClipReviewStart=state["start"]!.GetValue<double>();ClipReviewEnd=state["end"]!.GetValue<double>();
        ClipAlternatives.Clear();clipAlternativeIds.Clear();
        foreach(var row in state["alternatives"]!.AsArray())
        {
            var label=$"{row!["start"]!.GetValue<double>():F2}–{row["end"]!.GetValue<double>():F2} source seconds · option {ClipAlternatives.Count+1}";
            ClipAlternatives.Add(label);clipAlternativeIds[label]=row["id"]!.ToString();
        }
        HighlightLearningStatus=$"Immutable clip snapshot ready: {ClipReviewStart:F2}–{ClipReviewEnd:F2} source seconds. Alternatives: {ClipAlternatives.Count}. Explicit buttons record feedback; editor cuts remain unchanged.";
    });
    [RelayCommand] private Task RecordClipLearning(string action)=>Guard(async token=>
    {
        if(!HasEditor||clipRankingSnapshot is null)throw new IOException("Snapshot the current clip before submitting feedback.");
        var current=await engine.GetAsync(ClipLearningRoute,token);
        if(current["candidate"]?.ToString()!=clipRankingSnapshot)throw new IOException("Selected clip changed; refresh the snapshot.");
        var body=new JsonObject{["action"]=action};
        if(action=="rating")body["rating"]=LearningRating;
        if(action=="reject")body["negative_reason"]=ClipRejectionReason;
        if(action=="trim"){body["start"]=ClipReviewStart;body["end"]=ClipReviewEnd;}
        if(action=="alternative")body["alternative"]=ClipAlternative is not null&&clipAlternativeIds.TryGetValue(ClipAlternative,out var id)?id:throw new IOException("Choose an alternative source range first.");
        if(action=="category")body["category"]=ClipReviewCategory;
        if(action=="caption_style")body["preset"]=CaptionPreset;
        var reply=await engine.SendAsync(ClipLearningRoute,body,cancellationToken:token);
        HighlightLearningStatus=$"Clip feedback: {reply["status"]}. Saved locally; no automatic training or promotion.";
    });
    [RelayCommand] private Task TrainHighlightRanker()=>Guard(async token=>
    {await engine.SendAsync("/api/desktop/learning/train",new JsonObject{["epochs"]=100,["task"]="highlight-ranking"},cancellationToken:token);HighlightLearningStatus="Local training requested. Use Training status; insufficient real reviews leave the ranker OFF.";});
    [RelayCommand] private Task TransitionLearningModel(string state)=>Guard(async token=>
    {
        if(LearningModelId.Length!=64||!LearningModelId.All(Uri.IsHexDigit)||state is not ("approved" or "active" or "rolled_back"))throw new IOException("Enter an evaluated model's full ID and choose a valid transition.");
        await engine.SendAsync($"/api/desktop/learning/models/{LearningModelId}/{state}",new JsonObject(),cancellationToken:token);
        HighlightLearningStatus=$"Explicit model transition: {state}. Evaluation and schema gates were checked by the local engine.";
    });
    [RelayCommand] private async Task DeleteLearningHistory()
    {
        if(MessageBox.Show("Delete local learning history, datasets, model artifacts and learning backups? Saved video projects remain unchanged.","Delete local learning data",MessageBoxButton.YesNo,MessageBoxImage.Question)!=MessageBoxResult.Yes)return;
        await Guard(async token=>{await engine.SendAsync("/api/desktop/learning/delete",new JsonObject(),cancellationToken:token);learningCandidate=null;LearningStatus="Local learning data deleted. Saved projects were preserved.";});
    }
}
