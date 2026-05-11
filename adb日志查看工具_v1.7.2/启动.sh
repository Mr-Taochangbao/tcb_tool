#!/bin/bash
cd "$(dirname "$0")"

need_install=()
command -v python3 >/dev/null 2>&1 || need_install+=("python3")
python3 -c "import tkinter" 2>/dev/null || need_install+=("python3-tk")
command -v adb >/dev/null 2>&1 || need_install+=("adb")
command -v pip3 >/dev/null 2>&1 || need_install+=("python3-pip")
command -v ffmpeg >/dev/null 2>&1 || need_install+=("ffmpeg")

if [ ${#need_install[@]} -gt 0 ]; then
    echo "缺少依赖: ${need_install[*]}"
    read -p "是否自动安装? (y/N): " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        sudo apt update
        sudo apt install -y "${need_install[@]}"
    else
        echo "请手动安装上述依赖"
        exit 1
    fi
fi

# 拖拽支持 (tkinterdnd2): 自动安装, 启动时按需启用; 若不稳定可设 DISABLE_DND=1
python3 -c "import tkinterdnd2" 2>/dev/null || pip3 install --user tkinterdnd2
# 现代化界面主题 (Win/macOS 使用; Linux 仅作为 fallback)
python3 -c "import sv_ttk" 2>/dev/null || pip3 install --user sv-ttk
# 图标依赖
python3 -c "from PIL import Image" 2>/dev/null || pip3 install --user pillow

# 若图标文件缺失则现场生成
if [ ! -f "icon.png" ] && [ -f "gen_icon.py" ]; then
    python3 gen_icon.py || true
fi

# 自动安装桌面快捷方式 (含图标), 首次运行有效
DESKTOP_FILE="$HOME/.local/share/applications/adb-log-viewer.desktop"
if [ ! -f "$DESKTOP_FILE" ] && [ -f "icon.png" ]; then
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=ADB 日志查看工具
Comment=ADB Logcat Viewer & File Analyzer
Exec=python3 $(pwd)/log_viewer.py
Icon=$(pwd)/icon.png
Terminal=false
Categories=Development;Utility;
EOF
    echo "[OK] 已创建桌面快捷方式: $DESKTOP_FILE"
fi

if ! command -v scrcpy >/dev/null 2>&1; then
    echo "[提示] 未检测到 scrcpy, 准备自动安装最新版 (apt 版本太老, 使用 snap)..."

    # 1) 优先 snap 安装 (官方维护, 通常是最新稳定版)
    if ! command -v snap >/dev/null 2>&1; then
        echo "[安装] snapd 未安装, 先安装 snapd..."
        sudo apt update && sudo apt install -y snapd
    fi

    if command -v snap >/dev/null 2>&1; then
        echo "[安装] sudo snap install scrcpy"
        if sudo snap install scrcpy; then
            # snap 装的可执行在 /snap/bin, 部分系统 PATH 不含
            if ! command -v scrcpy >/dev/null 2>&1; then
                export PATH="/snap/bin:$PATH"
            fi
        fi
    fi

    # 2) snap 失败兜底: 提示手动方案
    if ! command -v scrcpy >/dev/null 2>&1; then
        echo "[警告] scrcpy 自动安装失败, 投屏功能不可用。"
        echo "       手动方案 1 (snap):   sudo snap install scrcpy"
        echo "       手动方案 2 (源码编译): https://github.com/Genymobile/scrcpy/blob/master/doc/build.md"
        echo "       不要用 sudo apt install scrcpy (那是老版本)。"
    else
        echo "[OK] scrcpy 已就绪: $(command -v scrcpy)"
    fi
fi

# Linux 启动: 后台运行, 启动成功 (3s 内未崩溃) 后释放终端
LOG_FILE="/tmp/adb_log_viewer_$$.log"
echo "[info] 启动中, 日志: $LOG_FILE"

# nohup + setsid 让进程脱离当前终端会话, 关掉终端不会带走 GUI
PYTHONFAULTHANDLER=1 setsid nohup python3 -X faulthandler log_viewer.py \
    > "$LOG_FILE" 2>&1 < /dev/null &
APP_PID=$!
disown 2>/dev/null || true

# 等 3 秒, 看进程是否仍存活
sleep 3
if kill -0 "$APP_PID" 2>/dev/null; then
    echo "[OK] 已启动 (PID=$APP_PID), 此终端可关闭"
    echo "      日志: $LOG_FILE"
    echo "      若需结束: kill $APP_PID"
    exit 0
fi

# 已退出 -> 启动失败, 显示日志
EXIT_CODE=$?
echo ""
echo "[ERROR] 启动失败 (3s 内退出), 日志: $LOG_FILE"
echo "[ERROR] 最后 30 行:"
tail -30 "$LOG_FILE"
echo ""
echo "若是段错误, 请尝试以下任一解决方案:"
echo "  1) 关闭拖拽支持:        DISABLE_DND=1 ./启动.sh"
echo "  2) 退回安全 UI 模式:    LINUX_SAFE_UI=1 ./启动.sh"
echo "  3) 使用纯 Tk 模式:      pip3 uninstall -y tkinterdnd2 sv-ttk"
echo "  4) 检查 Tk 版本:        python3 -c 'import tkinter; print(tkinter.TkVersion)'"
exit 1
