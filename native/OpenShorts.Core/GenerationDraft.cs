using System.Text.Json.Serialization;
namespace OpenShorts.Core;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record GenerationDraft
{
    public int Version { get; init; }=1;
    public int Revision { get; init; }
    public string SourceId { get; init; }="";
    public GenerationSettings Settings { get; init; }=new();
    public string Encoder { get; init; }="auto";
    public string OutputLocation { get; init; }="";
    public string TemplateId { get; init; }="";
    public void Validate(double duration)
    {
        if(Version!=1)throw new ArgumentException("This settings draft uses an unsupported version. Update the application before editing it.");
        if(!double.IsFinite(duration)||duration<=0)throw new ArgumentException("The source duration is invalid.");
        if(Settings is null || TemplateId is null || SourceId is null || SourceId.Length!=32 || SourceId.Any(c=>!"0123456789abcdef".Contains(c)))throw new ArgumentException("The settings draft has invalid source or template metadata.");
        Settings.ToFields();
        if(Settings.MinimumSeconds is double min && min>duration)throw new ArgumentException("Minimum clip duration exceeds the source duration.");
        if(!new[]{"auto","x264","nvenc"}.Contains(Encoder))throw new ArgumentException("Unsupported encoder.");
        if(!Path.IsPathFullyQualified(OutputLocation))throw new ArgumentException("The project output location is invalid.");
    }
}
