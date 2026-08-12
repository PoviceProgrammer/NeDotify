import logging
import socket
import threading
import time
import urllib.request

logger = logging.getLogger("NeDotify.NetworkSentinel")





class NetworkStatus:
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    CAPTIVE_PORTAL = "captive_portal"







class NetworkSentinelService:
    """
Monitors the network connection using multi-level checks (DNS + HTTP).







Emits events when network state changes.
"""
    
    def __init__(self, app_core):
        self.app_core = app_core
        self.current_status = NetworkStatus.UNKNOWN
        self.is_running = False
        self._thread = None






        self._consecutive_fails = 0
        self._consecutive_successes = 0

    def start(self):
        if self.is_running:
            return


















        self.is_running = True







        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,







            name="NetworkSentinel",
        )
        self._thread.start()

    def stop(self):
        self.is_running = False

    def _check_dns(self):
        try:
            socket.gethostbyname("dns.google")
            return True
        except socket.error:











            try:
                socket.gethostbyname("one.one.one.one")
                return True
            except socket.error:
                return False

    def _check_http(self):
        try:
            req = urllib.request.Request(
                "http://connectivitycheck.gstatic.com/generate_204",
                method="GET",
            )















            with urllib.request.urlopen(req, timeout=2.0) as response:
                if response.status == 204:
                    return NetworkStatus.ONLINE
                return NetworkStatus.CAPTIVE_PORTAL
        except Exception:
            return NetworkStatus.OFFLINE

    def _determine_status(self):
        dns_ok = self._check_dns()
        if not dns_ok:
            return NetworkStatus.OFFLINE
        http_status = self._check_http()





        if http_status == NetworkStatus.OFFLINE:
            return NetworkStatus.DEGRADED
        return http_status

    def _monitor_loop(self):
        initial_status = self._determine_status()
        self._update_status(initial_status)

        while self.is_running:
            if self.current_status == NetworkStatus.ONLINE:
                time.sleep(20)
            elif self.current_status in (NetworkStatus.OFFLINE, NetworkStatus.DEGRADED, NetworkStatus.CAPTIVE_PORTAL):
                time.sleep(3)
            else:
                time.sleep(5)

            new_status = self._determine_status()
            if new_status != self.current_status:
                if new_status in (NetworkStatus.OFFLINE, NetworkStatus.DEGRADED, NetworkStatus.CAPTIVE_PORTAL):
                    self._consecutive_fails += 1
                    self._consecutive_successes = 0
                else:
                    self._consecutive_successes += 1
                    self._consecutive_fails = 0

                if self._consecutive_fails >= 2 or self._consecutive_successes >= 2:
                    self._update_status(new_status)
                    self._consecutive_fails = 0
                    self._consecutive_successes = 0
            else:
                self._consecutive_fails = 0
                self._consecutive_successes = 0

    def _update_status(self, new_status):
        self.current_status = new_status
        logger.info(f"Network status changed to: {new_status}")
        if hasattr(self.app_core, "api"):
            payload = {
                "online": new_status == NetworkStatus.ONLINE,
                "status": new_status,
                "checked_at": time.time(),
            }
            if hasattr(self.app_core.api, "emit_event"):
                self.app_core.api.emit_event("network_status", payload)
            elif hasattr(self.app_core.api, "_emit"):
                self.app_core.api._emit("network_status", payload)
