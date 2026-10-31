@echo off
setlocal
set ROOT=%~dp0
set PYTHON=D:\python\py\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo ================================================
echo   ITEA - starting dev environment
echo ================================================
echo.

echo [1/2] Backend  http://127.0.0.1:8000
start "ITEA Backend" cmd /k "cd /d %ROOT%backend && %PYTHON% -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo [2/2] Frontend http://localhost:5173
start "ITEA Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"

echo.
echo Two windows opened. Keep them open.
echo   Backend  ready: "Application startup complete"  (about 45s)
echo   Frontend ready: "Local: http://localhost:5173/"
echo.
echo Closing a service window stops that service.
echo.
pause
