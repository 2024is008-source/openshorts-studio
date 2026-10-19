using System.Windows;
using System.Windows.Input;
using System.Windows.Threading;
namespace OpenShorts.Desktop;
public partial class MainWindow : Window
{
    private readonly MainViewModel model;
    private readonly DispatcherTimer timer = new() { Interval=TimeSpan.FromMilliseconds(200) };
    private int validationErrors;
    private bool closePrepared;
    public MainWindow(MainViewModel model)
    {
        App.StartupStage("Loading native window XAML");
        InitializeComponent();WindowWorkArea.Attach(this);App.StartupStage("Binding native window");this.model=model;DataContext=model;
        App.StartupStage("Native window bindings loaded");
        model.PropertyChanged+=(_,e)=>
        {
            if(e.PropertyName is nameof(MainViewModel.AssetsVisible) or nameof(MainViewModel.InspectorVisible))UpdateEditorLayout();
            if(e.PropertyName is not (nameof(MainViewModel.Route) or nameof(MainViewModel.ClipperMode)))return;
            if(model.IsHome)Dispatcher.BeginInvoke(()=>HomeDashboard.ScrollToTop());
            MovePlayerHost();
        };
        timer.Tick+=(_,_)=> { model.SyncPlayback(); model.DurationSeconds=Math.Max(0,model.Preview.Player.Length/1000d); if(!ClipperWorkspace.IsSeeking && !Playhead.IsMouseCaptureWithin && !Playhead.IsKeyboardFocusWithin && !SeekBox.IsKeyboardFocusWithin) model.SeekSeconds=Math.Max(0,model.Preview.Player.Time/1000d);model.UpdateStudioPlayback();model.UpdateReviewPlayback(); };
        PreviewKeyDown+=OnEditorKey;
        Loaded+=(_,_)=>{UpdateEditorLayout();timer.Start();};SizeChanged+=(_,_)=>UpdateEditorLayout();
        Closing+=async (_,e)=>
        {
            if(!closePrepared && model.HasEditor && !model.Busy)
            {e.Cancel=true;if(await model.PersistWorkspaceAsync()){closePrepared=true;_ = Dispatcher.BeginInvoke(Close);}return;}
            if(model.Busy && MessageBox.Show(this,"Closing stops active processing. Saved project files will be kept.","Close OpenShorts?",MessageBoxButton.YesNo,MessageBoxImage.Question)!=MessageBoxResult.Yes)e.Cancel=true;
        };
        Closed+=(_,_)=>{timer.Stop();model.StopPending();};
    }
    private void MovePlayerHost()
    {
        var desired=model.IsClipper?ClipperWorkspace.PlayerHost:EditorPreviewHost;
        if(VideoView.Parent is System.Windows.Controls.ContentControl current && current!=desired)
        {current.Content=null;desired.Content=VideoView;}
        if(!model.IsEditor && !model.IsClipper){model.Preview.Player.SetPause(true);model.PauseReviewRequests();}
        if(VideoView.Content is UIElement overlay)overlay.Visibility=model.IsEditor?Visibility.Visible:Visibility.Collapsed;
        if(!model.IsCreative)model.PauseCreativePlayback();
    }
    private void OnOpenQuickTour(object sender,RoutedEventArgs e)=>HomeDashboard.ShowQuickTour();
    private void OnEditorKey(object sender,KeyEventArgs e)
    {
        if(Keyboard.Modifiers==ModifierKeys.Control && e.Key==Key.K){model.Route="Home";HomeSearchBox.Focus();HomeSearchBox.SelectAll();e.Handled=true;return;}
        if(Keyboard.FocusedElement is System.Windows.Controls.Primitives.TextBoxBase or System.Windows.Controls.PasswordBox or System.Windows.Controls.ComboBox)return;
        System.Windows.Input.ICommand? command=null;
        if(Keyboard.Modifiers==ModifierKeys.Control)command=e.Key switch {Key.O=>model.IsEditor?model.ImportEditorMediaCommand:model.ImportCommand,Key.E=>model.ExportCommand,Key.S when model.IsEditor=>model.SaveEditorCommand,Key.Z when model.IsEditor=>model.UndoEditCommand,Key.Y when model.IsEditor=>model.RedoEditCommand,Key.B when model.IsEditor=>model.SplitSegmentCommand,_=>null};
        else if(model.IsEditor && Keyboard.Modifiers==ModifierKeys.None)command=e.Key switch {Key.Space=>model.PlayPauseCommand,Key.Delete=>model.RemoveSegmentCommand,_=>null};
        if(command?.CanExecute(null)==true){command.Execute(null);e.Handled=true;}
    }
    private async void OnDrop(object sender, DragEventArgs e)
    { if(!model.Busy && e.Data.GetData(DataFormats.FileDrop) is string[] { Length:>0 } files){if(model.IsEditor && model.HasEditor)await model.ImportEditorMediaAsync(files[0]);else model.OpenImportDialog(files[0]);} }
    private void UpdateEditorLayout()
    {
        AssetsColumn.Width=new GridLength(model.AssetsVisible?Math.Min(model.AssetsPanelWidth,ActualWidth<1400?260:600):0);
        InspectorColumn.Width=new GridLength(model.InspectorVisible?Math.Min(model.InspectorPanelWidth,ActualWidth<1400?280:600):0);
        PreviewRow.MinHeight=ActualHeight<700?150:245;
        TimelineRow.MinHeight=ActualHeight<700?170:280;
        TimelineRow.Height=new GridLength(Math.Min(model.EditorTimelineHeight,Math.Max(TimelineRow.MinHeight,ActualHeight-360)));
        AssetsDividerColumn.Width=new GridLength(model.AssetsVisible?8:0);InspectorDividerColumn.Width=new GridLength(model.InspectorVisible?8:0);
    }
    private void OnEditorLayoutDragCompleted(object sender,System.Windows.Controls.Primitives.DragCompletedEventArgs e)
    {
        if(!model.IsEditor)return;
        if(model.AssetsVisible)model.AssetsPanelWidth=Math.Clamp(AssetsColumn.ActualWidth,200,800);
        if(model.InspectorVisible)model.InspectorPanelWidth=Math.Clamp(InspectorColumn.ActualWidth,200,800);
        model.EditorTimelineHeight=Math.Clamp(TimelineRow.ActualHeight,280,800);
    }
    internal void OpenClipperFullscreen()=>OnFullscreenPreview(this,new RoutedEventArgs());
    private void OnFullscreenPreview(object sender,RoutedEventArgs e)
    {
        double originalPosition=Math.Max(0,model.Preview.Player.Time/1000d);bool originalPlaying=model.Preview.Player.IsPlaying;
        VideoView.Visibility=Visibility.Collapsed;VideoView.MediaPlayer=null;
        var overlay=new PreviewOverlayControl{DataContext=model};
        var fullscreenView=new LibVLCSharp.WPF.VideoView{DataContext=model,Content=model.IsEditor?overlay:null,MediaPlayer=model.Preview.Player};
        var host=new AspectRatioHost{Ratio=model.IsEditor?model.PreviewAspect:model.SourceAspect,Child=fullscreenView};
        var fullscreen=new Window{Owner=this,DataContext=model,WindowStyle=WindowStyle.None,WindowState=WindowState.Maximized,Background=System.Windows.Media.Brushes.Black,Content=host,Title="Preview · Esc to return"};
        fullscreen.Loaded+=(_,_)=>model.RestorePreviewAfterSurfaceChange(originalPosition,originalPlaying);
        fullscreen.PreviewKeyDown+=(_,key)=>{if(key.Key==Key.Escape){key.Handled=true;fullscreen.Close();}else if(key.Key==Key.Space){model.PlayPauseCommand.Execute(null);key.Handled=true;}};
        fullscreen.Closed+=(_,_)=>
        {
            double lastPosition=Math.Max(0,model.Preview.Player.Time/1000d);bool lastPlaying=model.Preview.Player.IsPlaying;
            fullscreenView.Content=null;fullscreenView.MediaPlayer=null;fullscreenView.Dispose();
            if(IsLoaded){VideoView.Visibility=Visibility.Visible;System.Windows.Data.BindingOperations.SetBinding(VideoView,LibVLCSharp.WPF.VideoView.MediaPlayerProperty,new System.Windows.Data.Binding("Preview.Player"){Source=model});model.RestorePreviewAfterSurfaceChange(lastPosition,lastPlaying);}
        };
        fullscreen.Show();
    }
    private void OnSeek(object sender,MouseButtonEventArgs e) => model.Preview.Seek(model.SeekSeconds);
    private void OnMinimize(object sender,RoutedEventArgs e)=>SystemCommands.MinimizeWindow(this);
    private void OnMaximize(object sender,RoutedEventArgs e)
    { if(WindowState==WindowState.Maximized)SystemCommands.RestoreWindow(this);else SystemCommands.MaximizeWindow(this); }
    private void OnClose(object sender,RoutedEventArgs e)=>Close();
    private void OnSearchKey(object sender,KeyEventArgs e)
    { if(e.Key==Key.Escape){model.HomeSearch="";e.Handled=true;}else if(e.Key==Key.Enter && model.HomeSearchResults.Count>0 && model.OpenHomeSearchCommand.CanExecute(model.HomeSearchResults[0])){model.OpenHomeSearchCommand.Execute(model.HomeSearchResults[0]);e.Handled=true;} }
    private void OnTimelineSeek(object? sender,double seconds)=>model.SeekTimeline(seconds);
    private void OnValidationError(object sender,System.Windows.Controls.ValidationErrorEventArgs e)
    { validationErrors=Math.Max(0,validationErrors+(e.Action==System.Windows.Controls.ValidationErrorEventAction.Added?1:-1));model.HasInputError=validationErrors>0; }
    private void OnElevenLabsChanged(object sender,RoutedEventArgs e)=>model.PendingElevenLabs=((System.Windows.Controls.PasswordBox)sender).Password;
    private void OnFalChanged(object sender,RoutedEventArgs e)=>model.PendingFal=((System.Windows.Controls.PasswordBox)sender).Password;
    private void OnUploadPostChanged(object sender,RoutedEventArgs e)=>model.PendingUploadPost=((System.Windows.Controls.PasswordBox)sender).Password;
    private void OnPasswordChanged(object sender,RoutedEventArgs e) { if(DataContext is MainViewModel vm) vm.PendingCredential=GeminiPassword.Password; }
}
