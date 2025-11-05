import asyncio
from bleak import BleakClient, BleakScanner

BUWIZZ_SERVICE_UUID = "936E67B1-1999-B388-8144-FB74D1920550"
BUWIZZ_CHARACTERISTIC_UUID = "50052901-74fb-4481-88b3-9919b1676e93"

# Helper: build motor command packet (see BuWizz API 3.6)
def build_motor_command(port_a, port_b):
    # Each motor command: [port_id, power, time?] (per API)
    # Power range: -100 to 100, mapped to 0–255 bytes
    def clamp(val): return max(-100, min(100, val))
    def encode(val): return int((clamp(val) + 100) * 255 / 200)

    # Example: control two ports (A,B) out of 4 (A,B,C,D)
    # Command format for "set all ports" (0x0A)
    # 0x0A <A power> <B power> <C power> <D power>
    packet = bytearray([
        0x0B,  # Command: set motor power
        encode(port_a),  # A
        encode(port_b),  # B
        0x80,            # C neutral
        0x80             # D neutral
    ])
    return packet



async def main():
    print("🔍 Scanning for BuWizz 3.0 Pro (5 seconds)...")
    devices = await BleakScanner.discover(timeout=5.0)

    if not devices:
        print("❌ No BLE devices found at all. Make sure Bluetooth is on and BuWizz is powered.")
        return

    device = None
    for d in devices:
        name = d.name or "<unknown>"
        print(f"Found device: {name} [{d.address}]")
        if name and "BuWizz" in name:
            device = d
            break

    if not device:
        print("❌ Could not find any device with 'BuWizz' in its name.")
        print("💡 Tip: run `bluetoothctl scan on` and check how your BuWizz appears.")
        return

    print(f"✅ Found {device.name} at {device.address}")

    async with BleakClient(device.address) as client:
        print("🔗 Connected!")

        while True:
            try:
                left = int(input("Left motor power (-100..100): "))
                right = int(input("Right motor power (-100..100): "))

                packet = build_motor_command(left, right)
                await client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, packet)
                print(f"Sent -> L:{left} R:{right}")

            except KeyboardInterrupt:
                print("\n🛑 Stopping motors...")
                stop = build_motor_command(0, 0)
                await client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, stop)
                break

    print("🔌 Disconnected.")


if __name__ == "__main__":
    asyncio.run(main())
