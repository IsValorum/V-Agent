; V-Agent installer hooks (Tauri NSIS).

; Default folder for a new per-user install: %LOCALAPPDATA%\Programs\V-Agent (where Windows puts per-user programs),
; not Tauri's %LOCALAPPDATA%\V-Agent right next to %LOCALAPPDATA%\V-Agent-Data, which read like two copies of the app.
; An earlier install keeps its folder: Tauri has already set it from the registry, and updates run silently (/S),
; where this page callback does not run at all.
!define MUI_CUSTOMFUNCTION_GUIINIT VAgentDefaultFolder
Function VAgentDefaultFolder
  ReadRegStr $R0 HKCU "Software\V-Agent\V-Agent" ""
  ${If} $R0 == ""
  ${AndIf} $INSTDIR == "$LOCALAPPDATA\V-Agent"
    StrCpy $INSTDIR "$LOCALAPPDATA\Programs\V-Agent"
  ${EndIf}
FunctionEnd

; The language chosen in the installer's selector ($LANGUAGE, a Windows LANGID) is saved next to
; V-Agent.exe. On first start V-Agent uses it for the interface and the interactive tutorial.
!macro NSIS_HOOK_POSTINSTALL
  FileOpen $0 "$INSTDIR\install-language.txt" w
  FileWrite $0 "$LANGUAGE"
  FileClose $0
!macroend

; Stops every process whose executable lives under a folder: the V-Agent core (core\v-agent-core.exe) and the
; tool servers it starts keep running in the background after the window closes, and Windows will not delete
; a file a running process has loaded (core\_internal\wintrust.dll stayed behind after "uninstall" in 1.1.15).
; Only processes started from that folder are stopped; the uninstaller itself runs from %TEMP%.
!macro VAGENT_STOP_PROCESSES_IN FOLDER
  ; The folder travels in the environment, never inside the command text (a quote in a user name would break it).
  System::Call 'Kernel32::SetEnvironmentVariable(t "VAGENT_STOP_DIR", t "${FOLDER}")'
  nsExec::Exec `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$d=[IO.Path]::GetFullPath($$env:VAGENT_STOP_DIR).TrimEnd('\')+'\'; Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -and $$_.ExecutablePath.StartsWith($$d,[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
  Pop $0
  Sleep 800
!macroend

; Before installing: stop what still runs from the program folder (a core left in the background keeps its files
; locked), then remove the layout of 1.1.15 and earlier (core\strata-core.exe and core\_internal\, ~0.5 GB),
; which the new one (core\v-agent-core.exe and core\lib\) would otherwise leave behind on an update.
!macro NSIS_HOOK_PREINSTALL
  !insertmacro VAGENT_STOP_PROCESSES_IN "$INSTDIR"
  Delete "$INSTDIR\core\strata-core.exe"
  RMDir /r "$INSTDIR\core\_internal"
  ; A scanner can hold a file a moment longer: one more try before installing.
  ${If} ${FileExists} "$INSTDIR\core\_internal\*.*"
    Sleep 1500
    RMDir /r "$INSTDIR\core\_internal"
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro VAGENT_STOP_PROCESSES_IN "$INSTDIR"
!macroend

; Uninstalling keeps chats, settings, downloaded engines and models in %LOCALAPPDATA%\V-Agent-Data (separate from the program folder),
; unless the user ticks "Delete the application data" in the uninstaller.
!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$INSTDIR\install-language.txt"
  ; Anything the core wrote next to itself after installing (caches, a file a scanner held a moment longer):
  ; core\ is V-Agent's own folder, so it goes whole. The install folder itself is removed only when empty.
  RMDir /r "$INSTDIR\core"
  RMDir "$INSTDIR"
  ${If} $DeleteAppDataCheckboxState = 1
    ; A loaded engine (llama.cpp, Strata…) runs from the data folder and would keep its files locked.
    !insertmacro VAGENT_STOP_PROCESSES_IN "$LOCALAPPDATA\V-Agent-Data"
    RMDir /r "$LOCALAPPDATA\V-Agent-Data"
  ${EndIf}
!macroend
