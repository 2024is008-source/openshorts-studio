using System.Windows.Controls;
namespace OpenShorts.Desktop;
public partial class EditorTimelinePanel : UserControl
{
    public EditorTimelinePanel()=>InitializeComponent();
    private void OnSeek(object? sender,double seconds){if(DataContext is MainViewModel model)model.SeekTimeline(seconds);}
}
