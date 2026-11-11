; V-Agent installer hooks (Tauri NSIS).

; The language chosen in the installer's selector ($LANGUAGE, a Windows LANGID) is saved next to
; V-Agent.exe. On first start V-Agent uses it for the interface and the interactive tutorial.
!macro NSIS_HOOK_POSTINSTALL
  FileOpen $0 "$INSTDIR\install-language.txt" w
  FileWrite $0 "$LANGUAGE"
  FileClose $0
!macroend

; Uninstalling keeps chats, settings, downloaded engines and models in %LOCALAPPDATA%\V-Agent-Data (separate from the program folder),
; unless the user ticks "Delete the application data" in the uninstaller.
!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$INSTDIR\install-language.txt"
  ${If} $DeleteAppDataCheckboxState = 1
    RMDir /r "$LOCALAPPDATA\V-Agent-Data"
  ${EndIf}
!macroend
