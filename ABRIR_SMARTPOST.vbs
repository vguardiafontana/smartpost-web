Option Explicit
Dim fs, shell, root, candidate, folder, base, pythonw, key, version
Set fs = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fs.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
pythonw = ""
For Each candidate In Array(root & "\.build-venv\Scripts\pythonw.exe", root & "\.venv\Scripts\pythonw.exe")
    If fs.FileExists(candidate) Then
        pythonw = candidate
        Exit For
    End If
Next
If pythonw = "" Then
    For Each base In Array(shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python", shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python")
        If fs.FolderExists(base) Then
            For Each folder In fs.GetFolder(base).SubFolders
                candidate = folder.Path & "\pythonw.exe"
                If fs.FileExists(candidate) Then pythonw = candidate
            Next
        End If
    Next
End If
If pythonw = "" Then
    On Error Resume Next
    For Each version In Array("3.14", "3.13", "3.12", "3.11", "3.10")
        For Each key In Array("HKCU\Software\Python\PythonCore\", "HKLM\Software\Python\PythonCore\")
            Err.Clear
            base = shell.RegRead(key & version & "\InstallPath\")
            If Err.Number = 0 Then
                candidate = fs.BuildPath(base, "pythonw.exe")
                If fs.FileExists(candidate) Then pythonw = candidate
            End If
        Next
    Next
    On Error GoTo 0
End If
If pythonw = "" Then
    MsgBox "Instala SmartPost con SmartPost_Instalador.exe para abrir la app directamente.", vbInformation, "SmartPost"
    WScript.Quit 1
End If
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & root & "\desktop.py" & Chr(34), 0, False
