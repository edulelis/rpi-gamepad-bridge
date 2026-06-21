#!/usr/bin/env python3
"""
Gamepad Server - runs on Raspberry Pi
Reads /dev/input/js* and streams via TCP to Windows
"""
import socket
import json
import struct
import glob
import time
import threading
import os

PORT = 9876

def read_gamepad(device_path):
    """Read raw events from a gamepad device."""
    try:
        with open(device_path, 'rb') as f:
            while True:
                # Linux joystick event: 8 bytes (time, value, type, number)
                # struct js_event: time(4) + value(2) + type(1) + number(1) = 8 bytes
                # But real format has 4-byte time, 2-byte value, 1-byte type, 1-byte number
                data = f.read(8)
                if not data:
                    break
                time_val, value, evtype, number = struct.unpack('<IhBB', data)
                # Strip down to the actual fields
                evtype = evtype & 0x7f  # Clear init flag
                yield (evtype, number, value)
    except Exception as e:
        print(f"[!] Error reading {device_path}: {e}")

def get_controller_count():
    """Count available controllers."""
    devices = sorted(glob.glob('/dev/input/js*'))
    return len(devices)

class GamepadState:
    """Track state of a single controller."""
    def __init__(self, idx, device_path):
        self.idx = idx
        self.path = device_path
        self.axes = {}
        self.buttons = {}
        self.name = "Unknown"
        # Try to get name
        for line in open(f'/sys/class/input/js{idx}/device/name', 'r'):
            self.name = line.strip()

    def update(self, evtype, number, value):
        if evtype == 1:  # Button
            self.buttons[number] = value
        elif evtype == 2:  # Axis
            self.axes[number] = value

    def to_json(self):
        # Fill axes array (0-7 typical)
        axes = [0] * 8
        for k, v in self.axes.items():
            if k < 8:
                axes[k] = v
        # Fill buttons array (0-31 typical)
        buttons = [0] * 32
        for k, v in self.buttons.items():
            if k < 32:
                buttons[k] = v
        return json.dumps({
            "id": self.idx,
            "name": self.name,
            "axes": axes,
            "buttons": buttons
        })

def main():
    print("=== Gamepad Server (Pi -> Windows) ===")
    
    # Wait for controllers with retry loop
    while True:
        devices = sorted(glob.glob('/dev/input/js*'))
        if devices:
            break
        print(f"[!] Nenhum controle. Aguardando... ({time.strftime('%H:%M:%S')})")
        time.sleep(3)
    
    print(f"[+] {len(devices)} controle(s) encontrados:")
    for d in devices:
        idx = int(d.replace('/dev/input/js', ''))
        name = "Unknown"
        try:
            name = open(f'/sys/class/input/js{idx}/device/name', 'r').read().strip()
        except:
            pass
        print(f"    js{idx}: {name}")
    
    # Start TCP server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PORT))
    server.listen(1)
    print(f"\n[+] Aguardando conexao na porta {PORT}...")
    print(f"    IP do Pi: {os.popen('hostname -I').read().strip()}")
    
    conn, addr = server.accept()
    print(f"[+] Conectado: {addr}")
    
    # Start reader threads for each controller
    states = {}
    lock = threading.Lock()
    
    def reader_thread(dev_path, idx):
        state = GamepadState(idx, dev_path)
        with lock:
            states[idx] = state
        for evtype, number, value in read_gamepad(dev_path):
            state.update(evtype, number, value)
    
    threads = []
    for i, dev in enumerate(devices):
        t = threading.Thread(target=reader_thread, args=(dev, i), daemon=True)
        t.start()
        threads.append(t)
    
    # Main loop: send state every ~20ms (50Hz)
    print("[+] Transmitindo dados... Pressione Ctrl+C para parar.")
    try:
        while True:
            time.sleep(0.02)  # 50 Hz
            with lock:
                for idx, state in states.items():
                    msg = state.to_json() + "\n"
                    try:
                        conn.sendall(msg.encode())
                    except:
                        print("[!] Conexao perdida.")
                        return
    except KeyboardInterrupt:
        print("\n[+] Encerrando.")
    finally:
        conn.close()
        server.close()

if __name__ == '__main__':
    main()
