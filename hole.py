# holepunch_lib.py
import socket
import threading
import time
import select
from typing import Optional, Callable, Dict, Tuple

class HolePunchClient:
    def __init__(
        self,
        coord_host: str,
        coord_tcp_port: int = 9999,
        coord_udp_port: int = 9998,
        on_message: Optional[Callable[[str, bytes], None]] = None
    ):
        self.coord_host = coord_host
        self.coord_tcp_port = coord_tcp_port
        self.coord_udp_port = coord_udp_port
        self.on_message = on_message

        self.tcp_conn: Optional[socket.socket] = None
        self.udp_sock: Optional[socket.socket] = None
        self.my_id: Optional[str] = None

        # Thread-safe structures
        self.peer_endpoints: Dict[str, Tuple[str, int]] = {}
        self.relay_peers: set = set()
        self.last_udp_rx: Dict[str, float] = {}  # peer_id → last recv time
        self.last_udp_tx: Dict[str, float] = {}  # peer_id → last send time

        self.lock = threading.RLock()  # Reentrant lock for complex ops
        self.running = threading.Event()

    # ================================================================
    # Public API
    # ================================================================

    def create_udp_socket(self, local_port: int = 0) -> int:
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.bind(('0.0.0.0', local_port))
        self.udp_sock.setblocking(False)
        return self.udp_sock.getsockname()[1]

    def register(self, my_id: str) -> None:
        if not self.udp_sock:
            self.create_udp_socket()

        # --- Create non-blocking TCP socket ---
        self.tcp_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_conn.setblocking(False)

        # --- Non-blocking connect with proper error handling ---
        try:
            self.tcp_conn.connect((self.coord_host, self.coord_tcp_port))
        except BlockingIOError:
            pass  # Expected on non-blocking socket
        except OSError as e:
            raise ConnectionError(f"Failed to initiate connect: {e}")
    
        # Wait until socket is writable (connect completed)
        print(f"[TCP] Connecting to coordinator {self.coord_host}:{self.coord_tcp_port}...")
        writable = False
        for _ in range(50):  # ~5 sec timeout
            r, w, x = select.select([], [self.tcp_conn], [self.tcp_conn], 0.1)
            if x:
                raise ConnectionError("Connect failed (exception in socket)")
            if w:
                writable = True
                break
        if not writable:
            raise TimeoutError("Connection to coordinator timed out")

        # Check for connection error (getsockopt)
        err = self.tcp_conn.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if err != 0:
            raise ConnectionError(f"Connect failed: {socket.error(err)}")

        print("[TCP] Connected to coordinator")

        # --- Register ---
        self._send_tcp(f"REGISTER {my_id}")
        resp = self._recv_tcp_line_blocking(timeout=5.0)
        if not resp or not resp.startswith("OK"):
            raise ConnectionError(f"Registration failed: {resp}")

        # Register public UDP endpoint
        self.udp_sock.sendto(f"ID: {my_id}".encode('utf-8'), (self.coord_host, self.coord_udp_port))

        self.my_id = my_id
        self.running.set()

        # Start background threads
        threading.Thread(target=self._tcp_handler, daemon=True).start()
        threading.Thread(target=self._udp_receiver, daemon=True).start()
        threading.Thread(target=self._fallback_detector, daemon=True).start()
    def connect_to(self, peer_id: str) -> Tuple[str, int]:
        self._send_tcp(f"CONNECT {peer_id}")

        for _ in range(30):
            with self.lock:
                if peer_id in self.peer_endpoints:
                    endpoint = self.peer_endpoints[peer_id]
                    self.punch_hole(peer_id)
                    return endpoint
            time.sleep(0.5)
        raise TimeoutError(f"Peer {peer_id} not found")

    def punch_hole(self, peer_id: str) -> None:
        endpoint = self.get_peer_endpoint(peer_id)
        if not endpoint:
            return
        for _ in range(8):
            try:
                self.udp_sock.sendto(b"HOLE_PUNCH", endpoint)
            except:
                break
            time.sleep(0.12)

    def get_peer_endpoint(self, peer_id: str) -> Optional[Tuple[str, int]]:
        with self.lock:
            return self.peer_endpoints.get(peer_id)

    def send_to_peer(self, peer_id: str, data: bytes) -> None:
        """Send via UDP if possible, else TCP relay."""
        endpoint = self.get_peer_endpoint(peer_id)
        is_relay = False

        with self.lock:
            if peer_id in self.relay_peers:
                is_relay = True
            else:
                self.last_udp_tx[peer_id] = time.time()

        if endpoint and not is_relay:
            try:
                self.udp_sock.sendto(data, endpoint)
                return
            except Exception as e:
                print(f"[UDP SEND FAIL → {peer_id}] {e}")
                # Fall through to relay

        # === TCP Relay Fallback ===
        try:
            payload = data.decode('utf-8', errors='replace')
            self._send_tcp(f"RELAY {peer_id} {payload}")
        except Exception as e:
            print(f"[RELAY SEND FAIL → {peer_id}] {e}")

    # ================================================================
    # Internal: Safe TCP I/O (no lock during I/O)
    # ================================================================

    def _send_tcp(self, msg: str) -> None:
        if not self.tcp_conn:
            return
        try:
            self.tcp_conn.send((msg + "\n").encode('utf-8'))
        except:
            pass  # Will be cleaned up

    def _recv_tcp_line_blocking(self, timeout: float = 3.0) -> Optional[str]:
        """Blocking recv with timeout — safe, no lock."""
        if not self.tcp_conn:
            return None
        self.tcp_conn.settimeout(timeout)
        try:
            data = self.tcp_conn.recv(1024)
            if not data:
                return None
            return data.decode('utf-8').split('\n', 1)[0].strip()
        except socket.timeout:
            return None
        except:
            return None

    def _connect_nonblocking(self, timeout: float = 5.0) -> None:
        self.tcp_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_conn.setblocking(False)
        try:
            self.tcp_conn.connect((self.coord_host, self.coord_tcp_port))
        except BlockingIOError:
            pass
        except Exception as e:
            raise ConnectionError(f"Connect init failed: {e}")

        end_time = time.time() + timeout
        while time.time() < end_time:
            r, w, x = select.select([], [self.tcp_conn], [self.tcp_conn], 0.1)
            if x:
                raise ConnectionError("Socket error during connect")
            if w:
                err = self.tcp_conn.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err == 0:
                    return
                raise ConnectionError(f"Connect failed: {socket.error(err)}")
        raise TimeoutError("Coordinator connection timeout")

    # ================================================================
    # Background Threads
    # ================================================================

    def _tcp_handler(self):
        """Handle incoming coordinator messages."""
        buffer = ""
        while self.running.is_set():
            try:
                r, _, _ = select.select([self.tcp_conn], [], [], 0.1)
                if not r:
                    continue
                data = self.tcp_conn.recv(4096)
                if not data:
                    break
                buffer += data.decode('utf-8', errors='ignore')
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line:
                        self._handle_coord_message(line)
            except:
                continue
        self._cleanup()

    def _handle_coord_message(self, msg: str):
        parts = msg.split()
        if len(parts) < 1:
            return

        cmd = parts[0]

        if cmd == "PEER" and len(parts) >= 4:
            p_id, ip, port_str = parts[1], parts[2], parts[3]
            try:
                port = int(port_str)
                with self.lock:
                    self.peer_endpoints[p_id] = (ip, port)
                print(f"[Coord] Peer {p_id} @ {ip}:{port}")
            except:
                pass

        elif cmd == "RELAY" and len(parts) >= 3:
            src_id = parts[1]
            payload = " ".join(parts[2:])
            data = payload.encode('utf-8')

            # Update last RX time
            with self.lock:
                self.last_udp_rx[src_id] = time.time()

            # **DO NOT HOLD LOCK** while calling user callback
            if self.on_message:
                try:
                    self.on_message(src_id, data)
                except Exception as e:
                    print(f"[CALLBACK ERROR] {e}")

        elif cmd == "FALLBACK" and len(parts) >= 2:
            peer_id = parts[1]
            with self.lock:
                self.relay_peers.add(peer_id)
            print(f"[FALLBACK] Using TCP relay with {peer_id}")

    def _udp_receiver(self):
        """Receive direct UDP packets."""
        while self.running.is_set():
            try:
                r, _, _ = select.select([self.udp_sock], [], [], 0.1)
                if not r:
                    continue
                data, addr = self.udp_sock.recvfrom(4096)
                if data == b"HOLE_PUNCH":
                    continue

                # Find peer by address
                peer_id = None
                with self.lock:
                    for pid, ep in self.peer_endpoints.items():
                        if ep == addr:
                            peer_id = pid
                            self.last_udp_rx[pid] = time.time()
                            break

                if peer_id and self.on_message:
                    try:
                        self.on_message(peer_id, data)
                    except Exception as e:
                        print(f"[UDP CALLBACK ERROR] {e}")
            except:
                continue

    def _fallback_detector(self):
        """Detect UDP silence → trigger relay."""
        while self.running.is_set():
            time.sleep(5)

            now = time.time()
            peers_to_check = []

            with self.lock:
                for peer_id in self.peer_endpoints:
                    if peer_id in self.relay_peers:
                        continue
                    last_tx = self.last_udp_tx.get(peer_id, 0)
                    last_rx = self.last_udp_rx.get(peer_id, 0)
                    if last_tx > last_rx + 3 and now - last_tx > 10:
                        peers_to_check.append(peer_id)

            for peer_id in peers_to_check:
                self._request_fallback(peer_id)

    def _request_fallback(self, peer_id: str):
        with self.lock:
            if peer_id in self.relay_peers:
                return
            self.relay_peers.add(peer_id)
        self._send_tcp(f"FALLBACK {peer_id}")
        print(f"[FALLBACK] Requested relay with {peer_id}")

    def _cleanup(self):
        self.running.clear()
        if self.udp_sock:
            try:
                self.udp_sock.close()
            except:
                pass
        if self.tcp_conn:
            try:
                self.tcp_conn.close()
            except:
                pass
