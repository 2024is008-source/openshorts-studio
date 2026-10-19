using System.Collections;
using System.Collections.Specialized;
using System.ComponentModel;
using System.Globalization;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
namespace OpenShorts.Desktop;
/// <summary>Native multitrack overview; bars map source intervals to assembled time.</summary>
public sealed class TimelineSurface : FrameworkElement
{
    public static readonly DependencyProperty SegmentsProperty=DependencyProperty.Register(nameof(Segments),typeof(IEnumerable),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender,ItemsChanged));
    public static readonly DependencyProperty CaptionsProperty=DependencyProperty.Register(nameof(Captions),typeof(IEnumerable),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender,ItemsChanged));
    public static readonly DependencyProperty EffectsProperty=DependencyProperty.Register(nameof(Effects),typeof(IEnumerable),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender,ItemsChanged));
    public IEnumerable? Effects {get=>(IEnumerable?)GetValue(EffectsProperty);set=>SetValue(EffectsProperty,value);}
    public static readonly DependencyProperty PlayheadProperty=DependencyProperty.Register(nameof(Playhead),typeof(double),typeof(TimelineSurface),new FrameworkPropertyMetadata(0d,FrameworkPropertyMetadataOptions.AffectsRender));
    public IEnumerable? Segments { get=>(IEnumerable?)GetValue(SegmentsProperty);set=>SetValue(SegmentsProperty,value); }
    public IEnumerable? Captions { get=>(IEnumerable?)GetValue(CaptionsProperty);set=>SetValue(CaptionsProperty,value); }
    public double Playhead { get=>(double)GetValue(PlayheadProperty);set=>SetValue(PlayheadProperty,value); }
    public static readonly DependencyProperty ZoomProperty=DependencyProperty.Register(nameof(Zoom),typeof(double),typeof(TimelineSurface),new FrameworkPropertyMetadata(1d,FrameworkPropertyMetadataOptions.AffectsRender));
    public static readonly DependencyProperty SelectedSegmentProperty=DependencyProperty.Register(nameof(SelectedSegment),typeof(SegmentRow),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender|FrameworkPropertyMetadataOptions.BindsTwoWayByDefault));
    public static readonly DependencyProperty WaveformProperty=DependencyProperty.Register(nameof(Waveform),typeof(double[]),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender));
    public static readonly DependencyProperty SceneBoundariesProperty=DependencyProperty.Register(nameof(SceneBoundaries),typeof(double[]),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender));
    public double Zoom { get=>(double)GetValue(ZoomProperty);set=>SetValue(ZoomProperty,value); }
    public SegmentRow? SelectedSegment { get=>(SegmentRow?)GetValue(SelectedSegmentProperty);set=>SetValue(SelectedSegmentProperty,value); }
    public double[]? Waveform { get=>(double[]?)GetValue(WaveformProperty);set=>SetValue(WaveformProperty,value); }
    public double[]? SceneBoundaries { get=>(double[]?)GetValue(SceneBoundariesProperty);set=>SetValue(SceneBoundariesProperty,value); }
    public event EventHandler<double>? SeekRequested;
    public static readonly DependencyProperty FramesProperty=DependencyProperty.Register(nameof(Frames),typeof(IEnumerable),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender,ItemsChanged));
    public IEnumerable? Frames {get=>(IEnumerable?)GetValue(FramesProperty);set=>SetValue(FramesProperty,value);}
    public static readonly DependencyProperty SelectedCaptionProperty=DependencyProperty.Register(nameof(SelectedCaption),typeof(CaptionRow),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender|FrameworkPropertyMetadataOptions.BindsTwoWayByDefault));
    public static readonly DependencyProperty PanFractionProperty=DependencyProperty.Register(nameof(PanFraction),typeof(double),typeof(TimelineSurface),new FrameworkPropertyMetadata(0d,FrameworkPropertyMetadataOptions.AffectsRender,(d,e)=>{var t=(TimelineSurface)d;t.pan=Math.Clamp((double)e.NewValue,0,1)*Math.Max(0,t.Total-t.Span);}));
    public static readonly DependencyProperty SourceThumbnailProperty=DependencyProperty.Register(nameof(SourceThumbnail),typeof(ImageSource),typeof(TimelineSurface),new FrameworkPropertyMetadata(null,FrameworkPropertyMetadataOptions.AffectsRender));
    public CaptionRow? SelectedCaption {get=>(CaptionRow?)GetValue(SelectedCaptionProperty);set=>SetValue(SelectedCaptionProperty,value);}
    public double PanFraction {get=>(double)GetValue(PanFractionProperty);set=>SetValue(PanFractionProperty,value);}
    public ImageSource? SourceThumbnail {get=>(ImageSource?)GetValue(SourceThumbnailProperty);set=>SetValue(SourceThumbnailProperty,value);}
    private CaptionRow? dragCaption;
    private bool captionLeft,captionRight;
    private double captionStart,captionEnd,lastCaptionDelta;
    private double pan, dragX, dragTime, dragOffset, dragScale;
    private SegmentRow? dragging;
    private bool trimStart, trimming;
    private double Total=>Rows.Sum(s=>s.End-s.Start);
    private double Span=>Math.Max(.5,Total/Math.Max(1,Zoom));
    private double ViewWidth=>Math.Max(1,ActualWidth-122);
    private double X(double time)=>110+(time-pan)*ViewWidth/Span;
    private double Time(double x)=>pan+(x-110)/ViewWidth*Span;
    private void ClampPan()=>pan=Math.Clamp(pan,0,Math.Max(0,Total-Span));
    private readonly HashSet<INotifyPropertyChanged> observed=[];
    private static void ItemsChanged(DependencyObject target,DependencyPropertyChangedEventArgs e)
    {
        var surface=(TimelineSurface)target;
        if(e.OldValue is INotifyCollectionChanged old)old.CollectionChanged-=surface.Changed;
        if(e.NewValue is INotifyCollectionChanged next)next.CollectionChanged+=surface.Changed;
        surface.Observe();
    }
    private void Changed(object? sender,NotifyCollectionChangedEventArgs e)=>Observe();
    private void RowChanged(object? sender,PropertyChangedEventArgs e){cachedRows=null;InvalidateVisual();}
    private void Observe()
    {
        foreach(var row in observed)row.PropertyChanged-=RowChanged;observed.Clear();
        foreach(var item in (Segments?.Cast<object>() ?? []).Concat(Captions?.Cast<object>() ?? []).Concat(Effects?.Cast<object>() ?? []))
            if(item is INotifyPropertyChanged row && observed.Add(row))row.PropertyChanged+=RowChanged;
        cachedRows=null;InvalidateVisual();
    }
    private SegmentRow[]? cachedRows;
    private SegmentRow[] Rows => cachedRows ??= Segments?.Cast<SegmentRow>().Where(s=>double.IsFinite(s.Start)&&double.IsFinite(s.End)&&s.End>s.Start).ToArray() ?? [];
    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);dc.DrawRectangle(new SolidColorBrush(Color.FromRgb(16,23,34)),null,new Rect(RenderSize));
        var rows=Rows;double total=Total;ClampPan();
        void Text(string text,double x,double y,Color color) => dc.DrawText(new FormattedText(text,CultureInfo.CurrentCulture,FlowDirection.LeftToRight,new Typeface("Segoe UI"),10,new SolidColorBrush(color),VisualTreeHelper.GetDpi(this).PixelsPerDip),new Point(x,y));
        var muted=Color.FromRgb(148,163,184);var line=new Pen(new SolidColorBrush(Color.FromRgb(41,55,71)),1);
        foreach(var item in new[]{("TIME",8d),("Video",52d),("Captions",90d),("Original audio",124d),("Music",145d),("Effects",171d)})Text(item.Item1,10,item.Item2,muted);
        foreach(double y in new[]{24d,43,83,116,141,165,190})dc.DrawLine(line,new Point(0,y),new Point(ActualWidth,y));
        dc.DrawLine(line,new Point(110,0),new Point(110,ActualHeight));
        if(total<=0){Text("Open a clip to see its source ranges",122,52,muted);return;}
        for(int tick=0;tick<=10;tick++){double t=pan+Span*tick/10;Text(Span<10?$"{t:0.0}s":TimeSpan.FromSeconds(t).ToString(@"mm\:ss"),X(t),7,muted);dc.DrawLine(line,new Point(X(t),20),new Point(X(t),24));}
        if(ActualHeight<=25)return;
        dc.PushClip(new RectangleGeometry(new Rect(110,24,ViewWidth,Math.Max(1,ActualHeight-24))));
        double offset=0;
        foreach(var row in rows)
        {
            double duration=row.End-row.Start,x=X(offset),w=Math.Max(1,ViewWidth*duration/Span-2);
            if(offset+duration<pan || offset>pan+Span){offset+=duration;continue;}
            var videoRect=new Rect(x,47,w,32);
            dc.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(23,100,119)),new Pen(row==SelectedSegment?Brushes.Cyan:Brushes.SteelBlue,1),videoRect,4,4);
            var frames=Frames?.Cast<TimelineFrame>().ToArray() ?? [];
            if(SourceThumbnail is not null || frames.Length>0){dc.PushClip(new RectangleGeometry(videoRect));for(double at=Math.Max(x,110);at<Math.Min(x+w,ActualWidth);at+=76){var image=frames.OrderBy(f=>Math.Abs(f.Time-Time(at))).FirstOrDefault()?.Image ?? SourceThumbnail;if(image is not null)dc.DrawImage(image,new Rect(at,48,76,30));}dc.Pop();}
            dc.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(8,120,95)),null,new Rect(x,119,w,20),3,3);
            dc.DrawLine(new Pen(Brushes.White,2),new Point(x+3,53),new Point(x+3,73));dc.DrawLine(new Pen(Brushes.White,2),new Point(x+w-3,53),new Point(x+w-3,73));
            dc.DrawRectangle(new SolidColorBrush(Color.FromArgb(160,8,13,21)),null,new Rect(x+6,50,Math.Min(w,115),16));Text($"{row.Start:0.00}–{row.End:0.00}",x+9,51,Colors.White);
            foreach(var caption in Captions?.Cast<CaptionRow>() ?? [])
            {
                double start=Math.Max(row.Start,caption.Start),end=Math.Min(row.End,caption.End);
                if(end<=start)continue;
                var bounds=new Rect(X(offset+start-row.Start),87,Math.Max(1,ViewWidth*(end-start)/Span-2),25);
                if(bounds.Right<110 || bounds.Left>ActualWidth)continue;
                dc.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(36,92,154)),new Pen(caption==SelectedCaption?Brushes.Cyan:Brushes.CornflowerBlue,1),bounds,3,3);
                dc.PushClip(new RectangleGeometry(bounds));Text(caption.Text,bounds.X+7,92,Colors.White);dc.Pop();
            }
            offset+=duration;
        }
        var peaks=Waveform ?? [];
        for(int i=0;i<peaks.Length;i++){double x=X(total*i/peaks.Length);if(x>=110 && x<=ActualWidth-12)dc.DrawLine(new Pen(Brushes.MediumAquamarine,1),new Point(x,129-8*peaks[i]),new Point(x,129+8*peaks[i]));}
        foreach(var scene in SceneBoundaries ?? []){double x=X(scene);if(x>=110 && x<=ActualWidth-12){dc.DrawLine(new Pen(Brushes.Goldenrod,1),new Point(x,26),new Point(x,146));Text("Scene",x+3,28,Colors.Goldenrod);}}
        if(DataContext is MainViewModel hook && hook.SelectedTemplate is not null && hook.TemplateHeadline.Length>0)
        {double start=Math.Clamp(hook.HeadlineStart,0,total),end=Math.Clamp(hook.HeadlineEnd,start,total);dc.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(23,100,119)),null,new Rect(X(start),26,Math.Max(1,X(end)-X(start)),15),3,3);Text("Headline",X(start)+4,26,Colors.Cyan);}
        if(DataContext is MainViewModel music && music.CustomAudio && music.MusicFile.Length>0){dc.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(102,54,160)),null,new Rect(X(0),143,Math.Max(1,X(total)-X(0)),19),3,3);Text("Music stem · "+music.MusicFile,Math.Max(115,X(0)+5),145,Colors.White);}else Text("No independent music layer",115,145,muted);
        if(DataContext is MainViewModel vm && vm.CustomCaptionStyle && vm.CaptionsEnabled && vm.CaptionAnimation!="none" && vm.SelectedTemplate is null)
        {dc.DrawRoundedRectangle(new SolidColorBrush(Color.FromRgb(102,54,160)),null,new Rect(X(0),167,Math.Max(1,X(total)-X(0)),20),3,3);Text("Caption animation · "+vm.CaptionAnimation,Math.Max(115,X(0)+5),169,Colors.White);}
        else if(!(Effects?.Cast<AutoEffectRow>().Any() ?? false))Text("No separate effect layer",115,170,muted);
        foreach(var group in (Effects?.Cast<AutoEffectRow>() ?? []).GroupBy(e=>(e.Start,e.End)))
        {
            var effect=group.First();
            if(!double.IsFinite(effect.Start)||!double.IsFinite(effect.End)||effect.End<=effect.Start)continue;
            var bounds=new Rect(X(effect.Start),167,Math.Max(1,X(effect.End)-X(effect.Start)),20);
            dc.DrawRoundedRectangle(group.Any(e=>e.Enabled)?new SolidColorBrush(Color.FromRgb(19,95,112)):Brushes.DimGray,new Pen(Brushes.Cyan,1),bounds,3,3);
            dc.PushClip(new RectangleGeometry(bounds));Text(string.Join(" · ",group.Select(e=>e.Type)),bounds.X+4,169,Colors.White);dc.Pop();
        }
        double play=X(Playhead);dc.DrawLine(new Pen(Brushes.Cyan,2),new Point(play,24),new Point(play,ActualHeight));dc.DrawEllipse(Brushes.Cyan,null,new Point(play,25),4,4);
        dc.Pop();
    }
    protected override void OnMouseDown(MouseButtonEventArgs e)
    {
        base.OnMouseDown(e);Focus();ClampPan();var p=e.GetPosition(this);
        if(e.ChangedButton==MouseButton.Middle){dragX=p.X;dragOffset=pan;CaptureMouse();return;}
        if(e.ChangedButton!=MouseButton.Left || p.X<110)return;
        if(p.Y>=165 && p.Y<=190 && DataContext is MainViewModel effectsModel)
        {
            var at=Time(p.X);var effect=Effects?.Cast<AutoEffectRow>().FirstOrDefault(e=>e.Start<=at && e.End>=at);
            if(effect is not null){effectsModel.SelectedAutoEffect=effect;effectsModel.InspectorTab=3;effectsModel.SeekTimeline(effect.Start);e.Handled=true;return;}
        }
        if(p.Y>=87 && p.Y<=112 && DataContext is MainViewModel captionModel)
        {
            double offsetCaption=0;
            foreach(var segment in Rows)
            {
                foreach(var caption in Captions?.Cast<CaptionRow>() ?? [])
                {
                    double start=Math.Max(segment.Start,caption.Start),end=Math.Min(segment.End,caption.End);
                    double left=X(offsetCaption+start-segment.Start),right=X(offsetCaption+end-segment.Start);
                    if(end>start && p.X>=left && p.X<=right)
                    {
                        SetCurrentValue(SelectedCaptionProperty,caption);captionModel.InspectorTab=0;
                        dragCaption=caption;dragX=p.X;dragScale=Span/ViewWidth;captionLeft=Math.Abs(p.X-left)<8;captionRight=Math.Abs(p.X-right)<8;
                        captionStart=caption.Start;captionEnd=caption.End;lastCaptionDelta=0;captionModel.BeginEditingGesture();CaptureMouse();e.Handled=true;return;
                    }
                }
                offsetCaption+=segment.End-segment.Start;
            }
        }
        double offset=0;
        foreach(var row in Rows)
        {
            if(p.Y>=47 && p.Y<=79 && p.X>=X(offset) && p.X<=X(offset+row.End-row.Start))
            {
                SetCurrentValue(SelectedSegmentProperty,row);
                dragging=row;dragX=p.X;dragScale=Span/ViewWidth;trimStart=Math.Abs(p.X-X(offset))<9;
                trimming=trimStart || Math.Abs(p.X-X(offset+row.End-row.Start))<9;
                dragTime=trimStart?row.Start:row.End;
                if(DataContext is MainViewModel vm)vm.BeginEditingGesture();
                CaptureMouse();break;
            }
            offset+=row.End-row.Start;
        }
        if(!trimming)SeekRequested?.Invoke(this,Math.Clamp(Time(p.X),0,Total));
        e.Handled=true;
    }
    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);var p=e.GetPosition(this);
        if(IsMouseCaptured && e.MiddleButton==MouseButtonState.Pressed)
        {pan=dragOffset-(p.X-dragX)*Span/ViewWidth;ClampPan();SetCurrentValue(PanFractionProperty,Total>Span?pan/(Total-Span):0);InvalidateVisual();return;}
        if(dragCaption is not null && e.LeftButton==MouseButtonState.Pressed && DataContext is MainViewModel cm)
        {
            double delta=(p.X-dragX)*dragScale;
            if(captionLeft)cm.TrimCaption(dragCaption,true,captionStart+delta);
            else if(captionRight)cm.TrimCaption(dragCaption,false,captionEnd+delta);
            else{cm.MoveCaption(dragCaption,delta-lastCaptionDelta);lastCaptionDelta=delta;}
            InvalidateVisual();return;
        }
        if(dragging is not null && trimming && e.LeftButton==MouseButtonState.Pressed && DataContext is MainViewModel vm)
            vm.TrimSegment(dragging,trimStart,dragTime+(p.X-dragX)*dragScale);
        Cursor=p.Y>=47 && p.Y<=79?Cursors.SizeWE:Cursors.Arrow;
    }
    protected override void OnMouseUp(MouseButtonEventArgs e)
    {
        base.OnMouseUp(e);
        if(dragging is not null && !trimming && Math.Abs(e.GetPosition(this).X-dragX)>12 && DataContext is MainViewModel vm && vm.CanEdit)
        {
            var target=Time(e.GetPosition(this).X);double offset=0;int index=vm.Segments.Count-1;
            for(int i=0;i<vm.Segments.Count;i++){offset+=vm.Segments[i].End-vm.Segments[i].Start;if(target<offset){index=i;break;}}
            vm.Segments.Move(vm.Segments.IndexOf(dragging),index);
        }
        if(DataContext is MainViewModel model)model.EndEditingGesture();
        dragging=null;dragCaption=null;trimming=false;ReleaseMouseCapture();
    }
    protected override void OnLostMouseCapture(MouseEventArgs e)
    {
        base.OnLostMouseCapture(e);
        if(DataContext is MainViewModel vm && vm.MouseEditing)vm.EndEditingGesture();
        dragging=null;dragCaption=null;trimming=false;
    }
    protected override void OnMouseWheel(MouseWheelEventArgs e)
    {
        base.OnMouseWheel(e);
        if(Keyboard.Modifiers.HasFlag(ModifierKeys.Control))SetCurrentValue(ZoomProperty,Math.Clamp(Zoom*(e.Delta>0?1.25:.8),1,32));
        else pan-=Math.Sign(e.Delta)*Span*.15;
        ClampPan();SetCurrentValue(PanFractionProperty,Total>Span?pan/(Total-Span):0);InvalidateVisual();e.Handled=true;
    }
}
