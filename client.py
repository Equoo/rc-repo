# client_script.py
import sys
import time
from hole import HolePunchClient

def on_message(peer_id, data):
    try:
        msg = data.decode('utf-8')
    except:
        msg = f"<binary:{len(data)} bytes>"
    print(f"\n[RECEIVED from {peer_id}] {msg}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python client_script.py <my_id>")
        sys.exit(1)

    my_id = sys.argv[1]
    coord_host = '37.59.106.4'  # Change if coordinator is remote

    client = HolePunchClient(coord_host, on_message=on_message)
    client.register(my_id)

    print(f"Registered as '{my_id}'. Commands:")
    print("  connect <peer>  → initiate hole punch")
    print("  send <peer> <msg> → send message")
    print("  quit → exit")

    while True:
        try:
            cmd = input("\n> ").strip()
            if not cmd:
                continue
            if cmd == "quit":
                break

            parts = cmd.split()
            if parts[0] == "connect" and len(parts) >= 2:
                peer = parts[1]
                try:
                    client.connect_to(peer)
                except Exception as e:
                    print(f"Connect failed: {e}")

            elif parts[0] == "send" and len(parts) >= 3:
                peer = parts[1]
                msg = " ".join(parts[2:])
                client.send_to_peer(peer, msg.encode('utf-8'))

            else:
                print("Invalid command")
        except KeyboardInterrupt:
            break
        except EOFError:
            break

    print("Shutting down...")


