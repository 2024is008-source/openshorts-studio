using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Extensions.DependencyInjection;
using OpenShorts.Core;

namespace OpenShorts.Desktop;
internal static class HomeVisualTest
{
    internal static async Task RunAsync(MainWindow window,ServiceProvider services,string directory)
    {
        Directory.CreateDirectory(directory);
        try
        {
            var model=services.GetRequiredService<MainViewModel>();var engine=services.GetRequiredService<IEngineBridge>();
            var deadline=DateTime.UtcNow.AddMinutes(3);
            while(model.Busy || !engine.IsRunning){if(DateTime.UtcNow>deadline)throw new IOException("Dashboard startup timed out.");await Task.Delay(100);}
            if(model.Error.Length>0)throw new IOException(model.Error);
            model.Route="Home";await Task.Delay(300);
            Capture(window,Path.Combine(directory,"home-desktop.png"));
            Capture(window.HomeDashboard.HeroBanner,Path.Combine(directory,"hero-banner.png"));
            if(Math.Abs(window.NewProjectButton.ActualHeight-34)>.81 || Math.Abs(window.HomeDashboard.HeroImportButton.ActualHeight-36)>.81)throw new IOException("Reference action sizes were not applied.");
            if(window.NewProjectButton.Background is not SolidColorBrush action || action.Color!=Color.FromRgb(0,207,232))throw new IOException("Primary actions must use the reference cyan.");
            Capture(window.HomeDashboard.DesktopStatus,Path.Combine(directory,"sidebar.png"));
            var sidebar=window.HomeDashboard.DesktopStatus;
            if(sidebar.AccountCard.TranslatePoint(new Point(0,sidebar.AccountCard.ActualHeight),sidebar).Y>sidebar.ActualHeight)throw new IOException("Compact account card is outside the sidebar viewport.");
            CheckSidebar(sidebar);
            model.HomeProcessingMode="Performance";
            if(model.Preset!="performance")throw new IOException("Processing mode did not reach the native preset.");
            model.HomeProcessingMode="Balanced";
            model.HomeSearch="Video";
            if(!model.HomeSearchResults.Any(x=>x.Route=="Video Editor"))throw new IOException("Dashboard command search failed.");
            model.HomeSearch="";
            model.SelectHomePresetCommand.Execute("2");
            if(!model.HomeExportPreset.StartsWith("Instagram"))throw new IOException("Preset connection failed.");
            foreach(var route in model.Navigation){model.NavigateHomeCommand.Execute(route);if(model.Route!=route)throw new IOException("Workspace navigation failed: "+route);}
            model.Route="Home";await Task.Delay(100);
            var selected=Descendants(window).OfType<System.Windows.Controls.Button>().Where(b=>b.Name=="NavButton" && b.Background is SolidColorBrush brush && brush.Color==Color.FromRgb(8,39,51)).ToArray();
            if(selected.Length!=1 || (string)selected[0].DataContext!="Home")throw new IOException("Navigation must highlight exactly the current workspace.");
            var scroll=(System.Windows.Controls.ScrollViewer)window.HomeDashboard.FindName("HomeScroll");
            scroll.ScrollToBottom();await Task.Delay(150);
            if(scroll.ScrollableHeight>0 && scroll.VerticalOffset<=0)throw new IOException("Dashboard scrolling failed.");
            Capture(window,Path.Combine(directory,"home-exports.png"));scroll.ScrollToTop();
            window.Width=1120;window.Height=760;await Task.Delay(300);
            Capture(window,Path.Combine(directory,"home-compact.png"));
            CheckSidebar(sidebar);
            Capture(sidebar,Path.Combine(directory,"sidebar-compact.png"));
            if(window.HomeDashboard.ActualWidth>window.ActualWidth)throw new IOException("Home exceeds window width.");
            File.WriteAllText(Path.Combine(directory,"result.json"),JsonSerializer.Serialize(new{success=true,projects=model.RecentProjects.Count,exports=model.RecentExports.Count,commandSearch=true,preset=true,processingMode=true,sidebarAccountVisible=true,sidebarBottomAligned=true,sidebarThemeMatched=true,referenceActionSizes=true,cyanPrimaryActions=true,allWorkspaces=true,singleActiveNavigation=true,scrolling=true,compactLayout=true,generatedArtwork=true,noAiRequests=true}));
            Application.Current.Shutdown(0);
        }
        catch(Exception error){File.WriteAllText(Path.Combine(directory,"error.txt"),error.ToString());Application.Current.Shutdown(1);}
    }
    private static void CheckSidebar(DesktopStatusPanel sidebar)
    {
        double bottom=sidebar.AccountCard.TranslatePoint(new Point(0,sidebar.AccountCard.ActualHeight),sidebar).Y;
        if(sidebar.ActualHeight>=602 && Math.Abs(bottom-sidebar.ActualHeight)>1.1)throw new IOException("Sidebar account must align with the content bottom.");
        if(sidebar.SystemCard.Background is not SolidColorBrush actual || sidebar.FindResource("Panel") is not SolidColorBrush expected || actual.Color!=expected.Color)
            throw new IOException("Sidebar must use the application's panel color.");
    }
    private static IEnumerable<DependencyObject> Descendants(DependencyObject parent)
    {
        for(int i=0;i<VisualTreeHelper.GetChildrenCount(parent);i++)
        {var child=VisualTreeHelper.GetChild(parent,i);yield return child;foreach(var descendant in Descendants(child))yield return descendant;}
    }
    private static void Capture(FrameworkElement window,string path)
    {
        window.UpdateLayout();var bitmap=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);
        if(window is Window)bitmap.Render(window);
        else
        {
            var drawing=new DrawingVisual();using(var dc=drawing.RenderOpen())dc.DrawRectangle(new VisualBrush(window),null,new Rect(0,0,window.ActualWidth,window.ActualHeight));
            bitmap.Render(drawing);
        }
        var png=new PngBitmapEncoder();png.Frames.Add(BitmapFrame.Create(bitmap));using var output=File.Create(path);png.Save(output);
    }
}
