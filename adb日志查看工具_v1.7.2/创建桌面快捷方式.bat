@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "DESKTOP=%USERPROFILE%\Desktop"
set "LNK=%DESKTOP%\ADB日志查看工具.lnk"

:: 查找 pythonw.exe
where pythonw >nul 2>&1
if %errorlevel%==0 (
    set "PY=pythonw"
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo 错误: 找不到 Python，请先安装 Python
        pause
        exit /b 1
    )
)

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%LNK%'); $s.TargetPath = (Get-Command %PY%).Source; $s.Arguments = '\"%SCRIPT_DIR%\log_viewer.py\"'; $s.WorkingDirectory = '%SCRIPT_DIR%'; if (Test-Path '%SCRIPT_DIR%\icon.ico') { $s.IconLocation = '%SCRIPT_DIR%\icon.ico' }; $s.Description = 'ADB日志查看工具'; $s.Save()"

if exist "%LNK%" (
    echo 桌面快捷方式已创建: %LNK%
) else (
    echo 创建快捷方式失败
)
pause
