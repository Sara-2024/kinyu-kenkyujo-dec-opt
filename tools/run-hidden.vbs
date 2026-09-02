' 渡されたコマンドを、黒い画面を出さずに動かすだけの小道具。
'   例: wscript run-hidden.vbs "cmd /c npm start" "C:\path\to\server"
Option Explicit
Dim shell, cmd, cwd
If WScript.Arguments.Count = 0 Then WScript.Quit 1
Set shell = CreateObject("WScript.Shell")
cmd = WScript.Arguments(0)
If WScript.Arguments.Count > 1 Then
  cwd = WScript.Arguments(1)
  If Len(cwd) > 0 Then shell.CurrentDirectory = cwd
End If
shell.Run cmd, 0, False
