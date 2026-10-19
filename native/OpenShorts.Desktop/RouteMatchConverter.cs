using System.Globalization;
using System.Windows.Data;
namespace OpenShorts.Desktop;
public sealed class RouteMatchConverter : IMultiValueConverter
{
    public object Convert(object[] values,Type targetType,object parameter,CultureInfo culture)=>values.Length==2 && values[0] is string item && values[1] is string route && item==route;
    public object[] ConvertBack(object value,Type[] targetTypes,object parameter,CultureInfo culture)=>throw new NotSupportedException();
}
