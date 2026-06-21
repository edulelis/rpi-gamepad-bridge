#!/bin/bash
# Auto-connect all 4 Flydigi Direwolf controllers via Bluetooth
# No scan needed - connect by MAC directly

MACS=(
    "A4:C1:38:36:D8:E0"
    "A4:C1:38:34:6C:69"
    "A4:C1:38:31:33:B6"
    "A4:C1:38:3A:72:0F"
)

echo "[BT Auto-Connect] Starting..."

for mac in "${MACS[@]}"; do
    echo "  Connecting $mac..."
    echo -e "connect $mac\ntrust $mac\nquit" | bluetoothctl 2>/dev/null
    sleep 1
done

echo "[BT Auto-Connect] Done."
