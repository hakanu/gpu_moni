"""
Network & Tailscale Tailnet GPU + Thermal Telemetry Engine for GPU Sentry.
Provides:
1. Built-in HTTP Telemetry Server (default TCP port 51920) & UDP LAN Auto-Discovery (UDP port 51921)
   so multiple machines running GPU Sentry (GUI or headless `--agent`) automatically discover each other.
2. Automatic Tailscale Tailnet GPU Scanner (`tailscale status --json`):
   Scans online peers across the user's Tailnet in parallel via HTTP (:51920 / :8085) and Tailscale/OpenSSH,
   automatically discovering machines with NVIDIA, AMD (`amdgpu`), or Intel (`i915`/`xe`) GPUs and their thermals.
3. Agentless SSH Remote Polling (`user@host`) supporting NVIDIA (`nvidia-smi`), AMD (`amdgpu` sysfs/hwmon),
   and Intel (`i915`/`xe` sysfs/hwmon) GPUs + Host CPU/RAM/Thermal telemetry.
4. LibreHardwareMonitor / OpenHardwareMonitor Web Server (`http://host:8085/data.json`) parser.
"""

import concurrent.futures
import dataclasses
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
if "PyQt6" in sys.modules:
    from PyQt6.QtCore import QObject, pyqtSignal
else:
    class QObject:  # type: ignore
        def __init__(self, parent=None):
            pass

    class _DummySignal:
        def __init__(self):
            self._cbs = []
        def connect(self, cb):
            self._cbs.append(cb)
        def emit(self, *args, **kwargs):
            for cb in list(self._cbs):
                try:
                    cb(*args, **kwargs)
                except Exception:
                    pass

    def pyqtSignal(*args, **kwargs):  # type: ignore
        return _DummySignal()

from core.gpu_types import GpuDevice, GpuMetrics, GpuProcess, HostMetrics, CpuMetrics, RamMetrics


DEFAULT_HTTP_PORT = 51920
DEFAULT_UDP_PORT = 51921
DISCOVERY_MAGIC = b"GPUSENTRY_DISCOVER_V1"
DISCOVERY_REPLY_MAGIC = "GPUSENTRY_NODE_V1"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".gpu_sentry_network.json")

REMOTE_LINUX_SH_PROBE = r"""
echo "===HOST==="
hostname
nproc 2>/dev/null || echo 1
cat /proc/loadavg 2>/dev/null || echo "0 0 0"
grep -E '^(MemTotal|MemAvailable):' /proc/meminfo 2>/dev/null || true
for t in /sys/class/thermal/thermal_zone*/temp /sys/class/hwmon/hwmon*/temp1_input; do
  [ -r "$t" ] && echo "HTEMP=$(cat "$t" 2>/dev/null)"
done
echo "===NVIDIA==="
nvidia-smi --query-gpu=index,name,pci.bus_id,driver_version,vbios_version,pcie.link.gen.current,pcie.link.width.current,pcie.link.gen.max,pcie.link.width.max,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total,memory.free,power.draw,power.limit,fan.speed,clocks.current.graphics,clocks.current.memory --format=csv,noheader,nounits 2>/dev/null || true
echo "===DRM==="
for c in /sys/class/drm/card[0-9]; do
  [ -d "$c/device" ] || continue
  echo "---CARD:$c---"
  cat "$c/device/uevent" 2>/dev/null || true
  slot=$(grep '^PCI_SLOT_NAME=' "$c/device/uevent" 2>/dev/null | cut -d= -f2)
  if [ -n "$slot" ]; then
    (/usr/bin/lspci -s "$slot" 2>/dev/null || /sbin/lspci -s "$slot" 2>/dev/null || true) | head -n 1 | sed 's/^/LSPCI=/'
  fi
  rev=$(cat "$c/device/revision" 2>/dev/null | sed 's/^0x//i' | tr 'a-f' 'A-F')
  did=$(grep '^PCI_ID=' "$c/device/uevent" 2>/dev/null | cut -d: -f2 | tr 'a-f' 'A-F')
  if [ -n "$did" ] && [ -f /usr/share/libdrm/amdgpu.ids ]; then
    (grep -i "^${did},[[:space:]]*${rev}," /usr/share/libdrm/amdgpu.ids 2>/dev/null || grep -i "^${did}," /usr/share/libdrm/amdgpu.ids 2>/dev/null || true) | head -n 1 | cut -d, -f3- | sed 's/^[[:space:]]*/AMDGPU_NAME=/'
  fi
  echo "BUSY=$(cat $c/device/gpu_busy_percent 2>/dev/null || echo 0)"
  echo "VRAM_USED=$(cat $c/device/mem_info_vram_used 2>/dev/null || echo 0)"
  echo "VRAM_TOTAL=$(cat $c/device/mem_info_vram_total 2>/dev/null || echo 0)"
  for hw in $c/device/hwmon/hwmon*; do
    [ -d "$hw" ] || continue
    echo "TEMP1=$(cat $hw/temp1_input 2>/dev/null || echo 0)"
    echo "TEMP2=$(cat $hw/temp2_input 2>/dev/null || echo 0)"
    echo "TEMP3=$(cat $hw/temp3_input 2>/dev/null || echo 0)"
    echo "PWR=$(cat $hw/power1_average 2>/dev/null || cat $hw/power1_input 2>/dev/null || echo 0)"
    echo "PWR_CAP=$(cat $hw/power1_cap 2>/dev/null || echo 0)"
    echo "FAN_RPM=$(cat $hw/fan1_input 2>/dev/null || echo 0)"
    echo "PWM=$(cat $hw/pwm1 2>/dev/null || echo 0)"
    echo "FREQ1=$(cat $hw/freq1_input 2>/dev/null || echo 0)"
    echo "FREQ2=$(cat $hw/freq2_input 2>/dev/null || echo 0)"
  done
done
true
"""


@dataclass
class RemoteNodeConfig:
    node_id: str          # e.g. "sentry://192.168.1.50:51920" or "ssh://hakanu@hakuxtx"
    address: str          # IP, hostname, or user@host
    protocol: str = "auto"  # "auto", "sentry", "ssh", "lhm"
    port: int = DEFAULT_HTTP_PORT
    label: str = ""
    enabled: bool = True
    auto_discovered: bool = False
    is_tailscale: bool = False
    tailscale_ip: str = ""


@dataclass
class RemoteNodeState:
    node_id: str
    address: str
    protocol: str
    port: int = DEFAULT_HTTP_PORT
    hostname: str = ""
    os_name: str = ""
    online: bool = False
    is_tailscale: bool = False
    tailscale_ip: str = ""
    latency_ms: float = 0.0
    last_seen: float = 0.0
    error_msg: str = ""
    host_metrics: HostMetrics = field(default_factory=HostMetrics)
    gpus: List[GpuDevice] = field(default_factory=list)
    gpu_metrics: Dict[str, GpuMetrics] = field(default_factory=dict)


def get_local_lan_ips() -> List[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            ips.add(ip)
        s.close()
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


class LocalTelemetryServer:
    """Lightweight background HTTP server + UDP discovery responder."""

    def __init__(self, port: int = DEFAULT_HTTP_PORT):
        self.port = port
        self.instance_id = f"{socket.gethostname()}_{os.getpid()}_{int(time.time())}"
        self.hostname = socket.gethostname()
        self.os_name = f"{sys.platform}"
        self._lock = threading.Lock()
        self._latest_payload: bytes = b"{}"
        self._http_server: Optional[ThreadingHTTPServer] = None
        self._udp_sock: Optional[socket.socket] = None
        self._running = False

    def update_snapshot(
        self,
        devices: List[GpuDevice],
        metrics_by_id: Dict[str, GpuMetrics],
        host_metrics: Optional[HostMetrics],
        os_name: str = "",
    ):
        if os_name:
            self.os_name = os_name
        gpus_list = []
        for dev in devices:
            if dev.device_id.startswith("net_"):
                continue
            m = metrics_by_id.get(dev.device_id, GpuMetrics())
            dev_dict = dataclasses.asdict(dev)
            dev_dict["metrics"] = dataclasses.asdict(m)
            gpus_list.append(dev_dict)

        data = {
            "magic": DISCOVERY_REPLY_MAGIC,
            "instance_id": self.instance_id,
            "hostname": self.hostname,
            "os_name": self.os_name,
            "port": self.port,
            "timestamp": time.time(),
            "host": dataclasses.asdict(host_metrics) if host_metrics else dataclasses.asdict(HostMetrics()),
            "gpus": gpus_list,
        }
        raw = json.dumps(data).encode("utf-8")
        with self._lock:
            self._latest_payload = raw

    def get_payload(self) -> bytes:
        with self._lock:
            return self._latest_payload

    def start(self) -> bool:
        if self._running:
            return True
        parent = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/api/telemetry") or self.path == "/":
                    payload = parent.get_payload()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass

        for candidate_port in range(self.port, self.port + 10):
            try:
                srv = ThreadingHTTPServer(("0.0.0.0", candidate_port), _Handler)
                srv.daemon_threads = True
                self.port = candidate_port
                self._http_server = srv
                break
            except Exception:
                continue

        if not self._http_server:
            return False

        self._running = True
        threading.Thread(target=self._http_server.serve_forever, daemon=True).start()
        threading.Thread(target=self._udp_responder_loop, daemon=True).start()
        return True

    def _udp_responder_loop(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", DEFAULT_UDP_PORT))
            sock.settimeout(1.0)
            self._udp_sock = sock
        except Exception:
            return

        while self._running:
            try:
                data, addr = self._udp_sock.recvfrom(1024)
                if data and data.startswith(DISCOVERY_MAGIC):
                    reply = json.dumps({
                        "magic": DISCOVERY_REPLY_MAGIC,
                        "instance_id": self.instance_id,
                        "hostname": self.hostname,
                        "port": self.port,
                    }).encode("utf-8")
                    self._udp_sock.sendto(reply, addr)
            except socket.timeout:
                continue
            except Exception:
                if not self._running:
                    break

    def stop(self):
        self._running = False
        if self._http_server:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception:
                pass
            self._http_server = None
        if self._udp_sock:
            try:
                self._udp_sock.close()
            except Exception:
                pass
            self._udp_sock = None


class NetworkTelemetryManager(QObject):
    """
    Manages local telemetry sharing, LAN UDP auto-discovery, Tailscale Tailnet GPU discovery,
    and asynchronous polling of remote network nodes.
    """

    nodes_updated = pyqtSignal(dict)  # Dict[str, RemoteNodeState]
    tailnet_scan_status = pyqtSignal(str)
    tailscale_enabled_changed = pyqtSignal(bool)

    def __init__(self, os_name: str = "", parent=None):
        super().__init__(parent)
        self.local_server = LocalTelemetryServer(port=DEFAULT_HTTP_PORT)
        self.os_name = os_name
        self.server_enabled = True
        self.tailscale_enabled = True
        self.pin_remote_cards = False
        self.condensed_view = False
        self.tailnet_name = ""

        self._lock = threading.Lock()
        self.configs: Dict[str, RemoteNodeConfig] = {}
        self.states: Dict[str, RemoteNodeState] = {}
        self._probed_tailscale_peers: set = set()
        self._running = False
        self._scan_requested = False
        self._tailnet_scan_requested = False
        self._wake_poll = False

        self._load_config()

    def start(self):
        if self._running:
            return
        self._running = True
        if self.server_enabled:
            self.local_server.start()
        self.request_lan_scan()
        # Only auto-scan Tailnet on startup if Tailscale is enabled and no Tailscale nodes are saved yet
        if self.tailscale_enabled and not any(c.is_tailscale for c in self.configs.values()):
            self.request_tailnet_scan()
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def stop(self):
        self._running = False
        self.local_server.stop()

    def get_visible_states(self) -> Dict[str, RemoteNodeState]:
        """Returns node states respecting tailscale_enabled and per-node enabled flags."""
        with self._lock:
            out: Dict[str, RemoteNodeState] = {}
            for nid, st in self.states.items():
                cfg = self.configs.get(nid)
                if cfg and not cfg.enabled:
                    continue
                if (st.is_tailscale or (cfg and cfg.is_tailscale)) and not self.tailscale_enabled:
                    continue
                out[nid] = st
            return out

    def set_server_enabled(self, enabled: bool):
        self.server_enabled = enabled
        if enabled:
            self.local_server.start()
        else:
            self.local_server.stop()
        self._save_config()

    def set_tailscale_enabled(self, enabled: bool):
        self.tailscale_enabled = bool(enabled)
        if not self.tailscale_enabled:
            self._tailnet_scan_requested = False
            try:
                self.tailnet_scan_status.emit("")
            except RuntimeError:
                pass
        else:
            if not any(c.is_tailscale for c in self.configs.values()):
                self.request_tailnet_scan()
            else:
                self._wake_poll = True
        self._save_config()
        try:
            self.tailscale_enabled_changed.emit(self.tailscale_enabled)
        except RuntimeError:
            pass
        snapshot = self.get_visible_states()
        if self._running:
            try:
                self.nodes_updated.emit(snapshot)
            except RuntimeError:
                pass

    def set_condensed_view(self, condensed: bool):
        self.condensed_view = bool(condensed)
        self._save_config()

    def set_node_enabled(self, node_id: str, enabled: bool):
        with self._lock:
            cfg = self.configs.get(node_id)
            if cfg:
                cfg.enabled = bool(enabled)
                if enabled:
                    self._wake_poll = True
        self._save_config()
        snapshot = self.get_visible_states()
        if self._running:
            try:
                self.nodes_updated.emit(snapshot)
            except RuntimeError:
                pass

    def set_pin_remote_cards(self, pinned: bool):
        self.pin_remote_cards = pinned
        self._save_config()
        snapshot = self.get_visible_states()
        if self._running:
            try:
                self.nodes_updated.emit(snapshot)
            except RuntimeError:
                pass

    def update_local_telemetry(
        self,
        devices: List[GpuDevice],
        metrics_by_id: Dict[str, GpuMetrics],
        host_metrics: Optional[HostMetrics],
    ):
        if self.server_enabled:
            self.local_server.update_snapshot(devices, metrics_by_id, host_metrics, self.os_name)

    def request_lan_scan(self):
        self._scan_requested = True

    def request_tailnet_scan(self, force_reprobe: bool = False):
        if force_reprobe:
            with self._lock:
                self._probed_tailscale_peers.clear()
        self._tailnet_scan_requested = True

    def add_node(
        self,
        address: str,
        protocol: str = "auto",
        port: int = DEFAULT_HTTP_PORT,
        is_tailscale: bool = False,
        tailscale_ip: str = "",
        label: str = "",
    ) -> str:
        address = address.strip()
        if not address:
            return ""

        if "@" in address and protocol == "auto":
            protocol = "ssh"
        elif "://" in address:
            scheme, rest = address.split("://", 1)
            if scheme.lower() in ("ssh", "http", "https"):
                if scheme.lower() == "ssh":
                    protocol = "ssh"
                address = rest.rstrip("/")

        if ":" in address and protocol != "ssh":
            host_part, port_part = address.rsplit(":", 1)
            if port_part.isdigit():
                address = host_part
                port = int(port_part)
                if port == 8085 and protocol == "auto":
                    protocol = "lhm"

        if protocol == "lhm" and port == DEFAULT_HTTP_PORT:
            port = 8085

        node_id = f"{protocol}://{address}:{port}" if protocol != "ssh" else f"ssh://{address}"
        cfg = RemoteNodeConfig(
            node_id=node_id,
            address=address,
            protocol=protocol,
            port=port,
            label=label or address.split("@")[-1],
            enabled=True,
            auto_discovered=False,
            is_tailscale=is_tailscale,
            tailscale_ip=tailscale_ip,
        )
        with self._lock:
            self.configs[node_id] = cfg
            self.states[node_id] = RemoteNodeState(
                node_id=node_id,
                address=address,
                protocol=protocol,
                port=port,
                hostname=cfg.label,
                is_tailscale=is_tailscale,
                tailscale_ip=tailscale_ip,
            )
        self._save_config()
        return node_id

    def remove_node(self, node_id: str):
        with self._lock:
            self.configs.pop(node_id, None)
            self.states.pop(node_id, None)
        snapshot = self.get_visible_states()
        self._save_config()
        if self._running:
            try:
                self.nodes_updated.emit(snapshot)
            except RuntimeError:
                pass

    def _load_config(self):
        if not os.path.isfile(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.server_enabled = bool(data.get("server_enabled", True))
            self.tailscale_enabled = bool(data.get("tailscale_enabled", True))
            self.pin_remote_cards = bool(data.get("pin_remote_cards", False))
            self.condensed_view = bool(data.get("condensed_view", False))
            for item in data.get("nodes", []):
                # Filter valid fields
                valid_keys = {f.name for f in dataclasses.fields(RemoteNodeConfig)}
                clean_item = {k: v for k, v in item.items() if k in valid_keys}
                cfg = RemoteNodeConfig(**clean_item)
                self.configs[cfg.node_id] = cfg
                self.states[cfg.node_id] = RemoteNodeState(
                    node_id=cfg.node_id,
                    address=cfg.address,
                    protocol=cfg.protocol,
                    port=cfg.port,
                    hostname=cfg.label or cfg.address,
                    is_tailscale=cfg.is_tailscale,
                    tailscale_ip=cfg.tailscale_ip,
                )
        except Exception:
            pass

    def _save_config(self):
        try:
            with self._lock:
                nodes_data = [
                    dataclasses.asdict(c)
                    for c in self.configs.values()
                ]
            data = {
                "server_enabled": self.server_enabled,
                "tailscale_enabled": self.tailscale_enabled,
                "pin_remote_cards": self.pin_remote_cards,
                "condensed_view": self.condensed_view,
                "nodes": nodes_data,
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _discover_lan_nodes(self):
        """Send UDP broadcast to discover GPU Sentry agents on the LAN."""
        local_ips = set(get_local_lan_ips()) | {"127.0.0.1", "localhost"}
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.35)

            targets = ["255.255.255.255"]
            for lip in list(local_ips):
                parts = lip.split(".")
                if len(parts) == 4 and parts[0] != "127":
                    targets.append(f"{parts[0]}.{parts[1]}.{parts[2]}.255")

            for t in set(targets):
                try:
                    sock.sendto(DISCOVERY_MAGIC, (t, DEFAULT_UDP_PORT))
                except Exception:
                    pass

            deadline = time.time() + 0.45
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(2048)
                    remote_ip = addr[0]
                    info = json.loads(data.decode("utf-8", errors="ignore"))
                    if info.get("magic") != DISCOVERY_REPLY_MAGIC:
                        continue
                    if info.get("instance_id") == self.local_server.instance_id:
                        continue
                    if remote_ip in local_ips:
                        continue
                    r_port = int(info.get("port", DEFAULT_HTTP_PORT))
                    r_host = info.get("hostname", remote_ip)
                    node_id = f"sentry://{remote_ip}:{r_port}"
                    with self._lock:
                        # Avoid duplicate entry if this hostname is already monitored (e.g. via Tailscale)
                        already_exists = any(
                            c.label.lower() == str(r_host).lower() or c.address == remote_ip
                            for c in self.configs.values()
                        )
                        if node_id not in self.configs and not already_exists:
                            self.configs[node_id] = RemoteNodeConfig(
                                node_id=node_id,
                                address=remote_ip,
                                protocol="sentry",
                                port=r_port,
                                label=r_host,
                                enabled=True,
                                auto_discovered=True,
                            )
                            self.states[node_id] = RemoteNodeState(
                                node_id=node_id,
                                address=remote_ip,
                                protocol="sentry",
                                port=r_port,
                                hostname=r_host,
                            )
                except socket.timeout:
                    break
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def _discover_tailscale_nodes(self):
        """
        Queries `tailscale status --json` and probes online Linux/Windows peers in parallel
        to automatically discover machines equipped with GPUs across the Tailnet.
        """
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        try:
            proc = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=3.0,
                creationflags=creationflags,
            )
            if proc.returncode != 0 or not proc.stdout:
                return
            ts_data = json.loads(proc.stdout)
        except Exception:
            return

        self.tailnet_name = ts_data.get("MagicDNSSuffix") or ts_data.get("CurrentTailnet", {}).get("Name", "Tailnet")
        peers = ts_data.get("Peer", {})
        candidates = []
        for p in peers.values():
            if not p.get("Online"):
                continue
            os_type = str(p.get("OS", "")).lower()
            if os_type not in ("linux", "windows"):
                continue
            host_name = str(p.get("HostName", "")).strip()
            ts_ips = p.get("TailscaleIPs", [])
            ip = ts_ips[0] if ts_ips else ""
            if not host_name and not ip:
                continue
            peer_key = f"{host_name}_{ip}"
            with self._lock:
                if peer_key in self._probed_tailscale_peers:
                    continue
                # Skip if already configured
                if any(
                    c.tailscale_ip == ip or c.label.lower() == host_name.lower() or c.address.endswith(f"@{host_name}")
                    for c in self.configs.values()
                ):
                    self._probed_tailscale_peers.add(peer_key)
                    continue
            candidates.append((peer_key, host_name, ip, os_type))

        if not candidates:
            return

        if self._running:
            try:
                self.tailnet_scan_status.emit(f"🦊 Scanning {len(candidates)} online Tailnet machines for GPUs...")
            except RuntimeError:
                pass

        # Candidate SSH usernames to try for Tailscale SSH / OpenSSH
        local_user = ""
        try:
            local_user = getpass.getuser()
        except Exception:
            pass
        ssh_users = []
        for u in ("hakanu", local_user, "root"):
            if u and u not in ssh_users:
                ssh_users.append(u)

        def _probe_tailscale_peer(item):
            peer_key, host_name, ip, os_type = item
            with self._lock:
                self._probed_tailscale_peers.add(peer_key)

            # 1. Check if GPU Sentry HTTP (:51920) or LibreHardwareMonitor (:8085 on Windows) is open
            ports_to_check = [(DEFAULT_HTTP_PORT, "sentry")]
            if os_type == "windows":
                ports_to_check.append((8085, "lhm"))
            for port, proto in ports_to_check:
                try:
                    s = socket.create_connection((ip, port), timeout=0.35)
                    s.close()
                    node_id = f"{proto}://{ip}:{port}"
                    cfg = RemoteNodeConfig(
                        node_id=node_id,
                        address=ip,
                        protocol=proto,
                        port=port,
                        label=host_name or ip,
                        enabled=True,
                        auto_discovered=True,
                        is_tailscale=True,
                        tailscale_ip=ip,
                    )
                    st = self._poll_single_node(cfg)
                    if st.online and st.gpus:
                        return (cfg, st)
                except Exception:
                    pass

            # 2. Fast TCP check on SSH (:22) before spawning ssh.exe so non-SSH peers don't hang
            try:
                s = socket.create_connection((ip, 22), timeout=0.6)
                s.close()
            except Exception:
                return None

            target_host = host_name if host_name else ip
            for user in ssh_users:
                addr = f"{user}@{target_host}"
                node_id = f"ssh://{addr}"
                cfg = RemoteNodeConfig(
                    node_id=node_id,
                    address=addr,
                    protocol="ssh",
                    port=22,
                    label=host_name or ip,
                    enabled=True,
                    auto_discovered=True,
                    is_tailscale=True,
                    tailscale_ip=ip,
                )
                st = self._poll_ssh_node(cfg, time.perf_counter())
                if st.online:
                    if st.gpus:
                        return (cfg, st)
                    # Connected successfully via SSH, but this host has no GPUs (e.g. headless RPi)
                    return None
                # If Tailscale SSH explicitly says policy does not permit user, try next user immediately
                if "does not permit" in st.error_msg or "Permission denied" in st.error_msg:
                    continue
                if "timed out" in st.error_msg.lower() or "timeout" in st.error_msg.lower():
                    break
            return None

        discovered_count = 0
        for item in candidates:
            if not self._running or not self.tailscale_enabled:
                break
            res = _probe_tailscale_peer(item)
            if res is not None:
                cfg, st = res
                with self._lock:
                    self.configs[cfg.node_id] = cfg
                    self.states[cfg.node_id] = st
                discovered_count += 1

        if discovered_count > 0:
            self._save_config()
            snapshot = self.get_visible_states()
            if self._running:
                try:
                    self.nodes_updated.emit(snapshot)
                except RuntimeError:
                    pass

        if self._running:
            try:
                self.tailnet_scan_status.emit("")
            except RuntimeError:
                pass

    def _poll_loop(self):
        last_discovery = 0.0
        while self._running:
            self._wake_poll = False
            # 1. Poll configured nodes FIRST so saved Tailnet/LAN GPUs come online immediately (~1.4s total)
            with self._lock:
                active_configs = [
                    c for c in self.configs.values()
                    if c.enabled and (not c.is_tailscale or self.tailscale_enabled)
                ]

            if active_configs:
                for cfg in active_configs:
                    if not self._running:
                        break
                    if cfg.is_tailscale and not self.tailscale_enabled:
                        continue
                    try:
                        state = self._poll_single_node(cfg)
                        with self._lock:
                            prev = self.states.get(cfg.node_id)
                            # Avoid flickering to OFFLINE on a single transient SSH/DERP hiccup
                            if not state.online and prev and prev.online and (time.time() - prev.last_seen < 18.0):
                                pass
                            else:
                                self.states[cfg.node_id] = state
                        snapshot = self.get_visible_states()
                        if self._running:
                            try:
                                self.nodes_updated.emit(snapshot)
                            except RuntimeError:
                                break
                    except Exception:
                        pass

            # 2. Run LAN / Tailnet discovery after polling known nodes
            now = time.time()
            if self._scan_requested or (now - last_discovery > 30.0):
                self._scan_requested = False
                last_discovery = now
                self._discover_lan_nodes()

            if self._tailnet_scan_requested:
                self._tailnet_scan_requested = False
                if self.tailscale_enabled:
                    self._discover_tailscale_nodes()

            # 3. Wait 5.0 seconds before next poll cycle (wake early if manual scan requested)
            for _ in range(50):
                if not self._running or self._scan_requested or self._tailnet_scan_requested or self._wake_poll:
                    break
                time.sleep(0.1)

    def _poll_single_node(self, cfg: RemoteNodeConfig) -> RemoteNodeState:
        t0 = time.perf_counter()
        if cfg.protocol in ("auto", "sentry"):
            state = self._poll_sentry_http(cfg, t0)
            if state.online or cfg.protocol == "sentry":
                return state
            lhm_cfg = RemoteNodeConfig(
                node_id=cfg.node_id,
                address=cfg.address,
                protocol="lhm",
                port=8085 if cfg.port == DEFAULT_HTTP_PORT else cfg.port,
                label=cfg.label,
                is_tailscale=cfg.is_tailscale,
                tailscale_ip=cfg.tailscale_ip,
            )
            lhm_state = self._poll_lhm_http(lhm_cfg, t0)
            if lhm_state.online:
                return lhm_state
            return state
        elif cfg.protocol == "lhm":
            return self._poll_lhm_http(cfg, t0)
        elif cfg.protocol == "ssh":
            return self._poll_ssh_node(cfg, t0)
        return RemoteNodeState(
            node_id=cfg.node_id,
            address=cfg.address,
            protocol=cfg.protocol,
            online=False,
            is_tailscale=cfg.is_tailscale,
            tailscale_ip=cfg.tailscale_ip,
            error_msg="Unknown protocol",
        )

    def _poll_sentry_http(self, cfg: RemoteNodeConfig, t0: float) -> RemoteNodeState:
        url = f"http://{cfg.address}:{cfg.port}/api/telemetry"
        state = RemoteNodeState(
            node_id=cfg.node_id,
            address=cfg.address,
            protocol="sentry",
            port=cfg.port,
            hostname=cfg.label or cfg.address,
            is_tailscale=cfg.is_tailscale,
            tailscale_ip=cfg.tailscale_ip,
        )
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw)
            state.latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            state.online = True
            state.last_seen = time.time()
            state.hostname = data.get("hostname") or cfg.label or cfg.address
            state.os_name = data.get("os_name") or "Remote OS"

            h_raw = data.get("host", {})
            c_raw = h_raw.get("cpu", {})
            r_raw = h_raw.get("ram", {})
            state.host_metrics = HostMetrics(
                cpu=CpuMetrics(
                    name=c_raw.get("name", ""),
                    cores_physical=int(c_raw.get("cores_physical", 0)),
                    cores_logical=int(c_raw.get("cores_logical", 0)),
                    load_percent=float(c_raw.get("load_percent", 0.0)),
                    freq_mhz=float(c_raw.get("freq_mhz", 0.0)),
                    temp_core_c=float(c_raw.get("temp_core_c", 0.0)),
                    power_draw_w=c_raw.get("power_draw_w"),
                ),
                ram=RamMetrics(
                    used_gb=float(r_raw.get("used_gb", 0.0)),
                    total_gb=float(r_raw.get("total_gb", 0.0)),
                    free_gb=float(r_raw.get("free_gb", 0.0)),
                    load_percent=float(r_raw.get("load_percent", 0.0)),
                ),
            )

            for idx, g_raw in enumerate(data.get("gpus", [])):
                m_raw = g_raw.get("metrics", {})
                dev_id = f"net_{cfg.address}_{g_raw.get('device_id', idx)}"
                procs = [
                    GpuProcess(
                        pid=int(p.get("pid", 0)),
                        name=str(p.get("name", "")),
                        memory_used_mb=p.get("memory_used_mb"),
                        process_type=str(p.get("process_type", "Compute")),
                    )
                    for p in m_raw.get("processes", [])
                ]
                metrics = GpuMetrics(
                    gpu_util_percent=float(m_raw.get("gpu_util_percent", 0.0)),
                    mem_util_percent=float(m_raw.get("mem_util_percent", 0.0)),
                    temp_core_c=float(m_raw.get("temp_core_c", 0.0)),
                    temp_hotspot_c=m_raw.get("temp_hotspot_c"),
                    temp_memory_c=m_raw.get("temp_memory_c"),
                    vram_used_mb=float(m_raw.get("vram_used_mb", 0.0)),
                    vram_total_mb=float(m_raw.get("vram_total_mb", 0.0)),
                    vram_free_mb=float(m_raw.get("vram_free_mb", 0.0)),
                    power_draw_w=float(m_raw.get("power_draw_w", 0.0)),
                    power_limit_w=m_raw.get("power_limit_w"),
                    fan_speed_percent=m_raw.get("fan_speed_percent"),
                    fan_speed_rpm=m_raw.get("fan_speed_rpm"),
                    clock_graphics_mhz=m_raw.get("clock_graphics_mhz"),
                    clock_memory_mhz=m_raw.get("clock_memory_mhz"),
                    processes=procs,
                )
                dev = GpuDevice(
                    device_id=dev_id,
                    index=int(g_raw.get("index", idx)),
                    name=f"[{state.hostname}] {g_raw.get('name', 'Remote GPU')}",
                    vendor=str(g_raw.get("vendor", "NVIDIA")),
                    bus_id=f"{cfg.address} • {g_raw.get('bus_id', '')}".strip(" •"),
                    pcie_gen=g_raw.get("pcie_gen"),
                    pcie_width=g_raw.get("pcie_width"),
                    pcie_max_gen=g_raw.get("pcie_max_gen"),
                    pcie_max_width=g_raw.get("pcie_max_width"),
                    driver_version=str(g_raw.get("driver_version", "")),
                    vbios_version=str(g_raw.get("vbios_version", "")),
                    architecture=str(g_raw.get("architecture", "")),
                    cuda_cores=g_raw.get("cuda_cores"),
                    vram_total_mb=float(g_raw.get("vram_total_mb", metrics.vram_total_mb)),
                    metrics=metrics,
                )
                state.gpus.append(dev)
                state.gpu_metrics[dev_id] = metrics
        except Exception as e:
            state.online = False
            state.error_msg = f"Unreachable on :{cfg.port} ({type(e).__name__})"
        return state

    def _poll_ssh_node(self, cfg: RemoteNodeConfig, t0: float) -> RemoteNodeState:
        """
        Agentless SSH polling supporting NVIDIA (`nvidia-smi`), AMD (`amdgpu`),
        and Intel (`i915`/`xe`) GPUs + Linux Host CPU/RAM/Thermal metrics.
        """
        state = RemoteNodeState(
            node_id=cfg.node_id,
            address=cfg.address,
            protocol="ssh",
            port=cfg.port,
            hostname=cfg.label or cfg.address.split("@")[-1],
            is_tailscale=cfg.is_tailscale,
            tailscale_ip=cfg.tailscale_ip,
        )
        null_hosts = "NUL" if sys.platform == "win32" else "/dev/null"
        ssh_args = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8",
            "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=2",
            "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={null_hosts}",
            "-o", "LogLevel=ERROR",
            cfg.address,
            REMOTE_LINUX_SH_PROBE,
        ]
        try:
            creationflags = 0x08000000 if sys.platform == "win32" else 0
            proc = subprocess.run(
                ssh_args,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=12.0,
                creationflags=creationflags,
            )
            if proc.returncode != 0:
                state.online = False
                err = (proc.stderr or proc.stdout or "SSH error").strip().splitlines()
                state.error_msg = err[0][:90] if err else "SSH connection failed"
                return state

            out = proc.stdout or ""
            if "===HOST===" not in out:
                state.online = False
                state.error_msg = "Unexpected SSH output"
                return state

            state.latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            state.online = True
            state.last_seen = time.time()
            state.os_name = "Tailscale SSH Linux" if cfg.is_tailscale else "SSH Linux Host"

            # Split into sections
            host_sec = ""
            nv_sec = ""
            drm_sec = ""
            if "===NVIDIA===" in out:
                p1, rest = out.split("===NVIDIA===", 1)
                host_sec = p1.split("===HOST===", 1)[-1]
                if "===DRM===" in rest:
                    nv_sec, drm_sec = rest.split("===DRM===", 1)
                else:
                    nv_sec = rest

            # 1. Parse Host Section
            h_lines = [ln.strip() for ln in host_sec.strip().splitlines() if ln.strip()]
            if h_lines:
                state.hostname = h_lines[0]
            nproc = 1
            if len(h_lines) >= 2 and h_lines[1].isdigit():
                nproc = max(1, int(h_lines[1]))
            load1 = 0.0
            if len(h_lines) >= 3:
                try:
                    load1 = float(h_lines[2].split()[0])
                except Exception:
                    pass
            cpu_pct = min(100.0, round((load1 / nproc) * 100.0, 1))

            mem_total_kb = 0
            mem_avail_kb = 0
            host_temps = []
            for ln in h_lines[3:]:
                if ln.startswith("MemTotal:"):
                    parts = ln.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        mem_total_kb = int(parts[1])
                elif ln.startswith("MemAvailable:"):
                    parts = ln.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        mem_avail_kb = int(parts[1])
                elif ln.startswith("HTEMP="):
                    try:
                        tv = float(ln.split("=", 1)[1])
                        if tv > 1000:
                            tv /= 1000.0
                        if 10.0 < tv < 115.0:
                            host_temps.append(tv)
                    except Exception:
                        pass

            ram_tot_gb = round(mem_total_kb / (1024 * 1024), 1) if mem_total_kb > 0 else 0.0
            ram_free_gb = round(mem_avail_kb / (1024 * 1024), 1) if mem_avail_kb > 0 else 0.0
            ram_used_gb = round(max(0.0, ram_tot_gb - ram_free_gb), 1)
            ram_pct = round((ram_used_gb / ram_tot_gb) * 100.0, 1) if ram_tot_gb > 0 else 0.0
            cpu_temp_c = round(max(host_temps), 1) if host_temps else 0.0

            state.host_metrics = HostMetrics(
                cpu=CpuMetrics(
                    name=f"{state.hostname} CPU",
                    cores_logical=nproc,
                    load_percent=cpu_pct,
                    temp_core_c=cpu_temp_c,
                ),
                ram=RamMetrics(
                    used_gb=ram_used_gb,
                    total_gb=ram_tot_gb,
                    free_gb=ram_free_gb,
                    load_percent=ram_pct,
                ),
            )

            def _flt(val: str, default: float = 0.0) -> float:
                try:
                    return float(val.strip())
                except Exception:
                    return default

            def _int(val: str) -> Optional[int]:
                try:
                    return int(float(val.strip()))
                except Exception:
                    return None

            # 2. Parse NVIDIA GPUs
            has_nvidia = False
            for idx, line in enumerate(nv_sec.strip().splitlines()):
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 20:
                    continue
                has_nvidia = True
                g_idx = _int(parts[0]) or idx
                g_name = parts[1]
                bus_id = parts[2]
                drv = parts[3]
                vbios = parts[4]
                p_gen = _int(parts[5])
                p_wid = _int(parts[6])
                p_mgen = _int(parts[7])
                p_mwid = _int(parts[8])
                temp_c = _flt(parts[9])
                u_gpu = _flt(parts[10])
                u_mem = _flt(parts[11])
                v_used = _flt(parts[12])
                v_tot = _flt(parts[13])
                v_free = _flt(parts[14])
                pwr_w = _flt(parts[15])
                pwr_lim = _flt(parts[16])
                fan_pct = _flt(parts[17], -1.0)
                clk_gr = _int(parts[18])
                clk_mem = _int(parts[19])

                dev_id = f"net_ssh_{state.hostname}_nv_{g_idx}"
                metrics = GpuMetrics(
                    gpu_util_percent=u_gpu,
                    mem_util_percent=u_mem,
                    temp_core_c=temp_c,
                    vram_used_mb=v_used,
                    vram_total_mb=v_tot,
                    vram_free_mb=v_free,
                    power_draw_w=pwr_w,
                    power_limit_w=pwr_lim if pwr_lim > 0 else None,
                    fan_speed_percent=fan_pct if fan_pct >= 0 else None,
                    clock_graphics_mhz=clk_gr,
                    clock_memory_mhz=clk_mem,
                )
                dev = GpuDevice(
                    device_id=dev_id,
                    index=g_idx,
                    name=f"[{state.hostname}] {g_name}",
                    vendor="NVIDIA",
                    bus_id=f"{cfg.address} • {bus_id}",
                    pcie_gen=p_gen,
                    pcie_width=p_wid,
                    pcie_max_gen=p_mgen,
                    pcie_max_width=p_mwid,
                    driver_version=drv,
                    vbios_version=vbios,
                    vram_total_mb=v_tot,
                    metrics=metrics,
                )
                state.gpus.append(dev)
                state.gpu_metrics[dev_id] = metrics

            # 3. Parse Linux DRM GPUs (AMD amdgpu / Intel i915 / xe)
            card_blocks = drm_sec.split("---CARD:")
            for blk in card_blocks[1:]:
                b_lines = [ln.strip() for ln in blk.strip().splitlines() if ln.strip()]
                if not b_lines:
                    continue
                card_path = b_lines[0].rstrip("-")
                kv = {}
                for ln in b_lines[1:]:
                    if "=" in ln:
                        k, v = ln.split("=", 1)
                        kv[k.strip()] = v.strip()

                driver = kv.get("DRIVER", "").lower()
                pci_id = kv.get("PCI_ID", "").upper()
                pci_slot = kv.get("PCI_SLOT_NAME", "")
                lspci_line = kv.get("LSPCI", "")

                # Skip NVIDIA DRM node if already handled by nvidia-smi
                if ("10DE" in pci_id or "nvidia" in driver) and has_nvidia:
                    continue
                # Skip virtual/BMC/non-GPU display controllers without driver
                if driver not in ("amdgpu", "i915", "xe", "nouveau", "radeon"):
                    continue

                vendor = "AMD" if ("1002" in pci_id or driver in ("amdgpu", "radeon")) else (
                    "Intel" if ("8086" in pci_id or driver in ("i915", "xe")) else "Other"
                )

                # Extract clean GPU model name from amdgpu.ids or lspci output
                amdgpu_name = kv.get("AMDGPU_NAME", "").strip()
                gpu_name = f"{vendor} Graphics ({os.path.basename(card_path)})"
                if amdgpu_name:
                    gpu_name = amdgpu_name
                elif lspci_line:
                    # e.g. "0a:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 31 [Radeon RX 7900 XT/7900 XTX/7900 GRE/7900M] (rev c8)"
                    desc = lspci_line.split(": ", 1)[-1]
                    desc = re.sub(r"\s*\(rev [0-9a-fA-F]+\)$", "", desc)
                    brackets = re.findall(r"\[([^\]]+)\]", desc)
                    # Filter out vendor bracket like [AMD/ATI] or hex IDs
                    model_brackets = [
                        b for b in brackets
                        if "AMD" not in b and "ATI" not in b and not re.match(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$", b)
                    ]
                    if model_brackets:
                        model_str = model_brackets[-1]
                        if "/" in model_str and "7900 XTX" in model_str and "xtx" in state.hostname.lower():
                            model_str = "Radeon RX 7900 XTX"
                        gpu_name = f"{vendor} {model_str}"
                    else:
                        desc_clean = re.sub(r"Advanced Micro Devices, Inc\.\s*\[AMD/ATI\]\s*", "AMD Radeon ", desc)
                        desc_clean = re.sub(r"Intel Corporation\s*", "Intel ", desc_clean)
                        gpu_name = desc_clean.strip()

                busy_pct = _flt(kv.get("BUSY", "0"))
                vram_u_bytes = _flt(kv.get("VRAM_USED", "0"))
                vram_t_bytes = _flt(kv.get("VRAM_TOTAL", "0"))
                vram_u_mb = round(vram_u_bytes / (1024 * 1024), 1)
                vram_t_mb = round(vram_t_bytes / (1024 * 1024), 1)
                vram_f_mb = round(max(0.0, vram_t_mb - vram_u_mb), 1)
                mem_pct = round((vram_u_mb / vram_t_mb) * 100.0, 1) if vram_t_mb > 0 else 0.0

                t1 = _flt(kv.get("TEMP1", "0")) / 1000.0
                t2 = _flt(kv.get("TEMP2", "0")) / 1000.0
                t3 = _flt(kv.get("TEMP3", "0")) / 1000.0
                if t1 <= 0.0 and cpu_temp_c > 0.0:
                    t1 = cpu_temp_c  # Fallback to package temp for iGPUs sharing CPU die

                pwr_uw = _flt(kv.get("PWR", "0"))
                pwr_cap_uw = _flt(kv.get("PWR_CAP", "0"))
                pwr_w = round(pwr_uw / 1_000_000.0, 1) if pwr_uw > 0 else 0.0
                pwr_cap_w = round(pwr_cap_uw / 1_000_000.0, 1) if pwr_cap_uw > 0 else None

                fan_rpm = _int(kv.get("FAN_RPM", "0"))
                pwm_raw = _flt(kv.get("PWM", "0"))
                fan_pct = round((pwm_raw / 255.0) * 100.0, 1) if pwm_raw > 0 else None

                freq1_hz = _flt(kv.get("FREQ1", "0"))
                freq2_hz = _flt(kv.get("FREQ2", "0"))
                clk_gr = int(freq1_hz / 1_000_000) if freq1_hz > 0 else None
                clk_mem = int(freq2_hz / 1_000_000) if freq2_hz > 0 else None

                idx = len(state.gpus)
                dev_id = f"net_ssh_{state.hostname}_drm_{idx}"
                metrics = GpuMetrics(
                    gpu_util_percent=busy_pct,
                    mem_util_percent=mem_pct,
                    temp_core_c=round(t1, 1),
                    temp_hotspot_c=round(t2, 1) if t2 > 0 else None,
                    temp_memory_c=round(t3, 1) if t3 > 0 else None,
                    vram_used_mb=vram_u_mb,
                    vram_total_mb=vram_t_mb,
                    vram_free_mb=vram_f_mb,
                    power_draw_w=pwr_w,
                    power_limit_w=pwr_cap_w,
                    fan_speed_percent=fan_pct,
                    fan_speed_rpm=fan_rpm if (fan_rpm and fan_rpm > 0) else None,
                    clock_graphics_mhz=clk_gr,
                    clock_memory_mhz=clk_mem,
                )
                dev = GpuDevice(
                    device_id=dev_id,
                    index=idx,
                    name=f"[{state.hostname}] {gpu_name}",
                    vendor=vendor,
                    bus_id=f"{cfg.address} • {pci_slot or os.path.basename(card_path)}",
                    driver_version=driver,
                    architecture=pci_id,
                    power_limit_default_w=pwr_cap_w,
                    vram_total_mb=vram_t_mb,
                    metrics=metrics,
                )
                state.gpus.append(dev)
                state.gpu_metrics[dev_id] = metrics

        except Exception as e:
            state.online = False
            state.error_msg = f"SSH timeout/error ({type(e).__name__})"
        return state

    def _poll_lhm_http(self, cfg: RemoteNodeConfig, t0: float) -> RemoteNodeState:
        """Polls LibreHardwareMonitor / OpenHardwareMonitor web server (http://host:8085/data.json)."""
        url = f"http://{cfg.address}:{cfg.port}/data.json"
        state = RemoteNodeState(
            node_id=cfg.node_id,
            address=cfg.address,
            protocol="lhm",
            port=cfg.port,
            hostname=cfg.label or cfg.address,
            is_tailscale=cfg.is_tailscale,
            tailscale_ip=cfg.tailscale_ip,
        )
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            root = json.loads(raw)
            state.latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            state.online = True
            state.last_seen = time.time()
            state.os_name = "LibreHardwareMonitor Node"

            children = root.get("Children", [])
            if children:
                pc_node = children[0]
                state.hostname = pc_node.get("Text", cfg.address)
                for hw in pc_node.get("Children", []):
                    hw_text = hw.get("Text", "")
                    hw_img = hw.get("ImageURL", "").lower()
                    if any(k in hw_img or k in hw_text.lower() for k in ("nvidia", "amd", "intel", "gpu", "radeon", "geforce", "arc")):
                        if "cpu" in hw_img or "ryzen" in hw_text.lower() or "core i" in hw_text.lower():
                            continue
                        vendor = "NVIDIA" if ("nvidia" in hw_img or "geforce" in hw_text.lower()) else (
                            "AMD" if ("ati" in hw_img or "amd" in hw_img or "radeon" in hw_text.lower()) else "Intel"
                        )
                        metrics = GpuMetrics()
                        self._parse_lhm_gpu_node(hw, metrics)
                        idx = len(state.gpus)
                        dev_id = f"net_lhm_{cfg.address}_{idx}"
                        dev = GpuDevice(
                            device_id=dev_id,
                            index=idx,
                            name=f"[{state.hostname}] {hw_text}",
                            vendor=vendor,
                            bus_id=f"{cfg.address}:{cfg.port}",
                            vram_total_mb=metrics.vram_total_mb,
                            metrics=metrics,
                        )
                        state.gpus.append(dev)
                        state.gpu_metrics[dev_id] = metrics
        except Exception as e:
            state.online = False
            state.error_msg = f"LHM unreachable on :{cfg.port} ({type(e).__name__})"
        return state

    def _parse_lhm_gpu_node(self, node: dict, metrics: GpuMetrics):
        for group in node.get("Children", []):
            g_name = group.get("Text", "").lower()
            for sensor in group.get("Children", []):
                s_name = sensor.get("Text", "").lower()
                val_str = sensor.get("Value", "").split(" ")[0].replace(",", ".")
                try:
                    val = float(val_str)
                except Exception:
                    continue
                if "temperature" in g_name:
                    if "core" in s_name or metrics.temp_core_c == 0.0:
                        metrics.temp_core_c = val
                    elif "hot" in s_name:
                        metrics.temp_hotspot_c = val
                    elif "memory" in s_name:
                        metrics.temp_memory_c = val
                elif "load" in g_name:
                    if "core" in s_name:
                        metrics.gpu_util_percent = val
                elif "power" in g_name:
                    if "package" in s_name or "gpu" in s_name or metrics.power_draw_w == 0.0:
                        metrics.power_draw_w = val
                elif "clock" in g_name:
                    if "core" in s_name:
                        metrics.clock_graphics_mhz = int(val)
                    elif "memory" in s_name:
                        metrics.clock_memory_mhz = int(val)
                elif "fan" in g_name and metrics.fan_speed_rpm is None:
                    metrics.fan_speed_rpm = int(val)
                elif "control" in g_name and metrics.fan_speed_percent is None:
                    metrics.fan_speed_percent = val
                elif "data" in g_name or "memory" in g_name:
                    if "used" in s_name:
                        metrics.vram_used_mb = val
                    elif "total" in s_name:
                        metrics.vram_total_mb = val
                    elif "free" in s_name:
                        metrics.vram_free_mb = val
