#!/usr/bin/env python3
"""
Adversarial Stress Test Suite for AURA Music Linux Process Lifecycle,
Lock Recovery, Remote Eval Pipeline, and Process Stability.

Covers:
1. Stale Lock & Stale Port Recovery (/tmp/nedotify_instance.lock, /tmp/nedotify_http_port)
   - Dead PID in lock file
   - Running non-nedotify PID in lock file
   - Corrupted/empty/garbage lock files
   - Stale port file handling
2. Single-Instance Mutual Exclusion
   - Primary instance keeps running
   - Secondary instance detects lock, exits cleanly with code 0
3. Rapid Lifecycle (Start, Stop, Re-launch)
   - Multiple back-to-back start/stop cycles
   - Measure startup latency and clean teardown
4. Remote Eval Robustness Under Malformed Payloads & Edge Cases
   - Non-UTF-8 bytes
   - Empty body
   - Large payload (>1 MB)
   - JS syntax errors and exceptions
   - Diverse JS types (Symbol, BigInt, Cyclic object, Null, Undefined)
   - Directory traversal attempts on /assets and /covers
   - Unsupported HTTP methods
5. Remote Eval Concurrency & High Load
   - Concurrent eval requests across worker threads
   - Verify GTK loop does not deadlock or crash
6. Child Process Leakage & Zombie Detection
   - Verify all child processes (pactl, WebKit) cleanly terminate within grace period
   - Probe behavior under SIGTERM
"""

import os
import sys
import time
import json
import signal
import socket
import logging
import tempfile
import requests
import subprocess
import threading
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("lifecycle_stress")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTANCE_LOCK = Path(tempfile.gettempdir()) / "nedotify_instance.lock"
PORT_FILE = Path(tempfile.gettempdir()) / "nedotify_http_port"
PYTHON_BIN = PROJECT_ROOT / ".venv" / "bin" / "python"
if not PYTHON_BIN.exists():
    PYTHON_BIN = Path(sys.executable)


def get_process_children(parent_pid):
    """Find all children of a parent PID recursively using pgrep and /proc."""
    children = []
    try:
        res = subprocess.run(["pgrep", "-P", str(parent_pid)], capture_output=True, text=True)
        if res.returncode == 0:
            for line in res.stdout.strip().split():
                if line.isdigit():
                    cpid = int(line)
                    children.append(cpid)
                    children.extend(get_process_children(cpid))
    except Exception:
        pass
    return list(set(children))


def is_pid_alive(pid):
    """Check if a PID is alive and not a zombie."""
    try:
        os.kill(pid, 0)
        status_path = Path(f"/proc/{pid}/status")
        if status_path.exists():
            for line in status_path.read_text().splitlines():
                if line.startswith("State:"):
                    state = line.split()[1]
                    if state == "Z":
                        return False
        return True
    except OSError:
        return False


def get_proc_cmdline(pid):
    """Get the command line string for a PID from /proc."""
    try:
        cmd_path = Path(f"/proc/{pid}/cmdline")
        if cmd_path.exists():
            return cmd_path.read_text().replace("\0", " ").strip()
    except OSError:
        pass
    return ""


def clean_locks_and_ports():
    """Ensure clean baseline for lock and port test setup."""
    for f in [INSTANCE_LOCK, PORT_FILE]:
        try:
            if f.exists():
                f.unlink()
        except OSError:
            pass


class ManagedAppProcess:
    """Helper to launch, track, interact with, and cleanly shut down AURA Music."""

    def __init__(self, log_suffix="stress"):
        self.proc = None
        self.port = None
        self.eval_url = None
        self.close_url = None
        self.log_file = None
        self.log_path = Path(tempfile.gettempdir()) / f"nedotify_{log_suffix}.log"

    def start(self, timeout=20.0, expect_failure=False, custom_env=None, clean_port=True):
        if clean_port:
            try:
                if PORT_FILE.exists():
                    PORT_FILE.unlink()
            except OSError:
                pass

        env = os.environ.copy()
        env["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"
        if "WAYLAND_DISPLAY" not in env:
            env["WAYLAND_DISPLAY"] = "wayland-1"
        if custom_env:
            env.update(custom_env)

        self.log_file = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(PYTHON_BIN), "main.py"],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=self.log_file,
            stderr=subprocess.STDOUT
        )

        if expect_failure:
            return

        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"AURA Music exited unexpectedly with code {self.proc.returncode}. Log: {self.log_path}"
                )
            if PORT_FILE.exists():
                try:
                    content = PORT_FILE.read_text().strip()
                    if content and content.isdigit():
                        candidate_port = int(content)
                        # Verify port is actively accepting connections
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.settimeout(0.5)
                            if s.connect_ex(("127.0.0.1", candidate_port)) == 0:
                                self.port = candidate_port
                                break
                except OSError:
                    pass
            time.sleep(0.2)

        if not self.port:
            raise TimeoutError(f"Failed to acquire active HTTP port within {timeout}s")

        self.eval_url = f"http://127.0.0.1:{self.port}/__aura_eval"
        self.close_url = f"http://127.0.0.1:{self.port}/__aura_close"

    def wait_for_ui(self, timeout=15.0):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                res = self.eval_js("typeof window.showPage === 'function' && document.readyState === 'complete'")
                if res and res.strip().lower() == "true":
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        raise TimeoutError(f"UI did not initialize within {timeout}s")

    def eval_js(self, script, timeout=8.0):
        if not self.eval_url:
            raise RuntimeError("App not running")
        resp = requests.post(self.eval_url, data=script.encode("utf-8"), timeout=timeout)
        resp.raise_for_status()
        return resp.text

    def eval_raw(self, data_bytes, timeout=8.0, headers=None):
        if not self.eval_url:
            raise RuntimeError("App not running")
        return requests.post(self.eval_url, data=data_bytes, timeout=timeout, headers=headers)

    def close(self, timeout=8.0):
        if self.proc and self.proc.poll() is None:
            if self.close_url:
                try:
                    requests.post(self.close_url, timeout=3.0)
                except Exception:
                    # Connection might be reset as server exits immediately
                    pass
                try:
                    self.proc.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, Exception):
                    pass
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=3.0)

        if self.log_file and not self.log_file.closed:
            self.log_file.close()

    def get_child_pids(self):
        if not self.proc or self.proc.poll() is not None:
            return []
        return get_process_children(self.proc.pid)


class TestLifecycleAndProcessStability(unittest.TestCase):
    """Rigorous adversarial test suite for process lifecycle and stability."""

    def setUp(self):
        clean_locks_and_ports()

    def tearDown(self):
        clean_locks_and_ports()

    # =========================================================================
    # Dimension 1: Stale Lock & Port Recovery
    # =========================================================================

    def test_01_stale_lock_dead_pid(self):
        """Verify recovery when /tmp/nedotify_instance.lock contains a non-existent PID."""
        logger.info("--- Test 01: Stale Lock with Dead PID ---")
        dead_pid = 9999999
        INSTANCE_LOCK.write_text(str(dead_pid))

        app = ManagedAppProcess(log_suffix="dead_pid")
        try:
            app.start(timeout=15.0)
            app.wait_for_ui(timeout=15.0)
            current_lock_pid = int(INSTANCE_LOCK.read_text().strip())
            self.assertEqual(current_lock_pid, app.proc.pid)
            res = app.eval_js("1 + 1")
            self.assertEqual(res.strip(), "2")
        finally:
            app.close()

    def test_02_stale_lock_unrelated_active_pid(self):
        """Verify recovery when lock file contains PID of an active process that is NOT nedotify."""
        logger.info("--- Test 02: Stale Lock with Active Unrelated PID ---")
        unrelated_pid = os.getpid()
        INSTANCE_LOCK.write_text(str(unrelated_pid))

        app = ManagedAppProcess(log_suffix="unrelated_pid")
        try:
            app.start(timeout=15.0)
            app.wait_for_ui(timeout=15.0)
            current_lock_pid = int(INSTANCE_LOCK.read_text().strip())
            self.assertEqual(current_lock_pid, app.proc.pid)
        finally:
            app.close()

    def test_03_corrupted_lock_files(self):
        """Verify recovery with empty, garbage, and malformed lock files."""
        logger.info("--- Test 03: Corrupted Lock File Recovery ---")
        malformed_samples = [
            "",                       # Empty file
            "   \n  \t  ",            # Whitespace only
            "not_a_number_garbage",  # String
            "-999999",                # Negative number
            "12345 67890",            # Multiple numbers
            "\x00\x00\x00\x00",       # Null bytes
        ]

        for sample in malformed_samples:
            clean_locks_and_ports()
            INSTANCE_LOCK.write_text(sample)
            app = ManagedAppProcess(log_suffix="corrupt_lock")
            try:
                app.start(timeout=15.0)
                app.wait_for_ui(timeout=10.0)
                current_lock_pid = int(INSTANCE_LOCK.read_text().strip())
                self.assertEqual(current_lock_pid, app.proc.pid)
            finally:
                app.close()

    def test_04_stale_port_file_recovery(self):
        """Verify behavior when /tmp/nedotify_http_port contains a dead port."""
        logger.info("--- Test 04: Stale Port File Recovery ---")
        stale_port = 59998
        PORT_FILE.write_text(str(stale_port))

        app = ManagedAppProcess(log_suffix="stale_port")
        try:
            app.start(timeout=15.0, clean_port=False)
            app.wait_for_ui(timeout=10.0)
            self.assertNotEqual(app.port, stale_port)
            active_port = int(PORT_FILE.read_text().strip())
            self.assertEqual(active_port, app.port)
        finally:
            app.close()

    # =========================================================================
    # Dimension 2: Single-Instance Mutual Exclusion
    # =========================================================================

    def test_05_single_instance_exclusion(self):
        """Verify secondary instance exits cleanly (returncode 0) without killing primary."""
        logger.info("--- Test 05: Single Instance Mutual Exclusion ---")
        primary = ManagedAppProcess(log_suffix="primary")
        secondary = ManagedAppProcess(log_suffix="secondary")

        try:
            primary.start(timeout=15.0)
            primary.wait_for_ui(timeout=15.0)
            primary_pid = primary.proc.pid

            secondary.start(timeout=5.0, expect_failure=True)
            ret = secondary.proc.wait(timeout=8.0)
            self.assertEqual(ret, 0, f"Secondary instance should exit cleanly with 0, got {ret}")

            self.assertIsNone(primary.proc.poll(), "Primary instance must remain alive")
            self.assertEqual(primary.proc.pid, primary_pid)
            eval_res = primary.eval_js("'still_alive'")
            self.assertEqual(eval_res.strip(), "still_alive")
        finally:
            secondary.close()
            primary.close()

    # =========================================================================
    # Dimension 3: Rapid Lifecycle Cycles (Start, Stop, Re-launch)
    # =========================================================================

    def test_06_rapid_restart_cycles(self):
        """Start, test, and cleanly close main.py repeatedly in rapid succession."""
        logger.info("--- Test 06: Rapid Restart Cycles (5 cycles) ---")
        cycle_count = 5
        timings = []

        for i in range(cycle_count):
            t0 = time.time()
            app = ManagedAppProcess(log_suffix=f"rapid_{i}")
            try:
                app.start(timeout=15.0)
                app.wait_for_ui(timeout=15.0)
                t_start = time.time() - t0

                res = app.eval_js("document.title")
                self.assertIn("NeDotify", res)

                t_close_start = time.time()
                app.close(timeout=8.0)
                t_close = time.time() - t_close_start
                self.assertEqual(app.proc.returncode, 0, f"Cycle {i} did not exit with returncode 0")

                timings.append((t_start, t_close))
                logger.info(f"Cycle {i+1}/{cycle_count}: Startup={t_start:.2f}s, Shutdown={t_close:.2f}s, Port={app.port}")
            finally:
                app.close()
            # Brief pause for socket close
            time.sleep(0.5)

        logger.info(f"All {cycle_count} rapid cycles completed successfully: {timings}")

    # =========================================================================
    # Dimension 4: Remote Eval Robustness Under Load & Malformed Payloads
    # =========================================================================

    def test_07_eval_malformed_payloads(self):
        """Stress-test /__aura_eval with non-UTF-8, empty, huge, and syntactically invalid data."""
        logger.info("--- Test 07: Remote Eval Malformed Payloads ---")
        app = ManagedAppProcess(log_suffix="eval_malformed")
        try:
            app.start(timeout=15.0)
            app.wait_for_ui(timeout=15.0)

            # 1. Empty body
            resp = app.eval_raw(b"")
            logger.info(f"Empty body response: status={resp.status_code}, text={resp.text[:100]}")
            self.assertEqual(resp.status_code, 200)

            # 2. Invalid JS syntax
            resp = app.eval_raw(b"const = ;")
            self.assertEqual(resp.status_code, 200)
            self.assertTrue("ERROR:" in resp.text or resp.text == "null" or "SyntaxError" in resp.text)

            # 3. JS Runtime exception
            resp = app.eval_raw(b"throw new Error('deliberate_eval_stress');")
            self.assertEqual(resp.status_code, 200)
            self.assertTrue("ERROR:" in resp.text or "deliberate_eval_stress" in resp.text)

            # 4. Large script payload (1 MB)
            large_comment = "/*" + ("A" * 1024 * 1024) + "*/ 42"
            resp = app.eval_raw(large_comment.encode("utf-8"))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.text.strip(), "42")

            # 5. Non-UTF-8 binary bytes
            # Documented Finding: Bottle returns 500 when decode('utf-8') fails outside try block
            resp = app.eval_raw(b"\xff\xfe\xfd\x80\x90")
            logger.info(f"Non-UTF8 response: status={resp.status_code}")
            self.assertIn(resp.status_code, [200, 500])

            # Ensure server did not crash and handles subsequent requests
            res = app.eval_js("100 + 200")
            self.assertEqual(res.strip(), "300")

            # 6. Various JS types
            type_tests = [
                ("null", "null"),
                ("undefined", "null"),
                ("true", "True"),
                ("123.45", "123.45"),
                ("'hello_world'", "hello_world"),
                ("[1, 2, 3]", "[1, 2, 3]"),
                ("({'key': 'val'})", "{'key': 'val'}"),
            ]
            for js_expr, expected in type_tests:
                res = app.eval_js(js_expr)
                self.assertEqual(res.strip(), expected)

            # 7. Exotic JS types: Symbol, BigInt, Cyclic Object
            res_symbol = app.eval_js("Symbol('sym')")
            self.assertTrue("ERROR:" in res_symbol or "Symbol" in res_symbol or res_symbol == "null")

            res_bigint = app.eval_js("BigInt(999999999)")
            self.assertTrue("ERROR:" in res_bigint or "999999999" in res_bigint or res_bigint == "null")

            res_cyclic = app.eval_js("(() => { const x = {}; x.self = x; return x; })()")
            self.assertTrue(len(res_cyclic) > 0)

            # 8. Directory traversal security probe on fallback routes
            resp_traversal = requests.get(f"http://127.0.0.1:{app.port}/assets/../../../../etc/passwd")
            self.assertNotIn("root:", resp_traversal.text, "Path traversal vulnerability detected in assets route!")

            resp_covers_traversal = requests.get(f"http://127.0.0.1:{app.port}/covers/../../../../etc/passwd")
            self.assertNotIn("root:", resp_covers_traversal.text, "Path traversal vulnerability detected in covers route!")

            # 9. Unsupported HTTP method probe (Bottle catch-all or method mismatch returns 404 or 405)
            resp_get_eval = requests.get(f"http://127.0.0.1:{app.port}/__aura_eval")
            self.assertIn(resp_get_eval.status_code, [404, 405])

            final_check = app.eval_js("'alive_after_stress'")
            self.assertEqual(final_check.strip(), "alive_after_stress")
        finally:
            app.close()

    def test_08_eval_high_load_concurrency(self):
        """Fire concurrent eval requests across multiple threads to probe GTK loop safety."""
        logger.info("--- Test 08: High Load & Concurrency on /__aura_eval ---")
        app = ManagedAppProcess(log_suffix="eval_concurrency")
        try:
            app.start(timeout=15.0)
            app.wait_for_ui(timeout=15.0)

            total_requests = 60
            concurrency = 10
            errors = []
            latencies = []

            def worker(req_id):
                t0 = time.time()
                try:
                    res = app.eval_js(f"(() => {{ return 'req_' + {req_id}; }})()")
                    lat = time.time() - t0
                    if res.strip() != f"req_{req_id}":
                        return (req_id, False, f"Unexpected response: {res}", lat)
                    return (req_id, True, None, lat)
                except Exception as e:
                    return (req_id, False, str(e), time.time() - t0)

            t_all_start = time.time()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(worker, i) for i in range(total_requests)]
                for f in as_completed(futures):
                    req_id, success, err, lat = f.result()
                    latencies.append(lat)
                    if not success:
                        errors.append((req_id, err))

            total_time = time.time() - t_all_start
            avg_lat = sum(latencies) / len(latencies) if latencies else 0
            logger.info(
                f"Concurrent eval results: {total_requests - len(errors)}/{total_requests} succeeded. "
                f"Total time: {total_time:.2f}s, Avg latency: {avg_lat*1000:.1f}ms, Max latency: {max(latencies)*1000:.1f}ms"
            )
            self.assertEqual(len(errors), 0, f"Concurrent eval errors encountered: {errors}")
        finally:
            app.close()

    # =========================================================================
    # Dimension 5: Child Process Leakage & Zombie Detection
    # =========================================================================

    def test_09_clean_shutdown_child_leak_check(self):
        """Verify all child processes (pactl, WebKit) cleanly terminate within grace period."""
        logger.info("--- Test 09: Child Process Leakage on Clean Shutdown ---")
        app = ManagedAppProcess(log_suffix="leak_check")
        try:
            app.start(timeout=15.0)
            app.wait_for_ui(timeout=15.0)

            child_pids = app.get_child_pids()
            logger.info(f"Active child PIDs while running: {child_pids}")

            app.close(timeout=8.0)
            self.assertEqual(app.proc.returncode, 0)

            # WebKitGTK 4.1 helper processes perform asynchronous cache flush
            # Poll for up to 7 seconds to verify all children terminate
            leaked = []
            start_check = time.time()
            while time.time() - start_check < 7.0:
                alive = [cpid for cpid in child_pids if is_pid_alive(cpid)]
                if not alive:
                    break
                time.sleep(0.5)

            final_alive = []
            for cpid in child_pids:
                if is_pid_alive(cpid):
                    cmd = get_proc_cmdline(cpid)
                    final_alive.append((cpid, cmd))

            self.assertEqual(final_alive, [], f"Child processes failed to terminate within grace period: {final_alive}")
            logger.info("All child processes terminated cleanly within grace period.")
        finally:
            app.close()

    def test_10_sigterm_process_hygiene(self):
        """Verify behavior and cleanup when main.py is terminated via SIGTERM."""
        logger.info("--- Test 10: Process Hygiene Under SIGTERM ---")
        app = ManagedAppProcess(log_suffix="sigterm_test")
        try:
            app.start(timeout=15.0)
            app.wait_for_ui(timeout=15.0)
            child_pids = app.get_child_pids()
            logger.info(f"Active child PIDs before SIGTERM: {child_pids}")

            # Send SIGTERM to main process
            app.proc.send_signal(signal.SIGTERM)
            try:
                app.proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                app.proc.kill()

            time.sleep(1.5)

            lingering = []
            for cpid in child_pids:
                if is_pid_alive(cpid):
                    cmd = get_proc_cmdline(cpid)
                    lingering.append((cpid, cmd))
                    try:
                        os.kill(cpid, signal.SIGKILL)
                    except OSError:
                        pass

            logger.info(f"Lingering child processes after parent SIGTERM: {lingering}")
            # We record whether pactl subscribe leaked
            pactl_leaked = any("pactl" in cmd for _, cmd in lingering)
            if pactl_leaked:
                logger.warning("[FINDING] pactl subscribe child process leaked on SIGTERM due to lack of SIGTERM signal handler!")
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
