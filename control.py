import asyncio
from bleak import BleakClient, BleakScanner

BUWIZZ_SERVICE_UUID = "936E67B1-1999-B388-8144-FB74D1920550"
BUWIZZ_CHARACTERISTIC_UUID = "50052901-74fb-4481-88b3-9919b1676e93"

UDP_IP = "0.0.0.0"
UDP_PORT = 9999

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
        0x3F if brake else 0x00,  # bits 5-0 = 1 for brake
        0x00                      # LUT flags
    ])
    return packet

async def udp_listener(queue: asyncio.Queue):
    """Listen for UDP packets with motor values."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: UDPProtocol(queue),
        local_addr=(UDP_IP, UDP_PORT)
    )
    print(f"📡 UDP server listening on {UDP_IP}:{UDP_PORT}")
    try:
        await asyncio.Future()  # run forever
    finally:
        transport.close()

class UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    def datagram_received(self, data, addr):
        msg = data.decode().strip()
        parts = msg.split()
        if len(parts) >= 2:
            try:
                left = int(parts[0])
                right = int(parts[1])
                self.queue.put_nowait((left, right))
            except ValueError:
                print(f"⚠️ Invalid data from {addr}: {msg}")
        else:
            print(f"⚠️ Bad packet from {addr}: {msg}")

async def buwizz_task(queue: asyncio.Queue):
    """Connect to BuWizz and apply motor commands received via UDP."""
    print("🔍 Scanning for BuWizz 3.0 Pro...")
    devices = await BleakScanner.discover(timeout=5.0)
    device = next((d for d in devices if d.name and "BuWizz" in d.name), None)
    if not device:
        print("❌ No BuWizz found.")
        return

    print(f"✅ Found {device.name} at {device.address}")

    async with BleakClient(device.address) as client:
        print("🔗 Connected to BuWizz!")

        current = (0, 0)
        while True:
            try:
                left, right = await queue.get()
                current = (left, right)
                packet = build_motor_command(left, right)
                await client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, packet, response=False)
                print(f"➡️ Sent motors: L={left}, R={right}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ BLE error: {e}")
                break

        # stop on exit
        stop = build_motor_command(0, 0)
        await client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, stop, response=False)
        print("🛑 Motors stopped, disconnected.")

async def main():
    queue = asyncio.Queue()
    listener = asyncio.create_task(udp_listener(queue))
    controller = asyncio.create_task(buwizz_task(queue))

    try:
        await asyncio.gather(listener, controller)
    except KeyboardInterrupt:
        print("\n🧹 Shutting down...")
        controller.cancel()
        listener.cancel()
        await asyncio.gather(controller, listener, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())

