# DJI-Calib-UI
.bat file making dji gimbal calibration based on dji firmware tools easier to use.

USAGE
1. Install Python from [here](https://www.python.org/downloads/) 
2. Install PySerial from [here](https://pypi.org/project/pyserial/#files) or use this command in Python
"pip install pyserial"
3. Download repo as ZIP.
4. Extract zip file and copy content to your C: or D: drive e.g C:/DJItools/
5. copy pyserial folder contents to same folder above (C: or D: drive eg C:/DJItools
6. Install Python
7. Click the address bar in the file explorer when in the folder above and type CMD
8. Run the following code to install PySerial "py -m pip install pyserial"
9. Power on Drone and connect to PC via USB.
10. Open Device Manager and check under PORTS what number your DJI drone is.
11. Run the .bat file "Caliberate Gimbal.bat".
12. Select COM port
13. Select drone model. If you do not know the corresponding Model name and model number, check the MODELS.txt file included in the downloaded files.
14. Follow the prompts and run the first command. Wait till gimbal stops moving then run command 2.
15. redo if needed.
