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
OutputDir=dist
OutputBaseFilename=TokenMonitor-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
Uninstallable=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "dist\TokenMonitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Token Monitor"; Filename: "{app}\TokenMonitor.exe"
Name: "{group}\卸载 Token Monitor"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Token Monitor"; Filename: "{app}\TokenMonitor.exe"

[Run]
Filename: "{app}\TokenMonitor.exe"; Description: "启动 Token Monitor"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 清理更新残留
Type: files; Name: "{app}\TokenMonitor.exe.new"
