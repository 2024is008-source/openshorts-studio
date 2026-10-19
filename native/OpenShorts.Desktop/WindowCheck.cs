using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;

namespace OpenShorts.Desktop;
internal static class WindowCheck
{
    internal static async Task RunAsync(MainWindow window,string directory)
    {
        Directory.CreateDirectory(directory);
        try
        {
            await Task.Delay(600);
            nint handle=new WindowInteropHelper(window).Handle;
            CheckFits(handle);
            var brand=window.PointToScreen(new Point(100,30));
            int caption=(int)SendMessage(handle,0x84,0,Pack(brand));
            if(caption!=2)throw new Exception($"Title bar returned hit test {caption}, expected native HTCAPTION.");
            var search=window.HomeSearchBox.PointToScreen(new Point(40,15));
            int client=(int)SendMessage(handle,0x84,0,Pack(search));
            if(client!=1)throw new Exception($"Search returned hit test {client}, expected interactive HTCLIENT.");
            int close=(int)SendMessage(handle,0x84,0,Pack(window.PointToScreen(new Point(window.ActualWidth-25,30))));
            if(close!=1)throw new Exception("Close button is not interactive inside the caption.");
            int resize=(int)SendMessage(handle,0x84,0,Pack(window.PointToScreen(new Point(2,window.ActualHeight/2))));
            if(resize!=10)throw new Exception($"Left window edge returned {resize}, expected native resize HTLEFT.");
            window.WindowState=WindowState.Maximized;await Task.Delay(300);CheckFits(handle);
            window.WindowState=WindowState.Normal;await Task.Delay(300);CheckFits(handle);
            var bitmap=new System.Windows.Media.Imaging.RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,System.Windows.Media.PixelFormats.Pbgra32);
            bitmap.Render(window);var png=new System.Windows.Media.Imaging.PngBitmapEncoder();png.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(bitmap));
            using(var output=File.Create(Path.Combine(directory,"window.png")))png.Save(output);
            File.WriteAllText(Path.Combine(directory,"result.json"),JsonSerializer.Serialize(new{success=true,dpi=GetDpiForWindow(handle),window.ActualWidth,window.ActualHeight,nativeCaption=caption,interactiveSearch=client,interactiveClose=close,nativeResize=resize,maximizeRestore=true}));
            Application.Current.Shutdown(0);
        }
        catch(Exception error)
        {
            File.WriteAllText(Path.Combine(directory,"error.txt"),error.ToString());Application.Current.Shutdown(1);
        }
    }
    private static nint Pack(Point point)=>(nint)(((int)point.Y<<16)|((int)point.X&0xffff));
    private static void CheckFits(nint handle)
    {
        GetWindowRect(handle,out var rect);var monitor=new MonitorInfo{Size=Marshal.SizeOf<MonitorInfo>()};GetMonitorInfo(MonitorFromWindow(handle,2),ref monitor);
        if(rect.Left<monitor.Work.Left || rect.Top<monitor.Work.Top || rect.Right>monitor.Work.Right || rect.Bottom>monitor.Work.Bottom)
            throw new Exception($"Window [{rect.Left},{rect.Top},{rect.Right},{rect.Bottom}] extends beyond work area [{monitor.Work.Left},{monitor.Work.Top},{monitor.Work.Right},{monitor.Work.Bottom}].");
    }
    [StructLayout(LayoutKind.Sequential)] private struct RectI {public int Left,Top,Right,Bottom;}
    [StructLayout(LayoutKind.Sequential)] private struct MonitorInfo {public int Size;public RectI Monitor,Work;public uint Flags;}
    [DllImport("user32.dll")] private static extern nint MonitorFromWindow(nint hwnd,uint flags);
    [DllImport("user32.dll",CharSet=CharSet.Auto)] private static extern bool GetMonitorInfo(nint monitor,ref MonitorInfo info);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(nint hwnd,out RectI rect);
    [DllImport("user32.dll")] private static extern nint SendMessage(nint hwnd,uint message,nint wParam,nint lParam);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(nint hwnd);
}
