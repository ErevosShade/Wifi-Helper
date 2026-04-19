# BIT WiFi Helper

> Automatic Sophos captive portal login for **Birla Institute of Technology, Mesra**
> Made by **Erevos**

Supports **Windows** and **macOS**

---

## What it does

BIT's college WiFi uses a Sophos firewall that blocks all traffic until you log in through a web form. Sessions expire regularly and you have to log in again manually.

This tool sits silently in your **system tray / menu bar** and handles it for you:

- Detects when you join the college WiFi → asks if you want to login
- Detects when your session expires → asks to reconnect
- Confirms twice before alerting (no false alarms from brief hiccups)
- Sign out button to free your session for another device
- Supports all BIT hostels + CAMPUS-WIFI + any custom network name

---

## Download — no Python needed

👉 **[Download latest release](../../releases/latest)**

| File | Platform |
|------|----------|
| `BIT_WiFi_Helper.exe` | Windows 10/11 |
| `BIT_WiFi_Helper.app.zip` | macOS 12+ |

Just double-click and fill in your credentials on first run.

---

## Windows

### Run the .exe

1. Download `BIT_WiFi_Helper.exe` from Releases
2. Double-click it
3. Fill in your username, password, and select your hostel WiFi
4. A dot appears in your system tray (near the clock) — you're done

**Auto-start on boot:**
`Win + R` → type `shell:startup` → paste a shortcut to the `.exe` there

### Build from source

```bash
# Requirements: Python 3.8+, Windows
pip install -r requirements_windows.txt

# Run directly
python sophos_tray.py

# Build .exe
pyinstaller --onefile --windowed --name "BIT_WiFi_Helper" sophos_tray.py
# Output: dist/BIT_WiFi_Helper.exe
```

### Tray icon (near the clock)

| Color | Meaning |
|-------|---------|
| 🟢 Green | Connected and logged in |
| 🔴 Red | Session expired / login needed |
| 🟡 Yellow | Verifying connection |
| ⚫ Gray | Not on college WiFi |

---

## macOS

### Run the .app

1. Download `BIT_WiFi_Helper.app.zip` from Releases
2. Unzip and drag to Applications
3. Double-click — macOS may ask to allow it (System Settings → Privacy & Security → Open Anyway)
4. Fill in credentials when prompted
5. An emoji icon appears in your **menu bar** (top right)

**Auto-start on boot:**
System Settings → General → Login Items → add `BIT_WiFi_Helper.app`

### Build from source

```bash
# Requirements: Python 3.8+, macOS
pip install -r requirements_mac.txt

# Run directly
python3 sophos_tray_mac.py

# Build .app
pip install py2app
python3 setup_mac.py py2app
# Output: dist/BIT_WiFi_Helper.app
```

### Menu bar icon

| Icon | Meaning |
|------|---------|
| 🟢 | Connected and logged in |
| 🔴 | Session expired / login needed |
| 🟡 | Verifying connection |
| ⚫ | Not on college WiFi |

---

## First run setup

On first launch a setup window (Windows) or step-by-step dialogs (Mac) will ask for:

| Field | Example |
|-------|---------|
| Username | `btech10xxxxx` |
| Password | your Sophos password |
| WiFi Network | pick from dropdown or add custom |

**All 14 BIT networks are pre-loaded:**
Hostel-1 through Hostel-13 and CAMPUS-WIFI.
You can also type any custom name and it gets saved for future use.

Settings are saved to `bit_wifi_config.json` next to the app.
Change anytime via **tray/menu bar icon → Settings / Edit credentials**.

---

## Tray menu options (right-click on Windows, click on Mac)

- **Reconnect now** — manual login
- **Sign out** — ends your Sophos session so another device can log in
- **Settings / Edit credentials** — change username, password, or WiFi
- **About**
- **Quit**

---

## How it works

BIT's Sophos portal accepts a `POST` to `http://192.168.0.2:8090/httpclient.html`:

```
Login:  mode=191, username, password, a=<timestamp_ms>, producttype=0
Logout: mode=193, username, a=<timestamp_ms>, producttype=0
```

The `a` field is a `Date.now()` millisecond timestamp generated fresh per request.

Connectivity is checked every **15 seconds** using two Google endpoints.
Before showing a session-expired popup, it **confirms twice** (5s apart) to avoid false alarms.

---

## Sharing with batchmates

Share just the `.exe` or `.app` — each person fills in **their own credentials** on first run.
Nobody needs Python installed.

---

## Is this against the rules?

You are automating your **own login with your own credentials** — identical to typing it manually. You are not bypassing security or accessing anyone else's account.

---

## Files in this repo

| File | Description |
|------|-------------|
| `sophos_tray.py` | Windows source |
| `sophos_tray_mac.py` | macOS source |
| `requirements_windows.txt` | Windows pip dependencies |
| `requirements_mac.txt` | macOS pip dependencies |
| `README.md` | This file |

---

## License

MIT — free to use, modify, and share.
