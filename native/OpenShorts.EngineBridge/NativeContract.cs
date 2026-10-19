using System.Text.Json.Nodes;

namespace OpenShorts.EngineBridge;

/// <summary>Fail before editing when an independently exported worker is incompatible.</summary>
public static class NativeContract
{
    public static readonly string[] RequiredFeatures=["project-library","source-media","templates","pipeline-cancel","saved-timeline","timeline-features","caption-appearance","aligned-word-edits","advanced-caption-layout","native-editor-workspace","native-video-import","generation-drafts","generation-review","clip-duplication"];
    public static void Validate(JsonObject data)
    {
        const string error="The Python engine is incompatible with this native app. Use a matched source export or repair the engine installation.";
        try
        {
            if(data["protocol_version"]?.GetValue<int>()!=1 || data["editor_project_version"]?.GetValue<int>()!=1 || data["features"] is not JsonArray features)throw new IOException(error);
            var supported=features.Select(x=>x!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            if(RequiredFeatures.Any(f=>!supported.Contains(f)))throw new IOException(error);
            if(data["routes"] is not JsonArray routes)throw new IOException(error);
            var actual=routes.Select(r=>$"{r!["method"]!.GetValue<string>()} {r["path"]!.GetValue<string>()}").ToHashSet(StringComparer.Ordinal);
            foreach(var route in RequiredRoutes)if(!actual.Contains(route))throw new IOException(error);
        }
        catch(Exception e) when(e is InvalidOperationException or FormatException or NullReferenceException)
        {throw new IOException(error,e);}
    }
    public static readonly string[] RequiredRoutes=[
        "GET /api/desktop/caption-presets",
        "GET /api/desktop/imports/{identity}/settings","PUT /api/desktop/imports/{identity}/settings",
        "POST /api/desktop/imports","GET /api/desktop/imports/{identity}","POST /api/desktop/imports/{identity}/cancel",
        "GET /api/desktop/jobs/{job_id}/progress","GET /api/desktop/jobs/{job_id}/review","PUT /api/desktop/jobs/{job_id}/review",
        "GET /api/desktop/jobs/{job_id}/clips/{clip_index}/thumbnail",
        "GET /api/config","POST /api/process","GET /api/status/{job_id}",
        "GET /api/desktop/projects","GET /api/desktop/home","POST /api/desktop/projects/{job_id}/restore",
        "GET /api/desktop/assets/{job_id}",
        "POST /api/desktop/cache/cleanup",
        "GET /api/desktop/source/{job_id}","GET /api/desktop/media/{job_id}/{clip_index}",
        "GET /api/desktop/templates","GET /api/desktop/capabilities","POST /api/desktop/jobs/{job_id}/cancel",
        "POST /api/clip/{job_id}/{clip_index}/editor/duplicate",
        "GET /api/clip/{job_id}/{clip_index}/editor","PUT /api/clip/{job_id}/{clip_index}/editor",
        "POST /api/clip/{job_id}/{clip_index}/editor/features","POST /api/clip/{job_id}/{clip_index}/editor/run",
        "POST /api/clip/{job_id}/{clip_index}/editor/cancel",
        "GET /api/clip/{job_id}/{clip_index}/quality","POST /api/clip/{job_id}/{clip_index}/quality",
        "GET /api/jobs/{job_id}/ranking","POST /api/jobs/{job_id}/ranking/rescore",
        "GET /api/clip/{job_id}/{clip_index}/hooks","POST /api/hook","POST /api/hook/preview",
        "GET /api/clip/{job_id}/{clip_index}/scenes","POST /api/clip/reframe",
        "POST /api/thumbnail/analyze","POST /api/thumbnail/generate","POST /api/translate",
        "POST /api/saasshorts/analyze","POST /api/saasshorts/generate","POST /api/social/post"];
}
