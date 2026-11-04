@echo off
REM Tec Tha Care Connect demo for Windows. Double-click this file.
REM Extra options are passed on, e.g.:  setup-and-run-demo.bat -Port 8010 -Fresh
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-and-run-demo.ps1" %*
if errorlevel 1 pause
