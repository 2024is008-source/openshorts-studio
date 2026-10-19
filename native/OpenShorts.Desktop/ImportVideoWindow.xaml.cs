using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
namespace OpenShorts.Desktop;
public partial class ImportVideoWindow : Window
{
    private readonly ImportVideoViewModel model;
    private Border? shade;
    private bool accepted;
    public ImportVideoWindow(ImportVideoViewModel model)
    {
        InitializeComponent();this.model=model;DataContext=model;
        Width=Math.Min(620,SystemParameters.WorkArea.Width-32);Height=Math.Min(640,SystemParameters.WorkArea.Height-32);
        model.Opened+=()=>{accepted=true;DialogResult=true;};
        Loaded+=(_,_)=>
        {
            if(Owner?.Content is Panel panel)
            {
                shade=new Border{Background=new SolidColorBrush(Color.FromArgb(130,0,5,12)),IsHitTestVisible=false};
                Grid.SetRowSpan(shade,20);Grid.SetColumnSpan(shade,20);Panel.SetZIndex(shade,int.MaxValue);panel.Children.Add(shade);
            }
        };
        Closing+=(_,e)=>
        {
            if(model.Busy && !accepted)
            {e.Cancel=true;if(MessageBox.Show(this,"Cancel the active import and remove its incomplete files?","Cancel import",MessageBoxButton.YesNo,MessageBoxImage.Question)==MessageBoxResult.Yes)model.CancelCommand.Execute(null);}
        };
        Closed+=(_,_)=>{if(shade?.Parent is Panel panel)panel.Children.Remove(shade);};
        PreviewKeyDown+=(_,e)=>{if(e.Key==Key.Escape){e.Handled=true;Close();}};
    }
    private void OnTitleDrag(object sender,MouseButtonEventArgs e){if(e.ChangedButton==MouseButton.Left && e.LeftButton==MouseButtonState.Pressed)DragMove();}
    private void OnClose(object sender,RoutedEventArgs e)=>Close();
    private void OnBrowseTab(object sender,RoutedEventArgs e)=>model.UrlTab=false;
    private void OnUrlTab(object sender,RoutedEventArgs e)=>model.UrlTab=true;
    private async void OnDrop(object sender,DragEventArgs e)
    {if(!model.Busy && e.Data.GetData(DataFormats.FileDrop) is string[] {Length:>0} files)await model.ImportLocalAsync(files[0]);}
}
