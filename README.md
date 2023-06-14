# DJI-Calib-UI
.bat file making dji gimbal calibration based on dji firmware tools easier to use.

USAGE
1. Install Python from here https://www.python.org/downloads/
2. Install PySerial from here https://pypi.org/project/pyserial/ or use this command in Python
"pip install pyserial"
3. Download repo as ZIP.
4. Extract zip file and copy content to your C: or D: drive e.g C:/DJItools/
5. Power on Drone and connect to PC via USB.
6. Open Device Manager and check under PORTS what number your DJI drone is.
7. Run the .bat file "Caliberate Gimbal.bat".
8. Select COM port
9. Select drone model. If you do not know the corresponding Model name and model number, check the MODELS.txt file included in the downloaded files.
10. Follow the prompts and run the first command. Wait till gimbal stops moving then run command 2.
11. redo if needed.
