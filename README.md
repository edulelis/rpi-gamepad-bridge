# Raspberry Pi as a Wireless Multi-Controller Bridge for Windows

> How I turned a Raspberry Pi 3B into a 4-player wireless gamepad bridge using Bluetooth, Python, and ViGEmBus.

---

## The Problem

Here's the setup: gaming PC in one room. LG WebOS TV in the living room, running Moonlight to stream games from the PC via Sunshine. Works great.

Except for one thing: **WebOS only pairs 3 Bluetooth controllers.** I have 4 Flydigi Direwolf controllers and friends who want to play split-screen. 

I could buy a USB hub and run cables. I could pay for VirtualHere. But I had a Raspberry Pi 3B collecting dust in a drawer, and I'm stubborn.


**Requirements:**
- 4 wireless gamepads working simultaneously
- Controllers must feel native (no perceptible lag)
- Fully automatic (boot PC + Pi → play)
- Nothing plugged into the TV USB ports

---

## What Didn't Work

### The Dongles (at all)

Before even touching the Pi, I plugged a Flydigi dongle straight into the Windows PC. The controller wouldn't pair. Tried all 4 controllers. Tried every button combo (`FN+X`, `FN+A`, holding the dongle reset pin). Nothing. White LED just blinked forever.

The Flydigi dongles simply wouldn't pair with the controllers — not over USB/IP, not even plugged directly into the PC. Tried all 4 controllers, every button combo, the reset pin. Nothing. White LED blinked forever.

### USB/IP (worked, but useless without dongles)

Still curious, I tested one dongle through USB/IP — Pi as server, Windows as client. The Linux `usbip` server detected it. `usbip list -r` from Windows saw the device. `attach` succeeded on the second try. But since I couldn't pair a controller to it, this was academic. The USB/IP part is solid — the problem was always the dongle itself.

Also worth noting: the Pi kept dropping the dongle due to under-voltage (`throttled=0x50005`). A cheap thin microUSB cable was the culprit. A short thick cable fixed it.

---

## The Solution: Bluetooth + Gamepad Forwarding

Then it hit me: the Direwolf has Bluetooth mode (`FN + A`, blue LED). And the Pi 3B has Bluetooth built in. 

Instead of forwarding USB devices over the network — which is fragile — why not pair the controllers directly to the Pi and just forward the **gamepad input**? That's just numbers. Axis positions, button presses. A few kilobytes per second. Trivial.

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Raspberry Pi 3B (WiFi, next to TV)                              │
│                                                                  │
│  Bluetooth ─── 4× Flydigi Direwolf (paired, trusted)             │
│       │                                                          │
│       ▼                                                          │
│  /dev/input/js0, js1, js2, js3                                   │
│       │                                                          │
│       ▼                                                          │
│  gamepad-server.py (Python + evdev)                              │
│       │                                                          │
│       │  TCP :9876 (gamepad state @ 50Hz)                        │
│       ▼                                                          │
└───────┬──────────────────────────────────────────────────────────┘
        │
        │  WiFi (same LAN)
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  Windows PC (gaming rig, another room)                           │
│                                                                  │
│  gamepad-client.py (Python + vgamepad)                           │
│       │                                                          │
│       ▼                                                          │
│  ViGEmBus Driver                                                 │
│       │                                                          │
│       ▼                                                          │
│  4× Virtual Xbox 360 Controllers (XInput) → Games see native pads│
│       │                                                          │
│       ▼                                                          │
│  Sunshine → Moonlight (WebOS TV) → 4-player split-screen 🎮      │
└──────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Implementation

### 1. Raspberry Pi Setup

Flash Raspberry Pi OS Lite (32-bit) using the official Imager. Use `Ctrl+Shift+X` to pre-configure:
- Hostname: `usbpi`
- WiFi SSID and password
- SSH enabled
- Username: `pi` (or your Pi username)

Boot the Pi and SSH in.

### 2. Install Dependencies (Pi)

```bash
sudo apt update
sudo apt install -y python3-evdev python3-pip usbip hwdata bluetooth
pip3 install evdev --break-system-packages
```

### 3. Bluetooth: Auto-Connect Script

Create `/home/pi/bt-autoconnect.sh`:

```bash
#!/bin/bash
# Auto-connect all 4 Flydigi Direwolf controllers via Bluetooth
MACS=(
    "AA:BB:CC:DD:EE:01"  # Replace with your controller MACs
    "AA:BB:CC:DD:EE:02"
    "AA:BB:CC:DD:EE:03"
    "AA:BB:CC:DD:EE:04"
)
for mac in "${MACS[@]}"; do
    echo -e "connect $mac\ntrust $mac\nquit" | bluetoothctl 2>/dev/null
    sleep 1
done
```

**Pairing the controllers (one-time):**

Put each controller in Bluetooth mode (`HOME` to turn on, then `FN + A` — blue LED blinking). On the Pi, scan once:

```bash
sudo bluetoothctl
scan on
# Wait for "Flydigi Direwolf 3" to appear, note the MAC
pair AA:BB:CC:DD:EE:01
connect AA:BB:CC:DD:EE:01
trust AA:BB:CC:DD:EE:01
# Repeat for each controller
```

After pairing all 4, copy their MAC addresses into `bt-autoconnect.sh`. From then on, the script connects directly by MAC — **no scanning, no discovery, no interference with other Bluetooth devices in the house.**

### 4. Gamepad Server (Pi)

`/home/pi/gamepad-server.py`:

```python
#!/usr/bin/env python3
"""Reads /dev/input/js* and streams via TCP to Windows"""
import socket, json, struct, glob, time, threading, os

PORT = 9876

def read_gamepad(device_path):
    with open(device_path, 'rb') as f:
        while True:
            data = f.read(8)
            if not data: break
            time_val, value, evtype, number = struct.unpack('<IhBB', data)
            evtype = evtype & 0x7f
            yield (evtype, number, value)

class GamepadState:
    def __init__(self, idx, device_path):
        self.idx = idx
        self.axes = {}
        self.buttons = {}

    def update(self, evtype, number, value):
        if evtype == 1: self.buttons[number] = value
        elif evtype == 2: self.axes[number] = value

    def to_json(self):
        axes = [self.axes.get(i, 0) for i in range(8)]
        buttons = [self.buttons.get(i, 0) for i in range(32)]
        return json.dumps({"id": self.idx, "axes": axes, "buttons": buttons})

def main():
    print("=== Gamepad Server ===")
    while True:
        devices = sorted(glob.glob('/dev/input/js*'))
        if devices: break
        time.sleep(3)

    states = {}
    lock = threading.Lock()
    for i, dev in enumerate(devices):
        state = GamepadState(i, dev)
        states[i] = state
        t = threading.Thread(target=lambda d,i: [states[i].update(*e) for e in read_gamepad(d)], args=(dev,i), daemon=True)
        t.start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PORT))
    server.listen(1)
    conn, _ = server.accept()

    while True:
        time.sleep(0.02)
        with lock:
            for state in states.values():
                conn.sendall((state.to_json() + "\n").encode())

if __name__ == '__main__':
    main()
```

### 5. Gamepad Client (Windows)

**Prerequisites:** Install [ViGEmBus](https://github.com/nefarius/ViGEmBus/releases) driver and Python 3.12.

```cmd
pip install vgamepad
```

`gamepad-client.py`:

```python
#!/usr/bin/env python3
"""Receives gamepad state from Pi and feeds into ViGEmBus"""
import socket, json, sys
import vgamepad as vg

PI_IP = "192.168.15.84"
PORT = 9876

pads = [vg.VX360Gamepad() for _ in range(4)]
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((PI_IP, PORT))

buffer = ""
while True:
    data = sock.recv(4096)
    if not data: break
    buffer += data.decode()
    while "\n" in buffer:
        line, buffer = buffer.split("\n", 1)
        state = json.loads(line.strip())
        idx = state["id"]
        pad = pads[idx]
        axes = state["axes"]
        buttons = state["buttons"]
        pad.left_joystick_float(axes[0] / 32767, -axes[1] / 32767)
        pad.right_joystick_float(axes[2] / 32767, -axes[3] / 32767)
        if axes[4]: pad.left_trigger_float((axes[4] + 32767) / 65534)
        if axes[5]: pad.right_trigger_float((axes[5] + 32767) / 65534)
        for i, b in enumerate(buttons):
            btn = [vg.XUSB_BUTTON.XUSB_GAMEPAD_A, vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                   vg.XUSB_BUTTON.XUSB_GAMEPAD_X, vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                   vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                   vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                   vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
                   vg.XUSB_BUTTON.XUSB_GAMEPAD_START]
            if i < len(btn):
                (pad.press_button if b else pad.release_button)(btn[i])
        pad.update()

sock.close()
```

### 6. Auto-Start (Everything)

**Pi — systemd services:**

```ini
# /etc/systemd/system/bt-autoconnect.service
[Unit]
Description=BT Auto-Connect Flydigi
After=bluetooth.target

[Service]
Type=oneshot
ExecStart=/home/pi/bt-autoconnect.sh
User=pi

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/gamepad-server.service
[Unit]
Description=Gamepad Server
After=bt-autoconnect.service

[Service]
ExecStart=/usr/bin/python3 /home/pi/gamepad-server.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/wifi-fix.service
[Unit]
Description=WiFi Retry on Boot
After=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c "sleep 10; nmcli con up SkyNet2G 2>/dev/null"

[Install]
WantedBy=multi-user.target
```

Enable them:
```bash
sudo systemctl enable bt-autoconnect gamepad-server wifi-fix
```

**Windows — Scheduled Task (Admin):**

```cmd
schtasks /create /tn "GamepadBridge" /tr "C:\Users\...\pythonw.exe C:\Users\...\gamepad-client.py" /sc ONLOGON /rl HIGHEST /f
```

Using `pythonw.exe` (no console window) keeps the process invisible. The task runs on login with highest privileges so ViGEmBus works without UAC prompts.

### 7. Bluetooth Without Scanning

Enable `AutoEnable` in `/etc/bluetooth/main.conf` so the adapter starts on boot:
```ini
AutoEnable=true
```

Then `bt-autoconnect.sh` connects directly to known MACs. No scanning needed — won't interfere with anyone else's headphones or speakers.

---

## Result: Automated Gaming

| Event | What Happens |
|---|---|
| Power on TV + PC | Windows auto-logs in |
| PC boots | GamepadBridge task starts (invisible) |
| Pi boots (WiFi) | BT auto-connects 4 controllers |
| Pi boots | Gamepad server starts, waits for Windows client |
| Controllers turned on | BT auto-pairs, appears as `/dev/input/js0-3` |
| Client connects | 4× Xbox 360 virtual controllers created |
| Open any game | XInput works natively |

**Software: 100% open source**  
**Latency: imperceptible (WiFi, < 5ms on LAN)**

---

## Lessons Learned (the hard way)

1. **USB/IP is fine for keyboards and storage. Terrible for gamepads.** The protocol introduces just enough jitter that wireless dongles lose sync.

2. **A bad USB cable will ruin your week.** `vcgencmd get_throttled` was returning `0x50005` — under-voltage. A cheap thin microUSB cable was dropping the Pi to ~4V under load. Swapped it for a short thick one and everything stabilized.

3. **Bluetooth auto-reconnect on Pi 3B is flaky.** Trusted devices sometimes just… don't. The `bt-autoconnect.sh` boot script plus `AutoEnable=true` fixed it, but it took way too long to figure out.

4. **NetworkManager's WiFi doesn't always come up on headless Pi boot.** A 10-second-delayed retry service fixed the race condition. Ugly, but it works.

5. **ViGEmBus is solid.** Creates real Xbox 360 controllers that every Windows game sees natively. No x360ce, no driver hacks, just XInput.

6. **`pythonw.exe` for invisible Windows services.** No CMD window, no tray icon, just runs.

---

## What Could Be Improved

- **Use a Pi 4 or 5** for better Bluetooth range and WiFi stability
- **Dedicated Bluetooth 5.0 USB dongle** on the Pi for lower latency and multi-device support
- **Binary protocol instead of JSON** for lower CPU usage (JSON @ 50Hz works fine though)
- **Web-based pairing UI** so you don't need to SSH to add new controllers

---

## GitHub Repo

Full source code and systemd unit files available at: *(your repo here)*

---

*Tested on: Raspberry Pi 3B (WiFi 2.4GHz), Windows 10 22H2, 4× Flydigi Direwolf 3, ViGEmBus 1.22.0, Python 3.12*
