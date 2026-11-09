; Local test installer. No driver writes, downloads or capture startup.
#ifndef PackageVersion
  #define PackageVersion "0.1.0"
#endif
[Setup]
AppId={{D60511A5-FEF2-4EF0-9B98-B563DB8FBBF4}
AppName=C039 Recorder
AppVersion={#PackageVersion}
AppPublisher=C039 Recorder project
DefaultDirName={localappdata}\Programs\C039 Recorder
DefaultGroupName=C039 Recorder
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#PackageOutput}
OutputBaseFilename=C039Recorder-{#PackageVersion}-win-x64-Setup
Compression=lzma2
SolidCompression=yes
AppMutex=Local\C039Recorder.App
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\C039Recorder.exe
InfoBeforeFile={#AppSource}\_internal\TEST-BUILD.txt
LicenseFile={#AppSource}\_internal\licenses\LICENSE
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\C039 Recorder"; Filename: "{app}\C039Recorder.exe"; WorkingDir: "{app}"
Name: "{group}\Удалить C039 Recorder"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\C039Recorder.exe"; Description: "Открыть C039 Recorder"; Flags: nowait postinstall skipifsilent unchecked

[Code]
procedure InitializeWizard();
var
  Instances: TArrayOfString;
  I: Integer;
  Service: String;
  Ready: Boolean;
begin
  Ready := False;
  if RegGetSubkeyNames(HKLM, 'SYSTEM\CurrentControlSet\Enum\USB\VID_07CA&PID_C039&MI_01', Instances) then
    for I := 0 to GetArrayLength(Instances) - 1 do
      if RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Enum\USB\VID_07CA&PID_C039&MI_01\' + Instances[I], 'Service', Service) then
        if CompareText(Service, 'WinUSB') = 0 then Ready := True;
  if Ready then
    WizardForm.WelcomeLabel2.Caption := WizardForm.WelcomeLabel2.Caption + #13#10#13#10 + 'Найдена привязка MI_01 к WinUSB. Подключение устройства проверяется при запуске.'
  else
    WizardForm.WelcomeLabel2.Caption := WizardForm.WelcomeLabel2.Caption + #13#10#13#10 + 'Для захвата требуется предварительная настройка MI_01 на WinUSB. Этот установщик драйверы не меняет.';
end;
