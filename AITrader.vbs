' MT5 Automatic（画面を出さずに起動する入口）
'
' ダブルクリックしても黒い画面は出ません。中では connect.py が
'   ・ログイン中の MT5 を見つける
'   ・システム(EA)を配置してコンパイル
'   ・ブリッジを裏側で起動して中継サーバーにつなぐ
'   ・サイトのボタン(aitrader://)とPC起動時の自動接続を登録
' を順にやります。経過は %LOCALAPPDATA%\AITrader\connect.log に残ります。

Option Explicit
Dim fso, shell, here, py, cmd, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)

' 専用の python（venv）があればそれを使う。無ければ PATH のものに任せる
py = here & "\bridge\venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then py = "pythonw.exe"

cmd = """" & py & """ """ & here & "\connect.py"" --silent"

' aitrader://connect のようにブラウザから渡ってくる引数をそのまま送る
For i = 0 To WScript.Arguments.Count - 1
  cmd = cmd & " """ & WScript.Arguments(i) & """"
Next

' 第2引数 0 = ウィンドウを出さない / False = 終わるのを待たない
shell.Run cmd, 0, False
