using System.Globalization;
using System.Windows.Data;
using System.Windows.Media.Imaging;
namespace OpenShorts.Desktop;
public sealed class MediaThumbnailConverter : IValueConverter
{
    public object? Convert(object value,Type targetType,object parameter,CultureInfo culture)
    {
        if(value is not string path || !Path.IsPathFullyQualified(path) || !File.Exists(path))return null;
        try { var image=new BitmapImage();image.BeginInit();image.CacheOption=BitmapCacheOption.OnLoad;image.DecodePixelWidth=parameter is string requested && int.TryParse(requested,out int width)?Math.Clamp(width,100,1600):220;image.UriSource=new Uri(path);image.EndInit();image.Freeze();return image; }
        catch(Exception e) when(e is IOException or NotSupportedException or ArgumentException){return null;}
    }
    public object ConvertBack(object value,Type targetType,object parameter,CultureInfo culture)=>throw new NotSupportedException();
}
