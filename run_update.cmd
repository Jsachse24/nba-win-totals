@echo off
rem Daily scheduled run (see schedule_task.ps1). Output goes to logs\update.log via update.py.
cd /d "%~dp0"
"C:\Python314\python.exe" update.py >> "%~dp0logs\scheduler_stdout.log" 2>&1
