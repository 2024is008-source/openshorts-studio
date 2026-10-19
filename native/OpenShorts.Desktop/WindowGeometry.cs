namespace OpenShorts.Desktop;

// Coordinates are physical pixels throughout; WPF minimum sizes are converted separately.
internal readonly record struct WindowBounds(int Left,int Top,int Width,int Height);
internal static class WindowGeometry
{
    internal static WindowBounds Fit(WindowBounds work,WindowBounds current,bool center)
    {
        int margin=Math.Min(16,Math.Max(0,Math.Min(work.Width,work.Height)/20));
        int width=Math.Clamp(current.Width,1,Math.Max(1,work.Width-2*margin));
        int height=Math.Clamp(current.Height,1,Math.Max(1,work.Height-2*margin));
        int left=center?work.Left+(work.Width-width)/2:Math.Clamp(current.Left,work.Left,work.Left+work.Width-width);
        int top=center?work.Top+(work.Height-height)/2:Math.Clamp(current.Top,work.Top,work.Top+work.Height-height);
        return new(left,top,width,height);
    }
}
