@echo off
setlocal
set "BOND_ATLAS_NODE="
for /f "delims=" %%N in ('where node.exe 2^>nul') do if not defined BOND_ATLAS_NODE set "BOND_ATLAS_NODE=%%N"
if not defined BOND_ATLAS_NODE if exist "D:\nodejs\node.exe" set "BOND_ATLAS_NODE=D:\nodejs\node.exe"
if not defined BOND_ATLAS_NODE (
  echo Node.js non trovato. Questa versione richiede Node.js 24.
  pause
  exit /b 1
)
"%BOND_ATLAS_NODE%" "%~dp0scripts\local-launcher.mjs" start
if errorlevel 1 pause
endlocal
