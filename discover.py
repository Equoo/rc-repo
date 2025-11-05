# discover_buwizz.py
import asyncio
from bleak import BleakClient

address = "C4:50:A6:81:CC:CA"  # your BuWizz MAC

async def main():
    async with BleakClient(address) as client:
        print("Connected to BuWizz!")
        print("\n=== Services and Characteristics ===")
        for service in client.services:
            print(f"\nService: {service.uuid}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"  Characteristic: {char.uuid}  [{props}]")

asyncio.run(main())
