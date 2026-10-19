using System.Text.Json.Nodes;
using OpenShorts.EngineBridge;
using Xunit;

namespace OpenShorts.Tests;

public sealed class ContractCompatibility
{
    private static JsonObject Compatible()=>new()
    {
        ["protocol_version"]=1,["editor_project_version"]=1,
        ["features"]=new JsonArray(NativeContract.RequiredFeatures.Select(x=>(JsonNode?)JsonValue.Create(x)).ToArray()),
        ["routes"]=new JsonArray(NativeContract.RequiredRoutes.Select(x=>
        {var split=x.Split(' ',2);return (JsonNode)new JsonObject{["method"]=split[0],["path"]=split[1]};}).ToArray())
    };
    [Fact] public void MatchingEngineContractIsAccepted()=>NativeContract.Validate(Compatible());
    [Fact] public void MissingNativeRouteIsRejected()
    {var data=Compatible();data["routes"]!.AsArray().RemoveAt(0);Assert.Throws<IOException>(()=>NativeContract.Validate(data));}
    [Fact] public void MissingDashboardRouteIsRejected()
    {var data=Compatible();var routes=data["routes"]!.AsArray();routes.Remove(routes.First(r=>r?["path"]?.GetValue<string>()=="/api/desktop/home"));Assert.Throws<IOException>(()=>NativeContract.Validate(data));}
    [Fact] public void MissingEditorWorkspaceFeatureIsRejected()
    {var data=Compatible();var features=data["features"]!.AsArray();features.Remove(features.First(f=>f?.GetValue<string>()=="native-editor-workspace"));Assert.Throws<IOException>(()=>NativeContract.Validate(data));}
    [Fact] public void MissingAdvancedCaptionSupportIsRejected()
    {var data=Compatible();data["features"]!.AsArray().RemoveAt(7);Assert.Throws<IOException>(()=>NativeContract.Validate(data));}
    [Theory][InlineData("2")][InlineData("true")][InlineData("\"1\"")][InlineData("null")]
    public void IncompatibleSchemaIsRejected(string value)
    {var data=Compatible();data["protocol_version"]=JsonNode.Parse(value);Assert.Throws<IOException>(()=>NativeContract.Validate(data));}
}
