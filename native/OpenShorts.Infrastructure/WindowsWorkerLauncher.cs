using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using OpenShorts.Core;

namespace OpenShorts.Infrastructure;

public sealed class WindowsWorkerLauncher : IWorkerLauncher
{
    public IWorkerProcess Start(string executable, IReadOnlyList<string> arguments, string directory, IDictionary<string,string> environment)
        => new OwnedProcess(executable, arguments, directory, environment);

    private sealed class OwnedProcess : IWorkerProcess
    {
        private IntPtr job, process;
        public int Id { get; }
        public bool HasExited => process == IntPtr.Zero || WaitForSingleObject(process, 0) == 0;
        public OwnedProcess(string executable, IReadOnlyList<string> arguments, string directory, IDictionary<string,string> environment)
        {
            job = CreateJobObject(IntPtr.Zero, null);
            var limits = new ExtendedLimits(); limits.Basic.Flags = 0x2000;
            if (job == IntPtr.Zero || !SetInformationJobObject(job, 9, ref limits, Marshal.SizeOf<ExtendedLimits>())) { Dispose(); throw new Win32Exception(); }
            var block = string.Join('\0', environment.OrderBy(x => x.Key, StringComparer.OrdinalIgnoreCase).Select(x => x.Key + "=" + x.Value)) + "\0\0";
            var env = Marshal.StringToHGlobalUni(block);
            var startup = new StartupInfo { Size = Marshal.SizeOf<StartupInfo>() };
            ProcessInfo info = default;
            try
            {
                var command = new StringBuilder(string.Join(' ', new[] { executable }.Concat(arguments).Select(QuoteArgument)));
                if (!CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, false, 0x08000404, env, directory, ref startup, out info)) throw new Win32Exception();
                process = info.Process;
                Id = info.Id;
                if (!AssignProcessToJobObject(job, process)) throw new Win32Exception();
                if (ResumeThread(info.Thread) == uint.MaxValue) throw new Win32Exception();
            }
            catch { if (process != IntPtr.Zero) TerminateProcess(process, 1); Dispose(); throw; }
            finally { if (info.Thread != IntPtr.Zero) CloseHandle(info.Thread); Marshal.FreeHGlobal(env); }
        }
        public void Dispose()
        {
            if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
            if (process != IntPtr.Zero) { WaitForSingleObject(process, 5000); CloseHandle(process); process = IntPtr.Zero; }
        }
    }
    public static string QuoteArgument(string value)
    {
        if (value.Contains('\0')) throw new ArgumentException("Invalid process argument.");
        // Windows CommandLineToArgvW / Python CRT quoting, including trailing backslashes.
        var result = new StringBuilder("\""); int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            result.Append('\\', c == '"' ? slashes * 2 + 1 : slashes); slashes = 0; result.Append(c);
        }
        result.Append('\\', slashes * 2); return result.Append('"').ToString();
    }
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimits { public long ProcessTime, JobTime; public uint Flags; public UIntPtr MinWorking, MaxWorking; public uint ActiveProcesses; public UIntPtr Affinity; public uint Priority, Scheduling; }
    [StructLayout(LayoutKind.Sequential)] private struct IOCounters { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] private struct ExtendedLimits { public BasicLimits Basic; public IOCounters Io; public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct StartupInfo { public int Size; public string? Reserved, Desktop, Title; public int X,Y,Width,Height,XChars,YChars,Fill,Flags; public short Show,Reserved2; public IntPtr ReservedPtr,Input,Output,Error; }
    [StructLayout(LayoutKind.Sequential)] private struct ProcessInfo { public IntPtr Process,Thread; public int Id,ThreadId; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, EntryPoint="CreateJobObjectW", SetLastError=true)] private static extern IntPtr CreateJobObject(IntPtr attributes,string? name);
    [DllImport("kernel32.dll",SetLastError=true)] private static extern bool SetInformationJobObject(IntPtr job,int info,ref ExtendedLimits limits,int size);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,EntryPoint="CreateProcessW",SetLastError=true)] private static extern bool CreateProcess(string app,StringBuilder command,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr environment,string cwd,ref StartupInfo startup,out ProcessInfo info);
    [DllImport("kernel32.dll",SetLastError=true)] private static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
    [DllImport("kernel32.dll")] private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll")] private static extern uint WaitForSingleObject(IntPtr handle,uint timeout);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll")] private static extern bool TerminateProcess(IntPtr handle,uint code);
}
