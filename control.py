import asyncio
from bleak import BleakClient, BleakScanner

BUWIZZ_SERVICE_UUID = "936E67B1-1999-B388-8144-FB74D1920550"
BUWIZZ_CHARACTERISTIC_UUID = "936E67B2-1999-B388-8144-FB74D1920550"

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
        0x0A,  # Command: set motor power
        encode(port_a),  # A
        encode(port_b),  # B
        0x80,            # C neutral
        0x80             # D neutral
    ])
    return packet


async def main():
    print("Scanning for BuWizz 3.0 Pro...")
    device = None
    devices = await BleakScanner.discover()
    for d in devices:
        if "BuWizz" in d.name:
            device = d
            break

    if not device:
        print("❌ BuWizz not found. Make sure it's powered on and nearby.")
        return

    print(f"✅ Found {device.name} at {device.address}")

    async with BleakClient(device.address) as client:
        print("🔗 Connected!")

        # Example RC control loop
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
