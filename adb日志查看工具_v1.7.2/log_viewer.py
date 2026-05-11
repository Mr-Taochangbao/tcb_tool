#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADB 日志查看工具 (Logcat Viewer) - 增强版
- 美化 UI / 自定义主题 / 字体颜色背景
- 实时 logcat 抓取 + 多关键字高亮 + 过滤
- scrcpy 投屏 (支持选择 DisplayID)
- 文件查看 Tab: 拖拽加载, 大文件支持, 原始 + 过滤双视图
"""

import os
import sys
import re
import subprocess
import threading
import queue
import time
import platform
import shutil
import signal
import faulthandler
import json
from datetime import datetime
from collections import deque

# 段错误时打印 Python traceback 到 stderr (调试 Linux/Tk 崩溃)
try:
    faulthandler.enable()
except Exception:
    pass

# ============ 环境依赖自动检测 ============
def _ensure_pip_pkg(pkg, import_name=None):
    name = import_name or pkg
    try:
        __import__(name)
        return True
    except ImportError:
        print(f"[install] pip install {pkg}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            __import__(name)
            return True
        except Exception as e:
            print(f"[warn] 安装 {pkg} 失败: {e}")
            return False


def _check_environment():
    missing = []
    try:
        import tkinter  # noqa
    except ImportError:
        missing.append("tkinter")
    if shutil.which("adb") is None:
        missing.append("adb")

    if missing:
        system = platform.system()
        print("缺少依赖:", ", ".join(missing))
        if system == "Linux":
            cmds = []
            if "tkinter" in missing:
                cmds.append("sudo apt update && sudo apt install -y python3-tk")
            if "adb" in missing:
                cmds.append("sudo apt install -y adb")
            for c in cmds:
                print("  " + c)
            try:
                ans = input("自动安装? (y/N): ").strip().lower()
                if ans == "y":
                    for c in cmds:
                        subprocess.call(c, shell=True)
                else:
                    sys.exit(1)
            except EOFError:
                sys.exit(1)
        else:
            if "tkinter" in missing:
                print("  Windows: 请重装 Python 时勾选 tcl/tk and IDLE")
            if "adb" in missing:
                print("  Windows: 请下载 platform-tools 并加入 PATH")
            sys.exit(1)


_check_environment()
# 拖拽支持: 默认所有平台都启用 (Linux 需 tkinterdnd2 已安装).
# 用户可设 DISABLE_DND=1 强制禁用, 或 ENABLE_DND=1 强制启用.
_dnd_force_off = os.environ.get("DISABLE_DND") in ("1", "true", "yes")
_dnd_force_on = os.environ.get("ENABLE_DND") in ("1", "true", "yes")
if _dnd_force_off:
    HAS_DND = False
else:
    HAS_DND = _ensure_pip_pkg("tkinterdnd2")
# sv-ttk 在部分 Linux 发行版 + Tcl/Tk 8.6 上会触发段错误, 仅在 Windows / macOS 启用
if platform.system() in ("Windows", "Darwin"):
    HAS_SVTTK = _ensure_pip_pkg("sv-ttk", "sv_ttk")
else:
    HAS_SVTTK = False

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, font as tkfont, colorchooser

if HAS_SVTTK:
    import sv_ttk
if HAS_DND:
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        BaseTk = TkinterDnD.Tk
    except Exception as e:
        print(f"[warn] tkinterdnd2 加载失败, 关闭拖拽: {e}", file=sys.stderr)
        HAS_DND = False
        BaseTk = tk.Tk
else:
    BaseTk = tk.Tk

# 资源路径
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后: exe 所在目录
    RESOURCE_DIR = os.path.dirname(sys.executable)
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PNG = os.path.join(RESOURCE_DIR, "icon.png")
ICON_ICO = os.path.join(RESOURCE_DIR, "icon.ico")


# === BMP-only 兼容: 老版 Python (3.7) + Tcl/Tk 8.6 不支持 U+10000 以上字符 (emoji),
# 会在 menu.add_cascade 等地方抛 "character U+1f31e is above the range".
# 这里在导入 tkinter 后探测一次, 如果不行就 monkey-patch 把 SMP 字符替换成 BMP 等价物. ===
_SMP_FALLBACK_MAP = {
    0x1F31E: "\u2600",  # ☀ -> ☀
    0x1F319: "\u263E",  # ☾ -> ☾
    0x1F3A8: "*",       # ◐ -> *
    0x1F4A1: "i",       # ⓘ
    0x1F4BE: "[S]",     # ▽
    0x1F4C1: "[D]",     # ▤
    0x1F4C2: "[D]",     # ▤
    0x1F4C4: "[F]",     # ▤
    0x1F4CB: "[L]",     # ▥
    0x1F4DC: "[L]",     # ▦
    0x1F4E1: ">>",      # ▶
    0x1F4F1: "[P]",     # □
    0x1F504: "\u21BB",  # ↻ -> ↻
    0x1F50C: "[C]",     # ⏻
    0x1F50D: "\u2315",  # ⌕ -> ⌕
    0x1F50E: "\u2315",  # ⌕ -> ⌕
    0x1F518: "\u25C9",  # ◉ -> ◉
    0x1F53C: "\u25B2",  # ▲ -> ▲
    0x1F53D: "\u25BC",  # ▼ -> ▼
    0x1F5A5: "[PC]",    # □
    0x1F5D1: "X",       # ×
}


def _strip_smp(s):
    """把 U+10000 以上字符替换为 BMP 等价物 (老 Tcl 兼容)."""
    if not isinstance(s, str):
        return s
    out = []
    for c in s:
        cp = ord(c)
        if cp > 0xFFFF:
            out.append(_SMP_FALLBACK_MAP.get(cp, ""))
        else:
            out.append(c)
    return "".join(out)


def _patch_tk_for_bmp_only():
    """探测 Tcl 是否支持 SMP; 不支持则给 _tkinter.Tcl_Obj 调用链加过滤."""
    try:
        import tkinter as _tk
        _r = _tk.Tk()
        _r.withdraw()
        try:
            _r.tk.call("set", "_smp_test", "\U0001F31E")
            _r.destroy()
            return False  # 支持, 无需 patch
        except Exception:
            pass
        _r.destroy()
    except Exception:
        return False
    # 不支持 -> patch tkinter.Misc._options 和 tk.call
    try:
        import tkinter as _tk
        _orig_call = _tk.Misc._tk_call_orig = None
        # 直接 wrap Tcl interp 的 call (在 createcommand/_options 都会用)
        _orig_create = _tk.BaseWidget.__init__

        def _wrap_args(args):
            return tuple(_strip_smp(a) if isinstance(a, str) else a for a in args)

        # 给 tkapp 实例的 call 方法加包装 (tk.Tk 实例化后)
        def _patch_interp(root):
            interp = root.tk
            if getattr(interp, "_bmp_patched", False):
                return
            real_call = interp.call

            def patched_call(*args):
                return real_call(*_wrap_args(args))
            interp.call = patched_call
            interp._bmp_patched = True

        # patch Tk.__init__ 完成后的 root
        _orig_tk_init = _tk.Tk.__init__

        def _new_tk_init(self, *a, **kw):
            _orig_tk_init(self, *a, **kw)
            try:
                _patch_interp(self)
            except Exception:
                pass
        _tk.Tk.__init__ = _new_tk_init
        return True
    except Exception as e:
        print(f"[warn] BMP patch 失败: {e}", file=sys.stderr)
        return False


_BMP_PATCHED = _patch_tk_for_bmp_only()


def _resolve_scrcpy_bin():
    """跨系统定位 scrcpy 可执行文件:
    1) 优先随包目录 ./scrcpy/scrcpy(.exe)  (Win 用户解压即用, 不依赖 PATH)
    2) 系统 PATH (winget / apt 安装后)
    返回绝对路径或 None. 同时把 bundled 目录加到 os.environ['PATH'] 供子进程继承.
    为避免 adb server 冲突 (系统 adb 与 bundled adb 版本不一致 → 投屏间歇失败),
    同时设置 ADB 环境变量强制 scrcpy 使用 bundled adb.exe.
    """
    is_win = platform.system() == "Windows"
    exe_name = "scrcpy.exe" if is_win else "scrcpy"
    adb_name = "adb.exe" if is_win else "adb"
    bundled_dir = os.path.join(RESOURCE_DIR, "scrcpy")
    bundled = os.path.join(bundled_dir, exe_name)
    # PyInstaller onedir: scrcpy 可能在 _internal/scrcpy/
    if not os.path.isfile(bundled) and getattr(sys, 'frozen', False):
        internal_dir = os.path.join(RESOURCE_DIR, "_internal", "scrcpy")
        internal = os.path.join(internal_dir, exe_name)
        if os.path.isfile(internal):
            bundled_dir = internal_dir
            bundled = internal
    if os.path.isfile(bundled):
        # 把 bundled 目录加到 PATH 头, 让子进程也找得到 (并附带 adb.exe)
        sep = os.pathsep
        cur = os.environ.get("PATH", "")
        if bundled_dir not in cur.split(sep):
            os.environ["PATH"] = bundled_dir + sep + cur
        # 强制 scrcpy 用 bundled adb (scrcpy 会读 ADB 环境变量), 避免与系统 adb server 冲突
        bundled_adb = os.path.join(bundled_dir, adb_name)
        if os.path.isfile(bundled_adb):
            os.environ["ADB"] = bundled_adb
        return bundled
    found = shutil.which("scrcpy")
    return found


SCRCPY_BIN = _resolve_scrcpy_bin()


# ============ 常量 / 主题 ============
APP_TITLE = "ADB 日志查看工具"
APP_VERSION = "1.7.2"
APP_AUTHOR = "changtao.tao"
APP_EMAIL = "1808810376@qq.com"
IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"


def _safe_get_bg(widget, default="#fafbfc"):
    """安全获取 widget 背景色; ttk widget 不支持 cget(background) 会抛 TclError.
    返回值保证是合法的颜色字符串 (#开头或具名色), 不会返回空串."""
    val = None
    try:
        val = widget.cget("background")
    except Exception:
        pass
    if not val:
        try:
            st = ttk.Style()
            val = st.lookup("TFrame", "background")
        except Exception:
            val = None
    if not val or not isinstance(val, str) or len(val.strip()) == 0:
        return default
    return val


def make_checkbutton(master, **kw):
    """Linux 用 tk.Checkbutton 避免 ttk 在 clam/default 主题上显示打叉的图标.
    完全不传 bg/activebackground (空串或非法值会触发 Tk 段错误)."""
    if IS_LINUX:
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        return tk.Checkbutton(master, **kw)
    return ttk.Checkbutton(master, **kw)


def make_radiobutton(master, **kw):
    if IS_LINUX:
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 0)
        return tk.Radiobutton(master, **kw)
    return ttk.Radiobutton(master, **kw)
LOG_LEVELS = ["V", "D", "I", "W", "E"]
DEFAULT_LEVEL = "D"

HIGHLIGHT_PALETTE = [
    ("#fff176", "#000"),
    ("#ff8a65", "#000"),
    ("#81c784", "#000"),
    ("#64b5f6", "#000"),
    ("#ba68c8", "#fff"),
    ("#f06292", "#fff"),
    ("#4dd0e1", "#000"),
    ("#ffd54f", "#000"),
]

LEVEL_COLORS = {
    "V": "#9e9e9e",
    "D": "#1976d2",
    "I": "#2e7d32",
    "W": "#ef6c00",
    "E": "#c62828",
    "F": "#880000",
}

THEMES = {
    # === 浅色 ===
    "浅色 (默认)": {
        "bg": "#ffffff", "fg": "#1f2328", "select": "#bbdefb",
        "gutter_bg": "#f6f8fa", "gutter_fg": "#8c959f",
        "ui": "light",
    },
    "GitHub Light": {
        "bg": "#ffffff", "fg": "#24292f", "select": "#b6e3ff",
        "gutter_bg": "#f6f8fa", "gutter_fg": "#6e7781",
        "ui": "light",
    },
    "VS Code Light+": {
        "bg": "#ffffff", "fg": "#1e1e1e", "select": "#add6ff",
        "gutter_bg": "#f3f3f3", "gutter_fg": "#237893",
        "ui": "light",
    },
    "护眼 (米白)": {
        "bg": "#f5f5dc", "fg": "#1a1a1a", "select": "#d7ccc8",
        "gutter_bg": "#ede8c8", "gutter_fg": "#7d6d4f",
        "ui": "light",
    },
    "Solarized Light": {
        "bg": "#fdf6e3", "fg": "#586e75", "select": "#eee8d5",
        "gutter_bg": "#eee8d5", "gutter_fg": "#93a1a1",
        "ui": "light",
    },
    # === 深色 (现代) ===
    "VS Code Dark+": {
        "bg": "#1e1e1e", "fg": "#d4d4d4", "select": "#264f78",
        "gutter_bg": "#252526", "gutter_fg": "#858585",
        "ui": "dark",
    },
    "Android Studio Darcula": {
        "bg": "#2b2b2b", "fg": "#a9b7c6", "select": "#214283",
        "gutter_bg": "#313335", "gutter_fg": "#606366",
        "ui": "dark",
    },
    "One Dark Pro": {
        "bg": "#282c34", "fg": "#abb2bf", "select": "#3e4451",
        "gutter_bg": "#21252b", "gutter_fg": "#5c6370",
        "ui": "dark",
    },
    "Dracula": {
        "bg": "#282a36", "fg": "#f8f8f2", "select": "#44475a",
        "gutter_bg": "#21222c", "gutter_fg": "#6272a4",
        "ui": "dark",
    },
    "Monokai": {
        "bg": "#272822", "fg": "#f8f8f2", "select": "#49483e",
        "gutter_bg": "#1e1f1c", "gutter_fg": "#75715e",
        "ui": "dark",
    },
    "GitHub Dark": {
        "bg": "#0d1117", "fg": "#c9d1d9", "select": "#1f6feb",
        "gutter_bg": "#161b22", "gutter_fg": "#6e7681",
        "ui": "dark",
    },
    "Tokyo Night": {
        "bg": "#1a1b26", "fg": "#a9b1d6", "select": "#33467c",
        "gutter_bg": "#16161e", "gutter_fg": "#565f89",
        "ui": "dark",
    },
    "Nord": {
        "bg": "#2e3440", "fg": "#d8dee9", "select": "#434c5e",
        "gutter_bg": "#272b36", "gutter_fg": "#4c566a",
        "ui": "dark",
    },
    "Material Dark": {
        "bg": "#263238", "fg": "#eeffff", "select": "#314549",
        "gutter_bg": "#1e272c", "gutter_fg": "#546e7a",
        "ui": "dark",
    },
    "Solarized Dark": {
        "bg": "#002b36", "fg": "#839496", "select": "#073642",
        "gutter_bg": "#001f27", "gutter_fg": "#586e75",
        "ui": "dark",
    },
    # === 兼容旧名 ===
    "深色": {
        "bg": "#1e1e1e", "fg": "#d4d4d4", "select": "#264f78",
        "gutter_bg": "#252526", "gutter_fg": "#858585",
        "ui": "dark",
    },
    "Solarized": {
        "bg": "#fdf6e3", "fg": "#586e75", "select": "#eee8d5",
        "gutter_bg": "#eee8d5", "gutter_fg": "#93a1a1",
        "ui": "light",
    },
}


# ============ ADB 工具 ============
# Windows 下隐藏 subprocess 弹出的 cmd 黑窗
_SUBPROC_FLAGS = 0
if platform.system() == "Windows":
    _SUBPROC_FLAGS = 0x08000000  # CREATE_NO_WINDOW


def adb_run(args, device=None, timeout=10):
    cmd = ["adb"]
    if device:
        cmd += ["-s", device]
    cmd += args
    try:
        return subprocess.check_output(
            cmd, stderr=subprocess.STDOUT, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=_SUBPROC_FLAGS,
        )
    except subprocess.CalledProcessError as e:
        return e.output or ""
    except Exception as e:
        return f"[error] {e}"


def adb_devices():
    out = adb_run(["devices"])
    devs = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            devs.append((parts[0], parts[1]))
    return devs


SCRCPY_MAX_DISPLAY_ID = 2 ** 31 - 1

# scrcpy/截屏/录屏 等会临时创建的虚拟 display, 列表时过滤掉
_VIRTUAL_DISPLAY_KEYWORDS = (
    "scrcpy", "screenrecord", "screen recording", "mediaprojection",
    "mirror", "virtual", "cast", "record",
)


def _is_virtual_display(name: str) -> bool:
    if not name:
        return False
    low = name.lower()
    return any(k in low for k in _VIRTUAL_DISPLAY_KEYWORDS)


def _list_displays_via_scrcpy(device):
    """用 scrcpy --list-displays 列出 scrcpy 真正能投的 displayId.

    返回 [(id_str, info), ...] 或 None (scrcpy 不可用 / 解析失败).
    这是最权威来源 - 不会列出 scrcpy 自己跑会失败的 displayId.
    """
    if SCRCPY_BIN is None:
        return None
    try:
        cflags = _SUBPROC_FLAGS if platform.system() == "Windows" else 0
        proc = subprocess.run(
            [SCRCPY_BIN, "-s", device, "--list-displays"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=10, creationflags=cflags,
        )
        out = (proc.stdout or b"").decode("utf-8", errors="replace")
    except Exception:
        return None
    # 输出形如:    --display-id=0    (1080x2340)
    items = []
    seen = set()
    for m in re.finditer(r"--display-id[=\s]+(\d+)\s*\(([^)]*)\)", out):
        did = m.group(1)
        if did in seen:
            continue
        try:
            if int(did) > SCRCPY_MAX_DISPLAY_ID:
                continue
        except ValueError:
            continue
        seen.add(did)
        items.append((did, m.group(2).strip()))
    # 兼容只列 id 没分辨率的情况
    if not items:
        for m in re.finditer(r"--display-id[=\s]+(\d+)", out):
            did = m.group(1)
            if did in seen:
                continue
            try:
                if int(did) > SCRCPY_MAX_DISPLAY_ID:
                    continue
            except ValueError:
                continue
            seen.add(did)
            items.append((did, "Display"))
    return items if items else None


def list_displays(device):
    """返回 [(id_str, info), ...]; 仅返回 scrcpy 可用的小整数 displayId.

    优先调用 scrcpy --list-displays (最权威, 不会列出会失败的 displayId);
    若 scrcpy 不可用再回退到 dumpsys display + SurfaceFlinger.
    """
    # 0. 最权威: scrcpy --list-displays
    via_scrcpy = _list_displays_via_scrcpy(device)
    if via_scrcpy:
        return via_scrcpy

    displays = []
    seen = set()

    # 1. 框架层 displayId (scrcpy 真正使用的)
    out = adb_run(["shell", "dumpsys", "display"], device=device, timeout=8)
    # DisplayDeviceInfo 优先, 通常带 name=
    for m in re.finditer(
        r"DisplayDeviceInfo\{[^}]*displayId=(\d+)[^}]*?(?:name=\"([^\"]+)\")?",
        out
    ):
        did = m.group(1)
        if did in seen:
            continue
        try:
            if int(did) > SCRCPY_MAX_DISPLAY_ID:
                continue
        except ValueError:
            continue
        seen.add(did)
        name = (m.group(2) or "").strip()
        if _is_virtual_display(name):
            continue
        displays.append((did, name or "Display"))

    # 兜底: mDisplays 列表或 Display Devices: 段
    if not displays:
        for m in re.finditer(
            r"Display\s+(\d+):.*?DisplayInfo\{[^}]*?(?:name=\"([^\"]+)\")?",
            out, re.DOTALL
        ):
            did = m.group(1)
            if did in seen:
                continue
            try:
                if int(did) > SCRCPY_MAX_DISPLAY_ID:
                    continue
            except ValueError:
                continue
            seen.add(did)
            name = (m.group(2) or "").strip()
            if _is_virtual_display(name):
                continue
            displays.append((did, name or "Display"))

    if displays:
        return displays

    # 2. SurfaceFlinger 兜底, 但过滤 64-bit 物理 ID (scrcpy 不接受)
    out = adb_run(["shell", "dumpsys", "SurfaceFlinger", "--display-id"],
                  device=device, timeout=8)
    for m in re.finditer(r"Display\s+(\d+)\s*\(([^)]*)\)", out):
        did = m.group(1)
        try:
            if int(did) > SCRCPY_MAX_DISPLAY_ID:
                continue
        except ValueError:
            continue
        if did in seen:
            continue
        seen.add(did)
        name = m.group(2).strip()
        if _is_virtual_display(name):
            continue
        displays.append((did, name))

    if not displays:
        displays.append(("0", "Default"))
    return displays


# ============ 通用 LogText 控件 ============
class _LineGutter(tk.Canvas):
    """显示日志文本行号 (左侧装订线), 与 Text 滚动同步."""
    def __init__(self, master, text_widget, theme, **kw):
        super().__init__(master, width=56, highlightthickness=0,
                         bg=theme.get("gutter_bg", "#f0f0f0"),
                         takefocus=0, **kw)
        self.text = text_widget
        self.theme = theme
        # 字号比正文稍小, 颜色统一灰色
        self._font = tkfont.Font(family="Consolas", size=9)

    def set_theme(self, theme):
        self.theme = theme
        self.configure(bg=theme.get("gutter_bg", "#f0f0f0"))
        self.redraw()

    def set_font(self, family, size):
        try:
            self._font.configure(family=family, size=max(8, size - 1))
        except Exception:
            pass
        self.redraw()

    def redraw(self, *_):
        self.delete("all")
        try:
            i = self.text.index("@0,0")
        except tk.TclError:
            return
        w = self.winfo_width()
        last_logical = -1
        guard = 0
        while True:
            guard += 1
            if guard > 10000:
                break
            dline = self.text.dlineinfo(i)
            if dline is None:
                break
            y = dline[1]
            line_no = int(i.split(".")[0])
            # 仅在 logical 行首绘制行号 (避免 wrap 续行重复)
            if line_no != last_logical:
                self.create_text(
                    w - 4, y, anchor="ne",
                    text=str(line_no),
                    fill=self.theme.get("gutter_fg", "#888"),
                    font=self._font,
                )
                last_logical = line_no
            i = self.text.index(f"{i} +1display line")


class LogText(ttk.Frame):
    def __init__(self, master, theme=None, font_family="Consolas",
                 font_size=10, wrap_default=True, show_line_no=True,
                 monochrome=False, **kwargs):
        super().__init__(master, **kwargs)
        self.theme = theme or THEMES["浅色 (默认)"]
        self.font_family = font_family
        self.font_size = font_size
        self.highlight_keywords = []
        self.wrap_enabled = wrap_default
        self.show_line_no = show_line_no
        # monochrome: 不使用 V/D/I/W/E/F 等级配色, 全部用主题前景色
        self.monochrome = monochrome

        wrap_mode = tk.WORD if wrap_default else tk.NONE
        # === 关键: tk.Text 在某些 Linux Tk 8.6 + 字体组合下会段错误.
        # 解决: 先用最小参数创建 widget, 然后用 configure 单独设置, 失败也不致命. ===
        _stage(f"LogText: tk.Text(wrap={wrap_mode})")
        try:
            self.text = tk.Text(master=self, wrap=wrap_mode)
        except Exception as e:
            print(f"[warn] tk.Text 带 wrap 创建失败: {e}, 改用默认参数",
                  file=sys.stderr)
            self.text = tk.Text(master=self)
        _stage("LogText: tk.Text done")
        # 字体单独 configure (font 字符串失败时静默回退)
        try:
            self.text.configure(font=(self.font_family, self.font_size))
        except Exception as e:
            print(f"[warn] tk.Text font 配置失败 ({self.font_family}): {e}",
                  file=sys.stderr)
            try:
                self.text.configure(font=("TkFixedFont", self.font_size))
            except Exception:
                pass
        # 其它非关键属性, 失败静默忽略
        for opt in (("undo", False), ("spacing1", 0),
                    ("spacing3", 0), ("fg", "#000000")):
            try:
                self.text.configure(**{opt[0]: opt[1]})
            except Exception:
                pass
        # 行号装订线
        self.gutter = _LineGutter(self, self.text, self.theme)

        ysb = ttk.Scrollbar(self, orient=tk.VERTICAL,
                            command=self._on_yscroll)
        xsb = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.text.xview)
        self.text.configure(yscrollcommand=self._yset, xscrollcommand=xsb.set)
        self._ysb = ysb
        self._xsb = xsb

        # 布局: gutter | text | yscroll  /  _ | xscroll | _
        if show_line_no:
            self.gutter.grid(row=0, column=0, sticky="ns")
            self.text.grid(row=0, column=1, sticky="nsew")
            ysb.grid(row=0, column=2, sticky="ns")
            xsb.grid(row=1, column=1, sticky="ew")
            self.grid_columnconfigure(1, weight=1)
        else:
            self.text.grid(row=0, column=0, sticky="nsew")
            ysb.grid(row=0, column=1, sticky="ns")
            xsb.grid(row=1, column=0, sticky="ew")
            self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.apply_theme(self.theme)
        self._init_tags()
        self._init_context_menu()
        self.text.configure(state=tk.DISABLED)
        self.text.bind("<1>", lambda e: self.text.focus_set())
        # 滚动 / 尺寸变化时重绘行号
        self.text.bind("<Configure>", lambda e: self._schedule_gutter())
        self.text.bind("<MouseWheel>", lambda e: self._schedule_gutter())
        self.text.bind("<Button-4>", lambda e: self._schedule_gutter())
        self.text.bind("<Button-5>", lambda e: self._schedule_gutter())
        # 自动换行开关 (供外部使用): self.set_wrap(bool)
        self._gutter_after_id = None

    def _schedule_gutter(self):
        if not self.show_line_no:
            return
        if self._gutter_after_id:
            try:
                self.after_cancel(self._gutter_after_id)
            except Exception:
                pass
        self._gutter_after_id = self.after(20, self.gutter.redraw)

    def _yset(self, *args):
        self._ysb.set(*args)
        self._schedule_gutter()

    def _on_yscroll(self, *args):
        self.text.yview(*args)
        self._schedule_gutter()

    def set_wrap(self, enabled: bool):
        self.wrap_enabled = enabled
        self.text.configure(wrap=tk.WORD if enabled else tk.NONE)
        self._schedule_gutter()

    def _init_context_menu(self):
        m = tk.Menu(self.text, tearoff=0)
        m.add_command(label="▥ 复制选中", accelerator="Ctrl+C",
                      command=self._copy_selection)
        m.add_command(label="◉ 全选", accelerator="Ctrl+A",
                      command=self._select_all)
        m.add_command(label="▤ 复制全部", command=self._copy_all)
        m.add_separator()
        m.add_command(label="× 清空显示", command=self.clear)
        self._context_menu = m
        self.text.bind("<Button-3>", self._show_context_menu)
        self.text.bind("<Control-a>", lambda e: (self._select_all(), "break")[1])
        self.text.bind("<Control-A>", lambda e: (self._select_all(), "break")[1])
        self.text.bind("<Control-c>", lambda e: (self._copy_selection(), "break")[1])
        self.text.bind("<Control-C>", lambda e: (self._copy_selection(), "break")[1])

    def _show_context_menu(self, event):
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _copy_selection(self):
        try:
            sel = self.text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return
        if sel:
            self.clipboard_clear()
            self.clipboard_append(sel)

    def _copy_all(self):
        content = self.text.get("1.0", tk.END)
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)

    def _select_all(self):
        self.text.tag_add(tk.SEL, "1.0", tk.END + "-1c")
        self.text.mark_set(tk.INSERT, "1.0")

    def _init_tags(self):
        for lv, color in LEVEL_COLORS.items():
            if self.monochrome:
                # 单色模式: 不设 foreground, 文本沿用 widget 默认 fg (主题色)
                self.text.tag_configure(f"lv_{lv}")
            else:
                self.text.tag_configure(f"lv_{lv}", foreground=color)
        for i, (bg, fg) in enumerate(HIGHLIGHT_PALETTE):
            self.text.tag_configure(f"hl_{i}", background=bg, foreground=fg)
        self.text.tag_configure("jump_mark", background="#fff59d",
                                foreground="#000")
        self.text.tag_configure("notice", foreground="#9e9e9e",
                                font=(self.font_family, self.font_size, "italic"))

    def mark_line(self, line_no, scroll=True):
        self.text.tag_remove("jump_mark", "1.0", tk.END)
        start = f"{line_no}.0"
        end = f"{line_no}.end+1c"
        try:
            self.text.tag_add("jump_mark", start, end)
            if scroll:
                self.text.see(start)
        except tk.TclError:
            pass
        self._schedule_gutter()

    def apply_theme(self, theme):
        self.theme = theme
        is_dark = self._is_dark(theme.get("bg", "#fff"))
        fg = theme.get("fg", "#1f2328" if not is_dark else "#d4d4d4")
        self.text.configure(
            bg=theme["bg"], fg=fg,
            insertbackground=fg,
            selectbackground=theme["select"],
            selectforeground="#ffffff" if is_dark else fg,
        )
        # monochrome: 强制 lv_* 标签前景色 = 主题前景色 (覆盖等级配色)
        if self.monochrome:
            mono_fg = "#ffffff" if is_dark else "#000000"
            for lv in LEVEL_COLORS.keys():
                try:
                    self.text.tag_configure(f"lv_{lv}", foreground=mono_fg)
                except Exception:
                    pass
        if hasattr(self, "gutter"):
            gtheme = dict(theme)
            gtheme.setdefault("gutter_bg", "#2a2a2a" if is_dark else "#f0f0f0")
            gtheme.setdefault("gutter_fg", "#888" if is_dark else "#888")
            self.gutter.set_theme(gtheme)

    @staticmethod
    def _is_dark(hex_color):
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            return (r * 299 + g * 587 + b * 114) / 1000 < 128
        except Exception:
            return False

    def apply_font(self, family, size):
        self.font_family = family
        self.font_size = size
        self.text.configure(font=(family, size))
        if hasattr(self, "gutter"):
            self.gutter.set_font(family, size)

    def set_highlights(self, keywords, use_regex=False, case_sensitive=False):
        self.highlight_keywords = []
        for i, kw in enumerate(keywords[:len(HIGHLIGHT_PALETTE)]):
            if kw:
                self.highlight_keywords.append((kw, f"hl_{i}", use_regex, case_sensitive))

    def append_lines(self, lines, autoscroll=True):
        if not lines:
            return
        normalized = [ln if ln.endswith("\n") else ln + "\n" for ln in lines]
        block = "".join(normalized)
        self.text.configure(state=tk.NORMAL)
        # 限制 Text widget 最大行数, 防止行数过多导致 insert/tag_add 变慢
        max_lines = 20000
        cur_lines = int(self.text.index(tk.END + "-1c").split(".")[0])
        overflow = cur_lines + len(normalized) - max_lines
        if overflow > 0:
            self.text.delete("1.0", f"{overflow + 1}.0")
        start_index = self.text.index(tk.END + "-1c")
        start_line = int(start_index.split(".")[0])
        self.text.insert(tk.END, block)
        level_re = re.compile(r"^\d{2}-\d{2} \S+\s+\d+\s+\d+\s+([VDIWEF])\s")
        for i, ln in enumerate(normalized):
            m = level_re.match(ln)
            if m:
                ln_no = start_line + i
                self.text.tag_add(f"lv_{m.group(1)}", f"{ln_no}.0", f"{ln_no}.end")
        if self.highlight_keywords:
            self._apply_block_highlight(start_line, normalized)
        if autoscroll:
            self.text.see(tk.END)
        # 编辑模式下保持 NORMAL, 否则恢复 DISABLED
        if not getattr(self, "_user_editable", False):
            self.text.configure(state=tk.DISABLED)
        self._schedule_gutter()

    def _apply_block_highlight(self, start_line, normalized_lines):
        for kw, tag, use_re, cs in self.highlight_keywords:
            try:
                flags = 0 if cs else re.IGNORECASE
                pat = re.compile(kw if use_re else re.escape(kw), flags)
            except re.error:
                continue
            for i, ln in enumerate(normalized_lines):
                ln_no = start_line + i
                for mm in pat.finditer(ln):
                    self.text.tag_add(tag, f"{ln_no}.{mm.start()}",
                                      f"{ln_no}.{mm.end()}")

    def clear(self):
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        if not getattr(self, "_user_editable", False):
            self.text.configure(state=tk.DISABLED)
        self._schedule_gutter()

    # ===== 编辑模式 (Notepad++ 风格) =====
    def set_editable(self, editable, on_modified=None):
        """切换编辑模式: editable=True -> 可编辑且支持撤销; False -> 只读.
        on_modified: 回调函数, 当用户修改内容时触发 (无参数)."""
        self._user_editable = bool(editable)
        try:
            if editable:
                self.text.configure(state=tk.NORMAL, undo=True,
                                    autoseparators=True, maxundo=-1)
                self.text.bind("<Control-z>", lambda e: (self.text.edit_undo(), "break")[1])
                self.text.bind("<Control-Z>", lambda e: (self.text.edit_undo(), "break")[1])
                self.text.bind("<Control-y>", lambda e: (self.text.edit_redo(), "break")[1])
                self.text.bind("<Control-Y>", lambda e: (self.text.edit_redo(), "break")[1])
                if on_modified is not None:
                    def _on_mod(_e=None):
                        try:
                            if self.text.edit_modified():
                                on_modified()
                                self.text.edit_modified(False)
                        except Exception:
                            pass
                    self.text.bind("<<Modified>>", _on_mod)
            else:
                self.text.configure(state=tk.DISABLED)
                self.text.unbind("<<Modified>>")
        except Exception as e:
            print(f"[warn] set_editable({editable}) 失败: {e}", file=sys.stderr)

    def reset_undo(self):
        """重置 undo 栈 (加载新文件后调用, 避免一路 undo 到空)."""
        try:
            self.text.edit_reset()
            self.text.edit_modified(False)
        except Exception:
            pass


# ============ 实时 Logcat Tab ============
class LiveLogcatTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=4)
        self.app = app
        self.proc = None
        self.reader_thread = None
        self.line_queue = queue.Queue()
        self.running = False
        self.all_lines = deque(maxlen=200000)
        self.current_filter = ""
        self.use_regex = tk.BooleanVar(value=False)
        self.case_sensitive = tk.BooleanVar(value=False)
        self.auto_scroll = tk.BooleanVar(value=True)
        self._filter_after_id = None

        self._build()
        self.after(500, self._auto_set_level_d)
        self.after(100, self._poll_queue)
        # 自动监听设备热插拔: 后台轮询 adb devices, 变化时刷新 UI
        self._dev_signature = None  # 上次设备列表签名
        self._dev_monitor_running = True
        self.after(2000, self._poll_devices)

    def _build(self):
        _stage("LiveLogcatTab._build: top frame")
        top = ttk.Frame(self)
        top.pack(fill=tk.X, pady=(0, 4))

        _stage("LiveLogcatTab._build: device combo")
        ttk.Label(top, text="□ 设备:").pack(side=tk.LEFT)
        self.device_combo = ttk.Combobox(top, width=26, state="readonly")
        self.device_combo.pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="↻ 刷新", command=self._refresh_devices, width=9).pack(side=tk.LEFT)
        ttk.Button(top, text="⇌ 远程", command=self._adb_connect_remote, width=9).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="root", command=self._adb_root, width=6).pack(side=tk.LEFT, padx=2)
        # 投屏按钮: Accent 色 + ▶ 播放图标
        ttk.Button(top, text="▶ 投屏", command=self._launch_scrcpy,
                   style="Accent.TButton", width=10).pack(side=tk.LEFT, padx=2)
        # 录屏按钮: 用 tk.Button (非 ttk) 才能强制红色背景
        # (sv-ttk/Sun Valley 主题忽略 ttk Style 的 bg 配置)
        self.btn_record = tk.Button(
            top, text="● 录屏", command=self._toggle_record,
            bg="#d32f2f", fg="white",
            activebackground="#b71c1c", activeforeground="white",
            disabledforeground="#dddddd",
            relief=tk.FLAT, bd=0, padx=14, pady=4,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            highlightthickness=0,
        )
        self.btn_record.pack(side=tk.LEFT, padx=2, ipady=2)
        # 截屏按钮: 调 adb screencap
        ttk.Button(top, text="◉ 截屏", command=self._take_screenshot,
                   width=10).pack(side=tk.LEFT, padx=2)
        # 重置 ADB / 杀 scrcpy 残留: 投屏/录屏卡死后用这个恢复
        ttk.Button(top, text="⟳ 重置", command=self._reset_adb_scrcpy,
                   width=8).pack(side=tk.LEFT, padx=2)
        self._record_proc = None
        self._record_path = None

        # 第二行: 日志等级 + 抓取/清空/保存 (避免按钮被窗口宽度遮挡)
        top2 = ttk.Frame(self)
        top2.pack(fill=tk.X, pady=(0, 4))

        _stage("LiveLogcatTab._build: level combo")
        ttk.Label(top2, text="等级:").pack(side=tk.LEFT)
        self.level_combo = ttk.Combobox(top2, width=4, state="readonly", values=LOG_LEVELS)
        self.level_combo.set(DEFAULT_LEVEL)
        self.level_combo.pack(side=tk.LEFT, padx=4)
        # 选择后自动下发, 不需要点击应用按钮
        self.level_combo.bind("<<ComboboxSelected>>",
                              lambda e: self._apply_level())

        ttk.Separator(top2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        _stage("LiveLogcatTab._build: start btn")
        self.btn_start = ttk.Button(top2, text="▶ 开始抓取",
                                    style="Accent.TButton",
                                    command=self._toggle_capture, width=14)
        self.btn_start.pack(side=tk.LEFT, padx=2)
        ttk.Button(top2, text="× 清空", command=self._clear_log, width=9).pack(side=tk.LEFT, padx=2)
        ttk.Button(top2, text="▽ 保存", command=self._save_log, width=9).pack(side=tk.LEFT, padx=2)

        _stage("LiveLogcatTab._build: filter row")
        flt = ttk.Frame(self)
        flt.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(flt, text="⌕ 过滤:").pack(side=tk.LEFT)
        self.filter_entry = ttk.Entry(flt, width=36)
        self.filter_entry.pack(side=tk.LEFT, padx=4)
        self.filter_entry.bind("<KeyRelease>", lambda e: self._apply_filter_debounce())
        _stage("LiveLogcatTab._build: checkbuttons")
        make_checkbutton(flt, text="正则", variable=self.use_regex,
                        command=self._apply_filter).pack(side=tk.LEFT)
        make_checkbutton(flt, text="区分大小写", variable=self.case_sensitive,
                        command=self._apply_filter).pack(side=tk.LEFT)
        ttk.Separator(flt, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(flt, text="◐ 高亮(逗号分隔):").pack(side=tk.LEFT)
        self.hl_entry = ttk.Entry(flt, width=30)
        self.hl_entry.pack(side=tk.LEFT, padx=4)
        ttk.Button(flt, text="应用高亮", command=self._apply_highlight).pack(side=tk.LEFT)
        make_checkbutton(flt, text="▦ 自动滚动", variable=self.auto_scroll).pack(side=tk.LEFT, padx=8)

        _stage("LiveLogcatTab._build: LogText")
        # === Linux 解决方案: 在创建 tk.Text 前强制刷新 Tk 状态 ===
        # 某些 Linux Tk 8.6 上, 大量 ttk widget 创建后立即创建 tk.Text 会段错误.
        # 调用 update_idletasks() 让 Tk 处理完所有挂起任务后再创建.
        try:
            self.update_idletasks()
        except Exception:
            pass
        self.log_view = LogText(self, theme=self.app.current_theme,
                                font_family=self.app.font_family,
                                font_size=self.app.font_size)
        self.log_view.pack(fill=tk.BOTH, expand=True)
        _stage("LiveLogcatTab._build: done")

        self._refresh_devices()

    def _refresh_devices(self):
        devs = adb_devices()
        items = [f"{s} ({st})" for s, st in devs]
        cur = self.device_combo.get()
        self.device_combo["values"] = items
        # 保持原选中项 (若仍存在)
        if cur in items:
            self.device_combo.set(cur)
        elif items:
            self.device_combo.current(0)
        else:
            self.device_combo.set("")
        self._dev_signature = tuple(items)
        self.app.set_status(f"检测到 {len(devs)} 个设备")

    def _poll_devices(self):
        """后台监听设备变化, 不阻塞 UI."""
        if not self._dev_monitor_running:
            return
        def _worker():
            try:
                devs = adb_devices()
                items = [f"{s} ({st})" for s, st in devs]
                sig = tuple(items)
                if sig != self._dev_signature:
                    self.after(0, lambda: self._on_devices_changed(items, sig))
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()
        # 间隔 2 秒
        self.after(2000, self._poll_devices)

    def _on_devices_changed(self, items, sig):
        cur = self.device_combo.get()
        prev_count = len(self._dev_signature) if self._dev_signature else 0
        self._dev_signature = sig
        self.device_combo["values"] = items
        if cur in items:
            self.device_combo.set(cur)
        elif items:
            self.device_combo.current(0)
        else:
            self.device_combo.set("")
        new_count = len(items)
        if new_count > prev_count:
            self.app.set_status(f"⏻ 检测到新设备接入 (当前 {new_count} 台)")
        elif new_count < prev_count:
            self.app.set_status(f"❌ 检测到设备断开 (当前 {new_count} 台)")
        else:
            self.app.set_status(f"设备状态变化 (当前 {new_count} 台)")

    def _selected_device(self):
        s = self.device_combo.get()
        return s.split(" ")[0] if s else None

    def _adb_connect_remote(self):
        """弹窗输入 IP:PORT, 通过 adb connect 远程连接设备."""
        from tkinter import simpledialog
        addr = simpledialog.askstring(
            APP_TITLE, "输入设备 IP:PORT (如 192.168.1.100:5555):",
            parent=self)
        if not addr or not addr.strip():
            return
        addr = addr.strip()
        if ":" not in addr:
            addr += ":5555"
        self.app.set_status(f"正在连接 {addr}...")
        def _do():
            adb_bin = os.environ.get("ADB", "adb")
            try:
                r = subprocess.run(
                    [adb_bin, "connect", addr],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=15, creationflags=_SUBPROC_FLAGS,
                )
                msg = r.stdout.decode("utf-8", errors="replace").strip()
            except Exception as e:
                msg = str(e)
            self.after(0, lambda: self.app.set_status(f"adb connect: {msg}"))
            time.sleep(1)
            self.after(0, self._refresh_devices)
        threading.Thread(target=_do, daemon=True).start()

    def _adb_root(self):
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning(APP_TITLE, "请先选择设备")
            return
        self.app.set_status("adb root...")
        threading.Thread(target=self._do_root, args=(dev,), daemon=True).start()

    def _do_root(self, dev):
        adb_run(["root"], device=dev, timeout=15)
        time.sleep(1)
        adb_run(["wait-for-device"], device=dev, timeout=15)
        adb_run(["shell", "setprop", "persist.log.tag", "D"], device=dev)
        self.app.set_status(f"adb root 完成, log 等级 D ({dev})")

    def _auto_set_level_d(self):
        dev = self._selected_device()
        if not dev:
            return
        threading.Thread(target=self._do_set_level, args=("D",), daemon=True).start()

    def _apply_level(self):
        threading.Thread(target=self._do_set_level,
                         args=(self.level_combo.get(),), daemon=True).start()

    def _do_set_level(self, lv):
        dev = self._selected_device()
        if not dev:
            return
        adb_run(["shell", "setprop", "persist.log.tag", lv], device=dev, timeout=8)
        self.app.set_status(f"已设置 persist.log.tag={lv}")

    # ===== 重置 ADB / 杀 scrcpy 残留 =====
    def _reset_adb_scrcpy(self):
        """投屏/录屏卡死时, 强杀残留 scrcpy 进程并重启 adb-server.
        通常能让"再也起不来"的状态恢复."""
        if not messagebox.askyesno(
            APP_TITLE,
            "将执行:\n"
            "  1. 强杀所有 scrcpy 进程 (taskkill / pkill)\n"
            "  2. adb kill-server\n"
            "  3. adb start-server\n\n"
            "用于投屏/录屏卡死后的恢复. 是否继续?"):
            return
        self.app.set_status("正在重置 ADB / scrcpy ...")
        threading.Thread(target=self._do_reset_adb_scrcpy,
                         daemon=True).start()

    def _do_reset_adb_scrcpy(self):
        is_win = platform.system() == "Windows"
        adb_bin = os.environ.get("ADB", "adb")
        cflags = _SUBPROC_FLAGS if is_win else 0
        msgs = []
        # 1) 杀所有 scrcpy 进程 (我们自己也可能有残留)
        try:
            if is_win:
                r = subprocess.run(
                    ["taskkill", "/F", "/IM", "scrcpy.exe", "/T"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=10, creationflags=cflags)
                msgs.append(f"taskkill scrcpy: rc={r.returncode}")
            else:
                r = subprocess.run(
                    ["pkill", "-9", "-f", "scrcpy"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=10)
                msgs.append(f"pkill scrcpy: rc={r.returncode}")
        except Exception as e:
            msgs.append(f"杀 scrcpy 失败: {e}")
        # 也清掉自己跟踪的 record proc
        rp = self._record_proc
        if rp is not None:
            try: self._kill_proc_tree(rp)
            except Exception: pass
            self._record_proc = None
            self._record_stopping = False
            try: self.btn_record.config(text="● 录屏", state="normal")
            except Exception: pass
        # 2) adb kill-server
        try:
            r = subprocess.run(
                [adb_bin, "kill-server"], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=10, creationflags=cflags)
            msgs.append(f"adb kill-server: rc={r.returncode}")
        except Exception as e:
            msgs.append(f"adb kill-server 失败: {e}")
        time.sleep(0.5)
        # 3) adb start-server
        try:
            r = subprocess.run(
                [adb_bin, "start-server"], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=15, creationflags=cflags)
            msgs.append(f"adb start-server: rc={r.returncode}")
        except Exception as e:
            msgs.append(f"adb start-server 失败: {e}")
        result = "\n".join(msgs)
        def _finish():
            self.app.set_status("✅ 重置完成, 可重新尝试投屏/录屏")
            messagebox.showinfo(APP_TITLE, f"重置完成:\n\n{result}")
            self._refresh_devices()
        self.after(0, _finish)

    def _launch_scrcpy(self):
        if SCRCPY_BIN is None:
            messagebox.showwarning(
                APP_TITLE,
                "未检测到 scrcpy.\n\n"
                "Windows: 把 scrcpy 文件夹放到本工具同级目录, 或加入系统 PATH.\n"
                "        下载: https://github.com/Genymobile/scrcpy/releases\n"
                "Ubuntu:  sudo apt install scrcpy  或  sudo snap install scrcpy"
            )
            return
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning(APP_TITLE, "请先选择设备")
            return
        self.app.set_status("正在查询设备屏幕...")
        threading.Thread(target=self._do_scrcpy, args=(dev,), daemon=True).start()

    def _do_scrcpy(self, dev):
        displays = list_displays(dev)
        self.after(0, lambda: self._scrcpy_with_select(dev, displays))

    def _scrcpy_with_select(self, dev, displays):
        if not displays:
            # 未检测到任何 display, 尝试默认 display 0
            self._spawn_scrcpy(dev, "0")
            return
        if len(displays) == 1:
            # 只有一个 display, 仍弹窗让用户确认
            pass
        dlg = tk.Toplevel(self)
        dlg.title("选择投屏的屏幕")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.resizable(False, False)
        msg = f"设备 {dev} 检测到 {len(displays)} 个屏幕" if len(displays) > 1 else f"设备 {dev}"
        ttk.Label(dlg, text=f"{msg}，请选择:", padding=10).pack()
        var = tk.StringVar(value=displays[0][0])
        for did, info in displays:
            make_radiobutton(dlg, text=f"Display {did}  -  {info}",
                            variable=var, value=did).pack(anchor=tk.W, padx=20)
        btns = ttk.Frame(dlg, padding=10)
        btns.pack()

        def on_ok():
            display_id = var.get()
            dlg.destroy()
            self._spawn_scrcpy(dev, display_id)
        ttk.Button(btns, text="投屏", style="Accent.TButton",
                   command=on_ok).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.LEFT)
        # 居中显示在主窗口上方
        dlg.update_idletasks()
        try:
            root = self.winfo_toplevel()
            rx, ry = root.winfo_rootx(), root.winfo_rooty()
            rw, rh = root.winfo_width(), root.winfo_height()
            dw, dh = dlg.winfo_width(), dlg.winfo_height()
            x = rx + (rw - dw) // 2
            y = ry + (rh - dh) // 2
            dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    @staticmethod
    def _show_copyable_error(title, message):
        """用 Toplevel+Text 替代 messagebox.showerror, 文本可鼠标选中复制."""
        dlg = tk.Toplevel()
        dlg.title(title)
        dlg.geometry("640x400")
        dlg.resizable(True, True)
        dlg.attributes("-topmost", True)
        txt = tk.Text(dlg, wrap=tk.WORD, font=("Consolas", 10), bg="#fff8f0")
        txt.insert(tk.END, message)
        txt.config(state=tk.DISABLED)  # 只读但可选中复制
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=(0, 8))
        def _copy_all():
            dlg.clipboard_clear()
            dlg.clipboard_append(message)
            dlg.update()
        ttk.Button(btn_frame, text="复制全部", command=_copy_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="关闭", command=dlg.destroy).pack(side=tk.LEFT, padx=4)

    @staticmethod
    def _log_scrcpy_error(label, rc, display_id, msg):
        """把 scrcpy/录屏 错误写到日志文件 scrcpy_error.log."""
        log_path = os.path.join(RESOURCE_DIR, "scrcpy_error.log")
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            entry = (
                f"\n{'='*60}\n"
                f"[{ts}] {label}\n"
                f"exit={rc}, display={display_id}\n"
                f"scrcpy: {SCRCPY_BIN}\n"
                f"ADB: {os.environ.get('ADB','(unset)')}\n"
                f"output:\n{msg}\n"
            )
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass
        return log_path

    def _spawn_scrcpy(self, dev, display_id, _retried=False):
        # 先清理上一次的 scrcpy 进程
        old = getattr(self, "_scrcpy_proc", None)
        if old and old.poll() is None:
            try:
                old.terminate()
            except Exception:
                try:
                    old.kill()
                except Exception:
                    pass
        scrcpy_bin = SCRCPY_BIN or "scrcpy"
        # cwd 设为 scrcpy.exe 所在目录, 让 scrcpy 能找到同目录的 server jar / adb
        scrcpy_cwd = os.path.dirname(scrcpy_bin) if scrcpy_bin and os.path.isabs(scrcpy_bin) else None
        title = f"投屏 [{dev}] Display {display_id}"
        cmd = [scrcpy_bin,
               "--no-audio",        # 避免 MediaCodec audio 编码异常
               "--window-title", title,
               ]
        # display_id=0 时不传 --display-id (匹配参考工具行为;
        # 某些 scrcpy 版本 + GVM 设备, 明确指定 --display-id 0 会走
        # 不同的编码路径导致 CodecException)
        if str(display_id) != "0":
            cmd += ["--display-id", str(display_id)]
        if dev:
            cmd += ["-s", dev]
        try:
            if platform.system() == "Windows":
                # 隐藏 scrcpy 的控制台窗口 (它有自己的 GUI 不需要 console)
                CREATE_NO_WINDOW = 0x08000000
                proc = subprocess.Popen(
                    cmd,
                    creationflags=CREATE_NO_WINDOW,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=scrcpy_cwd,
                )
            else:
                # Linux: 不捕获 stdout (匹配参考工具行为, 避免管道干扰 scrcpy)
                proc = subprocess.Popen(cmd, cwd=scrcpy_cwd)
            self.app.set_status(f"scrcpy 已启动 (display={display_id})")
            self._scrcpy_proc = proc
            # 后台监测启动是否成功 (3秒内退出视为失败), 失败时弹窗显示真实错误
            threading.Thread(
                target=self._watch_scrcpy,
                args=(proc, display_id, dev, _retried),
                daemon=True,
            ).start()
        except Exception as e:
            err_text = f"启动 scrcpy 失败:\n{e}\n\nscrcpy 路径: {scrcpy_bin}"
            self._show_copyable_error(APP_TITLE + " - 投屏失败", err_text)

    def _watch_scrcpy(self, proc, display_id, dev=None, _retried=False):
        has_pipe = proc.stdout is not None
        try:
            if has_pipe:
                out, _ = proc.communicate(timeout=5)
            else:
                proc.wait(timeout=5)
                out = b""
        except subprocess.TimeoutExpired:
            # 5 秒未退出, 视为启动成功; 后台静默等进程自然退出
            if has_pipe:
                try:
                    proc.communicate()
                except Exception:
                    pass
            else:
                try:
                    proc.wait()
                except Exception:
                    pass
            return
        # 进程已结束; 提取错误信息
        rc = proc.returncode
        # rc==0 通常表示用户主动关闭窗口, 不算失败
        if rc == 0:
            self.after(0, lambda: self.app.set_status("投屏已关闭"))
            return
        msg = ""
        try:
            msg = (out or b"").decode("utf-8", errors="replace").strip()
        except Exception:
            pass
        if not msg:
            msg = "(scrcpy 未输出错误信息)"
        # 截取后 1500 字, 避免弹窗过长
        msg_short = msg[-1500:]
        self.after(0, lambda: self.app.set_status(
            f"scrcpy 启动失败 (display={display_id}, exit={rc})"))
        # 自动恢复: 第一次失败 -> 静默重置 adb 后重试一次
        if dev and not _retried:
            self.after(0, lambda: self.app.set_status(
                "scrcpy 启动失败, 正在自动重置 adb 后重试..."))
            def _retry():
                try:
                    self._do_reset_adb_silent()
                except Exception:
                    pass
                self.after(0, lambda: self._spawn_scrcpy(dev, display_id, _retried=True))
            threading.Thread(target=_retry, daemon=True).start()
            return
        # 只有非 0 退出才弹窗; rc==0 可能是用户主动关闭
        if rc != 0:
            log_path = self._log_scrcpy_error("投屏失败", rc, display_id, msg)
            err_text = (
                f"scrcpy 启动失败 (exit={rc})\n"
                f"display-id={display_id}\n\n"
                f"建议: 点击工具栏 [⟳ 重置] 按钮后重试\n\n"
                f"可能原因:\n"
                f"  • adb 与 scrcpy 版本不匹配 (scrcpy 自带 adb 与系统 adb 冲突)\n"
                f"  • 设备未授权 USB 调试 / 需要允许传输文件\n"
                f"  • 设备 Android 版本 < 5.0\n\n"
                f"scrcpy 输出 (可 Ctrl+C 复制):\n{msg_short}\n\n"
                f"完整日志: {log_path}"
            )
            self.after(0, lambda: self._show_copyable_error(APP_TITLE + " - 投屏失败", err_text))

    def _do_reset_adb_silent(self):
        """静默版重置 (供 _watch_scrcpy 自动重试用)."""
        is_win = platform.system() == "Windows"
        adb_bin = os.environ.get("ADB", "adb")
        cflags = _SUBPROC_FLAGS if is_win else 0
        try:
            if is_win:
                subprocess.run(["taskkill", "/F", "/IM", "scrcpy.exe", "/T"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10, creationflags=cflags)
            else:
                subprocess.run(["pkill", "-9", "-f", "scrcpy"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10)
        except Exception:
            pass
        try:
            subprocess.run([adb_bin, "kill-server"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, creationflags=cflags)
        except Exception:
            pass
        time.sleep(1)
        try:
            subprocess.run([adb_bin, "start-server"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15, creationflags=cflags)
        except Exception:
            pass
        time.sleep(1)

    def _toggle_capture(self):
        if self.running:
            self._stop()
        else:
            self._start()

    # ===== 屏幕录制 (adb shell screenrecord) =====
    # 使用设备端 screenrecord 命令, 录制到 /sdcard/ 后 pull 回本地
    # (比 scrcpy --record 兼容性更好, 不依赖硬件编码器)
    def _toggle_record(self):
        if self._record_proc is not None:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning(APP_TITLE, "请先选择设备")
            return
        # 查询 display 列表
        self.app.set_status("正在查询设备屏幕 (录制)...")
        threading.Thread(target=self._do_record_select, args=(dev,),
                         daemon=True).start()

    def _do_record_select(self, dev):
        displays = list_displays(dev)
        self.after(0, lambda: self._record_with_select(dev, displays))

    def _record_with_select(self, dev, displays):
        if len(displays) <= 1:
            display_id = displays[0][0] if displays else "0"
            self._begin_record(dev, display_id)
            return
        dlg = tk.Toplevel(self)
        dlg.title("选择要录制的屏幕")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.resizable(False, False)
        ttk.Label(dlg, text=f"设备 {dev} 检测到多个屏幕, 请选择要录制的:",
                  padding=10).pack()
        var = tk.StringVar(value=displays[0][0])
        for did, info in displays:
            make_radiobutton(dlg, text=f"Display {did}  -  {info}",
                            variable=var, value=did).pack(anchor=tk.W, padx=20)
        btns = ttk.Frame(dlg, padding=10)
        btns.pack()

        def on_ok():
            display_id = var.get()
            dlg.destroy()
            self._begin_record(dev, display_id)
        ttk.Button(btns, text="开始录制", style="Accent.TButton",
                   command=on_ok).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.LEFT)
        dlg.update_idletasks()
        try:
            root = self.winfo_toplevel()
            rx, ry = root.winfo_rootx(), root.winfo_rooty()
            rw = root.winfo_width()
            dw = dlg.winfo_width()
            x = rx + (rw - dw) // 2
            y = ry + 80
            dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def _begin_record(self, dev, display_id):
        """直接开始录制, 不弹路径选择框 (录完后自动保存到 video/ 目录)."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        video_dir = os.path.join(RESOURCE_DIR, "video")
        os.makedirs(video_dir, exist_ok=True)
        local_file = os.path.join(video_dir,
                                  f"record_{dev.replace(':', '_')}_d{display_id}_{ts}.mp4")
        device_file = f"/sdcard/adb_record_{ts}.mp4"

        adb_bin = os.environ.get("ADB", "adb")
        cmd = [adb_bin, "-s", dev, "shell", "screenrecord"]
        # 双屏拼接设备 screenrecord 默认录制整个合成屏幕(如5120x1440),
        # 导致视频两侧有黑边; 用 wm size 获取单屏分辨率并传 --size 限制.
        try:
            wm_out = subprocess.check_output(
                [adb_bin, "-s", dev, "shell", "wm", "size"],
                timeout=5, creationflags=_SUBPROC_FLAGS if platform.system() == "Windows" else 0,
            ).decode(errors="replace")
            m = re.search(r"(\d+x\d+)", wm_out)
            if m:
                cmd += ["--size", m.group(1)]
        except Exception:
            pass
        cmd.append(device_file)

        self._record_dev = dev
        self._record_display_id = display_id
        self._record_device_file = device_file
        self._record_local_file = local_file
        self._record_start_time = time.time()

        try:
            # 不捕获 stdout (匹配参考工具; 避免管道阻塞导致 screenrecord 挂起)
            proc = subprocess.Popen(
                cmd,
                creationflags=_SUBPROC_FLAGS if platform.system() == "Windows" else 0,
            )
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"启动录屏失败: {e}")
            return

        self._record_proc = proc
        self.btn_record.config(text="■ 停止录制", bg="#E65100")
        self.app.set_status(
            f"● 录制中 (display={display_id}) -> {local_file}")
        # 后台监测进程退出 (screenrecord 最长 3 分钟自动停止)
        threading.Thread(target=self._watch_record,
                         args=(proc,), daemon=True).start()

    def _stop_record(self):
        proc = self._record_proc
        if proc is None:
            return
        if getattr(self, "_record_stopping", False):
            return
        self._record_stopping = True
        self.app.set_status("正在停止录制...")
        try:
            self.btn_record.config(text="… 正在停止", state="disabled")
        except Exception:
            pass
        threading.Thread(target=self._do_stop_record, daemon=True).start()

    def _do_stop_record(self):
        dev = getattr(self, "_record_dev", None)
        adb_bin = os.environ.get("ADB", "adb")
        cflags = _SUBPROC_FLAGS if platform.system() == "Windows" else 0
        # 确保至少录制 3 秒, 避免 screenrecord 来不及封装 MP4 moov atom
        elapsed = time.time() - getattr(self, "_record_start_time", 0)
        if elapsed < 3:
            time.sleep(3 - elapsed)
        # screenrecord 需要通过设备端 kill -INT 让它正常封装 MP4 尾
        if dev:
            try:
                # 使用 shell=True 匹配参考工具; 确保 pkill 命令在设备 shell 中正确执行
                kill_cmd = f'"{adb_bin}" -s {dev} shell "pkill -INT screenrecord"'
                subprocess.run(
                    kill_cmd, shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5, creationflags=cflags,
                )
            except Exception:
                pass
        proc = self._record_proc
        if proc:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
        # screenrecord 完成后, 等 2 秒让设备端文件落盘
        time.sleep(2)
        self._pull_record_file()

    def _pull_record_file(self):
        """从设备 pull 录制文件到本地."""
        dev = getattr(self, "_record_dev", None)
        device_file = getattr(self, "_record_device_file", None)
        local_file = getattr(self, "_record_local_file", None)
        if not dev or not device_file or not local_file:
            self._record_finish_ui(False, "(无录制信息)")
            return
        adb_bin = os.environ.get("ADB", "adb")
        cflags = _SUBPROC_FLAGS if platform.system() == "Windows" else 0
        self.after(0, lambda: self.app.set_status("正在从设备拉取视频..."))
        try:
            r = subprocess.run(
                [adb_bin, "-s", dev, "pull", device_file, local_file],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=120, creationflags=cflags,
            )
        except Exception as e:
            self._record_finish_ui(False, f"pull 失败: {e}")
            return
        # 清理设备端文件
        try:
            subprocess.run(
                [adb_bin, "-s", dev, "shell", "rm", "-f", device_file],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, creationflags=cflags,
            )
        except Exception:
            pass

        if not os.path.isfile(local_file) or os.path.getsize(local_file) == 0:
            pull_msg = (r.stdout or b"").decode("utf-8", errors="replace")
            self._record_finish_ui(False, f"文件为空或 pull 失败:\n{pull_msg[-500:]}")
            return

        size_mb = os.path.getsize(local_file) / 1024 / 1024
        self._record_finish_ui(True, "", local_file, size_mb, "")

    def _record_finish_ui(self, success, err_msg="", path="", size_mb=0, wm_status=""):
        self._record_proc = None
        self._record_stopping = False

        def _finish():
            self.btn_record.config(text="● 录屏", bg="#d32f2f", state="normal")
            if success:
                self.app.set_status(f"✅ 录屏已保存: {path} ({size_mb:.1f} MB)")
                if messagebox.askyesno(
                    APP_TITLE,
                    f"录屏已保存:\n{path}\n\n"
                    f"大小: {size_mb:.1f} MB\n"

                    f"是否打开文件所在文件夹?"):
                    self._open_path_folder(path)
            else:
                self.app.set_status("❌ 录屏失败")
                display_id = getattr(self, "_record_display_id", "?")
                log_path = self._log_scrcpy_error("录屏失败", -1, display_id, err_msg)
                self._show_copyable_error(
                    APP_TITLE + " - 录屏失败",
                    f"录屏失败\n\n{err_msg}\n\n日志: {log_path}")
        self.after(0, _finish)

    def _watch_record(self, proc):
        """后台等待 screenrecord 进程退出 (自然结束或被 _do_stop_record kill)."""
        try:
            proc.wait(timeout=3600)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        # 如果是自然超时退出 (screenrecord 默认最长3分钟), 也需 pull
        if not getattr(self, "_record_stopping", False):
            self._record_stopping = True
            time.sleep(1)
            self._pull_record_file()

    @staticmethod
    def _open_path_folder(path):
        try:
            folder = os.path.dirname(os.path.abspath(path))
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", "/select,", os.path.abspath(path)])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            print(f"[warn] 打开文件夹失败: {e}", file=sys.stderr)

    # ===== 截屏 (adb screencap) =====
    def _take_screenshot(self):
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning(APP_TITLE, "请先选择设备")
            return
        ts = time.strftime("%Y%m%d_%H%M%S")
        # 保存到当前目录下的 截图/ 子目录
        screenshot_dir = os.path.join(RESOURCE_DIR, "截图")
        os.makedirs(screenshot_dir, exist_ok=True)
        dev_name = dev.replace(":", "_").replace(".", "_")
        filename = f"截图_{dev_name}_{ts}.png"
        path = os.path.join(screenshot_dir, filename)
        self.app.set_status(f"正在截屏 {dev}...")
        threading.Thread(target=self._do_screenshot,
                         args=(dev, path), daemon=True).start()

    def _do_screenshot(self, dev, path):
        adb_bin = os.environ.get("ADB", "adb")
        cflags = _SUBPROC_FLAGS if platform.system() == "Windows" else 0
        # 方案 A: exec-out 直接拿 stdout 二进制 (Linux/macOS 可靠).
        # Windows 上某些 adb 版本会做 CR/LF 翻译损坏 PNG, 失败则回退方案 B.
        data = b""
        err_a = ""
        try:
            proc = subprocess.run(
                [adb_bin, "-s", dev, "exec-out", "screencap", "-p"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=20, creationflags=cflags,
            )
            data = proc.stdout or b""
            err_a = (proc.stderr or b"").decode("utf-8", errors="replace")
        except Exception as e:
            err_a = str(e)

        if not (data and data.startswith(b"\x89PNG")):
            # 方案 B: 设备端落盘 + adb pull (最可靠, 不受 stdout 编码影响)
            remote = f"/data/local/tmp/_scrshot_{int(time.time()*1000)}.png"
            try:
                p1 = subprocess.run(
                    [adb_bin, "-s", dev, "shell",
                     f"screencap -p {remote}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=20, creationflags=cflags,
                )
                if p1.returncode != 0:
                    raise RuntimeError(
                        (p1.stderr or b"").decode("utf-8", errors="replace"))
                p2 = subprocess.run(
                    [adb_bin, "-s", dev, "pull", remote, path],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=30, creationflags=cflags,
                )
                # 清理
                subprocess.run(
                    [adb_bin, "-s", dev, "shell", f"rm -f {remote}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10, creationflags=cflags,
                )
                if p2.returncode != 0 or not os.path.isfile(path) or os.path.getsize(path) == 0:
                    err_b = (p2.stderr or b"").decode("utf-8", errors="replace")
                    self.after(0, lambda: messagebox.showerror(
                        APP_TITLE,
                        f"截屏失败:\n方案A(exec-out)未返回PNG: {err_a[-200:]}\n"
                        f"方案B(pull)失败: {err_b[-300:]}"))
                    return
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    APP_TITLE, f"截屏失败: {e}"))
                return
        else:
            try:
                with open(path, "wb") as f:
                    f.write(data)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(APP_TITLE, f"写文件失败: {e}"))
                return
        size_kb = os.path.getsize(path) / 1024

        def _finish():
            self.app.set_status(f"✅ 截屏已保存: {path} ({size_kb:.1f} KB)")
            if messagebox.askyesno(
                APP_TITLE,
                f"截屏已保存:\n{path}\n\n大小: {size_kb:.1f} KB\n\n是否打开文件所在文件夹?"):
                self._open_path_folder(path)
        self.after(0, _finish)


    def _start(self):
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning(APP_TITLE, "请先选择设备")
            return
        adb_run(["logcat", "-c"], device=dev, timeout=5)
        cmd = ["adb", "-s", dev, "logcat", "-v", "threadtime"]
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, encoding="utf-8", errors="replace",
                creationflags=_SUBPROC_FLAGS,
            )
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"启动 logcat 失败: {e}")
            return
        self.running = True
        self.btn_start.config(text="⏹ 停止抓取")
        self.app.set_status(f"正在抓取 {dev}")
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

    def _stop(self):
        # 1) 先标记停止 (reader 循环看到后立即退出)
        self.running = False
        # 2) 强杀进程 (Windows 下 terminate 不一定立即结束)
        proc = self.proc
        self.proc = None
        if proc:
            try:
                proc.kill()
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
        # 3) 立即清空队列, 防止残余日志继续刷新到界面
        try:
            while True:
                self.line_queue.get_nowait()
        except queue.Empty:
            pass
        self.btn_start.config(text="▶ 开始抓取")
        self.app.set_status("已停止")

    def _reader_loop(self):
        proc = self.proc
        if not proc or not proc.stdout:
            return
        # 过滤非 BMP Unicode 字符, 避免 X11 RENDER BadLength 崩溃 (Ubuntu 20.04)
        import re
        _non_bmp_re = re.compile(r'[\U00010000-\U0010FFFF]')
        try:
            for line in iter(proc.stdout.readline, ""):
                if not self.running:
                    break
                self.line_queue.put(_non_bmp_re.sub('?', line))
        except Exception:
            pass

    def _poll_queue(self):
        # 已停止时不再渲染, 仅丢弃残余数据, 防止"停止后界面还在刷新"
        if not self.running:
            try:
                while True:
                    self.line_queue.get_nowait()
            except queue.Empty:
                pass
            self.after(50, self._poll_queue)
            return
        batch = []
        try:
            for _ in range(500):
                batch.append(self.line_queue.get_nowait())
        except queue.Empty:
            pass
        if batch:
            for ln in batch:
                self.all_lines.append(ln)
            self._render(batch)
        self.after(50, self._poll_queue)

    def _render(self, lines):
        filtered = [ln for ln in lines if self._match(ln)]
        if filtered:
            self.log_view.append_lines(filtered, autoscroll=self.auto_scroll.get())

    def _match(self, line):
        kw = self.current_filter
        if not kw:
            return True
        try:
            if self.use_regex.get():
                flags = 0 if self.case_sensitive.get() else re.IGNORECASE
                return re.search(kw, line, flags) is not None
            if self.case_sensitive.get():
                return kw in line
            return kw.lower() in line.lower()
        except re.error:
            return True

    def _apply_filter_debounce(self):
        if self._filter_after_id:
            self.after_cancel(self._filter_after_id)
        self._filter_after_id = self.after(300, self._apply_filter)

    def _apply_filter(self):
        self.current_filter = self.filter_entry.get()
        self.log_view.clear()
        all_lines = list(self.all_lines)
        chunk = 1000
        for i in range(0, len(all_lines), chunk):
            self._render(all_lines[i:i + chunk])
        self.app.set_status(f"过滤: {self.current_filter or '(无)'}")

    def _apply_highlight(self):
        kws = [k.strip() for k in self.hl_entry.get().split(",") if k.strip()]
        self.log_view.set_highlights(kws, self.use_regex.get(), self.case_sensitive.get())
        self._apply_filter()

    def _clear_log(self):
        self.all_lines.clear()
        self.log_view.clear()
        self.app.set_status("已清空")

    def _save_log(self):
        # 默认保存到当前目录的 log/ 子目录
        log_dir = os.path.join(RESOURCE_DIR, "log")
        os.makedirs(log_dir, exist_ok=True)
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialdir=log_dir,
            initialfile=f"logcat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            filetypes=[("Text", "*.txt *.log"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(self.all_lines)
            self.app.set_status(f"已保存: {path}")
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def stop(self):
        self._dev_monitor_running = False
        self._stop()


# ============ 文件查看 Tab (容器: 多文件子标签) ============
class FileViewer(ttk.Frame):
    """单个文件查看器: 原始 + 过滤双视图, 支持双击过滤行跳转原始行."""
    MAX_INDEX_LINES = 5_000_000
    INITIAL_DISPLAY = 200_000  # 渲染上限, 大于此值时仅渲染前 N 行
    RENDER_CHUNK = 4000        # 每帧渲染行数, 控制 UI 流畅度
    RENDER_INTERVAL_MS = 15    # 帧间隔, 让出主循环

    def __init__(self, master, app, container):
        super().__init__(master, padding=4)
        self.app = app
        self.container = container  # FileViewerTab, 用于状态/标签更新
        self.lines = []
        self.file_path = None
        self.use_regex = tk.BooleanVar(value=False)
        self.case_sensitive = tk.BooleanVar(value=False)
        self.filtered_orig_idx = []  # 过滤后每行 -> 原始 0-based 行号
        self._filter_after_id = None
        self._rendered_count = 0  # 原始视图已渲染行数 (用于按需扩展)
        self._build()

    def _build(self):
        flt = ttk.Frame(self)
        flt.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(flt, text="� 文件:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value="(未打开)")
        ttk.Label(flt, textvariable=self.path_var,
                  foreground="#1565C0").pack(side=tk.LEFT, padx=4)
        ttk.Separator(flt, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(flt, text="⌕ 查找 (Ctrl+F)",
                   command=self._open_search).pack(side=tk.LEFT, padx=2)
        ttk.Button(flt, text="▽ 保存 (Ctrl+S)",
                   command=self._save_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(flt, text="▽ 另存为...",
                   command=self._save_as).pack(side=tk.LEFT, padx=2)
        ttk.Separator(flt, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        # 编辑模式开关 (Notepad++ 风格) - 默认开启 (用户偏好)
        self.edit_mode_var = tk.BooleanVar(value=True)
        self._is_modified = False
        make_checkbutton(flt, text="✏ 编辑模式",
                        variable=self.edit_mode_var,
                        command=self._toggle_edit_mode).pack(side=tk.LEFT, padx=2)
        ttk.Separator(flt, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(flt, text="◐ 高亮(逗号分隔):").pack(side=tk.LEFT)
        self.hl_entry = ttk.Entry(flt, width=24)
        self.hl_entry.pack(side=tk.LEFT, padx=4)
        ttk.Button(flt, text="应用高亮",
                   command=self._apply_highlight).pack(side=tk.LEFT)
        ttk.Separator(flt, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        self.wrap_var = tk.BooleanVar(value=True)
        make_checkbutton(flt, text="自动换行", variable=self.wrap_var,
                        command=self._toggle_wrap).pack(side=tk.LEFT)
        # 兼容老 _apply_filter 接口的隐藏控件 (避免旧调用 AttributeError)
        self.filter_entry = ttk.Entry(self)
        self.filter_entry.pack_forget()

        self.paned = tk.PanedWindow(
            self, orient=tk.VERTICAL,
            sashwidth=8, sashrelief=tk.RAISED,
            bg="#90A4AE", showhandle=False,
            opaqueresize=True,
        )
        self.paned.pack(fill=tk.BOTH, expand=True)

        orig_frame = ttk.LabelFrame(self.paned, text="▤ 原始日志", padding=4)
        self.original_view = LogText(orig_frame, theme=self.app.current_theme,
                                     font_family=self.app.font_family,
                                     font_size=self.app.font_size)
        self.original_view.pack(fill=tk.BOTH, expand=True)
        self.paned.add(orig_frame, minsize=80, stretch="always")

        filt_frame = ttk.LabelFrame(self.paned,
                                    text="⌕ 查找结果  (双击某行可跳转到原始日志对应位置 · Ctrl+F 查找)",
                                    padding=4)
        # 无匹配提示横幅 (默认隐藏, 只在 0 匹配时显示)
        self._no_match_banner = tk.Label(
            filt_frame,
            text="",
            font=(self.app.font_family, 11, "bold"),
            bg="#fff3cd", fg="#b00020",
            relief=tk.FLAT, anchor="center", padx=8, pady=6,
        )
        # 不 pack, 仅在 _show_no_match 时 pack 出来
        self.filtered_view = LogText(filt_frame, theme=self.app.current_theme,
                                     font_family=self.app.font_family,
                                     font_size=self.app.font_size,
                                     monochrome=True)
        self.filtered_view.pack(fill=tk.BOTH, expand=True)
        self.paned.add(filt_frame, minsize=80, stretch="always")

        # 双击过滤行 -> 跳转原始
        self.filtered_view.text.bind("<Double-Button-1>", self._on_filtered_double_click)
        # Ctrl+F 在两个视图上都生效
        for w in (self, self.original_view.text, self.filtered_view.text):
            w.bind("<Control-f>", lambda e: (self._open_search(), "break")[1])
            w.bind("<Control-F>", lambda e: (self._open_search(), "break")[1])
        # Ctrl+S 保存
        for w in (self, self.original_view.text):
            w.bind("<Control-s>", lambda e: (self._save_file(), "break")[1])
            w.bind("<Control-S>", lambda e: (self._save_file(), "break")[1])

        self._search_dialog = None
        # 启动时立即应用编辑模式 (默认开启)
        try:
            if self.edit_mode_var.get():
                self.original_view.set_editable(True, on_modified=self._on_text_modified)
        except Exception:
            pass

    def _show_no_match_banner(self, kw):
        """在查找结果窗口顶部显示醒目的"未找到"提示."""
        try:
            self._no_match_banner.config(
                text=f"⚠  未找到匹配项: \"{kw}\"  (请检查关键词或正则表达式)",
            )
            # 已经 pack 过则不重复
            if not self._no_match_banner.winfo_ismapped():
                self._no_match_banner.pack(fill=tk.X, before=self.filtered_view,
                                           padx=2, pady=(0, 4))
        except Exception:
            pass

    def _hide_no_match_banner(self):
        try:
            if self._no_match_banner.winfo_ismapped():
                self._no_match_banner.pack_forget()
        except Exception:
            pass

    def iter_views(self):
        return [self.original_view, self.filtered_view]

    def load_file(self, path):
        try:
            size = os.path.getsize(path)
        except OSError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        if size > 200 * 1024 * 1024:
            if not messagebox.askyesno(
                APP_TITLE, f"文件较大 ({size/1024/1024:.1f} MB), 仍要加载?"):
                return
        self.file_path = path
        self.app.set_status(f"加载中: {path}")
        # 切换文件: 清空 modified 状态; 编辑模式保持用户当前选择
        self._is_modified = False
        self.original_view.clear()
        self.filtered_view.clear()
        try:
            self.original_view.reset_undo()
        except Exception:
            pass
        # 隐藏可能存在的"未找到"提示横幅
        self._hide_no_match_banner()
        # clear() 会把 state 设回 DISABLED, 若用户开启编辑模式需要重新启用
        try:
            if self.edit_mode_var.get():
                self.original_view.set_editable(True, on_modified=self._on_text_modified)
        except Exception:
            pass
        self.lines = []
        self.filtered_orig_idx = []
        self.container.set_tab_title(self, os.path.basename(path))
        try:
            self.path_var.set(path)
        except Exception:
            pass
        threading.Thread(target=self._load_thread, args=(path,), daemon=True).start()

    def _load_thread(self, path):
        try:
            for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
                try:
                    with open(path, "r", encoding=enc, errors="replace") as f:
                        self.lines = f.readlines()
                    break
                except UnicodeDecodeError:
                    continue
        except Exception as e:
            self.after(0, lambda: messagebox.showerror(APP_TITLE, str(e)))
            return
        if len(self.lines) > self.MAX_INDEX_LINES:
            self.lines = self.lines[:self.MAX_INDEX_LINES]
        self.after(0, self._render_initial)

    def _render_initial(self):
        total = len(self.lines)
        head = self.lines[:self.INITIAL_DISPLAY]
        self._rendered_count = 0
        self.app.set_status(f"渲染中... 0 / {len(head)} 行")
        self._render_chunked_async(self.original_view, head, 0,
                                   on_done=lambda: self._after_initial_render(total))

    def _after_initial_render(self, total):
        self._rendered_count = min(total, self.INITIAL_DISPLAY)
        if total > self.INITIAL_DISPLAY:
            self.app.set_status(
                f"加载完成: {os.path.basename(self.file_path)}  共 {total} 行 "
                f"(已显示前 {self.INITIAL_DISPLAY}, 后台继续渲染剩余 {total - self.INITIAL_DISPLAY} 行)"
            )
            # 后台继续渲染剩余, 提升跳转响应
            self.after(500, self._continue_background_render)
        else:
            self.app.set_status(
                f"加载完成: {os.path.basename(self.file_path)}  共 {total} 行"
            )

    def _continue_background_render(self):
        """启动后台分帧渲染, 把剩余行追加到 original_view."""
        if self._rendered_count >= len(self.lines):
            return
        rest = self.lines[self._rendered_count:]
        start_count = self._rendered_count

        def _on_done():
            self._rendered_count = len(self.lines)
            self.app.set_status(
                f"全部渲染完成: 共 {len(self.lines)} 行"
            )

        # 用更大的 chunk + 更长的间隔, 不影响交互
        old_chunk = self.RENDER_CHUNK
        old_interval = self.RENDER_INTERVAL_MS
        self.RENDER_CHUNK = 8000
        self.RENDER_INTERVAL_MS = 30
        try:
            self._render_chunked_async(self.original_view, rest, 0,
                                       on_done=_on_done)
        finally:
            self.RENDER_CHUNK = old_chunk
            self.RENDER_INTERVAL_MS = old_interval

        # 持续更新已渲染计数
        def _track():
            # render 在 view 上不断追加, 用 view 的 line 总数估算
            try:
                cur_lines = int(self.original_view.text.index("end-1c").split(".")[0])
                self._rendered_count = max(self._rendered_count,
                                           min(len(self.lines), cur_lines))
            except Exception:
                pass
            if self._rendered_count < len(self.lines):
                self.after(500, _track)
        self.after(500, _track)

    def _ensure_rendered_to(self, target_idx):
        """确保 original_view 已渲染到 target_idx (0-based) 行. 用于大文件跳转.

        优化: 一次性大块插入 (Tk Text 单次 insert 比循环 append 快 10x+),
        +5000 行缓冲避免短跳转触发频繁扩展.
        """
        if target_idx < self._rendered_count:
            return True
        target_inclusive = min(len(self.lines), target_idx + 5000)
        extra = self.lines[self._rendered_count:target_inclusive]
        if not extra:
            return False
        n = len(extra)
        self.app.set_status(f"扩展渲染 +{n} 行 ...")
        self.update_idletasks()
        # 关闭重绘 (Tk Text 大块 insert 期间禁用 idletasks 加速)
        self.original_view.append_lines(extra, autoscroll=False)
        self._rendered_count = target_inclusive
        return True

    def _render_chunked_async(self, view, lines, start_idx, on_done=None):
        """分帧把 lines 追加到 view, 每帧渲染 RENDER_CHUNK 行."""
        if start_idx >= len(lines):
            if on_done:
                on_done()
            return
        end = min(start_idx + self.RENDER_CHUNK, len(lines))
        view.append_lines(lines[start_idx:end], autoscroll=False)
        # 状态更新 (节流)
        if start_idx % (self.RENDER_CHUNK * 5) == 0:
            try:
                self.app.set_status(f"渲染中... {end} / {len(lines)} 行")
            except Exception:
                pass
        self.after(self.RENDER_INTERVAL_MS,
                   lambda: self._render_chunked_async(view, lines, end, on_done))

    def _apply_filter_debounce(self):
        if self._filter_after_id:
            self.after_cancel(self._filter_after_id)
        self._filter_after_id = self.after(300, self._apply_filter)

    def _apply_filter(self):
        kw = self.filter_entry.get()
        self.filtered_view.clear()
        self.filtered_orig_idx = []
        if not kw or not self.lines:
            return
        try:
            if self.use_regex.get():
                flags = 0 if self.case_sensitive.get() else re.IGNORECASE
                pat = re.compile(kw, flags)
                check = lambda ln: pat.search(ln)  # noqa: E731
            elif self.case_sensitive.get():
                check = lambda ln: kw in ln  # noqa: E731
            else:
                kwl = kw.lower()
                check = lambda ln: kwl in ln.lower()  # noqa: E731
        except re.error as e:
            self.app.set_status(f"正则错误: {e}")
            return

        matched = []
        idx_list = []
        for i, ln in enumerate(self.lines):
            if check(ln):
                matched.append(ln)
                idx_list.append(i)
        self.filtered_orig_idx = idx_list

        # 设置过滤视图的搜索关键字高亮 (仅高亮关键字, 不是整行)
        self.filtered_view.set_highlights(
            [kw], self.use_regex.get(), self.case_sensitive.get())
        # 分帧异步渲染
        self._render_chunked_async(
            self.filtered_view, matched, 0,
            on_done=lambda: self.app.set_status(
                f"过滤匹配 {len(matched)} / {len(self.lines)} 行  (双击过滤行可跳转)"
            )
        )

    def _apply_highlight(self):
        kws = [k.strip() for k in self.hl_entry.get().split(",") if k.strip()]
        for v in (self.original_view, self.filtered_view):
            v.set_highlights(kws, self.use_regex.get(), self.case_sensitive.get())
        # 重新渲染原始 (异步分帧), 重置已渲染计数
        self.original_view.clear()
        self._rendered_count = 0
        head = self.lines[:self.INITIAL_DISPLAY]
        total = len(self.lines)
        self._render_chunked_async(
            self.original_view, head, 0,
            on_done=lambda: (self._after_initial_render(total), self._apply_filter())
        )

    def _toggle_wrap(self):
        enabled = self.wrap_var.get()
        for v in (self.original_view, self.filtered_view):
            v.set_wrap(enabled)
        self.app.set_status(f"自动换行: {'开' if enabled else '关'}")

    # ===== 编辑模式 (Notepad++ 风格) =====
    def _toggle_edit_mode(self):
        editable = self.edit_mode_var.get()
        if editable:
            self.original_view.set_editable(True, on_modified=self._on_text_modified)
            self.app.set_status("✏ 编辑模式已开启 (Ctrl+Z 撤销 / Ctrl+Y 重做 / Ctrl+S 保存)")
        else:
            # 退出编辑前如果有未保存修改, 提示
            if self._is_modified:
                ans = messagebox.askyesnocancel(
                    APP_TITLE,
                    "当前文件有未保存修改, 是否保存?\n是 = 保存; 否 = 丢弃; 取消 = 继续编辑")
                if ans is None:
                    self.edit_mode_var.set(True)
                    return
                if ans:
                    self._save_file()
            self.original_view.set_editable(False)
            self._is_modified = False
            self._refresh_tab_title()
            self.app.set_status("已退出编辑模式 (只读)")

    def _on_text_modified(self):
        if not self._is_modified:
            self._is_modified = True
            self._refresh_tab_title()

    def _refresh_tab_title(self):
        """根据 modified 状态在 tab 标题前加 '*'."""
        try:
            base = os.path.basename(self.file_path) if self.file_path else "未命名"
            title = ("● " + base) if self._is_modified else base
            self.container.set_tab_title(self, title)
        except Exception:
            pass

    # ===== 文件保存 =====
    def _get_text_content(self):
        """从 original_view 取当前内容 (含用户编辑)."""
        try:
            # text.get 用 "1.0", "end-1c" 去掉末尾自动追加的换行
            return self.original_view.text.get("1.0", "end-1c")
        except Exception:
            return ""

    def _save_file(self):
        if not self.file_path:
            # 无路径 -> 走另存为
            return self._save_as()
        if not os.path.exists(os.path.dirname(self.file_path) or "."):
            return self._save_as()
        content = self._get_text_content()
        try:
            with open(self.file_path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"保存失败: {e}")
            return
        self.app.set_status(f"✅ 已保存: {self.file_path}")
        # 同步内存 lines (按 \n 切分, 保留换行符以与 readlines 一致)
        self.lines = [ln + "\n" for ln in content.split("\n")]
        if self.lines and not content.endswith("\n"):
            # 去掉最后一行的尾换行
            self.lines[-1] = self.lines[-1].rstrip("\n")
        self._rendered_count = len(self.lines)
        self._is_modified = False
        self._refresh_tab_title()
        try:
            self.original_view.text.edit_modified(False)
        except Exception:
            pass

    def _save_as(self):
        initial = self.file_path or "untitled.log"
        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) if self.file_path else None,
            filetypes=[("Log/Text", "*.log *.txt"), ("All", "*.*")],
        )
        if not path:
            return
        content = self._get_text_content()
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"保存失败: {e}")
            return
        self.file_path = path
        self.path_var.set(path)
        self.container.set_tab_title(self, os.path.basename(path))
        self.app.set_status(f"✅ 已另存: {path}")
        self.lines = [ln + "\n" for ln in content.split("\n")]
        if self.lines and not content.endswith("\n"):
            self.lines[-1] = self.lines[-1].rstrip("\n")
        self._rendered_count = len(self.lines)
        self._is_modified = False
        self._refresh_tab_title()
        try:
            self.original_view.text.edit_modified(False)
        except Exception:
            pass

    # ===== Ctrl+F 搜索弹窗集成 =====
    def _open_search(self):
        if self._search_dialog is None or not self._search_dialog.winfo_exists():
            self._search_dialog = SearchDialog(self.winfo_toplevel(), self.app, self)
        else:
            self._search_dialog.deiconify()
            self._search_dialog.lift()
            try:
                self._search_dialog.attributes("-topmost", True)
            except Exception:
                pass
            self._search_dialog.combo.focus_set()

    def apply_search_filter(self, kw, use_regex=False, whole_word=False,
                            case_sensitive=False):
        """SearchDialog 的"在当前文件查找"调用此方法, 渲染过滤结果到 filtered_view."""
        self.filtered_view.clear()
        self.filtered_orig_idx = []
        self._hide_no_match_banner()
        if not kw or not self.lines:
            self.app.set_status("过滤: 无输入或文件为空")
            return
        try:
            if use_regex:
                pat_str = kw
            else:
                pat_str = re.escape(kw)
            if whole_word:
                pat_str = rf"\b{pat_str}\b"
            flags = 0 if case_sensitive else re.IGNORECASE
            pat = re.compile(pat_str, flags)
        except re.error as e:
            self.app.set_status(f"正则错误: {e}")
            self._show_no_match_banner(f"{kw} (正则错误: {e})")
            return
        matched = []
        idx_list = []
        for i, ln in enumerate(self.lines):
            if pat.search(ln):
                matched.append(ln)
                idx_list.append(i)
        self.filtered_orig_idx = idx_list
        if not matched:
            # 显著提示但不弹窗
            self._show_no_match_banner(kw)
            self.app.set_status(f"未找到匹配项: {kw}")
            return
        # 设置过滤视图的搜索关键字高亮 (仅高亮关键字, 不是整行)
        # pat_str 已包含 regex escape / whole_word \b 处理, 直接作为正则传入
        self.filtered_view.set_highlights([pat_str], use_regex=True,
                                           case_sensitive=case_sensitive)
        self._render_chunked_async(
            self.filtered_view, matched, 0,
            on_done=lambda: self.app.set_status(
                f"匹配 {len(matched)} / {len(self.lines)} 行 · 双击过滤行可跳转"
            )
        )

    def _on_filtered_double_click(self, event):
        try:
            # @x,y 在 wrap 模式下仍返回 logical "line.col"
            idx = self.filtered_view.text.index(f"@{event.x},{event.y}")
            line_no = int(idx.split(".")[0])
        except (tk.TclError, ValueError):
            self.app.set_status("双击位置无效")
            return "break"
        # 防止点到末尾空行
        if line_no <= 0:
            return "break"
        if line_no > len(self.filtered_orig_idx):
            self.app.set_status(
                f"该行尚未在过滤索引中 (line={line_no} / {len(self.filtered_orig_idx)})"
            )
            return "break"
        orig_idx = self.filtered_orig_idx[line_no - 1]
        if orig_idx >= len(self.lines):
            self.app.set_status("跳转目标越界")
            return "break"
        # 大文件按需扩展渲染
        if orig_idx >= self._rendered_count:
            self.app.set_status(f"按需加载到第 {orig_idx + 1} 行...")
            self.update_idletasks()
            self._ensure_rendered_to(orig_idx)
        self.filtered_view.mark_line(line_no, scroll=False)
        self.original_view.mark_line(orig_idx + 1, scroll=True)
        self.app.set_status(f"已跳转到原始日志第 {orig_idx + 1} 行")
        return "break"


class FileViewerTab(ttk.Frame):
    """文件查看器容器, 内嵌子 Notebook 支持多文件同时查看."""

    def __init__(self, master, app):
        super().__init__(master, padding=4)
        self.app = app
        self.viewers = []  # list[FileViewer]
        self._build()
        # 初始一个空白 viewer
        self._new_viewer()
        # 容器拖拽支持
        if HAS_DND:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(bar, text="▤ 打开文件", style="Accent.TButton",
                   command=self._open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="⌕ 目录查找",
                   command=self._open_dir_search).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="➕ 新建标签",
                   command=self._new_viewer).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="✕ 关闭当前",
                   command=self._close_current).pack(side=tk.LEFT, padx=2)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        self.tip_label = ttk.Label(
            bar,
            text="ⓘ 提示: 拖拽日志文件到窗口可在新标签中打开 / 双击过滤结果某行可跳转原始日志对应位置",
            foreground="#607D8B"
        )
        self.tip_label.pack(side=tk.LEFT)

        self.sub_nb = ttk.Notebook(self)
        self.sub_nb.pack(fill=tk.BOTH, expand=True)
        # 标签页右键菜单
        self.sub_nb.bind("<Button-3>", self._on_tab_right_click)
        self._tab_menu = None

    def _new_viewer(self, focus=True):
        viewer = FileViewer(self.sub_nb, self.app, self)
        self.viewers.append(viewer)
        title = f"未命名 {len(self.viewers)}"
        self.sub_nb.add(viewer, text=f"  {title}  ")
        if HAS_DND:
            try:
                for w in (viewer, viewer.original_view.text, viewer.filtered_view.text):
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", lambda e, v=viewer: self._on_drop_to_viewer(e, v))
            except Exception:
                pass
        if focus:
            self.sub_nb.select(viewer)
        return viewer

    def _open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Log/Text", "*.log *.txt *.csv *.out"), ("All", "*.*")]
        )
        if not path:
            return
        viewer = self._current_viewer()
        # 当前 viewer 已有内容则新开标签
        if viewer is None or viewer.file_path is not None:
            viewer = self._new_viewer()
        viewer.load_file(path)

    def _open_dir_search(self):
        DirSearchDialog(self.winfo_toplevel(), self.app, self._on_dir_search_result)

    def _on_dir_search_result(self, title, lines, per_line_meta):
        """在新 tab 显示目录搜索结果, 双击行可跳到对应文件 + 行."""
        viewer = self._new_viewer()
        viewer.lines = lines
        viewer.file_path = None
        viewer.path_var.set(f"[{title}]  共 {len(lines)} 行")
        self.set_tab_title(viewer, title[:24])
        viewer._dir_search_meta = per_line_meta  # 用于双击跳转
        # 渲染到 original_view
        viewer._rendered_count = 0
        viewer.original_view.clear()
        viewer.filtered_view.clear()
        viewer._render_chunked_async(
            viewer.original_view, lines, 0,
            on_done=lambda v=viewer: self._after_dir_render(v))
        # 给 original_view 行的双击事件
        viewer.original_view.text.bind(
            "<Double-Button-1>",
            lambda e, v=viewer: self._on_dir_result_double_click(e, v))

    def _after_dir_render(self, viewer):
        viewer._rendered_count = len(viewer.lines)
        # 给文件标题行染色, 让分隔更明显
        try:
            txt = viewer.original_view.text
            txt.tag_configure("dir_search_header",
                              foreground="#0D47A1",
                              font=("Consolas", 11, "bold"),
                              background="#E3F2FD")
            meta = getattr(viewer, "_dir_search_meta", [])
            for i, (fp, _ln) in enumerate(meta):
                if fp is None:
                    # 标题或分隔行
                    line_no = i + 1
                    line = viewer.lines[i] if i < len(viewer.lines) else ""
                    if line.startswith("====="):
                        txt.tag_add("dir_search_header",
                                    f"{line_no}.0", f"{line_no}.end")
        except Exception:
            pass
        self.app.set_status(
            f"目录搜索结果已渲染: {len(viewer.lines)} 行, 双击匹配行可在新标签打开源文件并跳转")

    def _on_dir_result_double_click(self, event, viewer):
        try:
            idx = viewer.original_view.text.index(f"@{event.x},{event.y}")
            line_no = int(idx.split(".")[0])
        except (tk.TclError, ValueError):
            return "break"
        meta = getattr(viewer, "_dir_search_meta", [])
        if line_no <= 0 or line_no > len(meta):
            return "break"
        fp, orig_lineno = meta[line_no - 1]
        if not fp or orig_lineno < 0:
            return "break"
        # 在新 tab 打开源文件, 加载完成后跳到 orig_lineno
        new_viewer = self._new_viewer()

        def _after_loaded():
            try:
                new_viewer._ensure_rendered_to(orig_lineno)
                new_viewer.original_view.mark_line(orig_lineno + 1, scroll=True)
                self.app.set_status(
                    f"已跳到 {os.path.basename(fp)}: 第 {orig_lineno + 1} 行")
            except Exception as e:
                self.app.set_status(f"跳转失败: {e}")

        # 重写 _after_initial_render 触发跳转 (一次性)
        original_after = new_viewer._after_initial_render

        def _patched(total):
            original_after(total)
            new_viewer.after(200, _after_loaded)
        new_viewer._after_initial_render = _patched
        new_viewer.load_file(fp)
        return "break"

    def _close_current(self):
        viewer = self._current_viewer()
        if not viewer:
            return
        if len(self.viewers) <= 1:
            # 只剩一个就清空
            viewer.lines = []
            viewer.file_path = None
            viewer.original_view.clear()
            viewer.filtered_view.clear()
            self.set_tab_title(viewer, "未命名 1")
            self.app.set_status("已关闭文件")
            return
        idx = self.viewers.index(viewer)
        self.sub_nb.forget(viewer)
        self.viewers.remove(viewer)
        viewer.destroy()
        # 切换到相邻
        if self.viewers:
            self.sub_nb.select(self.viewers[min(idx, len(self.viewers) - 1)])

    # ===== 标签页右键菜单 =====
    def _identify_tab(self, x, y):
        try:
            idx = self.sub_nb.index(f"@{x},{y}")
        except tk.TclError:
            return None
        if idx < 0 or idx >= len(self.viewers):
            return None
        return idx

    def _on_tab_right_click(self, event):
        idx = self._identify_tab(event.x, event.y)
        if idx is None:
            return
        viewer = self.viewers[idx]
        # 切换到右击的 tab
        self.sub_nb.select(viewer)

        m = tk.Menu(self.sub_nb, tearoff=0)
        m.add_command(label="✕ 关闭当前", command=lambda: self._close_at(idx))
        m.add_command(
            label="✕ 关闭其他",
            command=lambda: self._close_others(idx),
            state=tk.NORMAL if len(self.viewers) > 1 else tk.DISABLED,
        )
        m.add_command(
            label="◀ 关闭左侧全部",
            command=lambda: self._close_left(idx),
            state=tk.NORMAL if idx > 0 else tk.DISABLED,
        )
        m.add_command(
            label="▶ 关闭右侧全部",
            command=lambda: self._close_right(idx),
            state=tk.NORMAL if idx < len(self.viewers) - 1 else tk.DISABLED,
        )
        m.add_separator()
        has_path = bool(viewer.file_path) and os.path.exists(viewer.file_path or "")
        m.add_command(
            label="▤ 打开文件所在位置",
            command=lambda: self._open_in_explorer(viewer.file_path),
            state=tk.NORMAL if has_path else tk.DISABLED,
        )
        m.add_command(
            label="▥ 复制完整路径",
            command=lambda: self._copy_path(viewer.file_path),
            state=tk.NORMAL if has_path else tk.DISABLED,
        )
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _close_at(self, idx):
        if idx < 0 or idx >= len(self.viewers):
            return
        if len(self.viewers) <= 1:
            v = self.viewers[0]
            v.lines = []
            v.file_path = None
            v.original_view.clear()
            v.filtered_view.clear()
            self.set_tab_title(v, "未命名 1")
            return
        viewer = self.viewers[idx]
        self.sub_nb.forget(viewer)
        self.viewers.pop(idx)
        viewer.destroy()
        if self.viewers:
            self.sub_nb.select(self.viewers[min(idx, len(self.viewers) - 1)])

    def _close_others(self, idx):
        # 从两端往中间删除以保持索引稳定
        for i in range(len(self.viewers) - 1, idx, -1):
            self._close_at(i)
        for _ in range(idx):
            self._close_at(0)

    def _close_left(self, idx):
        for _ in range(idx):
            self._close_at(0)

    def _close_right(self, idx):
        # 从右往左删除
        for i in range(len(self.viewers) - 1, idx, -1):
            self._close_at(i)

    def _open_in_explorer(self, path):
        if not path or not os.path.exists(path):
            return
        try:
            system = platform.system()
            if system == "Windows":
                # 选中目标文件
                subprocess.Popen(
                    ["explorer", "/select,", os.path.normpath(path)],
                    creationflags=_SUBPROC_FLAGS,
                )
            elif system == "Darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                # Linux: 大多数文件管理器只支持目录
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"打开失败: {e}")

    def _copy_path(self, path):
        if not path:
            return
        self.clipboard_clear()
        self.clipboard_append(os.path.abspath(path))
        self.app.set_status(f"已复制路径: {path}")

    def _current_viewer(self):
        cur = self.sub_nb.select()
        if not cur:
            return None
        for v in self.viewers:
            if str(v) == cur:
                return v
        return None

    def set_tab_title(self, viewer, title):
        try:
            self.sub_nb.tab(viewer, text=f"  {title}  ")
        except tk.TclError:
            pass

    def iter_views(self):
        out = []
        for v in self.viewers:
            out.extend(v.iter_views())
        return out

    # ===== 拖拽 =====
    def _parse_dnd_paths(self, data):
        files = []
        i = 0
        while i < len(data):
            if data[i] == "{":
                end = data.find("}", i)
                if end < 0:
                    break
                files.append(data[i + 1:end])
                i = end + 1
            elif data[i] == " ":
                i += 1
            else:
                end = data.find(" ", i)
                if end < 0:
                    files.append(data[i:])
                    break
                files.append(data[i:end])
                i = end + 1
        return [f for f in files if os.path.isfile(f)]

    def _on_drop(self, event):
        files = self._parse_dnd_paths(event.data.strip())
        for i, f in enumerate(files):
            viewer = self._current_viewer() if i == 0 else None
            # 第一个: 当前 viewer 为空就用它, 否则新开
            if viewer is None or viewer.file_path is not None:
                viewer = self._new_viewer()
            viewer.load_file(f)

    def _on_drop_to_viewer(self, event, viewer):
        files = self._parse_dnd_paths(event.data.strip())
        if not files:
            return
        # 第一个文件加载到目标 viewer (若为空), 其它文件每个新开 tab
        first = files[0]
        if viewer.file_path is not None:
            viewer = self._new_viewer()
        viewer.load_file(first)
        for f in files[1:]:
            v = self._new_viewer()
            v.load_file(f)


# ============ Ctrl+F 搜索弹窗 (Notepad++ 风格) ============
SEARCH_HISTORY_FILE = os.path.join(
    os.path.expanduser("~"), ".adb_log_viewer_search_history.json"
)
SEARCH_HISTORY_LIMIT = 20

# 内存级共享状态: 所有 SearchDialog 实例共用同一份, 实时同步
_SEARCH_STATE = {
    "history": [],
    "use_regex": True,        # 默认开启正则
    "whole_word": False,
    "case_sensitive": False,
    "wrap_around": True,      # 默认开启循环查找
    "_loaded": False,
}


def _load_search_state():
    """从磁盘加载搜索状态 (history + 选项), 兼容老的纯列表格式."""
    if _SEARCH_STATE["_loaded"]:
        return
    try:
        with open(SEARCH_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            _SEARCH_STATE["history"] = [str(x) for x in data][:SEARCH_HISTORY_LIMIT]
        elif isinstance(data, dict):
            hist = data.get("history", [])
            if isinstance(hist, list):
                _SEARCH_STATE["history"] = [str(x) for x in hist][:SEARCH_HISTORY_LIMIT]
            for k in ("use_regex", "whole_word", "case_sensitive", "wrap_around"):
                if isinstance(data.get(k), bool):
                    _SEARCH_STATE[k] = data[k]
    except Exception:
        pass
    _SEARCH_STATE["_loaded"] = True


def _save_search_state():
    try:
        out = {
            "history": _SEARCH_STATE["history"][:SEARCH_HISTORY_LIMIT],
            "use_regex": _SEARCH_STATE["use_regex"],
            "whole_word": _SEARCH_STATE["whole_word"],
            "case_sensitive": _SEARCH_STATE["case_sensitive"],
            "wrap_around": _SEARCH_STATE["wrap_around"],
        }
        with open(SEARCH_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[warn] 保存查找状态失败: {e}", file=sys.stderr)


# 兼容旧函数名 (老调用点会被新代码替换)
def _load_search_history():
    _load_search_state()
    return list(_SEARCH_STATE["history"])


def _save_search_history(items):
    _SEARCH_STATE["history"] = list(items)[:SEARCH_HISTORY_LIMIT]
    _save_search_state()


class SearchDialog(tk.Toplevel):
    """Ctrl+F 弹窗: 输入框+历史下拉, 正则/全词/大小写/循环, 上一个/下一个/在当前文件查找/关闭."""

    def __init__(self, master, app, target):
        """target: 提供 lines (list[str]), original_view (LogText),
        ensure_rendered_to(idx), apply_search_filter(kw, regex, whole, case) 的对象."""
        super().__init__(master)
        self.app = app
        self.target = target
        self.title("查找")
        self.transient(master)
        self.resizable(False, False)
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        # 不设置 grab_set, 允许后台继续渲染交互

        self.history = _load_search_history()
        self.kw_var = tk.StringVar()
        # 启动时强制勾选: 正则 + 循环查找 (用户偏好)
        self.use_regex = tk.BooleanVar(value=True)
        self.whole_word = tk.BooleanVar(value=_SEARCH_STATE["whole_word"])
        self.case_sensitive = tk.BooleanVar(value=_SEARCH_STATE["case_sensitive"])
        self.wrap_around = tk.BooleanVar(value=True)
        # 选项变化时立即写回 + 通知其它已打开的 SearchDialog
        for name, var in (
            ("use_regex", self.use_regex),
            ("whole_word", self.whole_word),
            ("case_sensitive", self.case_sensitive),
            ("wrap_around", self.wrap_around),
        ):
            var.trace_add("write", lambda *a, n=name, v=var: self._on_option_changed(n, v))
        # 上次匹配位置 (target.lines 的 0-based 行号)
        self._last_match_line = -1

        self._build()
        self._center_on(master)
        self.bind("<Return>", lambda e: self._on_find_next())
        self.bind("<Escape>", lambda e: self._on_close())
        self.bind("<F3>", lambda e: self._on_find_next())
        self.bind("<Shift-F3>", lambda e: self._on_find_prev())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.combo.focus_set()

    def _build(self):
        pad = {"padx": 6, "pady": 4}
        row1 = ttk.Frame(self, padding=8)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="查找内容:").grid(row=0, column=0, sticky="w")
        self.combo = ttk.Combobox(row1, textvariable=self.kw_var,
                                  width=42, values=self.history)
        self.combo.grid(row=0, column=1, columnspan=4, sticky="we", **pad)
        row1.grid_columnconfigure(1, weight=1)

        # 选项行
        opt = ttk.Frame(self, padding=(8, 0, 8, 4))
        opt.pack(fill=tk.X)
        make_checkbutton(opt, text="正则", variable=self.use_regex).pack(side=tk.LEFT, padx=4)
        make_checkbutton(opt, text="全词匹配", variable=self.whole_word).pack(side=tk.LEFT, padx=4)
        make_checkbutton(opt, text="区分大小写", variable=self.case_sensitive).pack(side=tk.LEFT, padx=4)
        make_checkbutton(opt, text="循环查找", variable=self.wrap_around).pack(side=tk.LEFT, padx=4)

        # 按钮行
        btns = ttk.Frame(self, padding=(8, 0, 8, 8))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="▲ 查找上一个 (Shift+F3)",
                   command=self._on_find_prev).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="▼ 查找下一个 (F3 / Enter)",
                   command=self._on_find_next).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="▥ 在当前文件查找",
                   command=self._on_filter).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="✕ 关闭 (Esc)",
                   command=self._on_close).pack(side=tk.LEFT, padx=2)

        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status, padding=(8, 0, 8, 6),
                  foreground="#555").pack(fill=tk.X)

    def _center_on(self, parent):
        self.update_idletasks()
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            w = self.winfo_width() or 540
            h = self.winfo_height() or 130
            x = px + (pw - w) // 2
            y = py + 80
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _push_history(self, kw):
        if not kw:
            return
        if kw in self.history:
            self.history.remove(kw)
        self.history.insert(0, kw)
        self.history = self.history[:SEARCH_HISTORY_LIMIT]
        _save_search_history(self.history)
        self.combo["values"] = self.history

    def _build_pattern(self, kw):
        try:
            if self.use_regex.get():
                pat_str = kw
            else:
                pat_str = re.escape(kw)
            if self.whole_word.get():
                pat_str = rf"\b{pat_str}\b"
            flags = 0 if self.case_sensitive.get() else re.IGNORECASE
            return re.compile(pat_str, flags)
        except re.error as e:
            self.status.set(f"正则错误: {e}")
            return None

    def _find(self, direction):
        kw = self.kw_var.get()
        if not kw:
            self.status.set("请输入查找内容")
            return
        pat = self._build_pattern(kw)
        if pat is None:
            return
        lines = getattr(self.target, "lines", [])
        if not lines:
            self.status.set("当前文件无内容")
            return
        n = len(lines)
        start = self._last_match_line
        if direction > 0:
            rng = list(range(start + 1, n))
            if self.wrap_around.get():
                rng += list(range(0, start + 1))
        else:
            rng = list(range(start - 1, -1, -1))
            if self.wrap_around.get():
                rng += list(range(n - 1, start - 1, -1))

        for i in rng:
            if pat.search(lines[i]):
                self._last_match_line = i
                self._jump_to(i)
                self._push_history(kw)
                self.status.set(f"匹配第 {i + 1} 行 / 共 {n} 行")
                return
        self.status.set(f"未找到 “{kw}”")

    def _jump_to(self, line_idx):
        # 大文件按需扩展渲染
        try:
            self.target._ensure_rendered_to(line_idx)
        except AttributeError:
            pass
        try:
            self.target.original_view.mark_line(line_idx + 1, scroll=True)
        except Exception:
            pass

    def _on_find_next(self):
        self._find(+1)

    def _on_find_prev(self):
        self._find(-1)

    def _on_filter(self):
        kw = self.kw_var.get()
        if not kw:
            self.status.set("请输入查找内容")
            return
        self._push_history(kw)
        try:
            self.target.apply_search_filter(
                kw,
                use_regex=self.use_regex.get(),
                whole_word=self.whole_word.get(),
                case_sensitive=self.case_sensitive.get(),
            )
        except Exception as e:
            self.status.set(f"过滤失败: {e}")
            return
        self.withdraw()

    def _on_option_changed(self, name, var):
        try:
            _SEARCH_STATE[name] = bool(var.get())
            _save_search_state()
        except Exception:
            pass

    def _on_close(self):
        self.withdraw()


# ============ 目录搜索 ============
DIR_SEARCH_DEFAULT_EXTS = ".log,.txt,.csv,.out,.trace,.dmp"


class DirSearchDialog(tk.Toplevel):
    """目录批量搜索: 选目录+关键词+选项, 后台扫描所有文件, 结果按文件名分隔."""

    def __init__(self, master, app, on_result):
        super().__init__(master)
        self.app = app
        self.on_result = on_result  # callable(title, lines, file_index)
        self.title("目录中查找日志")
        self.transient(master)
        self.resizable(False, False)
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass

        self.dir_var = tk.StringVar(value="")
        self.kw_var = tk.StringVar()
        self.ext_var = tk.StringVar(value=DIR_SEARCH_DEFAULT_EXTS)
        self.use_regex = tk.BooleanVar(value=_SEARCH_STATE["use_regex"])
        self.whole_word = tk.BooleanVar(value=_SEARCH_STATE["whole_word"])
        self.case_sensitive = tk.BooleanVar(value=_SEARCH_STATE["case_sensitive"])
        self.recursive = tk.BooleanVar(value=True)
        self.context_var = tk.IntVar(value=0)  # 上下文行数
        self._cancel = False
        self._scanning = False

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())
        self.bind("<Return>", lambda e: self._on_search())
        self.update_idletasks()
        try:
            px, py = master.winfo_rootx(), master.winfo_rooty()
            pw = master.winfo_width()
            w = self.winfo_width() or 560
            x = px + (pw - w) // 2
            y = py + 90
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _build(self):
        pad = {"padx": 6, "pady": 4}
        f = ttk.Frame(self, padding=8)
        f.pack(fill=tk.X)

        ttk.Label(f, text="目录:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.dir_var, width=48).grid(
            row=0, column=1, sticky="we", **pad)
        ttk.Button(f, text="浏览...", command=self._browse_dir).grid(
            row=0, column=2, **pad)

        ttk.Label(f, text="关键词:").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.kw_var, width=48).grid(
            row=1, column=1, sticky="we", **pad)

        ttk.Label(f, text="文件后缀:").grid(row=2, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.ext_var, width=48).grid(
            row=2, column=1, sticky="we", **pad)
        ttk.Label(f, text="(逗号分隔, 留空=全部)",
                  foreground="#888").grid(row=2, column=2, sticky="w")

        f.grid_columnconfigure(1, weight=1)

        opt = ttk.Frame(self, padding=(8, 0, 8, 4))
        opt.pack(fill=tk.X)
        make_checkbutton(opt, text="正则", variable=self.use_regex).pack(side=tk.LEFT, padx=4)
        make_checkbutton(opt, text="全词匹配", variable=self.whole_word).pack(side=tk.LEFT, padx=4)
        make_checkbutton(opt, text="区分大小写", variable=self.case_sensitive).pack(side=tk.LEFT, padx=4)
        make_checkbutton(opt, text="递归子目录", variable=self.recursive).pack(side=tk.LEFT, padx=4)
        ttk.Label(opt, text="上下文行数:").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(opt, from_=0, to=10, textvariable=self.context_var,
                    width=4).pack(side=tk.LEFT)

        btns = ttk.Frame(self, padding=(8, 4, 8, 8))
        btns.pack(fill=tk.X)
        self.btn_search = ttk.Button(btns, text="⌕ 开始搜索",
                                     style="Accent.TButton",
                                     command=self._on_search)
        self.btn_search.pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="⏹ 取消", command=self._on_cancel).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="关闭", command=self._on_close).pack(side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(value="提示: 选择目录, 输入关键词后点击开始搜索")
        ttk.Label(self, textvariable=self.status_var,
                  foreground="#555", padding=(8, 0, 8, 6)).pack(fill=tk.X)

    def _browse_dir(self):
        d = filedialog.askdirectory(parent=self, title="选择要搜索的目录")
        if d:
            self.dir_var.set(d)

    def _on_search(self):
        if self._scanning:
            return
        d = self.dir_var.get().strip()
        kw = self.kw_var.get()
        if not d or not os.path.isdir(d):
            self.status_var.set("请选择有效的目录")
            return
        if not kw:
            self.status_var.set("请输入关键词")
            return
        # 同步选项到全局
        _SEARCH_STATE["use_regex"] = bool(self.use_regex.get())
        _SEARCH_STATE["whole_word"] = bool(self.whole_word.get())
        _SEARCH_STATE["case_sensitive"] = bool(self.case_sensitive.get())
        _save_search_state()

        try:
            if self.use_regex.get():
                pat_str = kw
            else:
                pat_str = re.escape(kw)
            if self.whole_word.get():
                pat_str = rf"\b{pat_str}\b"
            flags = 0 if self.case_sensitive.get() else re.IGNORECASE
            pat = re.compile(pat_str, flags)
        except re.error as e:
            self.status_var.set(f"正则错误: {e}")
            return

        exts = [e.strip().lower() for e in self.ext_var.get().split(",") if e.strip()]
        # 自动加点
        exts = [e if e.startswith(".") else "." + e for e in exts]
        ctx = max(0, int(self.context_var.get() or 0))

        self._cancel = False
        self._scanning = True
        self.btn_search.config(state=tk.DISABLED)
        self.status_var.set("扫描中...")
        threading.Thread(
            target=self._scan_thread,
            args=(d, pat, exts, self.recursive.get(), ctx, kw),
            daemon=True,
        ).start()

    def _scan_thread(self, root_dir, pat, exts, recursive, ctx, kw):
        # 收集文件
        files = []
        try:
            if recursive:
                for dp, _dn, fn in os.walk(root_dir):
                    for n in fn:
                        if not exts or any(n.lower().endswith(e) for e in exts):
                            files.append(os.path.join(dp, n))
                        if self._cancel:
                            break
                    if self._cancel:
                        break
            else:
                for n in os.listdir(root_dir):
                    p = os.path.join(root_dir, n)
                    if os.path.isfile(p) and (not exts or any(
                            n.lower().endswith(e) for e in exts)):
                        files.append(p)
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"扫描失败: {e}"))
            self.after(0, self._scan_done)
            return

        out_lines = []
        # file_index: list of (start_line_in_out_lines, file_path, original_lineno_per_match_line)
        # 简化: per-line 维度 -> [(orig_idx_or_None, file_path_or_None) for each output line]
        per_line_meta = []  # list of (file_path, orig_lineno)  None表示分隔行
        total_files = len(files)
        total_match = 0
        match_files = 0
        for fi, fp in enumerate(files):
            if self._cancel:
                break
            if fi % 10 == 0:
                self.after(0, lambda i=fi, n=total_files, m=total_match:
                           self.status_var.set(
                               f"扫描中 {i}/{n}, 已匹配 {m} 行..."))
            try:
                file_lines = None
                for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
                    try:
                        with open(fp, "r", encoding=enc, errors="replace") as f:
                            file_lines = f.read().splitlines(keepends=False)
                        break
                    except UnicodeDecodeError:
                        continue
                if file_lines is None:
                    continue
            except Exception:
                continue

            # 匹配
            hits = []
            for li, ln in enumerate(file_lines):
                if pat.search(ln):
                    hits.append(li)
            if not hits:
                continue
            match_files += 1
            # 输出文件标题分隔
            sep = f"===== {fp}  ({len(hits)} 处匹配) ====="
            out_lines.append("")
            per_line_meta.append((None, -1))
            out_lines.append(sep)
            per_line_meta.append((None, -1))

            # 输出匹配行 (含上下文)
            shown_ranges = []
            for li in hits:
                lo = max(0, li - ctx)
                hi = min(len(file_lines), li + ctx + 1)
                # 合并相邻段
                if shown_ranges and lo <= shown_ranges[-1][1]:
                    shown_ranges[-1] = (shown_ranges[-1][0], max(shown_ranges[-1][1], hi))
                else:
                    shown_ranges.append((lo, hi))
            for ridx, (lo, hi) in enumerate(shown_ranges):
                if ridx > 0 and ctx > 0:
                    out_lines.append("    --")
                    per_line_meta.append((None, -1))
                for ln_no in range(lo, hi):
                    out_lines.append(f"  {ln_no + 1:>6}: {file_lines[ln_no]}")
                    per_line_meta.append((fp, ln_no))
            total_match += len(hits)

        if self._cancel:
            self.after(0, lambda: self.status_var.set("已取消"))
        else:
            self.after(0, lambda: self.status_var.set(
                f"完成: 共扫描 {total_files} 文件, 匹配 {match_files} 文件, "
                f"{total_match} 处"))
        # 把结果交给回调 (即使空也回调, 让用户看到没结果)
        title = f"搜索: {kw}"
        self.after(0, lambda: self.on_result(title, out_lines, per_line_meta))
        self.after(0, self._scan_done)

    def _scan_done(self):
        self._scanning = False
        try:
            self.btn_search.config(state=tk.NORMAL)
        except Exception:
            pass

    def _on_cancel(self):
        if self._scanning:
            self._cancel = True
            self.status_var.set("正在取消...")

    def _on_close(self):
        if self._scanning:
            self._cancel = True
        self.destroy()


# ============ 主应用 ============
def _stage(msg):
    """Linux 调试: 打印初始化阶段, 段错误时可定位."""
    if platform.system() == "Linux":
        print(f"[stage] {msg}", file=sys.stderr, flush=True)


class App(BaseTk):
    def __init__(self):
        _stage("BaseTk.__init__ start")
        super().__init__()
        _stage("BaseTk.__init__ done")
        # Windows 高 DPI 适配 (字体清晰)
        self._setup_dpi()
        self.title(APP_TITLE)
        # 居中显示, 避免出现在屏幕外
        w, h = 1280, 820
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(960, 620)
        # topmost 在 Linux 部分窗口管理器下可能引发崩溃, 延迟到 mainloop 后
        if platform.system() == "Windows":
            try:
                self.deiconify()
                self.lift()
                self.attributes("-topmost", True)
                self.after(500, lambda: self.attributes("-topmost", False))
            except Exception:
                pass

        self.current_theme = THEMES["浅色 (默认)"].copy()
        self.current_theme_name = "浅色 (默认)"
        self.font_family = "Consolas" if platform.system() == "Windows" else "DejaVu Sans Mono"
        self.font_size = 11

        _stage("set_app_icon")
        # 应用图标
        self._set_app_icon()

        _stage("setup_style")
        self._setup_style()
        _stage("build_menu")
        self._build_menu()
        _stage("build_ui")
        self._build_ui()
        _stage("init done")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 加载用户上次保存的主题 (在所有 widget 创建后再 apply 避免段错误)
        try:
            saved = self._load_theme_pref()
            if saved and saved in THEMES:
                self.after(100, lambda n=saved: self._set_theme(n))
            else:
                # 即使没有保存的主题, 也对默认主题做一次 chrome 同步, 确保 UI 一致
                self.after(100, lambda: self._set_theme(self.current_theme_name))
        except Exception:
            pass

        # Linux: 在所有 widget 创建后, 尝试切换到 clam 主题以支持现代化按钮样式
        # (clam 支持 bordercolor/lightcolor/darkcolor; default 不支持).
        # 若用户设 TK_THEME=default 则跳过.
        if IS_LINUX:
            try:
                want = os.environ.get("TK_THEME", "clam").strip().lower()
                if want != "default":
                    self.after(150, lambda t=want: self._try_switch_theme(t))
            except Exception:
                pass

    def _try_switch_theme(self, name):
        """延迟切换 ttk 主题; 若失败 (如 clam 在某些 Linux 上崩) 静默回退."""
        try:
            style = ttk.Style(self)
            if name in style.theme_names() and style.theme_use() != name:
                style.theme_use(name)
                # 切换主题后必须重新应用 chrome (主题切换会重置样式)
                self._apply_ui_chrome(self.current_theme.get("ui", "light"))
        except Exception as e:
            print(f"[warn] 切换主题 {name} 失败: {e}", file=sys.stderr)

    def _set_app_icon(self):
        try:
            if platform.system() == "Windows" and os.path.exists(ICON_ICO):
                self.iconbitmap(default=ICON_ICO)
                return
            if platform.system() == "Linux":
                # 部分 Linux 发行版的 Tk 直接 PhotoImage(file=...png)
                # 在窗口管理器尚未就绪时调用 iconphoto 会段错误,
                # 改为延迟到 mainloop 中再设置
                if os.path.exists(ICON_PNG):
                    def _delayed():
                        try:
                            self._icon_img = tk.PhotoImage(file=ICON_PNG)
                            self.iconphoto(True, self._icon_img)
                        except Exception as ee:
                            print(f"[warn] 延迟设置图标失败: {ee}", file=sys.stderr)
                    self.after(800, _delayed)
                return
            # macOS / 其它
            if os.path.exists(ICON_PNG):
                self._icon_img = tk.PhotoImage(file=ICON_PNG)
                self.iconphoto(True, self._icon_img)
        except Exception as e:
            print(f"[warn] 设置图标失败: {e}", file=sys.stderr)

    def _setup_dpi(self):
        """Windows 高 DPI 下让 tkinter 字体清晰, 不发虚."""
        if platform.system() != "Windows":
            return
        try:
            from ctypes import windll
            try:
                # Per-monitor DPI aware (Windows 8.1+)
                windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                # 回退到 system DPI aware
                try:
                    windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
        except Exception as e:
            print(f"[warn] DPI 设置失败: {e}")
        try:
            # 通知 Tk 当前缩放比例
            scale = self.winfo_fpixels("1i") / 72.0
            if scale <= 0:
                scale = 1.0
            self.tk.call("tk", "scaling", scale)
        except Exception:
            pass

    def _setup_style(self):
        # 优先使用 sv-ttk (Sun Valley) 现代主题
        applied_modern = False
        # Linux 完全禁用 sv-ttk: sv-ttk 在 Tk 8.6 + Linux 上常触发段错误
        if HAS_SVTTK and not IS_LINUX:
            try:
                sv_ttk.set_theme("light")
                applied_modern = True
            except Exception as e:
                print(f"[warn] sv_ttk 失败, 回退 vista: {e}")

        style = ttk.Style(self)
        if not applied_modern:
            # === Linux: 强制 default 主题 (最稳定, Tk 8.6 兼容性最好,
            # 适配 Ubuntu 18.04/20.04/22.04/24.04). clam 主题在某些 Linux
            # 发行版 + 字体组合下会段错误, 因此放弃使用. ===
            if IS_LINUX:
                # 用户可设 TK_THEME=clam 强制使用 clam (自负风险)
                forced = os.environ.get("TK_THEME", "").strip().lower()
                if forced and forced in style.theme_names():
                    preferred = (forced, "default", "alt")
                else:
                    preferred = ("default", "alt", "clam")
            else:
                preferred = ("vista", "clam", "alt", "default")
            for theme in preferred:
                if theme in style.theme_names():
                    try:
                        style.theme_use(theme)
                        break
                    except Exception:
                        continue

        if IS_LINUX:
            ui_font = "Ubuntu"
            # 兜底字体探测
            try:
                avail = set(tkfont.families())
                for cand in ("Ubuntu", "Noto Sans CJK SC", "Source Han Sans CN",
                             "WenQuanYi Micro Hei", "DejaVu Sans"):
                    if cand in avail:
                        ui_font = cand
                        break
            except Exception:
                ui_font = "DejaVu Sans"
        elif IS_WINDOWS:
            ui_font = "Microsoft YaHei UI"
        else:
            ui_font = "Helvetica"
        self._ui_font = ui_font

        # Linux 安全模式: 用户出现段错误时设置 LINUX_SAFE_UI=1 完全跳过 configure
        if IS_LINUX and os.environ.get("LINUX_SAFE_UI") in ("1", "true", "yes"):
            try:
                style.configure("Header.TLabel", foreground="#0D47A1")
                style.configure("Status.TLabel", foreground="#37474F")
            except Exception:
                pass
            return

        def safe_cfg(name, **kw):
            try:
                style.configure(name, **kw)
            except Exception as e:
                print(f"[warn] style.configure({name}) 失败: {e}", file=sys.stderr)

        def safe_map(name, **kw):
            try:
                style.map(name, **kw)
            except Exception as e:
                print(f"[warn] style.map({name}) 失败: {e}", file=sys.stderr)

        # === Linux: 完全不动 ttk 样式数据库 (避免 Tk 8.6 段错误).
        # 只配 Header/Status 两个自定义 TLabel 样式 (它们不与系统 ttk 元素共享).
        # 想要更花哨可以设环境变量 LINUX_FANCY_UI=1 (自负风险). ===
        if IS_LINUX:
            try:
                style.configure("Header.TLabel",
                                font=(ui_font, 13, "bold"),
                                foreground="#0D47A1")
            except Exception:
                pass
            try:
                style.configure("Status.TLabel",
                                font=(ui_font, 9),
                                foreground="#5f6368")
            except Exception:
                pass

            if os.environ.get("LINUX_FANCY_UI") in ("1", "true", "yes"):
                # 用户主动选择: 加 padding 美化 (仍只动安全选项)
                ACCENT = "#1a73e8"
                safe_cfg("TButton", padding=(12, 6))
                safe_cfg("Accent.TButton", padding=(14, 7),
                         font=(ui_font, 10, "bold"))
                safe_cfg("TLabelframe", padding=8)
                safe_cfg("TLabelframe.Label",
                         font=(ui_font, 10, "bold"), foreground=ACCENT)
                safe_cfg("TNotebook.Tab", padding=(20, 8),
                         font=(ui_font, 10))
            return

        safe_cfg(".", font=(ui_font, 10))
        safe_cfg("TButton", padding=(10, 6))
        safe_cfg("Accent.TButton", padding=(12, 6), font=(ui_font, 10, "bold"))
        safe_cfg("Danger.TButton", padding=(10, 6))
        safe_cfg("TLabel", padding=(2, 2))
        safe_cfg("TLabelframe", padding=8)
        safe_cfg("TLabelframe.Label", font=(ui_font, 10, "bold"),
                 foreground="#1565C0")
        safe_cfg("TNotebook.Tab", padding=(20, 8), font=(ui_font, 10))
        safe_cfg("Header.TLabel", font=(ui_font, 12, "bold"),
                 foreground="#0D47A1", padding=(4, 2))
        safe_cfg("Status.TLabel", font=(ui_font, 9),
                 foreground="#37474F", padding=(8, 4))
        safe_cfg("TCombobox", padding=4)
        safe_cfg("TEntry", padding=4)
        safe_cfg("TPanedwindow", background="#90A4AE")

    def _build_menu(self):
        bar = tk.Menu(self)
        view = tk.Menu(bar, tearoff=0)

        # === 主题菜单: 按浅色/深色分组 ===
        themes_menu = tk.Menu(view, tearoff=0)
        light_menu = tk.Menu(themes_menu, tearoff=0)
        dark_menu = tk.Menu(themes_menu, tearoff=0)
        compat_menu = tk.Menu(themes_menu, tearoff=0)
        compat_names = {"深色", "Solarized"}  # 旧名兼容, 单独放
        for name, t in THEMES.items():
            if name in compat_names:
                target = compat_menu
            elif t.get("ui") == "dark":
                target = dark_menu
            else:
                target = light_menu
            target.add_command(label=name,
                               command=lambda n=name: self._set_theme(n))
        themes_menu.add_cascade(label="☀ 浅色主题", menu=light_menu)
        themes_menu.add_cascade(label="☾ 深色主题", menu=dark_menu)
        themes_menu.add_separator()
        themes_menu.add_cascade(label="(旧名兼容)", menu=compat_menu)
        view.add_cascade(label="◐ 主题", menu=themes_menu)

        if HAS_SVTTK:
            ui_menu = tk.Menu(view, tearoff=0)
            ui_menu.add_command(label="UI 浅色 (Sun Valley)",
                                command=lambda: self._set_ui_theme("light"))
            ui_menu.add_command(label="UI 深色 (Sun Valley)",
                                command=lambda: self._set_ui_theme("dark"))
            view.add_cascade(label="界面风格", menu=ui_menu)
        view.add_separator()
        view.add_command(label="字体...", command=self._choose_font)
        view.add_command(label="自定义背景色...", command=self._choose_bg)
        view.add_command(label="自定义字体颜色...", command=self._choose_fg)
        bar.add_cascade(label="视图", menu=view)

        help_menu = tk.Menu(bar, tearoff=0)
        help_menu.add_command(label="关于", command=self._show_about)
        bar.add_cascade(label="帮助", menu=help_menu)
        self.config(menu=bar)

    def _show_about(self):
        messagebox.showinfo(
            f"关于 {APP_TITLE}",
            f"{APP_TITLE}\n"
            f"版本: v{APP_VERSION}\n\n"
            "实时 logcat 抓取 + 多关键字高亮 + scrcpy 投屏/录制\n"
            "日志文件查看器: 多文件标签 / 双击过滤行跳转 / 拖拽加载 / 编辑保存\n\n"
            f"作者: {APP_AUTHOR}\n"
            f"邮箱: {APP_EMAIL}\n\n"
            "Made with tkinter + sv-ttk"
        )

    def _set_ui_theme(self, mode):
        if not HAS_SVTTK:
            return
        try:
            sv_ttk.set_theme(mode)
            # 同步日志区主题
            if mode == "dark":
                self._set_theme("深色")
            else:
                self._set_theme("浅色 (默认)")
            self.set_status(f"界面风格: {mode}")
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def _build_ui(self):
        # 状态栏先创建, 供子 Tab 在构造时调用 set_status
        _stage("build_ui: status bar")
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Frame(self)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Separator(status_bar, orient=tk.HORIZONTAL).pack(fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_var,
                  anchor=tk.W, style="Status.TLabel").pack(fill=tk.X)

        # 顶部 Header (紧凑居中)
        _stage("build_ui: header")
        header = ttk.Frame(self, padding=(8, 4, 8, 4))
        header.pack(fill=tk.X)
        # 居中容器
        center = ttk.Frame(header)
        center.pack(anchor="center")
        try:
            if os.path.exists(ICON_PNG):
                self._header_icon = tk.PhotoImage(file=ICON_PNG).subsample(12, 12)
                ttk.Label(center, image=self._header_icon).pack(side=tk.LEFT, padx=(0, 6))
        except Exception as e:
            print(f"[warn] header icon: {e}", file=sys.stderr)
        ttk.Label(center, text="ADB 日志查看工具",
                  style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X)

        _stage("build_ui: notebook")
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        _stage("build_ui: LiveLogcatTab")
        self.live_tab = LiveLogcatTab(self.notebook, self)
        _stage("build_ui: FileViewerTab")
        self.file_tab = FileViewerTab(self.notebook, self)
        _stage("build_ui: notebook.add")
        self.notebook.add(self.live_tab, text="  ▶  实时 Logcat  ")
        self.notebook.add(self.file_tab, text="  ▤  日志文件查看  ")

        if not HAS_DND:
            self.set_status("提示: 未安装 tkinterdnd2, 拖拽不可用 (pip install tkinterdnd2)")
        _stage("build_ui: done")

    def _set_theme(self, name):
        if name not in THEMES:
            return
        self.current_theme = THEMES[name].copy()
        self.current_theme_name = name
        self._apply_theme_all()
        # 同步 UI chrome (深色主题 -> 深色 UI)
        ui_mode = self.current_theme.get("ui", "light")
        self._apply_ui_chrome(ui_mode)
        # 同步 sv-ttk 界面风格 (Win/macOS 上默认启用的现代主题)
        if HAS_SVTTK:
            try:
                target = "dark" if ui_mode == "dark" else "light"
                if sv_ttk.get_theme() != target:
                    sv_ttk.set_theme(target)
                    # sv-ttk 切换后会重置样式, 重新应用我们的 chrome
                    self._apply_ui_chrome(ui_mode)
            except Exception as e:
                print(f"[warn] sv_ttk 同步失败: {e}", file=sys.stderr)
        self.set_status(f"主题: {name}")
        self._save_theme_pref(name)

    def _save_theme_pref(self, name):
        try:
            pref_file = os.path.join(os.path.expanduser("~"),
                                     ".adb_log_viewer_theme")
            with open(pref_file, "w", encoding="utf-8") as f:
                f.write(name)
        except Exception:
            pass

    def _load_theme_pref(self):
        try:
            pref_file = os.path.join(os.path.expanduser("~"),
                                     ".adb_log_viewer_theme")
            if os.path.exists(pref_file):
                with open(pref_file, "r", encoding="utf-8") as f:
                    name = f.read().strip()
                    if name in THEMES:
                        return name
        except Exception:
            pass
        return None

    def _apply_ui_chrome(self, ui_mode):
        """根据主题切换 UI chrome 颜色 (按钮/输入框/Combobox/Notebook 等).
        Linux 上谨慎只动 background/foreground/font 安全选项 (避免 Tk 8.6 段错误)."""
        theme = self.current_theme
        bg = theme.get("bg", "#ffffff")
        fg = theme.get("fg", "#000000")
        sel = theme.get("select", "#bbdefb")
        is_dark = ui_mode == "dark"

        if is_dark:
            panel_bg = self._tint(bg, 0.04)
            btn_bg = self._tint(bg, 0.10)
            btn_hover = self._tint(bg, 0.18)
            btn_fg = "#ffffff"
            entry_bg = self._tint(bg, 0.06)
            border = self._tint(bg, 0.20)
            tab_bg = self._tint(bg, -0.02)
            tab_active = bg
            accent = "#4ec9b0"
            accent_btn_bg = "#0e639c"
            accent_btn_hover = "#1177bb"
            danger_btn_bg = "#c14545"
            header_fg = "#4ec9b0"
            status_fg = "#9cdcfe"
        else:
            panel_bg = self._tint(bg, -0.02)
            btn_bg = self._tint(bg, -0.06)
            btn_hover = self._tint(bg, -0.12)
            btn_fg = fg
            entry_bg = "#ffffff"
            border = self._tint(bg, -0.18)
            tab_bg = self._tint(bg, -0.06)
            tab_active = bg
            accent = "#1a73e8"
            accent_btn_bg = "#1a73e8"
            accent_btn_hover = "#1565c0"
            danger_btn_bg = "#d93025"
            header_fg = "#0D47A1"
            status_fg = "#5f6368"

        ui_font = getattr(self, "_ui_font", "Helvetica")

        try:
            self.configure(background=bg)
        except Exception:
            pass

        style = ttk.Style(self)

        def cfg(name, **kw):
            try:
                style.configure(name, **kw)
            except Exception:
                pass

        def mp(name, **kw):
            try:
                style.map(name, **kw)
            except Exception:
                pass

        # === 容器/标签 ===
        cfg("TFrame", background=bg)
        cfg("TLabel", background=bg, foreground=fg)
        cfg("TLabelframe", background=bg, foreground=accent)
        cfg("TLabelframe.Label", background=bg, foreground=accent,
            font=(ui_font, 10, "bold"))
        cfg("Header.TLabel", background=bg, foreground=header_fg,
            font=(ui_font, 13, "bold"))
        cfg("Status.TLabel", background=panel_bg, foreground=status_fg,
            font=(ui_font, 9))
        cfg("TSeparator", background=border)

        # === Notebook (Tab) ===
        cfg("TNotebook", background=bg, borderwidth=0)
        cfg("TNotebook.Tab",
            background=tab_bg, foreground=fg,
            padding=(20, 8), font=(ui_font, 10))
        mp("TNotebook.Tab",
           background=[("selected", tab_active),
                       ("active", btn_hover)],
           foreground=[("selected", accent), ("active", fg)])

        # === 按钮 ===
        cfg("TButton",
            background=btn_bg, foreground=btn_fg,
            bordercolor=border, lightcolor=btn_bg, darkcolor=btn_bg,
            focuscolor=btn_bg, padding=(10, 6),
            font=(ui_font, 10))
        mp("TButton",
           background=[("active", btn_hover), ("pressed", border)],
           foreground=[("active", btn_fg)],
           bordercolor=[("focus", accent)])

        cfg("Accent.TButton",
            background=accent_btn_bg, foreground="#ffffff",
            bordercolor=accent_btn_bg, lightcolor=accent_btn_bg,
            darkcolor=accent_btn_bg, padding=(12, 6),
            font=(ui_font, 10, "bold"))
        mp("Accent.TButton",
           background=[("active", accent_btn_hover),
                       ("pressed", accent_btn_hover)],
           foreground=[("active", "#ffffff")])

        cfg("Danger.TButton",
            background=danger_btn_bg, foreground="#ffffff",
            bordercolor=danger_btn_bg, lightcolor=danger_btn_bg,
            darkcolor=danger_btn_bg, padding=(10, 6),
            font=(ui_font, 10, "bold"))
        mp("Danger.TButton",
           background=[("active", self._tint(danger_btn_bg, 0.10))],
           foreground=[("active", "#ffffff")])

        # === Entry / Combobox ===
        cfg("TEntry",
            fieldbackground=entry_bg, foreground=fg,
            insertcolor=fg, bordercolor=border,
            lightcolor=border, darkcolor=border,
            padding=4)
        mp("TEntry",
           fieldbackground=[("readonly", entry_bg)],
           bordercolor=[("focus", accent)])

        cfg("TCombobox",
            fieldbackground=entry_bg, foreground=fg,
            background=btn_bg, bordercolor=border,
            lightcolor=border, darkcolor=border,
            arrowcolor=fg, padding=4)
        mp("TCombobox",
           fieldbackground=[("readonly", entry_bg)],
           foreground=[("readonly", fg)],
           background=[("readonly", btn_bg)],
           bordercolor=[("focus", accent)])
        try:
            self.option_add("*TCombobox*Listbox.background", entry_bg)
            self.option_add("*TCombobox*Listbox.foreground", fg)
            self.option_add("*TCombobox*Listbox.selectBackground", sel)
            self.option_add("*TCombobox*Listbox.selectForeground",
                            "#ffffff" if is_dark else fg)
            self.option_add("*TCombobox*Listbox.font", (ui_font, 10))
        except Exception:
            pass

        cfg("TCheckbutton", background=bg, foreground=fg,
            font=(ui_font, 10))
        cfg("TRadiobutton", background=bg, foreground=fg,
            font=(ui_font, 10))

        cfg("TScrollbar", background=btn_bg, troughcolor=panel_bg,
            bordercolor=border, arrowcolor=fg)
        mp("TScrollbar", background=[("active", btn_hover)])

        # === 同步 tk 原生 widget (Linux 用的 Checkbutton 等) ===
        self._tk_widget_bg = bg
        self._tk_widget_fg = fg
        self._tk_widget_select = sel
        try:
            self._sync_tk_widgets(self)
        except Exception:
            pass

    def _sync_tk_widgets(self, parent):
        """递归同步所有 tk 原生 widget 的 bg/fg (Linux 上 tk.Checkbutton 等)."""
        try:
            children = parent.winfo_children()
        except Exception:
            return
        bg = self._tk_widget_bg
        fg = self._tk_widget_fg
        sel = self._tk_widget_select
        for w in children:
            try:
                cls = w.winfo_class()
            except Exception:
                continue
            try:
                if cls in ("Checkbutton", "Radiobutton"):
                    w.configure(background=bg, foreground=fg,
                                activebackground=bg, activeforeground=fg,
                                selectcolor=bg, highlightbackground=bg)
                elif cls == "Frame":
                    w.configure(background=bg)
                elif cls == "Label":
                    w.configure(background=bg, foreground=fg)
                elif cls == "Menu":
                    w.configure(background=bg, foreground=fg,
                                activebackground=sel,
                                activeforeground=fg)
            except Exception:
                pass
            self._sync_tk_widgets(w)

    @staticmethod
    def _tint(hex_color, amount):
        """颜色变亮 (amount > 0) 或变暗 (amount < 0). amount: -1.0 ~ 1.0."""
        try:
            c = hex_color.lstrip("#")
            if len(c) != 6:
                return hex_color
            r = int(c[0:2], 16)
            g = int(c[2:4], 16)
            b = int(c[4:6], 16)
            if amount > 0:
                r = int(r + (255 - r) * amount)
                g = int(g + (255 - g) * amount)
                b = int(b + (255 - b) * amount)
            else:
                r = int(r * (1 + amount))
                g = int(g * (1 + amount))
                b = int(b * (1 + amount))
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _apply_theme_all(self):
        for tab in (self.live_tab, self.file_tab):
            if hasattr(tab, "log_view"):
                tab.log_view.apply_theme(self.current_theme)
            if hasattr(tab, "iter_views"):
                for v in tab.iter_views():
                    v.apply_theme(self.current_theme)

    def _choose_bg(self):
        c = colorchooser.askcolor(title="选择背景色", initialcolor=self.current_theme["bg"])
        if c and c[1]:
            self.current_theme["bg"] = c[1]
            self._apply_theme_all()

    def _choose_fg(self):
        c = colorchooser.askcolor(title="选择字体颜色", initialcolor=self.current_theme["fg"])
        if c and c[1]:
            self.current_theme["fg"] = c[1]
            self._apply_theme_all()

    def _choose_font(self):
        dlg = tk.Toplevel(self)
        dlg.title("选择字体")
        dlg.transient(self)
        dlg.grab_set()
        ttk.Label(dlg, text="字体:", padding=4).grid(row=0, column=0, sticky="w")
        family_var = tk.StringVar(value=self.font_family)
        families = sorted(set(tkfont.families()))
        ttk.Combobox(dlg, textvariable=family_var, values=families, width=30).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(dlg, text="字号:", padding=4).grid(row=1, column=0, sticky="w")
        size_var = tk.IntVar(value=self.font_size)
        ttk.Spinbox(dlg, from_=6, to=24, textvariable=size_var, width=6).grid(row=1, column=1, sticky="w", padx=4)

        def ok():
            self.font_family = family_var.get()
            self.font_size = size_var.get()
            for tab in (self.live_tab, self.file_tab):
                if hasattr(tab, "log_view"):
                    tab.log_view.apply_font(self.font_family, self.font_size)
                if hasattr(tab, "iter_views"):
                    for v in tab.iter_views():
                        v.apply_font(self.font_family, self.font_size)
            dlg.destroy()
        ttk.Button(dlg, text="确定", command=ok).grid(row=2, column=0, columnspan=2, pady=8)

    def set_status(self, msg):
        self.status_var.set(f"{datetime.now().strftime('%H:%M:%S')}  {msg}")

    def _on_close(self):
        try:
            self.live_tab.stop()
        except Exception:
            pass
        self.destroy()


def main():
    # Ubuntu 20.04: X11 RENDER BadLength 默认致命, 设置自定义错误处理器使其非致命
    if platform.system() == "Linux":
        try:
            import ctypes, ctypes.util
            _xlib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
            _xerr_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
            _xerr_handler = _xerr_t(lambda display, event: 0)  # 忽略错误
            _xlib.XSetErrorHandler(_xerr_handler)
            # 防止被 GC 回收
            main._xerr_handler = _xerr_handler
        except Exception:
            pass
    try:
        App().mainloop()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        # 立即打印到 stderr, Linux 调试用
        print("\n========== 启动失败 traceback ==========", file=sys.stderr)
        print(tb, file=sys.stderr, flush=True)
        log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error.log")
        try:
            with open(log, "w", encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
        # Linux: Tk 已损坏, 不再调用 messagebox 避免二次段错误
        if platform.system() == "Windows":
            try:
                import tkinter as _tk
                from tkinter import messagebox as _mb
                r = _tk.Tk(); r.withdraw()
                _mb.showerror("启动失败", tb)
                r.destroy()
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
