"""Computer Use for the Complete mode: screen capture + Windows OCR + mouse/keyboard.

Screenshots are saved under data/screenshots and their OCR text is returned, so
text-only local models can still read what is on screen. Vision-capable models can
later receive the PNG path. Input uses Win32 SendInput; elevated windows require the
admin helper and are out of scope for this basic layer.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import ImageGrab
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from runtime_paths import DATA_ROOT, SOURCE_ROOT

mcp = FastMCP("V-Agent Computer")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]


def _send(*items: INPUT):
    array = (INPUT * len(items))(*items)
    if user32.SendInput(len(items), array, ctypes.sizeof(INPUT)) != len(items):
        raise OSError("SendInput was blocked by Windows UIPI or an inactive/locked desktop session.")


def _mouse(flags: int, x: int = 0, y: int = 0, data: int = 0):
    _send(INPUT(type=0, u=INPUTUNION(mi=MOUSEINPUT(x, y, data, flags, 0, 0))))


def _key(vk: int, up: bool = False):
    flags = 0x0002 if up else 0
    _send(INPUT(type=1, u=INPUTUNION(ki=KEYBDINPUT(vk, 0, flags, 0, 0))))


def _window_text(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _active_window() -> dict:
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return {"hwnd": int(hwnd), "pid": int(pid.value), "title": _window_text(hwnd)}


def _ocr(path: Path) -> str:
    script = SOURCE_ROOT / "agent" / "ocr.ps1"
    if not script.is_file():
        return ""
    powershell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    try:
        result = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-File", str(script), "-Path", str(path)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (result.stdout or "")[:20_000]
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _screenshot() -> dict:
    folder = DATA_ROOT / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("screen-" + time.strftime("%Y%m%d-%H%M%S") + ".png")
    try:
        image = ImageGrab.grab(all_screens=True)
    except OSError as error:
        raise RuntimeError(
            f"Screen capture failed ({error}). Windows blocks desktop grabs when the session is locked, disconnected, or headless."
        ) from error
    image.save(path)
    return {"ok": True, "path": str(path), "width": image.width, "height": image.height,
            "active": _active_window(), "ocr": _ocr(path)}


@mcp.tool(annotations=READ)
def screen_capture() -> str:
    """Capture the full desktop as PNG, save it under data/screenshots, and return OCR text plus the active window."""
    return json.dumps(_screenshot(), ensure_ascii=False)


@mcp.tool(annotations=READ)
def ocr_image(path: str) -> str:
    """Run Windows OCR on an existing PNG/JPEG and return its text."""
    image = Path(path).expanduser().resolve()
    if not image.is_file() or image.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
        raise ValueError("Invalid image file.")
    return json.dumps({"ok": True, "path": str(image), "text": _ocr(image)}, ensure_ascii=False)


@mcp.tool(annotations=READ)
def window_list(limit: int = 40) -> str:
    """List visible top-level windows with titles, process names and the active marker."""
    items = []
    foreground = user32.GetForegroundWindow()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if len(items) >= max(1, min(int(limit), 100)):
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_text(hwnd).strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ""
        try:
            import psutil
            name = psutil.Process(pid.value).name()
        except Exception:
            pass
        items.append({"hwnd": int(hwnd), "title": title[:180], "pid": int(pid.value),
                      "process": name, "active": hwnd == foreground})
        return True

    user32.EnumWindows(callback, 0)
    return json.dumps({"ok": True, "active": _active_window(), "windows": items}, ensure_ascii=False)


@mcp.tool(annotations=WRITE)
def window_focus(title_contains: str) -> str:
    """Bring the first visible window whose title contains the text to the foreground."""
    needle = str(title_contains or "").strip().lower()
    if not needle:
        raise ValueError("Provide part of the window title.")
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = _window_text(hwnd)
            if needle in title.lower():
                found.append((hwnd, title))
                return False
        return True

    user32.EnumWindows(callback, 0)
    if not found:
        raise ValueError("No visible window matched that title.")
    hwnd, title = found[0]
    for attempt in range(2):
        user32.ShowWindow(hwnd, 9)
        if attempt == 1:
            _key(0x12)
            _key(0x12, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.18)
        active = _active_window()
        if active.get("hwnd") == int(hwnd):
            break
    else:
        active = _active_window()
    focused = active.get("hwnd") == int(hwnd)
    out = {"ok": focused, "hwnd": int(hwnd), "title": title[:180], "active": active}
    if not focused:
        out["error"] = "Window did not acquire foreground focus."
    return json.dumps(out, ensure_ascii=False)


@mcp.tool(annotations=WRITE)
def mouse_move(x: int, y: int) -> str:
    """Move the mouse to absolute screen coordinates."""
    user32.SetCursorPos(int(x), int(y))
    return json.dumps({"ok": True, "x": int(x), "y": int(y)})


@mcp.tool(annotations=WRITE)
def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """Click at absolute screen coordinates."""
    count = int(clicks)
    if not 1 <= count <= 3:
        raise ValueError("clicks must be between 1 and 3.")
    flags = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}.get(str(button).lower())
    if not flags:
        raise ValueError("button must be left, right, or middle.")
    user32.SetCursorPos(int(x), int(y))
    for _ in range(count):
        _mouse(flags[0]); _mouse(flags[1]); time.sleep(0.05)
    return json.dumps({"ok": True, "x": int(x), "y": int(y), "button": button}, ensure_ascii=False)


@mcp.tool(annotations=WRITE)
def mouse_scroll(amount: int) -> str:
    """Scroll the wheel; positive is up, negative is down (typically 120 per notch)."""
    delta = int(amount)
    if delta == 0:
        raise ValueError("amount cannot be 0 (use positive to scroll up, negative to scroll down, e.g. 120 or -120).")
    _mouse(0x0800, data=delta)
    return json.dumps({"ok": True, "amount": delta})


KEY_NAMES = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
}
for _i in range(1, 13):
    KEY_NAMES["f" + str(_i)] = 0x6F + _i


@mcp.tool(annotations=WRITE)
def keyboard_type(text: str) -> str:
    """Type Unicode text into the focused control using SendInput."""
    if not isinstance(text, str) or not text:
        raise ValueError("text cannot be empty.")
    count = 0
    for char in text[:4000]:
        if char == "\n":
            _key(0x0D); _key(0x0D, True)
        elif char == "\t":
            _key(0x09); _key(0x09, True)
        else:
            scan = ord(char)
            _send(INPUT(type=1, u=INPUTUNION(ki=KEYBDINPUT(0, scan, 0x0004, 0, 0))),
                  INPUT(type=1, u=INPUTUNION(ki=KEYBDINPUT(0, scan, 0x0004 | 0x0002, 0, 0))))
        count += 1
        time.sleep(0.01)
    return json.dumps({"ok": True, "characters": count}, ensure_ascii=False)


@mcp.tool(annotations=WRITE)
def keyboard_key(keys: str) -> str:
    """Press a key or combo such as Enter, Tab, Ctrl+L, Alt+F4 or Shift+Tab."""
    parts = [part.strip().lower() for part in str(keys or "").split("+") if part.strip()]
    if not parts:
        raise ValueError("Provide a key name.")
    codes = []
    for part in parts:
        code = KEY_NAMES.get(part)
        if code is None and len(part) == 1:
            code = ord(part.upper())
        if code is None:
            raise ValueError("Unsupported key: " + part)
        codes.append(code)
    for code in codes:
        _key(code)
    for code in reversed(codes):
        _key(code, True)
    return json.dumps({"ok": True, "keys": keys}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
