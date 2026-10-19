using Microsoft.Extensions.Logging;
using System.Text.Json;

namespace OpenShorts.Infrastructure;

public sealed class SafeLogProvider(string path) : ILoggerProvider
{
    private readonly object gate = new();
    private readonly string file = path;
    public ILogger CreateLogger(string categoryName) => new SafeLogger(this, categoryName);
    public void Dispose() { }
    private sealed class SafeLogger(SafeLogProvider owner, string category) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
        public bool IsEnabled(LogLevel logLevel) => logLevel >= LogLevel.Information;
        public void Log<TState>(LogLevel level, EventId id, TState state, Exception? error, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(level)) return;
            // Deliberately omit arbitrary exception messages, user paths and API payloads.
            var entry = JsonSerializer.Serialize(new { time = DateTimeOffset.UtcNow, level = level.ToString(), category, eventId = id.Id, error = error?.GetType().Name });
            lock (owner.gate)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(owner.file)!);
                if (File.Exists(owner.file) && new FileInfo(owner.file).Length > 1024 * 1024) File.Move(owner.file, owner.file + ".previous", true);
                File.AppendAllText(owner.file, entry + Environment.NewLine);
            }
        }
    }
}
