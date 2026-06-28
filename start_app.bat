@echo off
setlocal

set "PROJECT_DIR=D:\Projects\CampusNet-Agent"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:8501"

cd /d "%PROJECT_DIR%"

if not exist "%PYTHON_EXE%" (
    echo [NetDiag Agent] Python venv not found:
    echo %PYTHON_EXE%
    echo.
    echo Please install the project dependencies first.
    pause
    exit /b 1
)

echo [NetDiag Agent] Stopping old local service...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*streamlit run app.py*' -and $_.CommandLine -like '*8501*' }; if ($procs) { $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force } }"

echo [NetDiag Agent] Starting local service...
start "" /min "%PYTHON_EXE%" -m streamlit run "%PROJECT_DIR%\app.py" --server.port 8501 --server.address 127.0.0.1 > "%PROJECT_DIR%\streamlit.out.log" 2> "%PROJECT_DIR%\streamlit.err.log"

echo [NetDiag Agent] Waiting for server...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ok = $false; for ($i = 0; $i -lt 20; $i++) { try { $r = Invoke-WebRequest -UseBasicParsing '%APP_URL%'; if ($r.StatusCode -eq 200) { $ok = $true; break } } catch {}; Start-Sleep -Milliseconds 800 }; if (-not $ok) { exit 1 }"

if errorlevel 1 (
    echo [NetDiag Agent] Failed to start. Check:
    echo   %PROJECT_DIR%\streamlit.err.log
    echo   %PROJECT_DIR%\streamlit.out.log
    pause
    exit /b 1
)

echo [NetDiag Agent] Started. Opening browser...
start "" "%APP_URL%"
exit /b 0
