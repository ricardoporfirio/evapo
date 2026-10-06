Set arquivos = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
pasta = arquivos.GetParentFolderName(WScript.ScriptFullName)
python = arquivos.BuildPath(pasta, ".venv\Scripts\pythonw.exe")
inicializador = arquivos.BuildPath(pasta, "abrir_evapo.pyw")
If Not arquivos.FileExists(python) Then
    MsgBox "Ambiente Python do projeto ausente. Abra o projeto com as dependencias instaladas.", 16, "Evapo"
Else
    shell.CurrentDirectory = pasta
    shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & inicializador & Chr(34), 1, False
End If
