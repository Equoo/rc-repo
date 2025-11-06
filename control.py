#!/usr/bin/env python3
"""
buwizz_punch_bridge.py

Pi-side bridge that:
 - registers with a coordinator WebSocket server
 - attempts UDP hole punching to a remote peer
 - listens for motor commands (either from punched peer or local UDP)
 - forwards motor commands to BuWizz over BLE

Usage:
  - Edit COORD_WS, MY_NAME and PEER_NAME to match your coordinator and peer.
  - Run on the Raspberry Pi that has BLE and BuWizz nearby.

Coordinator protocol expected (simple):
 - WS messages JSON:
   {"type":"register","name":"pi_01"}
   {"type":"request_peer","name":"pi_01","peer":"controller_01"}
   Server replies with {"type":"peer_info","peer":{"name":"controller_01","udp":{"ip":"x.x.x.x","port":12345}}}
   Optionally server accepts {"type":"exchange", "name":"pi_01", "peer":"controller_01"} to trigger an exchange.

Notes:
 - If hole punching fails, script will keep listening on UDP_PORT for local packets.
 - Control packets are expected as "left right" (two ints).
"""

import asyncio
import json
import socket
import time
from typing import Optional, Tuple

import websockets
from bleak import BleakClient, BleakScanner

# ---------------- CONFIG ----------------
COORD_WS = "ws://46.231.218.157:8765"   # change to your coordinator websocket URL
MY_NAME = "pi_01"                    # unique name for this Pi (must match controller's expectation)
PEER_NAME = "controller_01"          # remote controller name
LOCAL_UDP_BIND = "0.0.0.0"
UDP_PORT = 9999                      # local UDP port to bind (same as before)
LOCAL_UDP_PORT = UDP_PORT            # convenience alias

BUWIZZ_SERVICE_UUID = "936E67B1-1999-B388-8144-FB74D1920550"
BUWIZZ_CHARACTERISTIC_UUID = "50052901-74fb-4481-88b3-9919b1676e93"

PUNCH_PING = b"BUWIZZ_PUNCH"         # small payload used for punching
PUNCH_INTERVAL = 0.12                # seconds between punch packets
PUNCH_DURATION = 5.0                 # how long to aggressively punch
PUNCH_RECEIVE_TIMEOUT = 2.0          # how long to wait for an incoming during punching
# ----------------------------------------

# helper: build BuWizz 0x30 "Set motor data" packet
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

class IncomingUDPProtocol(asyncio.DatagramProtocol):
    """Receives UDP datagrams and forwards parsed commands to an asyncio.Queue."""
    def __init__(self, queue: asyncio.Queue, allowed_remote: Optional[Tuple[str,int]] = None):
        self.queue = queue
        self.allowed_remote = allowed_remote  # if set, only accept from this endpoint
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        sockname = transport.get_extra_info("sockname")
        print(f"[UDP] Bound to {sockname}")

    def datagram_received(self, data: bytes, addr):
        # debug print incoming
        # print(f"[UDP recv] from {addr}: {data!r}")
        # if allowed_remote set, filter out other senders
        if self.allowed_remote is not None and addr != self.allowed_remote:
            # ignore
            # print(f"[UDP] ignoring packet from {addr}, allowed {self.allowed_remote}")
            return

        text = None
        try:
            text = data.decode().strip()
        except UnicodeDecodeError:
            # ignore non-text packets, except we might use them for punch detection
            pass

        # If packet equals punch ping, notify queue (used for punching detection)
        if data == PUNCH_PING:
            # indicate "punch ping received" with special tuple
            self.queue.put_nowait(("__PUNCH__", addr, data))
            return

        if text:
            parts = text.split()
            if len(parts) >= 2:
                try:
                    left = int(parts[0])
                    right = int(parts[1])
                    self.queue.put_nowait(("CMD", addr, (left, right)))
                except ValueError:
                    print(f"[UDP] Invalid integers from {addr}: {text}")
            else:
                print(f"[UDP] Bad packet format from {addr}: {text}")

    def set_allowed(self, endpoint: Optional[Tuple[str,int]]):
        self.allowed_remote = endpoint

async def get_peer_udp_from_coordinator(ws_url: str, my_name: str, peer_name: str, ws_timeout=3.0):
    """
    Connect to coordinator and ask for peer info. Returns {'ip':..., 'port':...} or None.
    """
    try:
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"type":"register", "name": my_name}))
            # consume register response (if any)
            try:
                reg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                # print("Coord reg response:", reg)
            except asyncio.TimeoutError:
                pass

            # ask for peer info
            await ws.send(json.dumps({"type":"request_peer", "name": my_name, "peer": peer_name}))
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=ws_timeout)
            except asyncio.TimeoutError:
                print("[COORD] No reply for peer request")
                return None

            try:
                data = json.loads(msg)
            except Exception:
                print("[COORD] invalid JSON reply")
                return None

            if data.get("type") == "peer_info" and data.get("peer"):
                p = data["peer"].get("udp")
                if p and "ip" in p and "port" in p:
                    print(f"[COORD] peer UDP info: {p}")
                    return {"ip": p["ip"], "port": int(p["port"])}
                else:
                    print("[COORD] peer has no udp info yet")
                    # send exchange request to attempt push
                    await ws.send(json.dumps({"type":"exchange", "name": my_name, "peer": peer_name}))
                    # wait briefly for push
                    try:
                        push = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        pushdata = json.loads(push)
                        if pushdata.get("type") == "peer_info":
                            p2 = pushdata["peer"].get("udp")
                            if p2 and "ip" in p2 and "port" in p2:
                                return {"ip": p2["ip"], "port": int(p2["port"])}
                    except asyncio.TimeoutError:
                        pass
            else:
                print("[COORD] unexpected response:", data)
    except Exception as e:
        print("[COORD] error contacting coordinator:", e)
    return None

async def punch_and_listen(local_port: int, remote_ip: str, remote_port: int, incoming_queue: asyncio.Queue):
    """
    Attempt punching to remote_ip:remote_port. Bind local UDP and send repeated PINGs.
    Return the remote endpoint that sent back any packet, or None on failure.
    While punching, any incoming CMDs will be queued into incoming_queue as ("CMD", addr, (left,right)).
    """
    loop = asyncio.get_running_loop()
    transport = None
    protocol = None
    local_endpoint = None
    try:
        # bind UDP socket (protocol will put packets into incoming_queue)
        protocol = IncomingUDPProtocol(incoming_queue, allowed_remote=None)
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol, local_addr=(LOCAL_UDP_BIND, local_port)
        )
        sock = transport.get_extra_info("socket")
        local_endpoint = transport.get_extra_info("sockname")
        print(f"[PUNCH] Local UDP bound {local_endpoint}, punching {remote_ip}:{remote_port}")

        # send punches for PUNCH_DURATION while checking incoming_queue for punch responses
        end = time.time() + PUNCH_DURATION
        got_remote = None

        while time.time() < end:
            # send a burst of pings
            try:
                transport.sendto(PUNCH_PING, (remote_ip, remote_port))
            except Exception as e:
                print("[PUNCH] send error:", e)
            # check if we received anything from remote (including PING echo)
            try:
                item = incoming_queue.get_nowait()
                if item and item[0] == "__PUNCH__":
                    _, addr, _ = item
                    print(f"[PUNCH] Received punch from {addr}")
                    got_remote = addr
                    break
                elif item and item[0] == "CMD":
                    # If a CMD arrives during punching, treat that sender as remote
                    _, addr, (l, r) = item
                    print(f"[PUNCH] Received CMD during punch from {addr} -> {l} {r}")
                    got_remote = addr
                    # put cmd back into queue for normal processing
                    await incoming_queue.put(("CMD", addr, (l, r)))
                    break
            except asyncio.QueueEmpty:
                pass

            await asyncio.sleep(PUNCH_INTERVAL)

        # one last wait for RECEIVE_TIMEOUT seconds for a response if we didn't get earlier
        if got_remote is None:
            try:
                item = await asyncio.wait_for(incoming_queue.get(), timeout=PUNCH_RECEIVE_TIMEOUT)
                if item and item[0] in ("__PUNCH__", "CMD"):
                    _, addr, _ = item
                    got_remote = addr
            except asyncio.TimeoutError:
                pass

        if got_remote:
            # lock protocol to this remote only
            protocol.set_allowed(got_remote)
            print(f"[PUNCH] Established direct UDP with {got_remote}")
            return got_remote
        else:
            print("[PUNCH] Punching timed out / failed")
            # leave socket open in case we want to accept local connections
            # return None to indicate failure
            return None

    finally:
        # If we return a remote, leave the transport open and protocol active for the rest of runtime.
        # The caller will keep using the existing transport/protocol through incoming_queue behavior.
        pass

async def buwizz_ble_task(command_queue: asyncio.Queue):
    """
    Connect to BuWizz via BLE and forward motor commands pulled from command_queue.
    command_queue receives ("CMD", addr, (left,right)).
    """
    print("🔍 Scanning for BuWizz 3.0 Pro...")
    devices = await BleakScanner.discover(timeout=5.0)
    device = next((d for d in devices if d.name and "BuWizz" in d.name), None)
    if not device:
        print("❌ No BuWizz found.")
        return

    print(f"✅ Found {device.name} at {device.address}")

    try:
        async with BleakClient(device.address) as client:
            print("🔗 Connected to BuWizz!")
            while True:
                try:
                    item = await command_queue.get()
                except asyncio.CancelledError:
                    break

                if not item:
                    continue
                if item[0] != "CMD":
                    # ignore others
                    continue
                _, addr, (left, right) = item
                # here we assume left->m5 and right->m6 as in your build function
                packet = build_motor_command(left, right)
                try:
                    await client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, packet, response=False)
                    print(f"➡️ Sent motors to BuWizz from {addr}: L={left}, R={right}")
                except Exception as e:
                    print("[BLE] write error:", e)
                    # if BLE fails, break and let outer logic handle it
                    break

            # on exit, stop motors
            stop = build_motor_command(0, 0)
            try:
                await client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, stop, response=False)
            except Exception:
                pass
            print("🛑 Motors stopped, BLE disconnected.")
    except Exception as e:
        print("[BLE] BLE connection error:", e)

async def main():
    incoming_queue = asyncio.Queue()   # filled by UDP protocol (both punch and normal UDP)
    command_queue = asyncio.Queue()    # commands for BLE task (pulled from incoming_queue)

    # start BLE task (it will wait for commands)
    ble_task = asyncio.create_task(buwizz_ble_task(command_queue))

    # 1) attempt to get peer udp from coordinator
    peer = await get_peer_udp_from_coordinator(COORD_WS, MY_NAME, PEER_NAME)
    punched_remote = None

    if peer:
        # 2) attempt punching and listening; if successful, protocol will filter to that remote only
        punched_remote = await punch_and_listen(LOCAL_UDP_PORT, peer["ip"], peer["port"], incoming_queue)

    if not punched_remote:
        # 3) either punching failed OR no peer info available -> bind a normal UDP listener for local / any remote
        print("[MAIN] Falling back to generic UDP listener (accepting any sender).")
        # create UDP endpoint (IncomingUDPProtocol) bound to LOCAL_UDP_PORT and put it into incoming_queue
        loop = asyncio.get_running_loop()
        protocol = IncomingUDPProtocol(incoming_queue, allowed_remote=None)
        transport, _ = await loop.create_datagram_endpoint(lambda: protocol, local_addr=(LOCAL_UDP_BIND, LOCAL_UDP_PORT))
        print(f"[MAIN] UDP listener running on {(LOCAL_UDP_BIND, LOCAL_UDP_PORT)} (accepting any sender)")

    # forward CMD items from incoming_queue to command_queue for BLE handling
    async def forwarder():
        while True:
            try:
                item = await incoming_queue.get()
            except asyncio.CancelledError:
                break
            # Only forward actual CMD items to BLE; ignore punch pings
            if item and item[0] == "CMD":
                await command_queue.put(item)

    forwarder_task = asyncio.create_task(forwarder())

    try:
        # keep running until interrupted
        print("[MAIN] Bridge running. Press Ctrl+C to stop.")
        await asyncio.Future()
    except KeyboardInterrupt:
        print("\n[MAIN] Shutdown requested")
    finally:
        forwarder_task.cancel()
        ble_task.cancel()
        await asyncio.gather(forwarder_task, ble_task, return_exceptions=True)
        print("[MAIN] Exiting.")

if __name__ == "__main__":
    asyncio.run(main())

