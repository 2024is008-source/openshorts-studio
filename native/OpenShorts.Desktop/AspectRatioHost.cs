using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Globalization;
namespace OpenShorts.Desktop;
public sealed class AspectRatioHost : Decorator
{
    public static readonly DependencyProperty RatioProperty=DependencyProperty.Register(nameof(Ratio),typeof(double),typeof(AspectRatioHost),new FrameworkPropertyMetadata(9d/16,FrameworkPropertyMetadataOptions.AffectsArrange));
    public static readonly DependencyProperty ZoomProperty=DependencyProperty.Register(nameof(Zoom),typeof(double),typeof(AspectRatioHost),new FrameworkPropertyMetadata(1d,FrameworkPropertyMetadataOptions.AffectsArrange));
    public double Ratio {get=>(double)GetValue(RatioProperty);set=>SetValue(RatioProperty,value);}
    public double Zoom {get=>(double)GetValue(ZoomProperty);set=>SetValue(ZoomProperty,value);}
    protected override Size MeasureOverride(Size available){Child?.Measure(available);return new Size(double.IsFinite(available.Width)?available.Width:200,double.IsFinite(available.Height)?available.Height:300);}
    protected override Size ArrangeOverride(Size size)
    {
        double ratio=double.IsFinite(Ratio)&&Ratio>0?Ratio:9d/16;
        double height=Math.Min(size.Height,size.Width/ratio)*Math.Clamp(Zoom,.5,2),width=height*ratio;
        Child?.Arrange(new Rect((size.Width-width)/2,(size.Height-height)/2,width,height));Clip=new RectangleGeometry(new Rect(size));return size;
    }
}
public sealed class PreviewGuides : FrameworkElement
{
    public static readonly DependencyProperty SafeZoneProperty=DependencyProperty.Register(nameof(SafeZone),typeof(bool),typeof(PreviewGuides),new FrameworkPropertyMetadata(true,FrameworkPropertyMetadataOptions.AffectsRender));
    public static readonly DependencyProperty CropProperty=DependencyProperty.Register(nameof(Crop),typeof(bool),typeof(PreviewGuides),new FrameworkPropertyMetadata(false,FrameworkPropertyMetadataOptions.AffectsRender));
    public bool SafeZone {get=>(bool)GetValue(SafeZoneProperty);set=>SetValue(SafeZoneProperty,value);}
    public bool Crop {get=>(bool)GetValue(CropProperty);set=>SetValue(CropProperty,value);}
    protected override void OnRender(DrawingContext dc)
    {
        if(ActualWidth<30 || ActualHeight<30)return;
        var pen=new Pen(new SolidColorBrush(Color.FromArgb(170,245,247,251)),1){DashStyle=DashStyles.Dash};
        if(SafeZone){dc.DrawRectangle(null,pen,new Rect(ActualWidth*.06,ActualHeight*.06,ActualWidth*.88,ActualHeight*.83));dc.DrawText(new FormattedText("Safe zone · guide",CultureInfo.CurrentCulture,FlowDirection.LeftToRight,new Typeface("Segoe UI"),10,Brushes.White,VisualTreeHelper.GetDpi(this).PixelsPerDip),new Point(12,12));}
        if(Crop)for(int i=1;i<=2;i++){dc.DrawLine(pen,new Point(ActualWidth*i/3,0),new Point(ActualWidth*i/3,ActualHeight));dc.DrawLine(pen,new Point(0,ActualHeight*i/3),new Point(ActualWidth,ActualHeight*i/3));}
    }
}
