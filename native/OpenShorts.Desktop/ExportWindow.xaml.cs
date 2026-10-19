using System.Windows;
namespace OpenShorts.Desktop;
public partial class ExportWindow : Window
{
    public ExportWindow(MainViewModel model){InitializeComponent();DataContext=model;Closing+=(_,e)=>{if(model.Busy)e.Cancel=true;};}
}
