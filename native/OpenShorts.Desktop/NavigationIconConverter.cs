using System.Globalization;
using System.Windows.Data;
namespace OpenShorts.Desktop;
public sealed class NavigationIconConverter : IValueConverter
{
    public object Convert(object value,Type targetType,object parameter,CultureInfo culture)=>(value as string) switch
    { "Home"=>"\uE80F","Projects"=>"\uE8B7","AI Clipper"=>"\uE8C6","Video Editor"=>"\uE714","Templates"=>"\uE80A","Creative Studio"=>"\uE790","Publish"=>"\uE898","Settings"=>"\uE713","Account"=>"\uE77B",_=>"\uE10C" };
    public object ConvertBack(object value,Type targetType,object parameter,CultureInfo culture)=>throw new NotSupportedException();
}
