@echo off
chcp 65001 > nul
title %~nx1
color 0B

setlocal enabledelayedexpansion

echo ========================================================
echo   正在定位基准点 (base.txt) 并校准环境...
echo ========================================================

REM *** 初始化基准路径 ***
set "BAT_DIR=%~dp0"
set "BASE_MARKER=base.txt"
set "SEARCH_DIR=%BAT_DIR%"
set "MAX_LEVEL=10"
set "BASE_PATH="
set "LEVELS_UP=0"

REM *** 向上搜索基准文件 base.txt ***
echo 正在搜索基准标记文件 %BASE_MARKER% ...
for /l %%i in (0,1,%MAX_LEVEL%) do (
    if exist "!SEARCH_DIR!%BASE_MARKER%" (
        set "BASE_PATH=!SEARCH_DIR!"
        goto :FOUND_BASE
    )
    if "!SEARCH_DIR!"=="!SEARCH_DIR:~0,-1!" goto :BASE_NOT_FOUND
    set "SEARCH_DIR=!SEARCH_DIR!..\"
    set /a "LEVELS_UP=LEVELS_UP+1"
)

:BASE_NOT_FOUND
echo 错误：在向上 %MAX_LEVEL% 层目录内未找到 %BASE_MARKER%
echo 请确保在项目根目录存在 %BASE_MARKER% 文件
pause
exit /b 1

:FOUND_BASE
REM *** 转换为绝对路径 ***
pushd "!BASE_PATH!"
set "BASE_PATH=!CD!\"
popd

echo 成功定位基准点：!BASE_PATH!
echo 当前脚本到基准点的深度：%LEVELS_UP% 层

REM *** 设置虚拟环境路径 ***
set "VENV_DIR=!BASE_PATH!myenv"

if not exist "!VENV_DIR!" (
    echo 错误：未找到虚拟环境目录 "!VENV_DIR!"
    pause
    exit /b 1
)

echo 正在激活虚拟环境: "!VENV_DIR!"
REM 虽然这行看似多余了，但为了某些依赖激活脚本的环境变量配置，保留它比较好
call "!VENV_DIR!\Scripts\activate.bat"

echo.
echo ========================================================
echo   正在运行脚本: %*
echo   使用解释器: "!VENV_DIR!\Scripts\python.exe"
echo ========================================================

REM *** 强制使用虚拟环境的 Python 执行 ***
"!VENV_DIR!\Scripts\python.exe" %* 2>&1
set EXIT_CODE=%errorlevel%
echo.
echo ========================================================
if %EXIT_CODE% equ 0 (echo 脚本执行成功!) else (echo 脚本执行失败，错误代码: %EXIT_CODE%)
echo ========================================================
echo.
pause
