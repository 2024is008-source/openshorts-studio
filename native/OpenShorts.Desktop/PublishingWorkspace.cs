using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json.Nodes;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace OpenShorts.Desktop;
public partial class MainViewModel
{
    [ObservableProperty] private string publishingProfile="";
    [ObservableProperty] private string publishingTitle="";
    [ObservableProperty] private string publishingDescription="";
    [ObservableProperty] private bool publishYoutube=true;
    [ObservableProperty] private bool publishInstagram;
    [ObservableProperty] private bool publishTiktok;
    [ObservableProperty] private string scheduledDate="";
    [ObservableProperty] private string publishingTimezone="UTC";
    [ObservableProperty] private string publishingStatus="Connect your Upload-Post profile in Settings. Nothing is published automatically.";
    public ObservableCollection<ReportRow> PublishingReports { get; }=[];
    public ObservableCollection<ScheduledPost> ScheduledPosts { get; }=[];
    [ObservableProperty] private ScheduledPost? selectedScheduledPost;
    [RelayCommand(CanExecute=nameof(CanImport))] private Task LoadSocialProfiles()=>SocialRead("/api/social/user");
    [RelayCommand(CanExecute=nameof(CanImport))] private Task LoadSocialAnalytics()=>SocialRead("/api/social/analytics");
    [RelayCommand(CanExecute=nameof(CanImport))] private Task LoadScheduledPosts()=>SocialRead("/api/social/scheduled");
    private Task SocialRead(string route)=>Guard(async token=>
    {
        Dictionary<string,string>? query=null;
        if(route!="/api/social/user")
        {if(string.IsNullOrWhiteSpace(PublishingProfile))throw new ArgumentException("Enter the provider profile ID.");query=new(){["user"]=PublishingProfile};}
        var data=await engine.GetAsync(route,token,ProviderHeaders("uploadpost"),query);Report(PublishingReports,data);
        if(route=="/api/social/scheduled")
        {
            ScheduledPosts.Clear();foreach(var row in data["scheduled_posts"]?.AsArray() ?? [])
                if(row?["job_id"] is JsonValue id)ScheduledPosts.Add(new(id.ToString(),row["title"]?.ToString() ?? "Scheduled post",row["scheduled_date"]?.ToString() ?? ""));
        }
        PublishingStatus="Provider data refreshed.";
    });
    [RelayCommand(CanExecute=nameof(CanImport))] private Task CancelScheduledPost()=>Guard(async token=>
    {
        if(SelectedScheduledPost is null)throw new IOException("Load scheduled posts and select one first.");
        if(MessageBox.Show($"Cancel scheduled post '{SelectedScheduledPost.Title}'?","Cancel scheduled post",MessageBoxButton.OKCancel)!=MessageBoxResult.OK)return;
        var key=storage.LoadCredential("uploadpost");if(key.Length==0)throw new IOException("Add your Upload-Post key in Settings.");
        await engine.CancelScheduledAsync(SelectedScheduledPost.Id,PublishingProfile,key,token);ScheduledPosts.Remove(SelectedScheduledPost);PublishingStatus="Scheduled post cancelled.";
    });
    [RelayCommand(CanExecute=nameof(CanCreativeAction))] private Task PublishClip()=>Guard(async token=>
    {
        if(!HasEditor)throw new IOException("Open the clip you want to publish in the editor first.");
        if(string.IsNullOrWhiteSpace(PublishingProfile))throw new ArgumentException("Enter your connected provider profile ID.");
        var platforms=new List<string>();if(PublishYoutube)platforms.Add("youtube");if(PublishInstagram)platforms.Add("instagram");if(PublishTiktok)platforms.Add("tiktok");
        if(platforms.Count==0)throw new ArgumentException("Choose at least one platform.");
        string? scheduled=null;
        if(ScheduledDate.Trim().Length>0)
        {
            if(!System.Text.RegularExpressions.Regex.IsMatch(ScheduledDate,@"(Z|[+-]\d{2}:\d{2})$") || !DateTimeOffset.TryParse(ScheduledDate,CultureInfo.InvariantCulture,DateTimeStyles.None,out var date) || date<=DateTimeOffset.UtcNow)throw new ArgumentException("Enter a future ISO-8601 time with a UTC offset, or leave scheduling empty.");
            scheduled=date.ToString("O");
        }
        var confirmation=$"{(scheduled is null?"Publish":"Schedule")} clip {CurrentClip.Index+1} to {string.Join(", ",platforms)} using profile {PublishingProfile}?\n\nTitle: {PublishingTitle}\nTime: {scheduled ?? "now"}";
        if(MessageBox.Show(confirmation,"Review publication",MessageBoxButton.OKCancel,MessageBoxImage.Information)!=MessageBoxResult.OK)return;
        if(!await FlushDraftAsync(token))return;
        var body=ClipRequest();body["user_id"]=PublishingProfile;body["title"]=PublishingTitle;body["description"]=PublishingDescription;
        body["platforms"]=new JsonArray(platforms.Select(p=>(JsonNode?)JsonValue.Create(p)).ToArray());body["scheduled_date"]=scheduled;body["timezone"]=PublishingTimezone;
        var data=await engine.SendAsync("/api/social/post",body,cancellationToken:token,providerHeaders:ProviderHeaders("uploadpost"));
        Report(PublishingReports,data);PublishingStatus="Provider request completed. Review the returned publication status.";
    });
    private void NotifyPublishingCommands()
    {LoadSocialProfilesCommand.NotifyCanExecuteChanged();LoadSocialAnalyticsCommand.NotifyCanExecuteChanged();LoadScheduledPostsCommand.NotifyCanExecuteChanged();PublishClipCommand.NotifyCanExecuteChanged();CancelScheduledPostCommand.NotifyCanExecuteChanged();}
}
public sealed record ScheduledPost(string Id,string Title,string Scheduled);
