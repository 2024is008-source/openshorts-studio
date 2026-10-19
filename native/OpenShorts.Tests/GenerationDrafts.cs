using System.Text.Json;
using OpenShorts.Core;
using Xunit;
namespace OpenShorts.Tests;
public sealed class GenerationDrafts
{
    [Fact] public void AutomaticFieldsAreOmittedAndDurationBandUsesExistingContract()
    {
        var fields=new GenerationSettings{AutoDuration=true,AutoCount=true,MinimumSeconds=5,MaximumSeconds=60,OutputFormat="square",CaptionPreset="creator-bold",Framing="subject"}.ToFields();
        Assert.Null(fields["target_clips"]);Assert.Null(fields["clip_target_seconds"]);
        Assert.Equal("5",fields["clip_min_seconds"]!.GetValue<string>());Assert.Equal("60",fields["clip_max_seconds"]!.GetValue<string>());
        Assert.Equal("square",fields["output_format"]!.GetValue<string>());
    }
    [Fact] public void UnsupportedStrategiesAndInvalidBandsAreRejected()
    {
        Assert.Throws<ArgumentException>(()=>new GenerationSettings{HighlightStrategy="manual"}.ToFields());
        Assert.Throws<ArgumentException>(()=>new GenerationSettings{Analysis="thorough"}.ToFields());
        Assert.Throws<ArgumentException>(()=>new GenerationSettings{MinimumSeconds=31,MaximumSeconds=32}.ToFields());
        Assert.Throws<ArgumentException>(()=>new GenerationSettings{Mode="highlights",AutoDuration=true}.ToFields());
    }
    [Fact] public void VersionedDraftRoundTripsAndRejectsFutureFields()
    {
        var draft=new GenerationDraft{SourceId=new string('a',32),OutputLocation=Path.GetFullPath("output"),Settings=new(){Mode="highlights",Analysis="hybrid",OutputFormat="square",AudioPreset="dialogue"}};
        draft.Validate(120);var saved=JsonSerializer.Deserialize<GenerationDraft>(JsonSerializer.Serialize(draft));Assert.Equal(draft,saved);
        Assert.Throws<ArgumentException>(()=>(draft with{Version=2}).Validate(120));
        Assert.Throws<JsonException>(()=>JsonSerializer.Deserialize<GenerationSettings>("{\"UnsupportedFocus\":true}"));
        Assert.Throws<ArgumentException>(()=>(draft with{Settings=new(){MinimumSeconds=150}}).Validate(10));
    }
}
