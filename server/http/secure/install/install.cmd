@echo off
rem Froggyboot - Windows install from WinPE.
rem wimboot puts this file into X:\Windows\System32; winpeshl.ini starts it.
rem Pure ASCII, CRLF line endings (install.sh converts them).
rem Order: network -> share -> drivers -> firmware -> image -> DISK + ERASE -> apply.
setlocal
title Froggyboot - Windows install
set "SRV=@SERVER_IP@"
set "SHARE=\\%SRV%\images"

echo Starting network...
wpeinit
wpeutil UpdateBootInfo >nul 2>&1

rem ---------- connect to the read-only Samba share ----------
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
rem ---------- storage drivers (Intel VMD/RST etc.) before listing disks ----------
if not exist Z:\drivers\ goto firmware
echo Loading drivers from Z:\drivers ...
for /r Z:\drivers %%i in (*.inf) do drvload "%%i" >nul 2>&1

:firmware
set "FW=BIOS"
reg query HKLM\System\CurrentControlSet\Control /v PEFirmwareType 2>nul | find "0x2" >nul && set "FW=UEFI"

rem ---------- choose image file and edition ----------
:choose_wim
cls
echo Firmware: %FW%    Server: %SHARE%
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
goto partition

:cancel
echo Cancelled. Nothing was changed. Rebooting...
net use Z: /delete /y >nul 2>&1
ping -n 4 127.0.0.1 >nul
wpeutil reboot
exit /b 0

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
echo Partitioning disk %DISK% (%FW%)...
diskpart /s "%DP%" || goto fail

rem ---------- apply image, drivers, answer file, bootloader ----------
echo Applying %WIM% index %IDX% ...
dism /Apply-Image /ImageFile:"%WIM%" /Index:%IDX% /ApplyDir:W:\ || goto fail

if not exist Z:\drivers\ goto unattend
echo Adding drivers to the installed system...
dism /Image:W:\ /Add-Driver /Driver:Z:\drivers /Recurse

:unattend
if not exist Z:\unattend.xml goto bootloader
mkdir W:\Windows\Panther 2>nul
copy /y Z:\unattend.xml W:\Windows\Panther\unattend.xml >nul

:bootloader
bcdboot W:\Windows /s S: /f %FW% || goto fail

echo.
echo Done. Windows is installed on disk %DISK%. Rebooting in 10 s...
net use Z: /delete /y >nul 2>&1
ping -n 11 127.0.0.1 >nul
wpeutil reboot
exit /b 0

:fail
echo.
echo ERROR: the step above failed. The disk may be partly written.
echo Type exit to reboot.
cmd /k
wpeutil reboot
exit /b 1
