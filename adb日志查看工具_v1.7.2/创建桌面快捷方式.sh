#!/bin/bash
# 在 Ubuntu 创建应用程序快捷方式 (.desktop)
# 用法: ./创建桌面快捷方式.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 查找 Python3
PYTHON="$(which python3 2>/dev/null || which python 2>/dev/null)"
if [ -z "$PYTHON" ]; then
    echo "错误: 找不到 python3"
    exit 1
fi

# 查找图标
ICON=""
if [ -f "$SCRIPT_DIR/icon.png" ]; then
    ICON="$SCRIPT_DIR/icon.png"
fi

# 安装到应用程序目录 (~/.local/share/applications/)
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
DESKTOP_FILE="$APP_DIR/adb-log-viewer.desktop"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=ADB日志查看工具
Comment=ADB Logcat Viewer
Exec=$PYTHON "$SCRIPT_DIR/log_viewer.py"
Path=$SCRIPT_DIR
Icon=$ICON
Terminal=false
Categories=Development;
StartupNotify=true
EOF

chmod +x "$DESKTOP_FILE"

# 同时尝试在桌面创建 (兼容中文/英文桌面目录)
DESKTOP_DIR=""
if [ -d "$HOME/Desktop" ]; then
    DESKTOP_DIR="$HOME/Desktop"
elif [ -d "$HOME/桌面" ]; then
    DESKTOP_DIR="$HOME/桌面"
fi

if [ -n "$DESKTOP_DIR" ]; then
    cp "$DESKTOP_FILE" "$DESKTOP_DIR/adb-log-viewer.desktop"
    chmod +x "$DESKTOP_DIR/adb-log-viewer.desktop"
    gio set "$DESKTOP_DIR/adb-log-viewer.desktop" metadata::trusted true 2>/dev/null
    echo "桌面快捷方式已创建: $DESKTOP_DIR/adb-log-viewer.desktop"
fi

echo "应用程序快捷方式已创建: $DESKTOP_FILE"
echo "可在应用程序菜单中搜索 'ADB' 找到"
