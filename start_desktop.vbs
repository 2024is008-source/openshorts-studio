' Compatibility launcher for the maintained native Windows application.
Option Explicit
Dim shell, fso, root
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
shell.Run "wscript.exe " & Chr(34) & root & "\start_wpf.vbs" & Chr(34), 0, False
