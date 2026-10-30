@echo off
rem Drop a save file onto this file, or double-click it to open the window.
where py >nul 2>nul && (py -3 "%~dp0savetool\save_tool.py" %*) || (python "%~dp0savetool\save_tool.py" %*)
if errorlevel 1 pause
