using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
namespace OpenShorts.Desktop;
public partial class ClipperWorkspaceView : UserControl
{
    public ClipperWorkspaceView(){InitializeComponent();}
    public ContentControl PlayerHost=>PreviewHost;
    public bool IsSeeking=>ReviewSeek.IsMouseCaptureWithin || ReviewSeek.IsKeyboardFocusWithin;
    private void OnLayoutSizeChanged(object sender,SizeChangedEventArgs e)
    {
        bool compact=ActualWidth<1050;
        bool shortHeader=ActualHeight<600 || ActualWidth<1150;
        ReviewStepColumn.Width=new GridLength(shortHeader?0:.85,shortHeader?GridUnitType.Pixel:GridUnitType.Star);
        CompletionContainer.Visibility=ActualWidth<950?Visibility.Collapsed:Visibility.Visible;
        CompletionColumn.Width=new GridLength(ActualWidth<950?0:.95,ActualWidth<950?GridUnitType.Pixel:GridUnitType.Star);
        PreviewMetadata.Visibility=ActualHeight<600?Visibility.Collapsed:Visibility.Visible;
        ReviewStepper.Visibility=shortHeader?Visibility.Collapsed:Visibility.Visible;
        if(compact && WideDetailsHost.Content is not null){WideDetailsHost.Content=null;CompactDetailsHost.Content=DetailsView;}
        else if(!compact && CompactDetailsHost.Content is not null){CompactDetailsHost.Content=null;WideDetailsHost.Content=DetailsView;PreviewTabs.SelectedIndex=0;}
        CompactDetailsTab.Visibility=compact?Visibility.Visible:Visibility.Collapsed;
        DetailsColumn.Width=new GridLength(compact?0:282);ReviewDivider.Width=new GridLength(compact?0:8);
        DetailsBorder.Visibility=DetailsSplitter.Visibility=compact?Visibility.Collapsed:Visibility.Visible;
        ProcessingSidebar.Width=new GridLength(282);
    }
    internal void AssertProcessingFits()
    {
        UpdateLayout();
        foreach(var element in new FrameworkElement[]{ProcessingActions,ProcessingStagesView,ProcessingSystem})
        {
            var bounds=element.TransformToAncestor(ProcessingSurface).TransformBounds(new Rect(0,0,element.ActualWidth,element.ActualHeight));
            if(bounds.Bottom>ProcessingSurface.ActualHeight+1 || bounds.Top<0)throw new IOException($"Generation content exceeds fitted surface: {element.Name} / {bounds}");
        }
    }
    private void OnReviewSeek(object sender,MouseButtonEventArgs e){if(DataContext is MainViewModel vm)vm.Preview.Seek(vm.SeekSeconds);}
    private void OnFullscreen(object sender,RoutedEventArgs e){if(Window.GetWindow(this) is MainWindow window)window.OpenClipperFullscreen();}
    private void OnMoreActions(object sender,RoutedEventArgs e)
    {
        if(sender is not Button button || button.DataContext is not ReviewRow row || DataContext is not MainViewModel vm)return;
        var menu=new ContextMenu{PlacementTarget=button,Background=(System.Windows.Media.Brush)FindResource("Panel"),Foreground=(System.Windows.Media.Brush)FindResource("Ink")};
        menu.Items.Add(new MenuItem{Header="Copy clip title",Command=vm.CopyReviewTitleCommand,CommandParameter=row});
        menu.Items.Add(new MenuItem{Header="Copy generated hook",Command=vm.CopyReviewHookCommand,CommandParameter=row,IsEnabled=!string.IsNullOrWhiteSpace(row.Record.Hook)});
        menu.IsOpen=true;
    }
    private void OnSelectAll(object sender,RoutedEventArgs e){if(DataContext is MainViewModel vm){bool mark=vm.ReviewRows.Any(r=>r.Record.Ready && !r.Marked);foreach(var row in vm.ReviewRows.Where(r=>r.Record.Ready))row.Marked=mark;}}
}
