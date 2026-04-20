import sys
import os
import json
import threading
import time
import ctypes
import requests
import subprocess
import tkinter as tk
from tkinter import ttk
import pystray
from PIL import Image, ImageDraw

# ── Default BIT WiFi names ────────────────────────────────
DEFAULT_WIFI_NAMES = [
    "Hostel-1",  "Hostel-2",  "Hostel-3",  "Hostel-4",
    "Hostel-5",  "Hostel-6",  "Hostel-7",  "Hostel-8",
    "Hostel-9",  "Hostel-10", "Hostel-11", "Hostel-12",
    "Hostel-13", "CAMPUS-WIFI",
]

# ── Config ────────────────────────────────────────────────
def config_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "bit_wifi_config.json")

def load_config():
    try:
        with open(config_path()) as f:
            return json.load(f)
    except:
        return None

def save_config(data):
    with open(config_path(), "w") as f:
        json.dump(data, f, indent=2)

def get_all_wifi_names(cfg):
    """Merge defaults + any custom names saved in config."""
    custom = cfg.get("custom_wifis", []) if cfg else []
    combined = list(DEFAULT_WIFI_NAMES)
    for c in custom:
        if c not in combined:
            combined.append(c)
    return combined

# ── WiFi detection ────────────────────────────────────────
def get_current_ssid():
    """
    Try multiple methods to get the current WiFi SSID.
    Some Windows machines / locales fail with one method but not others.
    """

    # Method 1: netsh (standard, but can fail on non-English Windows)
    try:
        result = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in result.splitlines():
            stripped = line.strip()
            # Match "SSID" but not "BSSID" — works on English Windows
            if stripped.startswith("SSID") and "BSSID" not in stripped:
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    ssid = parts[1].strip()
                    if ssid:
                        return ssid
    except:
        pass

    # Method 2: netsh with cp1252 encoding (common on Indian/non-UTF8 Windows)
    try:
        result = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        result = result.decode("cp1252", errors="replace")
        for line in result.splitlines():
            stripped = line.strip()
            if "SSID" in stripped and "BSSID" not in stripped and ":" in stripped:
                # Also handles translated labels (Hindi/regional Windows)
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    ssid = parts[1].strip()
                    if ssid:
                        return ssid
    except:
        pass

    # Method 3: PowerShell fallback — works on all modern Windows regardless of locale
    try:
        ps_cmd = (
            "(Get-NetConnectionProfile | "
            "Where-Object { $_.InterfaceAlias -like '*Wi*' -or $_.InterfaceAlias -like '*Wireless*' } | "
            "Select-Object -ExpandProperty Name -First 1)"
        )
        result = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=8
        ).strip()
        if result and result != "":
            return result
    except:
        pass

    # Method 4: PowerShell via WiFi adapter profile name
    try:
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "[System.Windows.Forms.SystemInformation]::ComputerName | Out-Null; "
            "$wlan = [Windows.Networking.Connectivity.NetworkInformation, Windows, ContentType=WindowsRuntime]; "
            "$null"
        )
        # Simpler PowerShell: get SSID via netsh profile trick
        ps_cmd2 = (
            "netsh wlan show interfaces | "
            "Select-String 'SSID' | "
            "Where-Object { $_ -notmatch 'BSSID' } | "
            "Select-Object -First 1 | "
            "ForEach-Object { ($_ -split ':',2)[1].Trim() }"
        )
        result = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd2],
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=8
        ).strip()
        if result:
            return result
    except:
        pass

    # Method 5: wmic (older Windows, works even when netsh is broken)
    try:
        result = subprocess.check_output(
            ["wmic", "path", "Win32_NetworkAdapter",
             "where", "NetConnectionStatus=2",
             "get", "NetConnectionID"],
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=8
        )
        # wmic won't give SSID but helps confirm WiFi is connected at least
        # Fall through — not useful for SSID, but logged for debug
    except:
        pass

    return ""


def on_correct_wifi(ssid_list):
    """
    Returns the matched SSID name if current WiFi matches any in ssid_list.
    Uses case-insensitive comparison and partial match for robustness.
    """
    current = get_current_ssid()
    if not current:
        return None
    current_lower = current.lower().strip()
    for ssid in ssid_list:
        ssid_lower = ssid.lower().strip()
        # Exact match (case-insensitive)
        if ssid_lower == current_lower:
            return ssid
        # Partial match: e.g. "Hostel-1" in "BIT-Hostel-1" or vice versa
        if ssid_lower in current_lower or current_lower in ssid_lower:
            return ssid
    return None


def is_internet_alive():
    try:
        r = requests.get("http://clients1.google.com/generate_204", timeout=5)
        if r.status_code == 204:
            return True
    except:
        pass
    try:
        r = requests.get("http://connectivitycheck.gstatic.com/generate_204", timeout=5)
        if r.status_code == 204:
            return True
        # Sophos portal also redirects, so status 200/302 with Sophos content = no internet
    except:
        pass
    return False


def confirm_disconnected():
    """Check twice with 5s gap to avoid false session-expired alerts."""
    if is_internet_alive():
        return False
    time.sleep(5)
    return not is_internet_alive()

# ── Sophos token ──────────────────────────────────────────
def now_ms():
    return str(int(time.time() * 1000))

# ── Login / Logout ────────────────────────────────────────
def do_login(cfg):
    try:
        requests.post(
            "http://192.168.0.2:8090/httpclient.html",
            data={
                "mode":        "191",
                "username":    cfg["username"],
                "password":    cfg["password"],
                "a":           now_ms(),
                "producttype": "0",
            },
            timeout=10
        )
        return True
    except:
        return False

def do_logout(cfg):
    try:
        requests.post(
            "http://192.168.0.2:8090/httpclient.html",
            data={
                "mode":        "193",
                "username":    cfg["username"],
                "a":           now_ms(),
                "producttype": "0",
            },
            timeout=8
        )
    except:
        pass
    time.sleep(2)
    try:
        r = requests.get("http://192.168.0.2:8090/httpclient.html", timeout=5)
        if "Password" in r.text or "sign in" in r.text.lower():
            return True
    except:
        pass
    return not is_internet_alive()

# ── Tray icons ────────────────────────────────────────────
def dot(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([8, 8, 56, 56], fill=color)
    return img

ICON_GREEN  = dot("#22c55e")
ICON_RED    = dot("#ef4444")
ICON_YELLOW = dot("#f59e0b")
ICON_GRAY   = dot("#64748b")

# ── Win32 dialogs ─────────────────────────────────────────
def ask(title, msg):
    res = ctypes.windll.user32.MessageBoxW(0, msg, title, 4 | 0x1000)
    return res == 6

def info(title, msg):
    ctypes.windll.user32.MessageBoxW(0, msg, title, 0x40 | 0x1000)

# ── Settings window ───────────────────────────────────────
_settings_window = [None]

def open_settings(cfg=None, on_save=None):
    if _settings_window[0] is not None:
        try:
            _settings_window[0].lift()
            _settings_window[0].focus_force()
            return
        except:
            _settings_window[0] = None

    def _run():
        root = tk.Tk()
        _settings_window[0] = root
        root.title("BIT WiFi Helper — Settings")
        root.resizable(False, False)
        root.configure(bg="#0f172a")

        w, h = 460, 660
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        root.lift()
        root.attributes("-topmost", True)
        root.after(300, lambda: root.attributes("-topmost", False))

        def on_close():
            _settings_window[0] = None
            root.destroy()
        root.protocol("WM_DELETE_WINDOW", on_close)

        # ── Header ────────────────────────────────────────
        tk.Label(root, text="BIT WiFi Helper", bg="#0f172a",
                 fg="#f1f5f9", font=("Segoe UI", 17, "bold")).pack(pady=(28, 2))
        tk.Label(root, text="Configure your Sophos auto-login", bg="#0f172a",
                 fg="#475569", font=("Segoe UI", 9)).pack()
        tk.Label(root, text="Made by Erevos", bg="#0f172a",
                 fg="#3b82f6", font=("Segoe UI", 8, "italic")).pack(pady=(2, 22))

        pad = tk.Frame(root, bg="#0f172a")
        pad.pack(padx=40, fill="x")

        # ── Credentials ───────────────────────────────────
        tk.Label(pad, text="CREDENTIALS", bg="#0f172a",
                 fg="#3b82f6", font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 4))

        entries = {}
        def field(key, label, placeholder, show=None):
            tk.Label(pad, text=label, bg="#0f172a", fg="#94a3b8",
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(6, 2))
            e = tk.Entry(pad, bg="#1e293b", fg="#f1f5f9",
                         font=("Segoe UI", 10), relief="flat", bd=8,
                         insertbackground="#f1f5f9", show=show or "")
            e.pack(fill="x", ipady=7)
            if cfg and cfg.get(key):
                e.insert(0, cfg[key])
                e.config(fg="#f1f5f9")
            else:
                e.insert(0, placeholder)
                e.config(fg="#475569")
                def on_in(ev, en=e, ph=placeholder):
                    if en.get() == ph:
                        en.delete(0, "end"); en.config(fg="#f1f5f9")
                def on_out(ev, en=e, ph=placeholder):
                    if not en.get():
                        en.insert(0, ph); en.config(fg="#475569")
                e.bind("<FocusIn>",  on_in)
                e.bind("<FocusOut>", on_out)
            entries[key] = e

        field("username", "Username", "e.g. btech10xxxxx")
        field("password", "Password", "your password", show="•")

        # ── WiFi Networks ─────────────────────────────────
        tk.Label(pad, text="", bg="#0f172a").pack()  # spacer
        tk.Label(pad, text="WIFI NETWORK", bg="#0f172a",
                 fg="#3b82f6", font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(8, 4))

        # All available names = defaults + custom saved ones
        all_names    = get_all_wifi_names(cfg)
        saved_ssids  = []
        if cfg:
            saved_ssids = cfg.get("ssids") or ([cfg["ssid"]] if cfg.get("ssid") else [])

        # Selected network (single active network)
        selected_var = tk.StringVar()
        # Pre-select saved one if exists
        initial = saved_ssids[0] if saved_ssids else (all_names[0] if all_names else "")
        selected_var.set(initial)

        # Dropdown (Combobox)
        combo_style = ttk.Style()
        combo_style.theme_use("clam")
        combo_style.configure("Dark.TCombobox",
            fieldbackground="#1e293b", background="#1e293b",
            foreground="#f1f5f9", selectbackground="#3b82f6",
            selectforeground="#f1f5f9", bordercolor="#334155",
            arrowcolor="#94a3b8", insertcolor="#f1f5f9",
            relief="flat"
        )
        combo_style.map("Dark.TCombobox",
            fieldbackground=[("readonly", "#1e293b")],
            foreground=[("readonly", "#f1f5f9")],
            background=[("readonly", "#1e293b"), ("active", "#2d3f55")],
        )

        combo = ttk.Combobox(pad, textvariable=selected_var,
                             values=all_names, state="readonly",
                             style="Dark.TCombobox", font=("Segoe UI", 10))
        combo.pack(fill="x", ipady=5)

        # ── Add custom WiFi ───────────────────────────────
        tk.Label(pad, text="Add a custom WiFi name:", bg="#0f172a",
                 fg="#64748b", font=("Segoe UI", 8)).pack(anchor="w", pady=(12, 2))

        add_row = tk.Frame(pad, bg="#0f172a")
        add_row.pack(fill="x")

        custom_entry = tk.Entry(add_row, bg="#1e293b", fg="#f1f5f9",
                                font=("Segoe UI", 10), relief="flat", bd=8,
                                insertbackground="#f1f5f9")
        custom_entry.pack(side="left", fill="x", expand=True, ipady=7)

        custom_wifis = list(cfg.get("custom_wifis", []) if cfg else [])

        def add_custom():
            name = custom_entry.get().strip()
            if not name:
                return
            if name in combo["values"]:
                selected_var.set(name)
                custom_entry.delete(0, "end")
                return
            # Add to list and save for later
            if name not in custom_wifis:
                custom_wifis.append(name)
            new_vals = list(combo["values"]) + [name]
            combo["values"] = new_vals
            selected_var.set(name)
            custom_entry.delete(0, "end")

        tk.Button(
            add_row, text=" + Add ", command=add_custom,
            bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 9),
            relief="flat", padx=10, pady=0, cursor="hand2",
            activebackground="#334155", activeforeground="#f1f5f9", bd=0
        ).pack(side="left", padx=(6, 0), ipady=7)

        # Also allow pressing Enter in the custom field
        custom_entry.bind("<Return>", lambda e: add_custom())

        # ── Detect current WiFi helper ────────────────────
        def auto_detect_wifi():
            detected = get_current_ssid()
            if detected:
                # Check if it's already in the list
                if detected not in combo["values"]:
                    if detected not in custom_wifis:
                        custom_wifis.append(detected)
                    new_vals = list(combo["values"]) + [detected]
                    combo["values"] = new_vals
                selected_var.set(detected)
                detect_btn.config(text=f"✓ Detected: {detected}", fg="#22c55e")
            else:
                detect_btn.config(text="✗ Could not detect WiFi", fg="#ef4444")

        detect_btn = tk.Button(
            pad, text="⟳ Auto-detect current WiFi", command=auto_detect_wifi,
            bg="#0f172a", fg="#64748b", font=("Segoe UI", 8),
            relief="flat", cursor="hand2", bd=0,
            activebackground="#0f172a", activeforeground="#94a3b8"
        )
        detect_btn.pack(anchor="w", pady=(4, 0))

        # ── Error + Save ──────────────────────────────────
        err_lbl = tk.Label(root, text="", bg="#0f172a",
                           fg="#ef4444", font=("Segoe UI", 8))
        err_lbl.pack(pady=(14, 0))

        def save():
            user = entries["username"].get().strip()
            pwd  = entries["password"].get().strip()
            ssid = selected_var.get().strip()

            if not user or user == "e.g. btech10xxxxx":
                err_lbl.config(text="Please enter your username."); return
            if not pwd or pwd == "your password":
                err_lbl.config(text="Please enter your password."); return
            if not ssid:
                err_lbl.config(text="Please select a WiFi network."); return

            data = {
                "username":     user,
                "password":     pwd,
                "ssids":        [ssid],
                "custom_wifis": custom_wifis,
            }
            save_config(data)
            if on_save:
                on_save(data)
            _settings_window[0] = None
            root.destroy()

        tk.Button(
            root, text="  Save & Apply  ", command=save,
            bg="#3b82f6", fg="white", font=("Segoe UI", 10, "bold"),
            relief="flat", padx=20, pady=10, cursor="hand2",
            activebackground="#2563eb", activeforeground="white", bd=0
        ).pack(pady=18)

        tk.Label(root, text="Saved as bit_wifi_config.json next to the .exe",
                 bg="#0f172a", fg="#334155", font=("Segoe UI", 7)).pack(pady=(0, 16))

        root.mainloop()
        _settings_window[0] = None

    threading.Thread(target=_run, daemon=True).start()

# ── Sign out ──────────────────────────────────────────────
def handle_signout(icon, cfg_holder):
    cfg = cfg_holder[0]
    if not cfg:
        info("No Config", "Set up credentials first via Settings.")
        return
    if ask("Sign Out",
           "Sign out from Sophos WiFi?\n\n"
           "Your session will end so you can\nlog in from another device."):
        icon.icon  = ICON_YELLOW
        icon.title = "BIT WiFi: Signing out..."
        ok = do_logout(cfg)
        if ok:
            icon.icon  = ICON_GRAY
            icon.title = "BIT WiFi: Signed out"
            info("Signed Out", "Session ended.\nYou can now log in from another device.")
        else:
            icon.icon  = ICON_GREEN
            icon.title = "BIT WiFi: Connected"
            info("Sign Out Failed",
                 "Sophos did not end the session.\n\n"
                 "Try manually:\nhttp://192.168.0.2:8090/httpclient.html")

# ── About ─────────────────────────────────────────────────
def show_about():
    info("BIT WiFi Helper",
         "BIT WiFi Helper v1.0\n"
         "Made by Erevos\n\n"
         "Sophos auto-login tool for BIT Mesra.\n"
         "Checks every 15s, confirms twice before alerting.\n\n"
         "Right-click tray icon for all options.")

# ── Monitor ───────────────────────────────────────────────
def monitor(icon, cfg_holder):
    prev_on_wifi   = False
    prev_connected = False
    popup_active   = False

    while True:
        cfg = cfg_holder[0]

        if not cfg:
            icon.icon  = ICON_GRAY
            icon.title = "BIT WiFi: No config — right-click → Settings"
            time.sleep(5)
            continue

        ssids   = cfg.get("ssids") or ([cfg["ssid"]] if cfg.get("ssid") else [])
        matched = on_correct_wifi(ssids)
        on_wifi = matched is not None
        connected = is_internet_alive() if on_wifi else False

        alerts_on = cfg.get("alerts", True)

        # Just joined college WiFi
        if on_wifi and not prev_on_wifi and not popup_active:
            if alerts_on:
                # Ask user before logging in
                popup_active = True
                icon.icon  = ICON_RED
                icon.title = "BIT WiFi: Login needed"
                if ask("BIT WiFi Helper",
                       f"You joined {matched}!\nLogin to Sophos now?"):
                    do_login(cfg)
                    time.sleep(4)
                    if is_internet_alive():
                        icon.icon  = ICON_GREEN
                        icon.title = f"BIT WiFi: Connected ✓  ({matched})"
                    else:
                        icon.icon  = ICON_YELLOW
                        icon.title = "BIT WiFi: Verifying login..."
                popup_active = False
            else:
                # Silent — just show red, user reconnects manually from tray
                icon.icon  = ICON_RED
                icon.title = f"BIT WiFi: Login needed — click tray to reconnect ({matched})"

        # Possible drop — confirm twice before alerting
        elif on_wifi and prev_connected and not connected and not popup_active:
            popup_active = True
            icon.icon  = ICON_YELLOW
            icon.title = "BIT WiFi: Checking..."
            if confirm_disconnected():
                if alerts_on:
                    # Ask user before reconnecting
                    icon.icon  = ICON_RED
                    icon.title = "BIT WiFi: Session expired!"
                    if ask("BIT WiFi — Session Expired",
                           "Your Sophos session has expired.\nReconnect now?"):
                        do_login(cfg)
                        time.sleep(4)
                        if is_internet_alive():
                            icon.icon  = ICON_GREEN
                            icon.title = f"BIT WiFi: Reconnected ✓  ({matched})"
                        else:
                            icon.icon  = ICON_YELLOW
                            icon.title = "BIT WiFi: Verifying..."
                else:
                    # Silent — just turn red, user reconnects manually from tray
                    icon.icon  = ICON_RED
                    icon.title = "BIT WiFi: Session expired — click tray to reconnect"
            else:
                icon.icon  = ICON_GREEN
                icon.title = f"BIT WiFi: Connected ✓  ({matched})"
            popup_active = False

        elif on_wifi and connected:
            icon.icon  = ICON_GREEN
            icon.title = f"BIT WiFi: Connected ✓  ({matched})"

        elif not on_wifi:
            icon.icon  = ICON_GRAY
            icon.title = "BIT WiFi: Not on college network"

        prev_on_wifi   = on_wifi
        prev_connected = connected
        time.sleep(15)

# ── Main ──────────────────────────────────────────────────
def main():
    cfg_holder = [load_config()]

    if not cfg_holder[0]:
        done = threading.Event()
        def first_save(d):
            cfg_holder[0] = d
            done.set()
        open_settings(on_save=first_save)
        done.wait()
        if not cfg_holder[0]:
            sys.exit()

    def on_reconnect(i, it):
        cfg = cfg_holder[0]
        if cfg:
            threading.Thread(target=do_login, args=(cfg,), daemon=True).start()

    def on_signout(i, it):
        threading.Thread(target=handle_signout,
                         args=(i, cfg_holder), daemon=True).start()

    def on_settings(i, it):
        open_settings(cfg=cfg_holder[0],
                      on_save=lambda d: cfg_holder.__setitem__(0, d))

    def on_about(i, it):
        threading.Thread(target=show_about, daemon=True).start()

    def on_quit(i, it):
        i.stop()
        sys.exit()

    def on_toggle_alerts(i, it):
        cfg = cfg_holder[0]
        if not cfg:
            return
        # Flip the alerts value
        cfg["alerts"] = not cfg.get("alerts", True)
        save_config(cfg)
        # Update tray title to reflect new state
        state = "ON" if cfg["alerts"] else "OFF"
        i.title = f"BIT WiFi Helper  •  Alerts {state}  •  Made by Erevos"

    def alerts_checked(it):
        cfg = cfg_holder[0]
        return cfg.get("alerts", True) if cfg else True

    icon = pystray.Icon(
        "bit_wifi", ICON_GRAY,
        "BIT WiFi Helper  •  Made by Erevos",
        menu=pystray.Menu(
            pystray.MenuItem("Reconnect now",               on_reconnect),
            pystray.MenuItem("Sign out",                    on_signout),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Popup alerts",
                on_toggle_alerts,
                checked=alerts_checked   # shows checkmark when ON
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings / Edit credentials", on_settings),
            pystray.MenuItem("About",                       on_about),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",                        on_quit),
        )
    )

    threading.Thread(target=monitor, args=(icon, cfg_holder), daemon=True).start()
    icon.run()

if __name__ == "__main__":
    main()
