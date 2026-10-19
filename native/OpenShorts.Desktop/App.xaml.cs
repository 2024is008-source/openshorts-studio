using System.Windows;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using OpenShorts.Core;
using OpenShorts.EngineBridge;
using OpenShorts.Infrastructure;

namespace OpenShorts.Desktop;
public partial class App : Application
{
    internal static string? DiagnosticDirectory;
    internal static void StartupStage(string stage)
    { if(DiagnosticDirectory is not null)File.WriteAllText(Path.Combine(DiagnosticDirectory,"startup-stage.txt"),stage); }
    private ServiceProvider? services;
    private InstanceLock? instance;
    public static string? Argument(string[] args,string name) { var i=Array.IndexOf(args,name);return i>=0 && i+1<args.Length ? args[i+1] : null; }
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        try
        {
            string? integration=Argument(e.Args,"--integration-test");
            string? review=Argument(e.Args,"--editor-review");
            string? importSmoke=Argument(e.Args,"--import-smoke");
            string? transcriptionCheck=Argument(e.Args,"--transcription-check");
            string? clipperSmoke=Argument(e.Args,"--clipper-smoke");
            string? homeReview=Argument(e.Args,"--home-review");
            string? windowCheck=Argument(e.Args,"--window-check");
            string? smoke=Argument(e.Args,"--smoke-test") ?? integration ?? review ?? windowCheck ?? homeReview ?? importSmoke ?? clipperSmoke ?? transcriptionCheck;
            DiagnosticDirectory=smoke;
            if(smoke is not null)DispatcherUnhandledException+=(_,failure)=>
            {
                File.WriteAllText(Path.Combine(smoke,"dispatcher-error.txt"),failure.Exception.ToString());
                failure.Handled=true;Shutdown(1);
            };
            var root=Path.GetFullPath(Argument(e.Args,"--source-root") ?? FindSourceRoot());
            IUserStorage storage=new UserStorage(Argument(e.Args,"--library"),smoke is null?null:Path.Combine(Path.GetFullPath(smoke),"profile"));
            try { storage.CheckSpace(); }
            catch(IOException) when(smoke is null)
            {
                var dialog=new Microsoft.Win32.OpenFolderDialog{Title="Choose an OpenShorts library drive with at least 2 GB free"};
                if(dialog.ShowDialog()!=true) { Shutdown();return; }
                var library=Path.Combine(dialog.FolderName,"OpenShorts Library");
                File.WriteAllText(Path.Combine(storage.Roaming,"library-location.json"),System.Text.Json.JsonSerializer.Serialize(library));
                storage=new UserStorage(library,storage.Roaming); storage.CheckSpace();
            }
            instance=new InstanceLock(storage.Roaming);
            var collection=new ServiceCollection();
            collection.AddSingleton(storage);collection.AddSingleton(new EngineLaunchOptions(root));
            collection.AddLogging(builder=>builder.AddProvider(new SafeLogProvider(Path.Combine(storage.Library,"logs","wpf.jsonl"))));
            collection.AddSingleton<IWorkerLauncher,WindowsWorkerLauncher>();
            if(clipperSmoke is null && importSmoke is null)collection.AddSingleton<IEngineBridge,EngineClient>();
            else {collection.AddSingleton<EngineClient>();collection.AddSingleton<IEngineBridge>(sp=>new ClipperSmokeBridge(sp.GetRequiredService<EngineClient>()));}
            collection.AddSingleton<MediaPreview>();collection.AddSingleton<MainViewModel>();collection.AddSingleton<MainWindow>();
            services=collection.BuildServiceProvider();
            if(smoke is not null)File.WriteAllText(Path.Combine(smoke,"startup-stage.txt"),"Constructing native window");
            var window=services.GetRequiredService<MainWindow>();window.Show();
            if(windowCheck is not null){_=WindowCheck.RunAsync(window,Path.GetFullPath(windowCheck));return;}
            _=services.GetRequiredService<MainViewModel>().InitializeAsync();
            if(smoke is not null)File.WriteAllText(Path.Combine(smoke,"startup-stage.txt"),"Native window shown");
            if(integration is not null)
            {
                if(!e.Args.Contains("--authorize-gemini") || Argument(e.Args,"--video") is not string video)throw new IOException("Real integration requires a video path and explicit --authorize-gemini.");
                _=IntegrationTest.RunAsync(window,services,Path.GetFullPath(integration),video);
            }
            else if(transcriptionCheck is not null) _=TranscriptionLiveTest.RunAsync(window,services,Path.GetFullPath(transcriptionCheck),Argument(e.Args,"--video") ?? throw new IOException("A video is required."),root);
            else if(clipperSmoke is not null) _=ClipperSmokeTest.RunAsync(window,services,Path.GetFullPath(clipperSmoke));
            else if(importSmoke is not null) _=ImportSmokeTest.RunAsync(window,services,Path.GetFullPath(importSmoke),Argument(e.Args,"--import-test-url"));
            else if(homeReview is not null) _=HomeVisualTest.RunAsync(window,services,Path.GetFullPath(homeReview));
            else if(review is not null) _=EditorVisualTest.RunAsync(window,services,Path.GetFullPath(review));
            else if(smoke is not null) _=SmokeTest.RunAsync(window,services,Path.GetFullPath(smoke));
        }
        catch(Exception error)
        {
            var diagnostic=Argument(e.Args,"--smoke-test") ?? Argument(e.Args,"--integration-test") ?? Argument(e.Args,"--editor-review") ?? Argument(e.Args,"--window-check") ?? Argument(e.Args,"--home-review") ?? Argument(e.Args,"--import-smoke") ?? Argument(e.Args,"--clipper-smoke") ?? Argument(e.Args,"--transcription-check");
            if(diagnostic is not null)
            {
                Directory.CreateDirectory(diagnostic);
                File.WriteAllText(Path.Combine(diagnostic,"startup-error.txt"),error.ToString());
                Shutdown(1);return;
            }
            MessageBox.Show(error is IOException ? error.Message : "OpenShorts could not start. Check the .NET and media runtime installation.","OpenShorts",MessageBoxButton.OK,MessageBoxImage.Error);
            Shutdown(1);
        }
    }
    private static string FindSourceRoot()
    {
        for(var directory=new DirectoryInfo(AppContext.BaseDirectory);directory is not null;directory=directory.Parent)
            if(File.Exists(Path.Combine(directory.FullName,"desktop_entry.py"))) return directory.FullName;
        return AppContext.BaseDirectory;
    }
    protected override void OnExit(ExitEventArgs e)
    {
        if(services is not null)
        {
            services.GetService<MainViewModel>()?.StopPending();
            services.GetService<IEngineBridge>()?.DisposeAsync().AsTask().GetAwaiter().GetResult();
            services.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        instance?.Dispose();base.OnExit(e);
    }
}
