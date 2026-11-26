"""
Shortcut and Autostart Manager for GPU Sentry.
Supports Windows (Start Menu .lnk via native IShellLinkW COM & Run registry key)
and Linux (XDG .desktop files in ~/.local/share/applications and ~/.config/autostart).

Always prefers a true GUI (no-console) launcher on Windows:
- Frozen PyInstaller GUI exe (when running packaged release), or
- pythonw.exe + main.py (never a CUI console shim).
"""

import sys
import os
import shutil


def _resolve_windows_gui_target() -> tuple[str, str, str]:
    """
    Returns (exe_path, base_args, work_dir) for launching GPU Sentry on Windows
    without spawning a background console window.
    """
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        return exe, "", os.path.dirname(exe)

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_py = os.path.join(root_dir, "main.py")

    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    if not os.path.isfile(pythonw):
        found = shutil.which("pythonw")
        pythonw = found if found else sys.executable

    if os.path.isfile(main_py):
        return pythonw, f'"{main_py}"', root_dir
    return pythonw, "-m main", root_dir


def _resolve_icon_path() -> str:
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ico = os.path.join(base_dir, "assets", "gpu_sentry.ico")
    if os.path.isfile(ico):
        return ico
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return ico


def get_start_menu_shortcut_path() -> str:
    """Returns the full path to the user's Start Menu / Applications shortcut."""
    if sys.platform == "win32":
        programs = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")
        return os.path.join(programs, "GPU Sentry.lnk")
    else:
        apps = os.path.expanduser("~/.local/share/applications")
        return os.path.join(apps, "gpu-sentry.desktop")


def get_desktop_shortcut_path() -> str:
    """Returns the full path to the Desktop shortcut."""
    if sys.platform == "win32":
        desktop = os.path.expandvars(r"%USERPROFILE%\Desktop")
        return os.path.join(desktop, "GPU Sentry.lnk")
    else:
        desktop = os.path.expanduser("~/Desktop")
        return os.path.join(desktop, "gpu-sentry.desktop")


def is_start_menu_shortcut_installed() -> bool:
    """Checks if the Start Menu shortcut exists."""
    return os.path.isfile(get_start_menu_shortcut_path())


def install_start_menu_shortcut(desktop: bool = False) -> tuple[bool, str]:
    """
    Creates a shortcut in the Windows Start Menu (and optionally Desktop).
    On Linux, creates an XDG .desktop file.
    Returns (success, message).
    """
    if sys.platform == "win32":
        return _install_windows_shortcut(desktop=desktop)
    else:
        return _install_linux_shortcut(desktop=desktop)


def remove_start_menu_shortcut(desktop: bool = False) -> bool:
    """Removes the Start Menu shortcut (and optionally Desktop shortcut)."""
    success = True
    menu_path = get_start_menu_shortcut_path()
    if os.path.isfile(menu_path):
        try:
            os.remove(menu_path)
        except Exception:
            success = False

    if desktop:
        dt_path = get_desktop_shortcut_path()
        if os.path.isfile(dt_path):
            try:
                os.remove(dt_path)
            except Exception:
                success = False

    return success


def _install_windows_shortcut(desktop: bool = False) -> tuple[bool, str]:
    import ctypes
    from ctypes import wintypes
    import uuid

    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        def to_guid(s):
            u = uuid.UUID(s)
            g = GUID()
            ctypes.memmove(ctypes.byref(g), u.bytes_le, 16)
            return g

        CLSID_ShellLink = to_guid("{00021401-0000-0000-C000-000000000046}")
        IID_IShellLinkW = to_guid("{000214F9-0000-0000-C000-000000000046}")
        IID_IPersistFile = to_guid("{0000010b-0000-0000-C000-000000000046}")

        pLink = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_ShellLink), None, 1, ctypes.byref(IID_IShellLinkW), ctypes.byref(pLink)
        )
        if hr != 0 or not pLink.value:
            return False, f"CoCreateInstance failed (hr={hex(hr)})"

        vt = ctypes.cast(
            ctypes.cast(pLink, ctypes.POINTER(ctypes.c_void_p)).contents,
            ctypes.POINTER(ctypes.c_void_p),
        )

        QI_proto = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
        )
        SetPath_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        SetArgs_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        SetDesc_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        SetWorkDir_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        SetIcon_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int)

        QI = QI_proto(vt[0])
        SetDesc = SetDesc_proto(vt[7])
        SetWorkDir = SetWorkDir_proto(vt[9])
        SetArgs = SetArgs_proto(vt[11])
        SetIcon = SetIcon_proto(vt[17])
        SetPath = SetPath_proto(vt[20])

        target_exe, base_args, work_dir = _resolve_windows_gui_target()
        ico_path = _resolve_icon_path()

        SetPath(pLink, target_exe)
        if base_args:
            SetArgs(pLink, base_args)
        SetWorkDir(pLink, work_dir)
        SetDesc(pLink, "GPU & System Sentry - High-Performance Telemetry Dashboard")
        if os.path.isfile(ico_path):
            SetIcon(pLink, ico_path, 0)

        pFile = ctypes.c_void_p()
        hr_qi = QI(pLink, ctypes.byref(IID_IPersistFile), ctypes.byref(pFile))
        if hr_qi != 0 or not pFile.value:
            return False, "QueryInterface IPersistFile failed"

        vt_file = ctypes.cast(
            ctypes.cast(pFile, ctypes.POINTER(ctypes.c_void_p)).contents,
            ctypes.POINTER(ctypes.c_void_p),
        )
        Save_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.BOOL)
        Save = Save_proto(vt_file[6])

        targets = [get_start_menu_shortcut_path()]
        if desktop:
            targets.append(get_desktop_shortcut_path())

        for target in targets:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            hr_save = Save(pFile, target, True)
            if hr_save != 0:
                return False, f"Save failed on {target} (hr={hex(hr_save)})"

        return True, "Start Menu shortcut created successfully."
    except Exception as e:
        return False, str(e)


def _install_linux_shortcut(desktop: bool = False, extra_args: str = "") -> tuple[bool, str]:
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_py = os.path.join(root_dir, "main.py")
    png_icon = os.path.join(root_dir, "assets", "gpu_sentry.png")
    which_bin = shutil.which("gpu-sentry")

    exec_cmd = which_bin if which_bin else f"{sys.executable} {main_py}"
    if extra_args:
        exec_cmd = f"{exec_cmd} {extra_args}"

    desktop_entry = f"""[Desktop Entry]
Type=Application
Name=GPU Sentry
Comment=High-Performance Real-Time Multi-GPU & CPU Telemetry Dashboard
Exec={exec_cmd}
Icon={png_icon}
Terminal=false
Categories=System;Monitor;HardwareSettings;
Keywords=gpu;nvidia;amd;telemetry;hardware;monitor;
"""
    try:
        menu_path = get_start_menu_shortcut_path()
        os.makedirs(os.path.dirname(menu_path), exist_ok=True)
        with open(menu_path, "w", encoding="utf-8") as f:
            f.write(desktop_entry)
        os.chmod(menu_path, 0o755)

        if desktop:
            dt_path = get_desktop_shortcut_path()
            if os.path.isdir(os.path.dirname(dt_path)):
                with open(dt_path, "w", encoding="utf-8") as f:
                    f.write(desktop_entry)
                os.chmod(dt_path, 0o755)

        return True, "Desktop entry created successfully."
    except Exception as e:
        return False, str(e)


def is_autostart_enabled() -> bool:
    """Checks if GPU Sentry is configured to launch on Windows/Linux system login."""
    if sys.platform == "win32":
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ
            )
            val, _ = winreg.QueryValueEx(key, "GPUSentry")
            winreg.CloseKey(key)
            return bool(val)
        except Exception:
            return False
    else:
        autostart_file = os.path.expanduser("~/.config/autostart/gpu-sentry.desktop")
        return os.path.isfile(autostart_file)


def set_autostart(enable: bool, start_minimized: bool = True) -> tuple[bool, str]:
    """Enables or disables launching GPU Sentry on system login."""
    if sys.platform == "win32":
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ,
            )
            if enable:
                target_exe, base_args, _ = _resolve_windows_gui_target()
                parts = [f'"{target_exe}"']
                if base_args:
                    parts.append(base_args)
                if start_minimized:
                    parts.append("--minimized")
                cmd = " ".join(parts)
                winreg.SetValueEx(key, "GPUSentry", 0, winreg.REG_SZ, cmd)
                msg = "Autostart enabled on Windows login."
            else:
                try:
                    winreg.DeleteValue(key, "GPUSentry")
                except FileNotFoundError:
                    pass
                msg = "Autostart disabled."
            winreg.CloseKey(key)
            return True, msg
        except Exception as e:
            return False, str(e)
    else:
        autostart_dir = os.path.expanduser("~/.config/autostart")
        autostart_file = os.path.join(autostart_dir, "gpu-sentry.desktop")
        try:
            if enable:
                os.makedirs(autostart_dir, exist_ok=True)
                root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                main_py = os.path.join(root_dir, "main.py")
                png_icon = os.path.join(root_dir, "assets", "gpu_sentry.png")
                which_bin = shutil.which("gpu-sentry")
                exec_cmd = which_bin if which_bin else f"{sys.executable} {main_py}"
                if start_minimized:
                    exec_cmd = f"{exec_cmd} --minimized"
                entry = f"""[Desktop Entry]
Type=Application
Name=GPU Sentry
Comment=High-Performance Real-Time Multi-GPU & CPU Telemetry Dashboard
Exec={exec_cmd}
Icon={png_icon}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
                with open(autostart_file, "w", encoding="utf-8") as f:
                    f.write(entry)
                os.chmod(autostart_file, 0o755)
                return True, "Autostart enabled on Linux login."
            else:
                if os.path.isfile(autostart_file):
                    os.remove(autostart_file)
                return True, "Autostart disabled."
        except Exception as e:
            return False, str(e)


def refresh_autostart_if_enabled(start_minimized: bool = True):
    """If autostart is already enabled, re-writes the entry to use the current console-free binary."""
    if is_autostart_enabled():
        set_autostart(True, start_minimized=start_minimized)
