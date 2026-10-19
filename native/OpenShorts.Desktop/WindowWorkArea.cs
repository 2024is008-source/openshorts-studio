using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Threading;

namespace OpenShorts.Desktop;

internal sealed class WindowWorkArea
{
    private readonly Window window;
    private nint handle;
    private HwndSource? source;
    private WindowWorkArea(Window window)
    {
        this.window=window;
        window.SourceInitialized+=(_,_)=>
        {
            handle=new WindowInteropHelper(window).Handle;
            source=HwndSource.FromHwnd(handle);source?.AddHook(OnMessage);
            Fit(true);
        };
        window.Loaded+=(_,_)=>Fit(false);
        window.StateChanged+=(_,_)=>ScheduleFit();
        window.Closed+=(_,_)=>source?.RemoveHook(OnMessage);
    }
    internal static void Attach(Window window)=>_ = new WindowWorkArea(window);
    private void ScheduleFit()=>window.Dispatcher.BeginInvoke(DispatcherPriority.Loaded,()=>Fit(false));
    private void Fit(bool center)
    {
        if(handle==0 || window.WindowState!=WindowState.Normal || !GetWindowRect(handle,out var rect))return;
        var monitor=GetMonitor();
        double scale=Math.Max(96,GetDpiForWindow(handle))/96d;
        window.MinWidth=Math.Min(1120,Math.Max(1,(monitor.Work.Right-monitor.Work.Left-32)/scale));
        window.MinHeight=Math.Min(760,Math.Max(1,(monitor.Work.Bottom-monitor.Work.Top-32)/scale));
        var current=new WindowBounds(rect.Left,rect.Top,rect.Right-rect.Left,rect.Bottom-rect.Top);
        var work=new WindowBounds(monitor.Work.Left,monitor.Work.Top,monitor.Work.Right-monitor.Work.Left,monitor.Work.Bottom-monitor.Work.Top);
        var fit=WindowGeometry.Fit(work,current,center);
        if(fit!=current)SetWindowPos(handle,0,fit.Left,fit.Top,fit.Width,fit.Height,0x0014); // no activation or Z-order change
    }
    private MonitorInfo GetMonitor()
    {
        var info=new MonitorInfo{Size=Marshal.SizeOf<MonitorInfo>()};
        if(!GetMonitorInfo(MonitorFromWindow(handle,2),ref info))throw new InvalidOperationException("Cannot read the display work area.");
        return info;
    }
    private nint OnMessage(nint hwnd,int message,nint wParam,nint lParam,ref bool handled)
    {
        if(message==0x0024) // WM_GETMINMAXINFO: maximize inside this monitor's taskbar bounds.
        {
            var monitor=GetMonitor();var info=Marshal.PtrToStructure<MinMaxInfo>(lParam);
            info.MaxPosition=new PointI(monitor.Work.Left-monitor.Monitor.Left,monitor.Work.Top-monitor.Monitor.Top);
            info.MaxSize=new PointI(monitor.Work.Right-monitor.Work.Left,monitor.Work.Bottom-monitor.Work.Top);
            Marshal.StructureToPtr(info,lParam,false);handled=true;
        }
        else if(message is 0x02E0 or 0x007E)ScheduleFit(); // DPI or display configuration changed
        return 0;
    }
    [StructLayout(LayoutKind.Sequential)] private struct RectI { public int Left,Top,Right,Bottom; }
    [StructLayout(LayoutKind.Sequential)] private struct PointI(int x,int y) { public int X=x,Y=y; }
    [StructLayout(LayoutKind.Sequential)] private struct MonitorInfo { public int Size;public RectI Monitor,Work;public uint Flags; }
    [StructLayout(LayoutKind.Sequential)] private struct MinMaxInfo { public PointI Reserved,MaxSize,MaxPosition,MinTrackSize,MaxTrackSize; }
    [DllImport("user32.dll")] private static extern nint MonitorFromWindow(nint hwnd,uint flags);
    [DllImport("user32.dll",CharSet=CharSet.Auto)] [return:MarshalAs(UnmanagedType.Bool)] private static extern bool GetMonitorInfo(nint monitor,ref MonitorInfo info);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(nint hwnd);
    [DllImport("user32.dll")] [return:MarshalAs(UnmanagedType.Bool)] private static extern bool GetWindowRect(nint hwnd,out RectI rect);
    [DllImport("user32.dll")] [return:MarshalAs(UnmanagedType.Bool)] private static extern bool SetWindowPos(nint hwnd,nint after,int x,int y,int width,int height,uint flags);
}
