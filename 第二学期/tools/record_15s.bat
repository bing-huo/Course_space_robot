@echo off
cd /d "%~dp0.."

echo.
echo  ==================================================
echo   Recording 15 s  (2 lights / 10 ms / 60 fps)
echo   Starts in 5 s - let the car run through the frame
echo  ==================================================
echo.
ping -n 6 127.0.0.1 >nul

python -m camera.camera_capture --fps 60 --exposure 10000 record out\car_2lights_15s.mp4 -s 15

echo.
echo  Done: out\car_2lights_15s.mp4
echo  Tell me in the chat, then I will analyze it.
pause
