using System.Windows;
using System.Windows.Media;

namespace OpenShorts.Desktop;

// Native gradients keep the banner sharp at every window size and display scale.
public sealed class HeroBackdrop : FrameworkElement
{
    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);
        if(ActualWidth<=0 || ActualHeight<=0)return;
        dc.PushClip(new RectangleGeometry(new Rect(0,0,ActualWidth,ActualHeight),10,10));
        dc.PushTransform(new ScaleTransform(ActualWidth,ActualHeight));
        var area=new Rect(0,0,1,1);
        var background=new LinearGradientBrush{StartPoint=new Point(0,0),EndPoint=new Point(1,1)};
        background.GradientStops.Add(new(Color.FromRgb(18,21,43),0));
        background.GradientStops.Add(new(Color.FromRgb(6,21,35),.48));
        background.GradientStops.Add(new(Color.FromRgb(4,23,35),1));
        dc.DrawRectangle(background,null,area);
        var glow=new RadialGradientBrush{Center=new Point(.73,-.1),GradientOrigin=new Point(.73,-.1),RadiusX=.59,RadiusY=1.45};
        glow.GradientStops.Add(new(Color.FromArgb(80,0,126,158),0));
        glow.GradientStops.Add(new(Color.FromArgb(24,0,110,147),.52));
        glow.GradientStops.Add(new(Color.FromArgb(0,0,110,147),1));
        dc.DrawRectangle(glow,null,area);
        Beam(dc,"M.24,1 L.54,0 .74,0 .44,1 Z",.54,.20,Color.FromArgb(36,0,137,166));
        Beam(dc,"M.49,1 L.79,0 .96,0 .66,1 Z",.79,.17,Color.FromArgb(30,0,143,167));
        Beam(dc,"M.71,1 L1.01,0 1.17,0 .87,1 Z",1.01,.16,Color.FromArgb(15,0,125,156));
        var shade=new LinearGradientBrush{StartPoint=new Point(0,0),EndPoint=new Point(0,1)};
        shade.GradientStops.Add(new(Color.FromArgb(0,0,5,14),.1));shade.GradientStops.Add(new(Color.FromArgb(95,0,5,14),1));
        dc.DrawRectangle(shade,null,area);dc.Pop();dc.Pop();
    }
    private static void Beam(DrawingContext dc,string path,double left,double width,Color color)
    {
        var brush=new LinearGradientBrush{MappingMode=BrushMappingMode.Absolute,StartPoint=new Point(left,0),EndPoint=new Point(left+width/1.09,width*.3/1.09)};
        var clear=Color.FromArgb(0,color.R,color.G,color.B);
        brush.GradientStops.Add(new(clear,0));brush.GradientStops.Add(new(color,.48));brush.GradientStops.Add(new(clear,1));
        dc.DrawGeometry(brush,null,Geometry.Parse(path));
    }
}
