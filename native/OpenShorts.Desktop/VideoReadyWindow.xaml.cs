using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
namespace OpenShorts.Desktop;
public partial class VideoReadyWindow : Window
{
    private readonly VideoReadyViewModel model;
    private Border? shade;
    private bool accepted;
    private readonly HashSet<ValidationError> inputErrors=[];
    public bool ChangeVideoRequested {get;private set;}
    public VideoReadyWindow(VideoReadyViewModel model)
    {
        InitializeComponent();this.model=model;DataContext=model;
        Width=Math.Min(1100,SystemParameters.WorkArea.Width-40);Height=Math.Min(700,SystemParameters.WorkArea.Height-40);
        model.Accepted+=()=>{accepted=true;DialogResult=true;};
        model.ChangeRequested+=()=>{ChangeVideoRequested=true;DialogResult=false;};
        Validation.AddErrorHandler(this,(_,e)=>{if(e.Action==ValidationErrorEventAction.Added)inputErrors.Add(e.Error);else inputErrors.Remove(e.Error);model.SetInputInvalid(inputErrors.Count>0);});
        Loaded+=async (_,_)=>
        {
            if(Owner?.Content is Panel panel){shade=new Border{Background=new SolidColorBrush(Color.FromArgb(140,0,4,10)),IsHitTestVisible=false};Grid.SetRowSpan(shade,20);Grid.SetColumnSpan(shade,20);Panel.SetZIndex(shade,int.MaxValue);panel.Children.Add(shade);}
            await model.LoadAsync();
        };
        Closing+=(_,e)=>{if(model.Busy && !accepted)e.Cancel=true;};
        Closed+=(_,_)=>{if(shade?.Parent is Panel p)p.Children.Remove(shade);model.Dispose();};
        PreviewKeyDown+=(_,e)=>{if(e.Key==Key.Escape){e.Handled=true;Close();}};
    }
    private void OnClose(object sender,RoutedEventArgs e)=>Close();
    private void OnDrag(object sender,MouseButtonEventArgs e){if(e.LeftButton==MouseButtonState.Pressed)DragMove();}
}
