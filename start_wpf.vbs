' Native development launcher. Previous start_desktop.vbs remains available.
Option Explicit
Dim shell, fso, root, executable, releaseExecutable, previewExecutable
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
executable = root & "\native\OpenShorts.Desktop\bin\Debug\net10.0-windows\OpenShorts.Desktop.exe"
releaseExecutable = root & "\native\OpenShorts.Desktop\bin\Release\net10.0-windows\OpenShorts.Desktop.exe"
If fso.FileExists(releaseExecutable) Then
    If Not fso.FileExists(executable) Then
        executable = releaseExecutable
    ElseIf fso.GetFile(releaseExecutable).DateLastModified >= fso.GetFile(executable).DateLastModified Then
        executable = releaseExecutable
    End If
End If
previewExecutable = root & "\build\preview-flow\OpenShorts.Desktop.exe"
If fso.FileExists(previewExecutable) And fso.FileExists(root & "\build\preview-flow\OpenShorts.Desktop.dll") Then
    If Not fso.FileExists(executable) Then
        executable = previewExecutable
    ElseIf fso.GetFile(root & "\build\preview-flow\OpenShorts.Desktop.dll").DateLastModified >= fso.GetFile(fso.GetParentFolderName(executable) & "\OpenShorts.Desktop.dll").DateLastModified Then
        executable = previewExecutable
    End If
End If
If Not fso.FileExists(executable) Then
    MsgBox "Build the native solution first. See docs\WPF_BUILD.md.", 16, "OpenShorts"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run Chr(34) & executable & Chr(34) & " --source-root " & Chr(34) & root & Chr(34), 1, False
