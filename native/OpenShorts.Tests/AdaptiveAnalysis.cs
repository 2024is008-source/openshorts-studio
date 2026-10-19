using System.Text.Json.Nodes;
using OpenShorts.Core;
using Xunit;
namespace OpenShorts.Tests;
public sealed class AdaptiveAnalysis
{
    [Theory]
    [InlineData("adaptive-economy")][InlineData("adaptive-balanced")][InlineData("adaptive-quality")]
    public void ExplicitAdaptiveSettingsRoundTrip(string mode)
    {
        var settings=new GenerationSettings{Analysis=mode,AnalysisCategory="football",AnalysisPrompt="Focus on build-up",Mode="highlights"};
        var fields=settings.ToFields();
        Assert.Equal(mode,fields["analysis_mode"]!.GetValue<string>());
        Assert.Equal("football",fields["analysis_category"]!.GetValue<string>());
        Assert.Equal("transcript",new GenerationSettings().Analysis);
    }
    [Fact]public void ProgressShowsMeasuredCountsAndCache()
    {
        var value=GenerationProgress.Parse(JsonNode.Parse("""{"state":"running","stage":"Verifying important moments","stages":[{"title":"Verifying important moments","state":"active","percent":40,"completed_count":2,"total_count":5,"elapsed_seconds":3.5,"cache_reuse":true,"retry":true}]}""")!.AsObject());
        Assert.Null(value.Overall);Assert.Contains("2/5",value.Stages[0].Description);Assert.Contains("cached",value.Stages[0].Description);Assert.Contains("retry",value.Stages[0].Description);
    }
}
