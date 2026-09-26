@echo off
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel% equ 0 (
  start "" pyw -3 monitoramento_gui.py
  exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel% equ 0 (
  start "" pythonw monitoramento_gui.py
  exit /b 0
)

echo Python 3 nao foi encontrado.
echo Instale Python 3 e marque a opcao "Add Python to PATH".
pause
