@echo off
cd /d "%~dp0.."

echo.
echo  ==================================================
echo   Recording 15 s  (2 lights / F2.8 / 10 ms / 6 dB / 60 fps)
echo   Starts in 5 s - let the car run through the frame
echo  ==================================================
echo.
ping -n 6 127.0.0.1 >nul

python -m camera.camera_capture --fps 60 --exposure 10000 --gain 6 record out\truss_15s.mp4 -s 15

echo.
echo  Done: out\truss_15s.mp4
echo  Tell me in the chat, then I will analyze it.
pause
