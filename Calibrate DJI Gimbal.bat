
@echo off
setlocal enabledelayedexpansion

REM Define the list of models
set "models=A2 P330 P330V P330Z P330VP WM610 P3X P3S MAT100 P3C MG1 WM325 WM330 MAT600 WM220 WM620 WM331 MAT200 MG1S WM332 WM100 WM230 WM335 WM240 WM245 WM246 WM160 WM231 WM232 WM260"

REM Get a list of available COM ports
for /f "tokens=2 delims==" %%A in ('wmic path Win32_SerialPort Get DeviceID /value') do (
  set "com_ports=!com_ports!%%A;"
)

REM Remove trailing semicolon from the list of COM ports
set "com_ports=!com_ports:~0,-1!"

REM Check if any COM ports are available
if not defined com_ports (
  echo No COM ports available.
  exit /b
)

REM Prompt user to select a COM port
echo Available COM Ports:
set /a count=0
for %%A in (!com_ports!) do (
  set /a count+=1
  echo !count!. %%A
  set "com_port[!count!]=%%A"
)

REM Prompt user to enter the number of the desired COM port
set /p "selection=Select the COM port (enter the corresponding number): "

REM Validate the user's selection
if not defined com_port[%selection%] (
  echo Invalid selection. Please try again.
  exit /b
)

REM Get the selected COM port from the list
set "com_port=!com_port[%selection%]!"

REM Prompt user to select a model number
echo Available Models:
set /a count=0
for %%A in (%models%) do (
  set /a count+=1
  echo !count!. %%A
  set "model[!count!]=%%A"
)

REM Prompt user to enter the number of the desired model number
set /p "selection=Select the model number (enter the corresponding number): "

REM Validate the user's selection
if not defined model[%selection%] (
  echo Invalid selection. Please try again.
  exit /b
)

REM Get the selected model number from the list
set "model_num=!model[%selection%]!"

REM Replace 'comX' and 'MODEL' with the selected COM port and model number in the commands
set "command1=python comm_og_service_tool.py --port %com_port% %model_num% GimbalCalib JointCoarse"
echo Running command 1: %command1%
REM Execute command1 here and capture the output
for /f "delims=" %%B in ('%command1%') do (
  echo %%B
)

REM Prompt for the second command
echo Do you want to run the second command?
echo 1. YES
echo 2. NO

REM Prompt user to enter 1 for YES or 2 for NO
set /p "choice=Enter 1 for YES or 2 for NO: "

REM Validate the user's choice
if "%choice%" equ "1" (
  set "command2=python comm_og_service_tool.py --port %com_port% %model_num% GimbalCalib LinearHall"
  echo Running command 2: %command2%
  REM Execute command2 here and capture the output
  for /f "delims=" %%B in ('%command2%') do (
    echo %%B
  )
  pause
) else if "%choice%" equ "2" (
  echo Second command skipped.
)

REM Prompt user to press 1 to exit