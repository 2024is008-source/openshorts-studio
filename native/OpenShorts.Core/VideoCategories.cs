namespace OpenShorts.Core;

/// <summary>Category Intelligence v1. Legacy IDs serialize unchanged.</summary>
public static class VideoCategories
{
    public const int Version=1;
    public static readonly IReadOnlyDictionary<string,string[]> Registry=new Dictionary<string,string[]>
    {
        ["podcast"]=["auto","motivation","education","comedy"],
        ["challenge"]=["auto","competition","survival","experiment","general"],
        ["sports_highlights"]=["auto","cricket","football"],
        ["general"]=["auto"]
    };
    public static (string Primary,string Subcategory) Parse(string value)
    {
        if(value=="auto")return ("auto","auto");
        if(value=="default_clipping")return ("general","auto");
        if(value=="educational")return ("podcast","education");
        if(value=="emotional")return ("general","auto");
        if(value is "cricket" or "football")return ("sports_highlights",value);
        foreach(var (primary,subs) in Registry)
        {
            if(value==primary)return(primary,"auto");
            foreach(var sub in subs.Where(s=>s!="auto"))if(value==$"{primary}-{sub}")return(primary,sub);
        }
        throw new ArgumentException("Unsupported category selection.");
    }
    public static string Id(string primary,string subtype)
    {
        if(primary=="auto" && subtype=="auto")return "auto";
        if(!Registry.TryGetValue(primary,out var subs)||!subs.Contains(subtype))throw new ArgumentException("Unsupported category subtype.");
        return primary=="sports_highlights" && subtype!="auto"?subtype:subtype=="auto"?primary:$"{primary}-{subtype}";
    }
}
