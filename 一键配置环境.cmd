@echo off
setlocal
chcp 65001 >nul
title Golden Bull Python Environment
rem Avoid inheriting incompatible PowerShell 7 module paths through cmd.exe.
set "PSModulePath="
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0env_setup\setup.ps1" %*
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (echo 环境已准备好。) else (echo 环境配置未完成，请查看上面的错误；普通配置日志位于 "%~dp0logs\environment_setup\latest.log"。)
pause
exit /b %RESULT%
