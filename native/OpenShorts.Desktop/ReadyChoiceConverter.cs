using System.Globalization;
using System.Windows;
using System.Windows.Data;
namespace OpenShorts.Desktop;
public sealed class ReadyChoiceConverter : IValueConverter
{
 public object Convert(object value,Type target,object parameter,CultureInfo culture)=>Equals(value?.ToString(),parameter?.ToString());
 public object ConvertBack(object value,Type target,object parameter,CultureInfo culture)=>(value is true)?parameter.ToString()!:Binding.DoNothing;
}
