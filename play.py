#!/usr/bin/env python3
import asyncio
import json
import pygame
import socket
import time
import websockets

# === CONFIG ===
COORD_WS = "ws://37.59.106.4:8765"   # 🔧 Replace with your coordinator address
MY_NAME = "controller_01"
PEER_NAME = "pi_01"

LOCAL_UDP_BIND = "0.0.0.0"
LOCAL_UDP_PORT = 50000

DEADZONE = 0.1
MAX_SPEED = 127
SEND_INTERVAL = 0.05  # 20Hz
PUNCH_PING = b"BUWIZZ_PUNCH"
PUNCH_INTERVAL = 0.12
PUNCH_DURATION = 5.0
PUNCH_RECEIVE_TIMEOUT = 2.0

# === FUNCTIONS ===

def axis_to_motor(value: float) -> int:
    if abs(value) < DEADZONE:
        return 0
    return int(-value * MAX_SPEED)

def tank_drive(left_axis, right_axis):
    left = axis_to_motor(left_axis)
    right = axis_to_motor(right_axis)
    return left, right

async def get_peer_udp_from_coordinator(ws_url: str, my_name: str, peer_name: str, ws_timeout=3.0):
    try:
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"type":"register", "name": my_name}))
            try:
                await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            await ws.send(json.dumps({"type":"request_peer", "name": my_name, "peer": peer_name}))
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=ws_timeout)
            except asyncio.TimeoutError:
                print("[COORD] No reply for peer request")
                return None
            data = json.loads(msg)
            if data.get("type") == "peer_info" and data.get("peer"):
                p = data["peer"].get("udp")
                if p and "ip" in p and "port" in p:
                    print(f"[COORD] peer UDP info: {p}")
                    return {"ip": p["ip"], "port": int(p["port"])}
            print("[COORD] Unexpected or missing UDP info:", data)
    except Exception as e:
        print("[COORD] Error contacting coordinator:", e)
    return None

async def punch_peer(local_port, peer_ip, peer_port):
    """Attempt to open NAT by sending punch packets."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LOCAL_UDP_BIND, local_port))
    sock.settimeout(0.5)
    local_endpoint = sock.getsockname()
    print(f"[PUNCH] Bound local UDP {local_endpoint}, punching {peer_ip}:{peer_port}")

    got_reply = None
    start = time.time()
    while time.time() - start < PUNCH_DURATION:
        try:
            sock.sendto(PUNCH_PING, (peer_ip, peer_port))
        except Exception as e:
            print("[PUNCH] send error:", e)
        try:
            data, addr = sock.recvfrom(1024)
            if data == PUNCH_PING:
                print(f"[PUNCH] Received punch response from {addr}")
                got_reply = addr
                break
        except socket.timeout:
            pass
        await asyncio.sleep(PUNCH_INTERVAL)

    if got_reply:
        print(f"[PUNCH] Hole punching succeeded with {got_reply}")
        return sock, got_reply
    else:
        print("[PUNCH] Punching failed or timed out.")
        sock.close()
        return None, None

async def controller_main():
    # === Setup controller ===
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        raise SystemExit("❌ No joystick detected! Connect an Xbox controller.")
    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"🎮 Using controller: {js.get_name()}")

    # === Hole punching phase ===
    peer = await get_peer_udp_from_coordinator(COORD_WS, MY_NAME, PEER_NAME)
    udp_sock = None
    remote = None

    if peer:
        udp_sock, remote = await punch_peer(LOCAL_UDP_PORT, peer["ip"], peer["port"])

    if not udp_sock:
        # fallback — direct UDP (LAN or forwarded)
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.bind((LOCAL_UDP_BIND, LOCAL_UDP_PORT))
        remote = (peer["ip"] if peer else "192.168.1.42", 9999)
        print(f"[FALLBACK] Using normal UDP to {remote}")

    # === Main control loop ===
    last_send = 0.0
    print(f"📡 Sending motor commands to {remote}")

    try:
        while True:
            pygame.event.pump()
            left_axis = js.get_axis(1)
            right_axis = js.get_axis(4)
            left, right = tank_drive(left_axis, right_axis)
            now = time.time()
            if now - last_send >= SEND_INTERVAL:
                msg = f"{left} {right}".encode()
                udp_sock.sendto(msg, remote)
                last_send = now
                print(f"➡️ L={left:4d} R={right:4d}", end="\r")
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n🛑 Exiting...")
    finally:
        udp_sock.close()
        pygame.quit()

if __name__ == "__main__":
    asyncio.run(controller_main())

