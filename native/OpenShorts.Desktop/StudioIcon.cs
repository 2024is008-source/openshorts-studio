using System.Windows;
using System.Windows.Media;

namespace OpenShorts.Desktop;

/// <summary>Original, resolution-independent 24-unit outline icons. No font glyph dependencies.</summary>
public sealed class StudioIcon : FrameworkElement
{
    public static readonly DependencyProperty KindProperty=DependencyProperty.Register(nameof(Kind),typeof(string),typeof(StudioIcon),new FrameworkPropertyMetadata("Home",FrameworkPropertyMetadataOptions.AffectsRender));
    public static readonly DependencyProperty StrokeProperty=DependencyProperty.Register(nameof(Stroke),typeof(Brush),typeof(StudioIcon),new FrameworkPropertyMetadata(Brushes.White,FrameworkPropertyMetadataOptions.AffectsRender));
    public string Kind { get=>(string)GetValue(KindProperty);set=>SetValue(KindProperty,value); }
    public Brush Stroke { get=>(Brush)GetValue(StrokeProperty);set=>SetValue(StrokeProperty,value); }
    private static readonly Dictionary<string,Geometry> Shapes=new()
    {
        ["Home"]=Geometry.Parse("M3,10 L12,3 21,10 M5,9 L5,21 10,21 10,14 14,14 14,21 19,21 19,9"),
        ["Projects"]=Geometry.Parse("M5,2 L14,2 20,8 20,22 5,22 Z M14,2 L14,8 20,8"),
        ["AI Clipper"]=Geometry.Parse("M10,18 A3,3 0 1 1 4,18 A3,3 0 1 1 10,18 M20,18 A3,3 0 1 1 14,18 A3,3 0 1 1 20,18 M8.5,15.5 L17,3 M15.5,15.5 L7,3"),
        ["Video Editor"]=Geometry.Parse("M3,8 L21,8 21,21 3,21 Z M3,8 L2,4 20,1 21,5 Z M7,3 L10,7 M13,2 L16,6 M10,12 L16,15 10,18 Z"),
        ["Templates"]=Geometry.Parse("M3,3 L10,3 10,10 3,10 Z M14,3 L21,3 21,10 14,10 Z M3,14 L10,14 10,21 3,21 Z M14,14 L21,14 21,21 14,21 Z"),
        ["Creative Studio"]=Geometry.Parse("M12,3 C5,3 2,7 3,13 C4,20 10,22 13,20 C16,18 12,16 15,15 C21,15 23,11 20,7 C18,4 15,3 12,3 M7,9 L7.1,9 M12,7 L12.1,7 M17,9 L17.1,9"),
        ["Publish"]=Geometry.Parse("M4,14 L4,21 20,21 20,14 M12,3 L12,16 M7,8 L12,3 17,8"),
        ["Settings"]=Geometry.Parse("M9,3 L15,3 16,6 19,7 22,10 20,13 20,16 17,19 14,19 12,22 9,20 6,20 3,17 4,14 2,11 4,8 7,7 Z M16,12 A4,4 0 1 1 8,12 A4,4 0 1 1 16,12"),
        ["Account"]=Geometry.Parse("M16,7 A4,4 0 1 1 8,7 A4,4 0 1 1 16,7 M4,21 C4,12 20,12 20,21"),
        ["Help"]=Geometry.Parse("M22,12 A10,10 0 1 1 2,12 A10,10 0 1 1 22,12 M9,8 C9,4 17,6 14,10 L12,12 12,14 M12,18 L12.1,18"),
        ["Import"]=Geometry.Parse("M4,15 L4,21 20,21 20,15 M12,17 L12,3 M6,9 L12,3 18,9"),
        ["Play"]=Geometry.Parse("M9,5 L19,12 9,19 Z"),
        ["PlayCircle"]=Geometry.Parse("M22,12 A10,10 0 1 1 2,12 A10,10 0 1 1 22,12 M10,7 L17,12 10,17 Z"),
        ["Brain"]=Geometry.Parse("M12,4 C9,0 5,3 5,6 C1,6 1,12 4,13 C1,18 5,22 9,20 C10,22 12,20 12,17 Z M12,4 C15,0 19,3 19,6 C23,6 23,12 20,13 C23,18 19,22 15,20 C14,22 12,20 12,17 M7,7 L7,11 10,13 M17,7 L17,11 14,13 M5,15 L8,16 M19,15 L16,16"),
        ["Link"]=Geometry.Parse("M10,14 L14,10 M8,15 L6,17 C1,22 -2,15 3,11 L7,7 C10,4 14,6 14,9 M10,15 C10,18 14,20 17,17 L21,13 C26,8 19,2 15,6 L13,8"),
        ["Copy"]=Geometry.Parse("M8,7 L20,7 20,22 8,22 Z M4,17 L4,3 15,3 15,7"),
        ["Info"]=Geometry.Parse("M22,12 A10,10 0 1 1 2,12 A10,10 0 1 1 22,12 M12,11 L12,17 M12,7 L12.1,7"),
        ["Chevron"]=Geometry.Parse("M9,5 L16,12 9,19"),
        ["Disk"]=Geometry.Parse("M5,4 L19,4 22,18 2,18 Z M2,18 L2,21 22,21 22,18 M17,18 L18,18"),
        ["Gpu"]=Geometry.Parse("M3,6 L21,6 21,18 3,18 Z M9,9 L16,9 16,15 9,15 Z M6,9 L6,15 M6,21 L15,21 M18,18 L18,21"),
        ["Search"]=Geometry.Parse("M17,10 A7,7 0 1 1 3,10 A7,7 0 1 1 17,10 M15,15 L22,22"),
        ["Plus"]=Geometry.Parse("M12,4 L12,20 M4,12 L20,12"),
        ["Arrow"]=Geometry.Parse("M3,12 L21,12 M14,5 L21,12 14,19"),
        ["Folder"]=Geometry.Parse("M3,6 L10,6 12,9 21,9 21,20 3,20 Z"),
        ["More"]=Geometry.Parse("M5,12 L5.1,12 M12,12 L12.1,12 M19,12 L19.1,12"),
        ["YouTube"]=Geometry.Parse("M3,6 Q12,4 21,6 L21,18 Q12,20 3,18 Z M10,9 L15,12 10,15 Z"),
        ["TikTok"]=Geometry.Parse("M14,3 L14,16 C14,23 3,23 5,16 C6,13 10,14 10,14 M14,3 C15,8 18,9 21,9"),
        ["Instagram"]=Geometry.Parse("M7,3 L17,3 Q21,3 21,7 L21,17 Q21,21 17,21 L7,21 Q3,21 3,17 L3,7 Q3,3 7,3 M17,12 A5,5 0 1 1 7,12 A5,5 0 1 1 17,12 M17,7 L17.1,7"),
        ["Check"]=Geometry.Parse("M5,12 L10,17 20,6"),
        ["Bell"]=Geometry.Parse("M5,17 L7,14 7,8 C7,1 17,1 17,8 L17,14 19,17 Z M10,21 L14,21"),
        ["Sparkles"]=Geometry.Parse("M12,3 L14,9 20,11 14,13 12,19 10,13 4,11 10,9 Z M20,2 L20,6 M18,4 L22,4"),
        ["Portrait"]=Geometry.Parse("M7,2 L17,2 17,22 7,22 Z"),
        ["Square"]=Geometry.Parse("M4,4 L20,4 20,20 4,20 Z"),
        ["Landscape"]=Geometry.Parse("M2,6 L22,6 22,18 2,18 Z"),
        ["Audio"]=Geometry.Parse("M4,10 L4,14 8,14 13,19 13,5 8,10 Z M17,8 C21,10 21,14 17,16"),
        ["Close"]=Geometry.Parse("M6,6 L18,18 M18,6 L6,18"),
        ["Minimize"]=Geometry.Parse("M5,12 L19,12"),
        ["Maximize"]=Geometry.Parse("M5,5 L19,5 19,19 5,19 Z")
    };
    protected override Size MeasureOverride(Size availableSize)=>new(double.IsNaN(Width)?20:Width,double.IsNaN(Height)?20:Height);
    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);double scale=Math.Min(ActualWidth,ActualHeight)/24;
        dc.PushTransform(new TranslateTransform((ActualWidth-24*scale)/2,(ActualHeight-24*scale)/2));dc.PushTransform(new ScaleTransform(scale,scale));
        var pen=new Pen(Stroke,1.65){StartLineCap=PenLineCap.Round,EndLineCap=PenLineCap.Round,LineJoin=PenLineJoin.Round};
        dc.DrawGeometry(null,pen,Shapes.GetValueOrDefault(Kind??"Home",Shapes["Templates"]));dc.Pop();dc.Pop();
    }
}
