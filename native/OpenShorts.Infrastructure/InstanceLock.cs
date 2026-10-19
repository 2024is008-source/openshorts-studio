namespace OpenShorts.Infrastructure;

public sealed class InstanceLock : IDisposable
{
    private readonly FileStream stream;
    public InstanceLock(string directory)
    {
        Directory.CreateDirectory(directory);
        // Same file as the previous shell, so WPF and WebView2 cannot own the
        // same library concurrently. Windows byte locks interoperate with msvcrt.
        stream = new FileStream(Path.Combine(directory, "desktop.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.ReadWrite);
        try { stream.Lock(0, 1); }
        catch { stream.Dispose(); throw new IOException("OpenShorts is already running for this Windows user."); }
    }
    public void Dispose() => stream.Dispose();
}
