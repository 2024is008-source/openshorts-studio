namespace OpenShorts.EngineBridge;

public sealed class EngineRequestException(int statusCode, string message) : IOException(message)
{
    public int StatusCode { get; } = statusCode;
}
