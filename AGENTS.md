# AGENTS.md — Complete Setup Guide for AI Agents

This file contains step-by-step instructions for an AI coding agent to set up the **Raspberry Pi Bluetooth-to-XInput gamepad bridge** for a user end-to-end.

---

## Overview

**Goal:** Route 4 Bluetooth gamepads (Flydigi Direwolf or similar) through a Raspberry Pi to a Windows gaming PC as virtual Xbox 360 controllers.

**Architecture:**
```
Controllers --(Bluetooth)--> Raspberry Pi --(WiFi/TCP)--> Windows PC --(ViGEmBus)--> XInput games
```

---

## Phase 1: Raspberry Pi Setup

### 1.1 Flash the SD card
- Ask the user to download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
- Select **Raspberry Pi OS Lite (32-bit)**
- Press `Ctrl+Shift+X` for advanced options:
  - Hostname: `usbpi` (or user's choice)
  - SSH: enable (password)
  - WiFi: user's SSID + password, country code (e.g. `BR`)
  - Username: `pi` (or user's choice) + password
  - Locale: user's timezone
- Flash the SD card

### 1.2 First boot and SSH
- User inserts SD, powers on Pi
- Agent finds the Pi on the network:
  ```bash
  # Scan for SSH on common IPs
  for i in $(seq 1 254); do (echo >/dev/tcp/192.168.15.$i/22) 2>/dev/null && echo "SSH: 192.168.15.$i" & done; wait
  
  # Or check ARP for Raspberry Pi MAC (b8:27:eb)
  arp -a | grep "b8:27:eb"
  ```
- SSH in: `ssh pi@usbpi.local` or by IP
- First boot takes 2-3 minutes — retry if it doesn't connect immediately

### 1.3 Install dependencies
```bash
sudo apt update
sudo apt install -y python3-evdev python3-pip bluetooth
pip3 install evdev --break-system-packages
```

### 1.4 Verify Bluetooth
```bash
# Unblock if needed
sudo rfkill unblock bluetooth
hciconfig hci0 up
# Should show "UP RUNNING"
hciconfig hci0
```

### 1.5 Enable Bluetooth auto-start
```bash
sudo sed -i 's/^#AutoEnable=true/AutoEnable=true/' /etc/bluetooth/main.conf
```

---

## Phase 2: Controller Pairing

### 2.1 Pair all 4 controllers
For Flydigi Direwolf: `HOME` to power on, then `FN + A` for Bluetooth mode (blue LED).

```bash
sudo bluetoothctl
scan on
# Wait for "Flydigi Direwolf 3" to appear
pair AA:BB:CC:DD:EE:01
connect AA:BB:CC:DD:EE:01
trust AA:BB:CC:DD:EE:01
# Repeat for controllers 2-4
```

Note each MAC address. After all 4 are paired, verify:
```bash
# Should show 4 devices, all "Paired: yes, Trusted: yes"
echo "devices" | bluetoothctl
```

### 2.2 Verify /dev/input/js* devices appear
With controllers powered on and connected:
```bash
ls /dev/input/js*  # Should show js0, js1, js2, js3
```

If they don't appear, reconnect manually:
```bash
for mac in MAC1 MAC2 MAC3 MAC4; do
    echo -e "connect $mac" | bluetoothctl
    sleep 1
done
```

---

## Phase 3: Deploy Server on Pi

### 3.1 Upload files
Copy from the repo to the Pi:
```bash
scp server/gamepad-server.py pi@usbpi.local:/home/pi/
scp scripts/bt-autoconnect.sh pi@usbpi.local:/home/pi/
ssh pi@usbpi.local "chmod +x /home/pi/bt-autoconnect.sh"
```

### 3.2 Edit bt-autoconnect.sh with actual MACs
Replace the placeholder MACs with the ones from Phase 2:
```bash
ssh pi@usbpi.local "nano /home/pi/bt-autoconnect.sh"
```
The script should contain:
```bash
MACS=(
    "actual:mac:of:controller:01"
    "actual:mac:of:controller:02"
    "actual:mac:of:controller:03"
    "actual:mac:of:controller:04"
)
```

### 3.3 Install systemd services
Copy from `systemd/` in the repo:
```bash
scp systemd/bt-autoconnect.service pi@usbpi.local:/tmp/
scp systemd/gamepad-server.service pi@usbpi.local:/tmp/
scp systemd/wifi-fix.service pi@usbpi.local:/tmp/
ssh pi@usbpi.local "sudo mv /tmp/*.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable bt-autoconnect gamepad-server wifi-fix"
```

### 3.4 WiFi persistence
The Pi 3B sometimes fails to connect WiFi on boot. The `wifi-fix.service` retries after 10 seconds. Verify it's targeting the right SSID:
```bash
ssh pi@usbpi.local "sudo sed -i 's/SkyNet2G/ACTUAL_SSID/g' /etc/systemd/system/wifi-fix.service && sudo systemctl daemon-reload"
```

### 3.5 Test reboot (WiFi only, no ethernet)
```bash
ssh pi@usbpi.local "sudo reboot"
# Wait 60-90 seconds, then try via WiFi IP
ssh pi@192.168.15.84 "echo ONLINE"
```
If WiFi doesn't come up, have the user plug in ethernet temporarily, then debug:
```bash
ssh pi@192.168.15.5 "nmcli con show SkyNet2G | grep autoconnect"
```

---

## Phase 4: Windows Setup

### 4.1 Install ViGEmBus driver
- Download from: https://github.com/nefarius/ViGEmBus/releases/latest
- The user must run the installer (GUI, requires admin)
- Verify: Device Manager should show "ViGEmBus" under "System devices"

### 4.2 Install Python 3.12
- Download from https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe
- Install with "Add to PATH" checked
- Or install silently: `python-3.12.3-amd64.exe /quiet PrependPath=1 Include_pip=1`
- Verify: `python --version` and `pip --version`

### 4.3 Install vgamepad
```bash
pip install vgamepad
```

### 4.4 Copy client script
Copy `client/gamepad-client.py` from the repo to the user's Desktop:
```bash
scp client/gamepad-client.py user@windows-ip:/C:/Users/Username/Desktop/
```

Edit the `PI_IP` variable in the script to match the Pi's WiFi IP (or hostname).

### 4.5 Create scheduled task for auto-start
```cmd
schtasks /create /tn "GamepadBridge" /tr "C:\Users\Username\AppData\Local\Programs\Python\Python312\pythonw.exe C:\Users\Username\Desktop\gamepad-client.py" /sc ONLOGON /rl HIGHEST /f
```

Use `pythonw.exe` (not `python.exe`) to avoid a CMD window.

### 4.6 Test the bridge
1. Power on the Pi (WiFi), wait 60s
2. Turn on all 4 controllers (they should auto-connect via `bt-autoconnect.sh`)
3. On Windows, run the scheduled task: `schtasks /run /tn GamepadBridge`
4. Open `joy.cpl` — 4 "Xbox 360 Controller" entries should appear
5. Test each controller — axes and buttons should respond

---

## Troubleshooting

### Pi not appearing on network
- Check `arp -a | grep "b8:27:eb"` — the Pi's MAC prefix
- First boot takes 2-3 minutes. Power cycle if stuck.
- WiFi may need ethernet for initial setup (race condition)

### Bluetooth devices not connecting
- Verify `AutoEnable=true` in `/etc/bluetooth/main.conf`
- Run `bt-autoconnect.sh` manually: `sudo /home/pi/bt-autoconnect.sh`
- Check `bluetoothctl` output for "Paired: yes, Trusted: yes"
- If controllers show "Connected: yes" but no `/dev/input/js*`, the HID profile didn't negotiate — disconnect and reconnect

### Controllers appear in joy.cpl but don't work in games
- Verify ViGEmBus is installed (Device Manager)
- Check `pythonw.exe` is running (Task Manager)
- Restart the bridge client: `schtasks /run /tn GamepadBridge`
- Some games require the controller to be "Player 1" — reorder in joy.cpl

### Under-voltage (throttled != 0x0)
```bash
vcgencmd get_throttled
```
- `0x0` = OK
- `0x50005` = under-voltage has occurred
- Fix: shorter/thicker microUSB cable, 5.1V 2.5A+ power supply

### WiFi doesn't auto-connect on boot
- This is a known Pi 3B race condition
- The `wifi-fix.service` retries after 10 seconds
- If still failing, increase the delay or add `nmcli con up SSID` to `/etc/rc.local`

---

## File Reference

| File | Location | Purpose |
|---|---|---|
| `gamepad-server.py` | `/home/pi/` on Pi | Reads /dev/input/js* and streams via TCP |
| `gamepad-client.py` | Desktop on Windows | Receives TCP data, feeds ViGEmBus |
| `bt-autoconnect.sh` | `/home/pi/` on Pi | Connects known Bluetooth MACs |
| `bt-autoconnect.service` | `/etc/systemd/system/` | Runs BT connect on boot |
| `gamepad-server.service` | `/etc/systemd/system/` | Runs gamepad server on boot |
| `wifi-fix.service` | `/etc/systemd/system/` | Retries WiFi on boot |
| `install.sh` | Run on Pi | One-shot dependency install |

---

## Hardware Requirements

- Raspberry Pi 3B or newer (needs Bluetooth + WiFi)
- 5V 2.5A+ power supply with short/thick microUSB cable
- 4 Bluetooth gamepads (tested: Flydigi Direwolf 3 in `FN+A` mode)
- Windows 10/11 PC with ViGEmBus, Python 3.12
- Both devices on same LAN

---

## Time Estimate

| Phase | Time |
|---|---|
| Flash SD + first boot | 10 min |
| Install dependencies | 5 min |
| Pair 4 controllers | 10 min |
| Deploy scripts + services | 5 min |
| Windows setup | 10 min |
| Testing + debugging | 15 min |
| **Total** | **~55 min** |
