; AI Trader Connect のインストーラー（Inno Setup 6）
;
; 作り方:
;   1. Windows で tools\build-windows.bat を実行して dist\AITrader.exe を作る
;   2. Inno Setup 6 をインストール（https://jrsoftware.org/isdl.php）
;   3. このファイルを Inno Setup Compiler で開いて [ビルド]
;   → tools\installer\AITraderConnect-Setup.exe ができる
;
; 方針:
;   ・管理者権限を要求しない（PrivilegesRequired=lowest）。UAC の画面を出さない
;   ・入れる場所は各ユーザーのフォルダ。会社の PC でも入れられる
;   ・aitrader:// の登録はここで行う。アンインストールで消える
;   ・コード署名はまだ。SmartScreen の警告が出る（別工程で対応）

#define AppName "AI Trader Connect"
#define AppVersion "1.0.0"
#define AppPublisher "AI Trader"
#define AppExe "AITrader.exe"

[Setup]
AppId={{9A5C2F41-7E6B-4C2A-9E3D-1B7F0A8C5D24}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\AITraderConnect
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=AITraderConnect-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; アンインストール時に、お客様のデータ（設定・記録）は消さない
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作る"; GroupDescription: "追加の設定:"

[Registry]
; サイトのボタンからこのアプリを呼べるようにする（aitrader://）。
; アプリ自身も起動時に登録するが、インストーラーで入れておけば
; 一度も開かないうちからサイト側の導線が使える。
Root: HKCU; Subkey: "Software\Classes\aitrader"; ValueType: string; ValueName: ""; ValueData: "URL:{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\aitrader"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\aitrader\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\aitrader\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKCU; Subkey: "Software\Classes\aitrader\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""--silent"" ""--from-site"" ""%1"""

[Run]
; 入れ終わったらそのまま開く。ここで MT5 を探して EA を置く（サイトとは通信しない）
Filename: "{app}\{#AppExe}"; Description: "{#AppName} を開いて設定する"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 裏で動いているものがあれば止めてから消す
Filename: "{app}\{#AppExe}"; Parameters: "--stop"; Flags: runhidden; RunOnceId: "StopBridge"
