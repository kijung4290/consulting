; Inno Setup 6 스크립트: 사회복지 상담기록 AI 어시스턴트 설치 프로그램
; Inno Setup Compiler로 열고 컴파일(Ctrl+F9)하면 단일 설치파일(.exe)이 생성됩니다.

#define MyAppName "사회복지 상담기록 AI"
#define MyAppVersion "1.1.0"
#ifndef BuildDir
  #define BuildDir "dist\WelfareAI"
#endif
#ifndef ReleaseDir
  #define ReleaseDir "installer_output"
#endif
#define MyAppPublisher "원주종합사회복지관"
#define MyAppExeName "WelfareAI.exe"

[Setup]
AppId={{D821F248-12A4-48E6-9C6E-9E1123498ABC}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir={#ReleaseDir}
OutputBaseFilename=WelfareAI-Setup-1.1.0
Compression=lzma2/fast
SolidCompression=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 1. 1.7GB 모델 파일은 이미 Q4_K_M 양자화 압축되어 있으므로 무압축 저장 (메모리 부족 및 파일 손상 완벽 방지)
Source: "{#BuildDir}\models\*"; DestDir: "{app}\models"; Flags: ignoreversion nocompression recursesubdirs createallsubdirs skipifsourcedoesntexist
; 2. 나머지 프로그램 및 라이브러리는 압축 패키징
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: "models\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
