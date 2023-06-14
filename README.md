# DJI-Calib-UI
.bat file making dji gimbal calibration based on dji firmware tools easier to use.

USAGE
1. Install Python from [here](https://www.python.org/downloads/) 
2. Install PySerial from [here](https://pypi.org/project/pyserial/#files) (HINT: click pyserial-3.5.tar.gz)
3. Download and install [7ZIP](https://7-zip.org/)
4. Download  this repo as ZIP.
5. Extract zip file and copy content to a new folder on your C: drive called DJItools
6. copy pyserial folder contents to same folder above (C: or D: drive eg C:/DJItools
7. Install Python
8. Open the start menu, type "CMD", right click and run as administrator.
9. type cd c:/DJItools, press enter
10. Run the following code to install PySerial "py setup.py install"
11. Power on Drone and connect to PC via USB.
12. Open Device Manager and check under PORTS what number your DJI drone is.
13. Run the .bat file "Caliberate Gimbal.bat".
14. Select COM port
15. Select drone model. If you do not know the corresponding Model name and model number, check the MODELS.txt file included in the downloaded files.
16. Follow the prompts and run the first command. Wait till gimbal stops moving then run command 2.
17. redo if needed.
