#!/usr/bin/env python3
import asyncio
import pygame
import time
from hole import HolePunchClient

# === CONFIG ===
COORD_HOST = "37.59.106.4"      # Coordinator IP
MY_NAME = "controller_01"
PEER_NAME = "pi_01"
LOCAL_UDP_PORT = 50000
DEADZONE = 0.1
MAX_SPEED = 40
SEND_INTERVAL = 0.05  # 20Hz

def axis_to_motor(value: float) -> int:
    if abs(value) < DEADZONE:
        return 0
    return int(-value * MAX_SPEED)

def tank_drive(left_axis, right_axis):
    left = axis_to_motor(left_axis)
    right = axis_to_motor(right_axis)
    return left, right

# === Global client ===
client: HolePunchClient = None
remote_endpoint = None

def on_peer_message(src: str, data: bytes):
    """Optional: receive commands back from Pi (e.g. sensor data)"""
    try:
        print(f"\n[FROM {src}] {data.decode('utf-8')}")
    except:
        print(f"\n[FROM {src}] <binary {len(data)} bytes>")

async def setup_p2p():
    global client, remote_endpoint

    print(f"[P2P] Registering as '{MY_NAME}'...")
    client = HolePunchClient(
        coord_host=COORD_HOST,
        on_message=on_peer_message
    )
    client.register(MY_NAME)

    print(f"[P2P] Requesting peer '{PEER_NAME}'...")
    try:
        remote_endpoint = client.connect_to(PEER_NAME)
        print(f"[P2P] Direct UDP endpoint: {remote_endpoint}")
    except Exception as e:
        print(f"[P2P] Direct connect failed: {e}. Will use TCP relay fallback.")

    # Wait a moment for hole punching
    await asyncio.sleep(2.0)

async def controller_loop():
    global remote_endpoint

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        raise SystemExit("No joystick detected!")

    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"Using controller: {js.get_name()}")

    last_send = 0.0
    print("Control loop started. Use left/right sticks.")

    try:
        while True:
            pygame.event.pump()
            left_axis = js.get_axis(1)   # Left stick Y
            right_axis = js.get_axis(4)  # Right stick Y
            left, right = tank_drive(left_axis, right_axis)

            now = time.time()
            if now - last_send >= SEND_INTERVAL:
                msg = f"{left} {right}".encode()
                client.send_to_peer(PEER_NAME, msg)
                last_send = now
                print(f"L={left:4d} R={right:4d}", end="\r")

            await asyncio.sleep(0.01)
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        pygame.quit()

async def main():
    await setup_p2p()
    await controller_loop()

if __name__ == "__main__":
    asyncio.run(main())
