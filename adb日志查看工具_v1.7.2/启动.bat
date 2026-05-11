@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python, 请先安装 Python 3.7+:
    echo   https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 用官方源安装(规避用户本地 pip 镜像配置错误)，依次尝试官方/清华/阿里
set "PIP_INDEX=-i https://pypi.org/simple --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.aliyun.com/pypi/simple --trusted-host pypi.org --trusted-host pypi.tuna.tsinghua.edu.cn --trusted-host mirrors.aliyun.com"

REM 自动安装 tkinterdnd2 (拖拽支持, 可选, 失败不影响主程序)
python -c "import tkinterdnd2" >nul 2>nul
if errorlevel 1 (
    echo [安装] tkinterdnd2 ...
    python -m pip install --user tkinterdnd2 %PIP_INDEX%
)

REM 自动安装 sv-ttk (现代化界面主题, 可选)
python -c "import sv_ttk" >nul 2>nul
if errorlevel 1 (
    echo [安装] sv-ttk ...
    python -m pip install --user sv-ttk %PIP_INDEX%
)

REM 自动安装 pillow (图标支持, 可选)
python -c "from PIL import Image" >nul 2>nul
if errorlevel 1 (
    echo [安装] pillow ...
    python -m pip install --user pillow %PIP_INDEX%
)

REM 若图标文件缺失则现场生成
if not exist "icon.ico" (
    if exist "gen_icon.py" python gen_icon.py
)

REM ============ 自动安装 scrcpy (投屏依赖) ============
REM 1) 检测当前目录 scrcpy\scrcpy.exe -> 加 PATH
if exist "%~dp0scrcpy\scrcpy.exe" (
    set "PATH=%~dp0scrcpy;%PATH%"
    goto :scrcpy_done
)
REM 2) 检测系统 PATH 是否已有
where scrcpy >nul 2>nul
if not errorlevel 1 goto :scrcpy_done

echo [安装] 未检测到 scrcpy, 正在自动下载安装...

REM 3) 优先用 winget 静默安装
where winget >nul 2>nul
if not errorlevel 1 (
    winget install --id Genymobile.scrcpy -e --silent --accept-source-agreements --accept-package-agreements
    where scrcpy >nul 2>nul
    if not errorlevel 1 goto :scrcpy_done
)

REM 4) winget 不可用或失败 -> PowerShell 下载 GitHub release zip 到当前目录
set "SCRCPY_VER=v3.5"
set "SCRCPY_ZIP=scrcpy-win64-%SCRCPY_VER%.zip"
set "SCRCPY_URL=https://github.com/Genymobile/scrcpy/releases/download/%SCRCPY_VER%/%SCRCPY_ZIP%"
echo [下载] %SCRCPY_URL%
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "try { Invoke-WebRequest -Uri '%SCRCPY_URL%' -OutFile '%~dp0%SCRCPY_ZIP%' -UseBasicParsing;" ^
  "  Expand-Archive -Path '%~dp0%SCRCPY_ZIP%' -DestinationPath '%~dp0_scrcpy_tmp' -Force;" ^
  "  $sub=Get-ChildItem '%~dp0_scrcpy_tmp' -Directory | Select-Object -First 1;" ^
  "  if($sub){ Move-Item $sub.FullName '%~dp0scrcpy' -Force } else { Move-Item '%~dp0_scrcpy_tmp' '%~dp0scrcpy' -Force };" ^
  "  Remove-Item '%~dp0_scrcpy_tmp' -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "  Remove-Item '%~dp0%SCRCPY_ZIP%' -Force -ErrorAction SilentlyContinue;" ^
  "  Write-Host '[OK] scrcpy 已解压到 %~dp0scrcpy' } catch { Write-Host ('[失败] '+$_.Exception.Message); exit 1 }"

if exist "%~dp0scrcpy\scrcpy.exe" (
    set "PATH=%~dp0scrcpy;%PATH%"
    goto :scrcpy_done
)

echo [警告] scrcpy 自动安装失败, 投屏功能将不可用。
echo         请手动从 https://github.com/Genymobile/scrcpy/releases 下载 scrcpy-win64 zip,
echo         解压后把 scrcpy 文件夹放到本目录, 或加入系统 PATH。
echo.

:scrcpy_done

REM ============ ffmpeg (录屏水印依赖, 可选, 异步后台安装不阻塞 GUI) ============
where ffmpeg >nul 2>nul
if errorlevel 1 (
    if exist "%~dp0scrcpy\ffmpeg.exe" (
        echo [OK] ffmpeg 已存在 - 随 scrcpy 包
    ) else (
        where winget >nul 2>nul
        if not errorlevel 1 (
            echo [后台安装] ffmpeg 用于录屏时间水印, 不阻塞 GUI...
            start "ffmpeg-install" /min cmd /c "winget install --id Gyan.FFmpeg -e --silent --accept-source-agreements --accept-package-agreements >nul 2>nul"
        ) else (
            echo [提示] 未安装 ffmpeg, 录屏将无时间水印.
            echo         手动下载: https://www.gyan.dev/ffmpeg/builds/
        )
    )
)

REM scrcpy 自带 adb.exe; 此时再检测 adb
where adb >nul 2>nul
if errorlevel 1 (
    echo [警告] 仍未检测到 adb, 部分功能不可用。
    echo   下载 platform-tools: https://developer.android.com/studio/releases/platform-tools
    echo.
)

REM 静默后台启动 GUI (通过 vbs 包装, 无控制台残留)
if exist "启动.vbs" (
    wscript.exe "启动.vbs"
) else (
    start "" pythonw log_viewer.py
)
exit /b 0
