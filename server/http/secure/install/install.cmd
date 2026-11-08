@echo off
rem Froggyboot - Windows install from WinPE.
rem wimboot puts this file and froggy.txt into X:\Windows\System32; winpeshl.ini starts it.
rem Pure ASCII, CRLF line endings (install.sh converts them).
rem Order: network -> shares -> drivers -> firmware -> image -> DISK + ERASE -> backup -> apply.
rem froggy.txt (from the server) gives MAC, HOST, STAMP and, for admin assignments,
rem AUTO=1 with WIM, IDX, DISK, BACKUP - then no questions are asked.
setlocal
title Froggyboot - Windows install
set "SRV=@SERVER_IP@"
set "SHARE=\\%SRV%\images"
set "INBOX=\\%SRV%\incoming"

set "FB_MAC=unknown"
set "FB_HOST="
set "FB_AUTO=0"
set "FB_STAMP=nostamp"
if exist "%SystemRoot%\System32\froggy.txt" (
  for /f "usebackq tokens=1,* delims==" %%a in ("%SystemRoot%\System32\froggy.txt") do set "FB_%%a=%%b"
)

echo Starting network...
wpeinit
wpeutil UpdateBootInfo >nul 2>&1

rem ---------- connect to the read-only images share ----------
set /a TRY=0
:mount
set /a TRY+=1
net use Z: "%SHARE%" /user:@SMB_USER@ @SMB_PASS@ >nul 2>&1 && goto mounted
if %TRY% GEQ 10 goto nonet
echo Waiting for network (%TRY%/10)...
ping -n 4 127.0.0.1 >nul
goto mount

:nonet
echo.
echo ERROR: cannot reach %SHARE%. Nothing was changed.
echo Type exit to reboot.
cmd /k
wpeutil reboot
exit /b 1

:mounted
rem Reports and backups go to a separate writable share; without it we just don't report.
net use R: "%INBOX%" /user:@SMB_USER@ @SMB_PASS@ >nul 2>&1

rem ---------- storage drivers (Intel VMD/RST etc.) before listing disks ----------
if not exist Z:\drivers\ goto firmware
echo Loading drivers from Z:\drivers ...
for /r Z:\drivers %%i in (*.inf) do drvload "%%i" >nul 2>&1

:firmware
set "FW=BIOS"
reg query HKLM\System\CurrentControlSet\Control /v PEFirmwareType 2>nul | find "0x2" >nul && set "FW=UEFI"

if "%FB_AUTO%"=="1" goto auto

rem ---------- choose image file and edition ----------
:choose_wim
cls
echo Firmware: %FW%    Server: %SHARE%    PC: %FB_HOST%
echo.
echo Images on the server:
dir /b Z:\*.wim Z:\*.esd 2>nul
echo.
set "WIMNAME=install.wim"
set /p "WIMNAME=Image file [install.wim]: "
set "WIM=Z:\%WIMNAME%"
if exist "%WIM%" goto choose_index
echo Not found: %WIM%
pause
goto choose_wim

:choose_index
echo.
dism /English /Get-ImageInfo /ImageFile:"%WIM%" | findstr /b /c:"Index" /c:"Name"
echo.
set "IDX="
set /p "IDX=Edition index to install (Enter = cancel and reboot): "
if "%IDX%"=="" goto cancel
echo %IDX%| findstr /r "^[0-9][0-9]*$" >nul || goto choose_index

rem ---------- second line of defence: pick the disk by hand ----------
:confirm_disk
cls
echo ==============================================================
echo   WARNING: THE SELECTED DISK WILL BE COMPLETELY ERASED
echo ==============================================================
echo Firmware: %FW%    Image: %WIM%    Index: %IDX%
echo list disk> X:\listdisk.txt
diskpart /s X:\listdisk.txt
echo.
set "DISK="
set /p "DISK=Disk number to erase (Enter = cancel and reboot): "
if "%DISK%"=="" goto cancel
echo %DISK%| findstr /r "^[0-9][0-9]*$" >nul || goto confirm_disk
set "CONFIRM="
set /p "CONFIRM=Type ERASE %DISK% to confirm: "
if not "%CONFIRM%"=="ERASE %DISK%" goto cancel
set "BACKUP=0"
if not exist R:\ goto partition
set "ANS="
set /p "ANS=Copy Users folders to the server first? [y/N]: "
if /i "%ANS%"=="y" set "BACKUP=1"
goto backup

rem ---------- admin assignment: everything comes from froggy.txt ----------
:auto
set "WIM=Z:\%FB_WIM%"
set "IDX=%FB_IDX%"
set "DISK=%FB_DISK%"
set "BACKUP=%FB_BACKUP%"
echo %IDX%| findstr /r "^[0-9][0-9]*$" >nul || goto badauto
echo %DISK%| findstr /r "^[0-9][0-9]*$" >nul || goto badauto
if not exist "%WIM%" goto badauto
> X:\seldisk.txt echo select disk %DISK%
diskpart /s X:\seldisk.txt >nul 2>&1 || goto badauto
cls
echo ==============================================================
echo   ADMIN ASSIGNMENT: %FB_HOST% - disk %DISK% will be ERASED
echo   Image %WIM% index %IDX%. Starting in 15 s. Power off to stop.
echo ==============================================================
ping -n 16 127.0.0.1 >nul
goto backup

:badauto
call :report fail "assignment invalid: %FB_WIM% #%FB_IDX% disk %FB_DISK%"
echo ERROR: the assignment from the server is invalid. Nothing was changed.
echo Type exit to reboot.
cmd /k
wpeutil reboot
exit /b 1

:cancel
call :report cancel "by user"
echo Cancelled. Nothing was changed. Rebooting...
net use * /delete /y >nul 2>&1
ping -n 4 127.0.0.1 >nul
wpeutil reboot
exit /b 0

rem ---------- optional backup of Users folders on any volume ----------
:backup
call :report start "%WIM% #%IDX% disk %DISK% %FW%"
if not "%BACKUP%"=="1" goto partition
if not exist R:\ goto partition
set "BDIR=R:\backups\%FB_HOST%-%FB_STAMP%"
call :report backup "%BDIR%"
for %%d in (C D E F G H I J K L M N O P Q S T U V W Y) do (
  if exist %%d:\Users\ if exist %%d:\Windows\ (
    echo Backing up %%d:\Users ...
    robocopy %%d:\Users "%BDIR%\%%d" /E /XJ /R:1 /W:1 /NFL /NDL /NP /XF ntuser.dat* UsrClass.dat* /XD AppData
  )
)
call :report backup-done ""

rem ---------- partitioning: always %DISK%, never an auto-picked disk ----------
:partition
set "DP=X:\diskpart.txt"
rem Redirection goes first, so "disk 1" is not read as stream 1.
> "%DP%" echo select disk %DISK%
>>"%DP%" echo clean
if "%FW%"=="UEFI" goto dp_uefi

>>"%DP%" echo convert mbr
>>"%DP%" echo create partition primary size=500
>>"%DP%" echo format quick fs=ntfs label="System"
>>"%DP%" echo active
>>"%DP%" echo assign letter=S
>>"%DP%" echo create partition primary
>>"%DP%" echo format quick fs=ntfs label="Windows"
>>"%DP%" echo assign letter=W
goto dp_run

:dp_uefi
>>"%DP%" echo convert gpt
>>"%DP%" echo create partition efi size=260
>>"%DP%" echo format quick fs=fat32 label="System"
>>"%DP%" echo assign letter=S
>>"%DP%" echo create partition msr size=16
>>"%DP%" echo create partition primary
>>"%DP%" echo format quick fs=ntfs label="Windows"
>>"%DP%" echo assign letter=W

:dp_run
call :report partition "disk %DISK% %FW%"
echo Partitioning disk %DISK% (%FW%)...
diskpart /s "%DP%" || goto fail

rem ---------- apply image, drivers, answer file, bootloader ----------
call :report apply ""
echo Applying %WIM% index %IDX% ...
dism /Apply-Image /ImageFile:"%WIM%" /Index:%IDX% /ApplyDir:W:\ || goto fail

if not exist Z:\drivers\ goto unattend
call :report drivers ""
echo Adding drivers to the installed system...
dism /Image:W:\ /Add-Driver /Driver:Z:\drivers /Recurse

:unattend
mkdir W:\Windows\Panther 2>nul
set "UA=W:\Windows\Panther\unattend.xml"
if exist Z:\unattend.xml goto unattend_copy
if "%FB_HOST%"=="" goto bootloader
rem No answer file on the server: only set the computer name, setup stays interactive.
> "%UA%" echo ^<?xml version="1.0" encoding="utf-8"?^>
>>"%UA%" echo ^<unattend xmlns="urn:schemas-microsoft-com:unattend"^>^<settings pass="specialize"^>
>>"%UA%" echo ^<component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS"^>
>>"%UA%" echo ^<ComputerName^>%FB_HOST%^</ComputerName^>
>>"%UA%" echo ^</component^>^</settings^>^</unattend^>
goto bootloader

:unattend_copy
rem Copy the server's answer file, replacing FROGGY_HOSTNAME with this PC's name.
type nul > "%UA%"
for /f "usebackq delims=" %%L in ("Z:\unattend.xml") do (
  set "LINE=%%L"
  setlocal enabledelayedexpansion
  set "LINE=!LINE:FROGGY_HOSTNAME=%FB_HOST%!"
  >>"%UA%" echo(!LINE!
  endlocal
)

:bootloader
call :report bootloader ""
bcdboot W:\Windows /s S: /f %FW% || goto fail

call :report done "%FB_HOST%"
echo.
echo Done. Windows is installed on disk %DISK%. Rebooting in 10 s...
net use * /delete /y >nul 2>&1
ping -n 11 127.0.0.1 >nul
wpeutil reboot
exit /b 0

:fail
call :report fail "step failed, errorlevel %ERRORLEVEL%"
echo.
echo ERROR: the step above failed. The disk may be partly written.
echo Type exit to reboot.
cmd /k
wpeutil reboot
exit /b 1

rem ---------- call :report <step> "<detail>" - one line per step for the server ----------
:report
if not exist R:\reports\ exit /b 0
>>"R:\reports\%FB_MAC%.log" echo %~1^|%~2
exit /b 0
