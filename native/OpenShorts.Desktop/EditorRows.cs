using CommunityToolkit.Mvvm.ComponentModel;
using System.Collections.ObjectModel;
namespace OpenShorts.Desktop;

public partial class SegmentRow : ObservableObject
{
    [ObservableProperty] private double start;
    [ObservableProperty] private double end;
    public SegmentRow(double start, double end) { Start = start; End = end; }
}
public partial class CaptionRow : ObservableObject
{
    public string Id { get; }
    [ObservableProperty] private double start;
    [ObservableProperty] private double end;
    [ObservableProperty] private string text;
    public ObservableCollection<WordRow> Words { get; } = [];
    public string OriginalText { get; set; } = "";
    public bool WordEditingSupported => Words.Count>0 && Words.All(w=>w.Aligned) && Text==OriginalText;
    partial void OnTextChanged(string value)=>OnPropertyChanged(nameof(WordEditingSupported));
    public CaptionRow(string id,double start,double end,string text) { Id=id;Start=start;End=end;this.text=text; }
}
public partial class WordRow : ObservableObject
{
    public string Word { get; }
    public bool Aligned { get; }
    [ObservableProperty] private double start;
    [ObservableProperty] private double end;
    [ObservableProperty] private bool emphasis;
    public WordRow(string word,double start,double end,bool emphasis,bool aligned)
    { Word=word;Start=start;End=end;Emphasis=emphasis;Aligned=aligned; }
}
public sealed record TemplateItem(string Id, string Name, System.Text.Json.Nodes.JsonObject Definition)
{public override string ToString()=>Name;}
