using System.Text.Json;
using OpenShorts.Core;
using Xunit;

public class CategoryIntelligence
{
    [Theory]
    [InlineData("podcast-motivation","podcast","motivation")]
    [InlineData("podcast-education","podcast","education")]
    [InlineData("podcast-comedy","podcast","comedy")]
    [InlineData("challenge-survival","challenge","survival")]
    [InlineData("challenge-competition","challenge","competition")]
    [InlineData("challenge-experiment","challenge","experiment")]
    [InlineData("challenge-general","challenge","general")]
    [InlineData("football","sports_highlights","football")]
    [InlineData("cricket","sports_highlights","cricket")]
    [InlineData("sports_highlights","sports_highlights","auto")]
    public void SettingsRoundTrip(string id,string primary,string sub)
    {
        Assert.Equal((primary,sub),VideoCategories.Parse(id));
        Assert.Equal(id,VideoCategories.Id(primary,sub));
        var settings=new GenerationSettings{AnalysisCategory=id,Analysis="adaptive-balanced"};
        var reopened=JsonSerializer.Deserialize<GenerationSettings>(JsonSerializer.Serialize(settings))!;
        Assert.Equal(id,reopened.ToFields()["analysis_category"]!.GetValue<string>());
    }
    [Fact] public void OldProjectAndUnknownCategory()
    {
        Assert.Equal("auto",JsonSerializer.Deserialize<GenerationSettings>("{}")!.AnalysisCategory);
        Assert.Throws<ArgumentException>(()=>new GenerationSettings{AnalysisCategory="gaming"}.ToFields());
        Assert.Throws<ArgumentException>(()=>VideoCategories.Id("sports_highlights","motivation"));
    }
}
