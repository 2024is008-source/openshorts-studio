using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
namespace OpenShorts.Desktop;
public partial class HomePanel : UserControl
{
    public HomePanel()
    {
        InitializeComponent();
        SizeChanged+=(_,_)=>
        {
            StatusColumn.Width=new GridLength(ActualWidth<1120?230:245);
            HeroTitle.FontSize=ActualWidth<1120?25:29;
        };
    }
    public void ScrollToTop()=>HomeScroll.ScrollToTop();
    private void OnQuickTour(object sender,RoutedEventArgs e)=>ShowQuickTour();
    public void ShowQuickTour()
    {
        var panel=new StackPanel{Margin=new Thickness(26)};
        panel.Children.Add(new TextBlock{Text="From a long video to your next short",FontSize=22,FontWeight=FontWeights.SemiBold,Margin=new Thickness(0,0,0,20)});
        string[] titles=["01   Import your source","02   Find the best moments","03   Make it yours","04   Export and share"];
        string[] descriptions=["Choose a local video, or drop it into the window. Your original stays intact.","Configure your AI provider in Settings, then choose the clip length and analysis options in AI Clipper.","Open a generated clip in Video Editor. Adjust captions, source ranges, framing and audio, then save your project.","Choose a vertical, square or landscape output in Export. Rendering uses the local Python and FFmpeg engine."];
        for(int i=0;i<titles.Length;i++)
        {
            panel.Children.Add(new TextBlock{Text=titles[i],FontSize=14,FontWeight=FontWeights.SemiBold,Foreground=new SolidColorBrush(Color.FromRgb(143,180,255)),Margin=new Thickness(0,0,0,6)});
            panel.Children.Add(new TextBlock{Text=descriptions[i],FontSize=12,Foreground=new SolidColorBrush(Color.FromRgb(175,179,191)),TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,0,0,20)});
        }
        var dialog=new Window{Owner=Window.GetWindow(this),Title="OpenShorts · Quick tour",Width=530,Height=550,WindowStartupLocation=WindowStartupLocation.CenterOwner,ResizeMode=ResizeMode.CanResize,Content=new ScrollViewer{Content=panel,VerticalScrollBarVisibility=ScrollBarVisibility.Auto}};
        var done=new Button{Content="Start creating",HorizontalAlignment=HorizontalAlignment.Left,Style=(Style)FindResource("Primary")};
        done.Click+=(_,_)=>dialog.Close();panel.Children.Add(done);dialog.ShowDialog();
    }
}
