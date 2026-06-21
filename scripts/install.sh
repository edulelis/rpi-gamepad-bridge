#!/bin/bash
set -e
echo "=== RPi Gamepad Bridge - Auto Install ==="
echo ""

# Install system packages
sudo apt update
sudo apt install -y python3-evdev python3-pip bluetooth

# Install Python dependencies
pip3 install evdev --break-system-packages 2>/dev/null || pip3 install evdev

# Enable Bluetooth auto-start
sudo sed -i 's/^#AutoEnable=true/AutoEnable=true/' /etc/bluetooth/main.conf

# Copy files
sudo cp server/gamepad-server.py /home/pi/
sudo cp scripts/bt-autoconnect.sh /home/pi/
sudo chmod +x /home/pi/bt-autoconnect.sh /home/pi/gamepad-server.py

# Install systemd services
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bt-autoconnect gamepad-server wifi-fix

echo ""
echo "=== Done! ==="
echo "1. Edit /home/pi/bt-autoconnect.sh with your controller MACs"
echo "2. Pair controllers: sudo bluetoothctl -> scan on -> pair MAC -> trust MAC"
echo "3. Reboot: sudo reboot"
echo "4. On Windows: install ViGEmBus + Python, run client/gamepad-client.py"
