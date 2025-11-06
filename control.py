#!/usr/bin/env python3
"""
buwizz_punch_bridge.py
Pi-side bridge using holepunch_lib:
 - Registers with TCP coordinator
 - Receives motor commands via P2P (UDP or TCP relay)
 - Forwards to BuWizz via BLE
"""

import asyncio
import time
from typing import Tuple
from bleak import BleakClient, BleakScanner
from hole import HolePunchClient

# ---------------- CONFIG ----------------
COORD_HOST = "37.59.106.4"           # Coordinator IP
MY_NAME = "pi_01"
PEER_NAME = "controller_01"
LOCAL_UDP_PORT = 9999
BUWIZZ_SERVICE_UUID = "936E67B1-1999-B388-8144-FB74D1920550"
BUWIZZ_CHARACTERISTIC_UUID = "50052901-74fb-4481-88b3-9919b1676e93"

# ----------------------------------------
def build_motor_command(m5, m6, m3=0, m4=0, m1=0, m2=0, brake=False):
    def clamp(v): return max(-127, min(127, v))
    packet = bytearray([
        0x30,
        clamp(m1) & 0xFF,
        clamp(m2) & 0xFF,
        clamp(m3) & 0xFF,
        clamp(m4) & 0xFF,
        clamp(m5) & 0xFF,
        clamp(m6) & 0xFF,
        0x3F if brake else 0x00,
        0x00
    ])
    return packet

# Global client
client: HolePunchClient = None
command_queue = asyncio.Queue()

async def buwizz_ble_task():
    print("Scanning for BuWizz 3.0 Pro...")
    devices = await BleakScanner.discover(timeout=5.0)
    device = next((d for d in devices if d.name and "BuWizz" in d.name), None)
    if not device:
        print("No BuWizz found.")
        return

    print(f"Found {device.name} at {device.address}")
    try:
        async with BleakClient(device.address) as ble_client:
            print("Connected to BuWizz!")
            while True:
                try:
                    src, data = await command_queue.get()
                except asyncio.CancelledError:
                    break

                try:
                    text = data.decode('utf-8').strip()
                    parts = text.split()
                    if len(parts) >= 2:
                        left = int(parts[0])
                        right = int(parts[1])
                        packet = build_motor_command(left, right)
                        await ble_client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, packet, response=False)
                        print(f"Motors → L={left:4d} R={right:4d} from {src}")
                    else:
                        print(f"Invalid command: {text}")
                except Exception as e:
                    print(f"[BLE] Error: {e}")
                    break

            # Stop motors on exit
            stop = build_motor_command(0, 0)
            try:
                await ble_client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, stop, response=False)
            except:
                pass
            print("Motors stopped, BLE disconnected.")
    except Exception as e:
        print(f"[BLE] Connection error: {e}")

def on_peer_message(src: str, data: bytes):
    """Callback: forward any message from controller to BLE task."""
    if src == PEER_NAME:
        asyncio.create_task(command_queue.put((src, data)))

async def setup_p2p():
    global client
    print(f"[P2P] Registering as '{MY_NAME}'...")
    client = HolePunchClient(
        coord_host=COORD_HOST,
        on_message=on_peer_message
    )
    client.register(MY_NAME)

    print(f"[P2P] Connecting to peer '{PEER_NAME}'...")
    try:
        endpoint = client.connect_to(PEER_NAME)
        print(f"[P2P] Direct UDP: {endpoint}")
    except Exception as e:
        print(f"[P2P] Direct failed: {e} → using TCP relay fallback")

    # Give hole punching time
    await asyncio.sleep(2.0)

async def main():
    ble_task = asyncio.create_task(buwizz_ble_task())
    await setup_p2p()

    print("[MAIN] Bridge running. Waiting for motor commands...")
    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        print("\n[MAIN] Shutting down...")
    finally:
        ble_task.cancel()
        await asyncio.gather(ble_task, return_exceptions=True)
        if client:
            client._cleanup()
        print("[MAIN] Exited.")

if __name__ == "__main__":
    asyncio.run(main())
