@echo off

REM Check if pyserial is installed
python -c "import serial" >nul 2>&1
if %errorlevel% equ 0 (
    echo pyserial is already installed.
) else (
    REM Install pyserial using setup.py
    python setup.py install
)

REM Run gimbal_tool.py
python gimbal_tool.py

pause
