#!/usr/bin/env python3
"""
Gamepad Client - runs on Windows
Receives gamepad state from Pi via TCP and feeds into ViGEmBus
REQUIRES: ViGEmBus driver installed + pip install vgamepad
"""
import socket
import json
import sys
import time

PI_IP = "192.168.15.84"
PORT = 9876

try:
    import vgamepad as vg
except ImportError:
    print("[!] Instale o vgamepad: pip install vgamepad")
    print("[!] E instale o ViGEmBus (setup na area de trabalho)")
    sys.exit(1)

class GamepadBridge:
    def __init__(self):
        # Create 4 virtual Xbox 360 controllers
        self.pads = [
            vg.VX360Gamepad(),
            vg.VX360Gamepad(),
            vg.VX360Gamepad(),
            vg.VX360Gamepad(),
        ]
        print(f"[+] {len(self.pads)} controles virtuais criados")
    
    def map_axis(self, value, axis_idx):
        """Map raw axis value to Xbox 360 axis."""
        # Linux axes are typically -32767 to 32767
        # Xbox 360 axes are -32768 to 32767
        return max(-32768, min(32767, value))
    
    def update(self, data):
        idx = data.get("id", 0)
        if idx >= len(self.pads):
            return
        
        pad = self.pads[idx]
        axes = data.get("axes", [])
        buttons = data.get("buttons", [])
        
        # Map axes (Linux js order: X, Y, Z, Rx, Ry, Rz, ...)
        # Xbox 360: LeftX, LeftY, RightX, RightY
        if len(axes) > 0: pad.left_joystick_float(
            axes[0] / 32767.0 if len(axes) > 0 else 0,
            axes[1] / -32767.0 if len(axes) > 1 else 0  # Y is inverted
        )
        if len(axes) > 3: pad.right_joystick_float(
            axes[2] / 32767.0 if len(axes) > 2 else 0,
            axes[3] / -32767.0 if len(axes) > 3 else 0
        )
        
        # Triggers (typically axes 4=L2, 5=R2)
        if len(axes) > 4: pad.left_trigger_float((axes[4] + 32767) / 65534.0)
        if len(axes) > 5: pad.right_trigger_float((axes[5] + 32767) / 65534.0)
        
        # Map buttons (Linux js order: A, B, X, Y, LB, RB, Select, Start, ...)
        btn_map = {
            0: vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            1: vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            2: vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            3: vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            4: vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
            5: vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
            6: vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
            7: vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
            8: vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
            9: vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
            10: vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
        }
        
        for btn_idx, pressed in enumerate(buttons):
            if btn_idx in btn_map and pressed:
                pad.press_button(button=btn_map[btn_idx])
            elif btn_idx in btn_map:
                pad.release_button(button=btn_map[btn_idx])
        
        # D-pad
        dpad_state = 0
        # Hat0X (axis 6) and Hat0Y (axis 7) or buttons 11-14 for d-pad
        if len(axes) > 7:
            hat_x = axes[6] if abs(axes[6]) > 16000 else 0
            hat_y = axes[7] if abs(axes[7]) > 16000 else 0
            if hat_y < 0: dpad_state |= vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP
            if hat_y > 0: dpad_state |= vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN
            if hat_x < 0: dpad_state |= vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT
            if hat_x > 0: dpad_state |= vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT
        
        pad.update()

def main():
    print("=== Gamepad Client (Windows) ===")
    print(f"[+] Conectando ao Pi {PI_IP}:{PORT}...")
    
    bridge = GamepadBridge()
    
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        try:
            sock.connect((PI_IP, PORT))
        except:
            print(f"[!] Pi offline. Retentando em 5s...")
            time.sleep(5)
            continue
        
        print("[+] Conectado! Transmitindo...")
        
        buffer = ""
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                buffer += data.decode()
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    try:
                        state = json.loads(line.strip())
                        bridge.update(state)
                    except json.JSONDecodeError:
                        pass
        except:
            print("[!] Conexao perdida. Reconectando...")
            sock.close()
            time.sleep(2)

if __name__ == '__main__':
    main()
