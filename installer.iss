; Token Monitor —— Inno Setup 安装包脚本
; CI 调用：iscc installer.iss /DAppVersion=v1.2.3

#ifndef AppVersion
#define AppVersion "dev"
#endif

[Setup]
AppId={{7E1C4A62-93B8-4F1D-9A55-2C6E44E1A730}}
AppName=Token Monitor
AppVersion={#AppVersion}
AppPublisher=liixnglinb
DefaultDirName={localappdata}\Programs\TokenMonitor
DefaultGroupName=Token Monitor
UninstallDisplayName=Token Monitor
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\TokenMonitor.exe
OutputDir=dist
OutputBaseFilename=TokenMonitor-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
Uninstallable=yes
; 覆盖安装时如果程序正在跑：显式写出这两条（Inno 默认已是 yes，但依赖默认值
; 看不出来我们在管这件事）。RestartApplications 关掉 —— 这是个常驻托盘的工具，
; 让安装器替用户悄悄重新拉起进程反而更容易撞上"两个实例"。
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=*.exe,*.dll

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\TokenMonitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Token Monitor"; Filename: "{app}\TokenMonitor.exe"
Name: "{group}\卸载 Token Monitor"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Token Monitor"; Filename: "{app}\TokenMonitor.exe"

[Run]
Filename: "{app}\TokenMonitor.exe"; Description: "启动 Token Monitor"; \
  Flags: nowait postinstall skipifsilent

[InstallDelete]
; 上一次自更新半途失败会留下 .new；覆盖安装前先清掉，别让安装目录里
; 永远躺着一份没人认的旧 exe（卸载时同样会清，但升级路径上不该等卸载）
Type: files; Name: "{app}\TokenMonitor.exe.new"

[UninstallDelete]
; 清理更新残留
Type: files; Name: "{app}\TokenMonitor.exe.new"
Type: files; Name: "{app}\TokenMonitor.preflight.exe"
