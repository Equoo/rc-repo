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

