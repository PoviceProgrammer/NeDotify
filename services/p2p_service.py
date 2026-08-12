"""
NeDotify - P2P Sync Service
Discovers other NeDotify instances on the local network using Zeroconf (mDNS)
and provides basic sync over TCP sockets.
"""

import socket
import logging
import threading

logger = logging.getLogger(__name__)

try:
    from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, ServiceListener
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False
    logger.warning("zeroconf module not available. P2P service disabled.")
    Zeroconf = ServiceInfo = ServiceBrowser = ServiceListener = object


class NeDotifyListener(ServiceListener):
    def __init__(self, p2p_service):
        self.p2p = p2p_service

    def remove_service(self, zc, type_: str, name: str) -> None:
        if name in self.p2p.discovered_peers:
            del self.p2p.discovered_peers[name]
            logger.info(f"P2P Peer disconnected: {name}")

    def add_service(self, zc, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info:
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            port = info.port
            self.p2p.discovered_peers[name] = {
                "name": name,
                "addresses": addresses,
                "port": port,
                "server": info.server
            }
            logger.info(f"P2P Peer discovered: {name} at {addresses}:{port}")

    def update_service(self, zc, type_: str, name: str) -> None:
        self.add_service(zc, type_, name)


class P2PService:
    def __init__(self, instance_name="NeDotify-Peer", port=53535):
        self.instance_name = instance_name
        self.port = port
        self.service_type = "_nedotify._tcp.local."
        self.zeroconf = None
        self.browser = None
        self.discovered_peers = {}
        self._is_running = False

    def start(self):
        if not HAS_ZEROCONF or self._is_running:
            return False
        try:
            self.zeroconf = Zeroconf()
            info = ServiceInfo(
                self.service_type,
                f"{self.instance_name}.{self.service_type}",
                addresses=[socket.inet_aton("127.0.0.1")],
                port=self.port,
                properties={"version": "1.0.0"}
            )
            self.zeroconf.register_service(info)
            listener = NeDotifyListener(self)
            self.browser = ServiceBrowser(self.zeroconf, self.service_type, listener)
            self._is_running = True
            logger.info(f"P2P Service started for instance: {self.instance_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to start P2P service: {e}")
            return False

    def stop(self):
        if not self._is_running:
            return
        try:
            if self.zeroconf:
                self.zeroconf.unregister_all_services()
                self.zeroconf.close()
            self._is_running = False
            logger.info("P2P Service stopped.")
        except Exception as e:
            logger.error(f"Error stopping P2P service: {e}")

    def get_peers(self):
        return list(self.discovered_peers.values())

    def _find_free_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('', 0))
        port = s.getsockname()[1]
        s.close()
        return port
