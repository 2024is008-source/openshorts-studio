using System.Globalization;
using System.Windows;
using System.Windows.Media;
using System.Xml.Linq;
namespace OpenShorts.Desktop;
/// <summary>Bundled upstream Lucide SVGs, rendered as native WPF vectors. See Assets/Lucide/LICENSE.txt.</summary>
public sealed class LucideIcon : FrameworkElement
{
 public static readonly DependencyProperty KindProperty=DependencyProperty.Register(nameof(Kind),typeof(string),typeof(LucideIcon),new FrameworkPropertyMetadata("sparkles",FrameworkPropertyMetadataOptions.AffectsRender));
 public static readonly DependencyProperty StrokeProperty=DependencyProperty.Register(nameof(Stroke),typeof(Brush),typeof(LucideIcon),new FrameworkPropertyMetadata(Brushes.White,FrameworkPropertyMetadataOptions.AffectsRender));
 public string Kind {get=>(string)GetValue(KindProperty);set=>SetValue(KindProperty,value);}
 public Brush Stroke {get=>(Brush)GetValue(StrokeProperty);set=>SetValue(StrokeProperty,value);}
 private static readonly Dictionary<string,Geometry> Cache=[];
 internal static readonly HashSet<string> Failures=[];
 private static readonly Dictionary<string,string> Aliases=new(){["Import"]="upload",["Play"]="play",["Pause"]="pause",["Brain"]="brain",["Check"]="check",["Copy"]="copy",["Close"]="x",["More"]="ellipsis-vertical",["Audio"]="volume-2",["Maximize"]="maximize",["Video Editor"]="clapperboard",["AI Clipper"]="scissors",["Folder"]="folder-open",["Templates"]="layout-grid",["Home"]="house",["Projects"]="file",["Creative Studio"]="palette",["Publish"]="upload",["Settings"]="settings",["Account"]="user-round",["Help"]="circle-question-mark",["Search"]="search",["Plus"]="plus",["Bell"]="bell",["Minimize"]="minus",["Clock"]="clock",["Captions"]="captions"};
 private static Geometry Shape(string key)
 {
  key=Aliases.GetValueOrDefault(key,key);
  if(Cache.TryGetValue(key,out var cached))return cached;
  var group=new GeometryGroup();
  try
  {
   using var stream=Application.GetResourceStream(new Uri($"/OpenShorts.Desktop;component/Assets/Lucide/{key}.svg",UriKind.Relative))!.Stream;
   var document=XDocument.Load(stream);
   foreach(var e in document.Root!.Elements())
   {
    double N(string n)=>double.Parse(e.Attribute(n)?.Value ?? "0",CultureInfo.InvariantCulture);
    Geometry? shape=e.Name.LocalName switch {
     "path"=>Geometry.Parse(e.Attribute("d")!.Value),
     "circle"=>new EllipseGeometry(new Point(N("cx"),N("cy")),N("r"),N("r")),
     "ellipse"=>new EllipseGeometry(new Point(N("cx"),N("cy")),N("rx"),N("ry")),
     "rect"=>new RectangleGeometry(new Rect(N("x"),N("y"),N("width"),N("height")),N("rx"),N("rx")),
     "line"=>new LineGeometry(new Point(N("x1"),N("y1")),new Point(N("x2"),N("y2"))),
     "polyline" or "polygon"=>Geometry.Parse("M"+e.Attribute("points")!.Value+(e.Name.LocalName=="polygon"?" Z":"")),_=>null};
    if(shape is not null)group.Children.Add(shape);
   }
  }
  catch(Exception e) when(e is IOException or FormatException or NullReferenceException){Failures.Add(key);group.Children.Add(new EllipseGeometry(new Point(12,12),8,8));}
  group.Freeze();Cache[key]=group;return group;
 }
 protected override Size MeasureOverride(Size available)=>new(double.IsNaN(Width)?18:Width,double.IsNaN(Height)?18:Height);
 protected override void OnRender(DrawingContext dc)
 {
  double scale=Math.Min(ActualWidth,ActualHeight)/24;dc.PushTransform(new TranslateTransform((ActualWidth-24*scale)/2,(ActualHeight-24*scale)/2));dc.PushTransform(new ScaleTransform(scale,scale));
  dc.DrawGeometry(null,new Pen(Stroke,1.75){StartLineCap=PenLineCap.Round,EndLineCap=PenLineCap.Round,LineJoin=PenLineJoin.Round},Shape(Kind));dc.Pop();dc.Pop();
 }
}
