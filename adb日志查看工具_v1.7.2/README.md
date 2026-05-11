# ADB 日志查看工具

跨平台 logcat 查看 + 日志文件分析工具。

## 启动

- **Windows**：双击 `启动.bat`
- **Ubuntu**：`./启动.sh`（缺依赖自动 apt 安装）
- **macOS**：见下方 macOS 安装说明

首次启动会自动 `pip install tkinterdnd2`（用于拖拽）。

## macOS 安装与使用

### 1. 安装依赖

```bash
# 安装 Homebrew（若未安装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装 Python（自带 tkinter）、adb、scrcpy
brew install python android-platform-tools scrcpy
```

### 2. 安装 Python 包

```bash
pip3 install tkinterdnd2 sv-ttk
```

### 3. 启动工具

```bash
cd /path/to/adb工具
python3 log_viewer.py
```

### 4. adb 远程连接（无USB线场景）

当 Mac 无法通过 USB 连接设备时（例如手机 USB 口被其他设备占用），可通过 Wi-Fi 远程连接：

**前提条件**：Mac 和目标设备在同一局域网内。

**步骤**：

1. **先在另一台电脑上通过 USB 开启设备的 TCP/IP 模式**：
   ```bash
   adb tcpip 5555
   ```

2. **查看设备 IP 地址**：
   ```bash
   adb shell ip addr show wlan0
   # 或在设备设置 → 关于手机 → 状态 中查看 IP
   ```

3. **在 Mac 上的工具中连接**：
   - 启动工具后，点击设备栏的 **「🔗 远程」** 按钮
   - 输入设备 IP:PORT，例如 `192.168.1.100:5555`
   - 连接成功后设备会自动出现在设备下拉列表中

4. **也可以在终端直接连接**：
   ```bash
   adb connect 192.168.1.100:5555
   ```

> **注意**：远程连接速度取决于 Wi-Fi 质量，投屏/录屏可能有延迟。

## 两个 Tab

### Tab 1：实时 Logcat
- 设备下拉切换、刷新
- `root` 一键切到 root 模式
- 启动时自动 `setprop persist.log.tag D`，可切换 V/D/I/W/E
- 投屏：检测设备多屏幕时弹窗让你选 DisplayID，调起 scrcpy `--display-id`
- 实时关键字过滤（普通/正则/区分大小写）
- 多关键字高亮（最多 8 色，逗号分隔）
- V/D/I/W/E/F 自动着色
- 自动滚动开关、清空、保存

### Tab 2：日志文件查看
- **拖拽** .log/.txt/.csv 等文本文件到窗口加载
- 或点 "打开文件" 按钮
- **双视图**（上下分栏）：
  - 上：原始日志（大文件仅渲染前 5 万行）
  - 下：过滤结果（实时关键字 → 显示全部匹配行）
- 多关键字高亮 + 正则 + 区分大小写
- 多种文本编码自动尝试（utf-8/gbk/latin-1）
- 大文件保护：>200MB 弹窗确认；>500 万行截断索引

## 视图菜单

- **主题**：浅色（默认白底黑字）/ 护眼米白 / 深色 / Solarized
- **字体...**：自由选择字体家族 + 字号
- **自定义背景色 / 字体颜色**：调色板任意选

## 依赖

| 必需 | 说明 |
|------|------|
| Python 3.7+ | 主程序 |
| tkinter | GUI（Linux 装 `python3-tk`） |
| adb | Android Debug Bridge |

| 可选 | 说明 |
|------|------|
| tkinterdnd2 | 拖拽（启动脚本自动 pip 安装） |
| scrcpy | 投屏 |

## 注意

- 切换设备：先点"停止抓取"→ 选新设备 → 点"开始抓取"
- `persist.log.tag` 持久化属性，重启后仍生效
- 文件查看 Tab 的过滤是从全量行扫描，不受原始视图截断影响
