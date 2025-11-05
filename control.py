import asyncio
from bleak import BleakClient, BleakScanner

BUWIZZ_SERVICE_UUID = "936E67B1-1999-B388-8144-FB74D1920550"
BUWIZZ_CHARACTERISTIC_UUID = "936E67B1-1999-B388-8144-FB74D1920551"

# helper: build BuWizz 0x30 "Set motor data" packet
def build_motor_command(m1, m2, m3=0, m4=0, m5=0, m6=0, brake=False):
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

async def main():
    print("🔍 Scanning for BuWizz 3.0 Pro...")
    devices = await BleakScanner.discover(timeout=5.0)

    device = next((d for d in devices if d.name and "BuWizz" in d.name), None)
    if not device:
        print("❌ No BuWizz found.")
        return

    print(f"✅ Found {device.name} at {device.address}")

    async with BleakClient(device.address) as client:
        print("🔗 Connected!")

        while True:
            try:
                left = int(input("Left motor (-127..127): "))
                right = int(input("Right motor (-127..127): "))

                # Assuming motor 1 = left, motor 2 = right
                packet = build_motor_command(left, right)
                await client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, packet, response=False)
                print(f"Sent 0x30 command: L={left}, R={right}")

            except KeyboardInterrupt:
                print("\n🛑 Stopping motors...")
                stop = build_motor_command(0, 0)
                await client.write_gatt_char(BUWIZZ_CHARACTERISTIC_UUID, stop, response=False)
                break

    print("🔌 Disconnected.")

if __name__ == "__main__":
    asyncio.run(main())

