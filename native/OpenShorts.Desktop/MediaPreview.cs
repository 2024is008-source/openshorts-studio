using LibVLCSharp.Shared;
namespace OpenShorts.Desktop;

public sealed class MediaPreview : IDisposable
{
    private readonly LibVLC vlc;
    public MediaPlayer Player { get; }
    public MediaPreview()
    {
        App.StartupStage("Loading native LibVLC");
        LibVLCSharp.Shared.Core.Initialize();
        vlc = new LibVLC("--no-video-title-show", "--no-snapshot-preview", "--quiet");
        Player = new MediaPlayer(vlc);
        App.StartupStage("Native LibVLC loaded");
    }
    public void Open(string path)
    {
        if (!Path.IsPathFullyQualified(path) || !File.Exists(path)) throw new IOException("Choose an existing local video.");
        using var media = new Media(vlc, path, FromType.FromPath);
        Player.Play(media);
    }
    public void Seek(double seconds) { if (Player.IsSeekable) Player.Time = (long)(Math.Max(0,seconds) * 1000); }
    public void Dispose() { Player.Stop(); Player.Dispose(); vlc.Dispose(); }
}
