@echo off
setlocal
cd /d "%~dp0"
title Media Converter - building the installer
echo ==============================================
echo    Media Converter - building the installer
echo ==============================================
echo.

set /p VER=<version.txt
set "PY=python"
%PY% --version >nul 2>&1
if errorlevel 1 set "PY=py"
%PY% --version >nul 2>&1
if errorlevel 1 goto nopython

if not exist ffmpeg.exe goto noffmpeg
if not exist ffprobe.exe goto noffmpeg

echo [1/4] Installing build tools (needs internet, first time only)...
%PY% -m pip install --upgrade pyinstaller tkinterdnd2
if errorlevel 1 goto fail

echo.
echo [2/4] Building the program...
%PY% -m PyInstaller --noconfirm --clean --onedir --noconsole --name MediaConverter --icon icon.ico --collect-all tkinterdnd2 --add-data "icon.ico;." --add-data "icon.png;." --add-data "version.txt;." --add-binary "ffmpeg.exe;." --add-binary "ffprobe.exe;." media_converter.py
if errorlevel 1 goto fail

REM FFmpeg needs its .dll files right next to ffmpeg.exe
if exist "dist\MediaConverter\_internal\ffmpeg.exe" copy /y *.dll "dist\MediaConverter\_internal\" >nul
if exist "dist\MediaConverter\ffmpeg.exe" copy /y *.dll "dist\MediaConverter\" >nul

echo.
echo [3/4] Looking for Inno Setup (the installer maker)...
set "PF86=%ProgramFiles(x86)%"
set "ISCC="
if exist "%PF86%\Inno Setup 6\ISCC.exe" set "ISCC=%PF86%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC goto compile

echo Inno Setup not found - trying to install it automatically...
winget install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
if exist "%PF86%\Inno Setup 6\ISCC.exe" set "ISCC=%PF86%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC goto compile
goto noinno

:compile
echo.
echo [4/4] Creating the installer...
"%ISCC%" /DMyAppVersion=%VER% installer.iss
if errorlevel 1 goto fail

REM ---- make the update file for your users ----
set "HASH="
for /f "skip=1 tokens=* delims=" %%h in ('certutil -hashfile "Output\MediaConverter_Setup.exe" SHA256') do if not defined HASH set "HASH=%%h"
set "HASH=%HASH: =%"
> "Output\version.json" echo {
>> "Output\version.json" echo   "version": "%VER%",
>> "Output\version.json" echo   "url": "PUT_THE_DIRECT_DOWNLOAD_LINK_OF_MediaConverter_Setup.exe_HERE",
>> "Output\version.json" echo   "sha256": "%HASH%",
>> "Output\version.json" echo   "notes": "What is new in this version."
>> "Output\version.json" echo }

echo.
echo ==============================================
echo  DONE!  Version %VER%  Your installer is here:
echo  %~dp0Output\MediaConverter_Setup.exe
echo ==============================================
start "" "%~dp0Output"
pause
exit /b 0

:nopython
echo Python was not found. Install it from https://www.python.org/downloads/
echo and tick "Add Python to PATH" during setup, then run this file again.
pause
exit /b 1

:noffmpeg
echo ffmpeg.exe / ffprobe.exe are missing from this folder.
pause
exit /b 1

:noinno
echo Could not install Inno Setup automatically.
echo Download it free from https://jrsoftware.org/isdl.php , install it, then run this file again.
pause
exit /b 1

:fail
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
