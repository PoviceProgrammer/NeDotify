## AREA WN-26 — Zapret (network bypass) & Discord RPC — ROLE B

### 1. Scope reviewed

**Files opened (full read):**

- `services/zapret_service.py` — 1475 physical lines / 1328 non-empty, read 1‑1475 in four slices (module constants + validators L37‑305; `ZapretService` L307‑1475).
- `core/services/discord_rpc.py` — 183 physical / 161 non-empty, read 1‑183 in full.
- `core/api.py` — bridge surface for this area: L60‑67 (bridge-thread budget), L502‑503 (offline interception of `check_zapret_update`/`update_zapret`), L514‑520 (`set_window` → `_set_elevation_window`), L1205‑1240 (`_on_track_changed` → `update_presence`), L1365‑1396 (`report_state` → `update_presence`/`clear_presence`), L3796‑3874 (`toggle_zapret`, `toggle_discord_rpc`, `get_discord_rpc_status`, `get_zapret_status`, `check_zapret_update`, `update_zapret`).
- `core/app.py` — L100‑186 (construction: `ZapretService`, `DiscordRPCService`, `discord_rpc.start()`, `zapret.auto_update_in_background()`), L236‑294 (`start_zapret_if_enabled`), L508‑586 (`cleanup()`).
- `main.py` — L505‑584 (watchdog restart path + post-`webview.start()` cleanup).
- `tests/test_zapret_binary_integrity.py` (375 L) and `tests/test_zapret_uac_window.py` (97 L) — read in full.
- `ui/web_new_v2/js/settings.js` L1849‑2019 (Zapret panel), `ui/web_new_v2/index.html` L1885‑1929 (Zapret settings markup), `ui/web_new_v2/js/player.js` L543/615/623/850/1671 (state/position reporting that drives Discord RPC).
- `docs/AUDIT.md`, `docs/REMEDIATION_TRACKER.md`, `docs/perf/prof_python_startup.md` (zapret rows), `git show a328835` ("scope the bypass" commit).

**Callees traced into other areas (not re-reported here):**

- `core/api.py::toggle_zapret / update_zapret / get_zapret_status` — bridge methods; the caller-side gaps (no status polling in the UI, `binary_path`/`custom_args` persisted with no UI) belong to **WN-10** (bridge) and **WN-30** (settings UI).
- `core/app.py::start_zapret_if_enabled` — autostart thread; the caller-side gap (a 40 s download inside `start()` can launch an elevated `winws.exe` after `cleanup()` returned — already noted in `docs/audits/_FINDINGS_SO_FAR.md:82`) belongs to **WN-02**.
- `core/settings.py::get` — DB-backed settings read from inside the services; **WN-14**.
- `core/proxy.py` — the `YOUTUBE_HOSTS` list the zapret host scope is said to mirror; **WN-11**.

**External facts verified (not guessed):**

- Upstream zapret v72.13 option semantics: `--hostlist-domains=<domain_list>` is *"comma separated fixed domain list"* (`https://raw.githubusercontent.com/bol-van/zapret/v72.13/docs/readme.en.md` L238/L961) → the app's scoped presets are **correct** upstream usage.
- The pinned hash is **correct**: GitHub's release API reports `zapret-v72.13.zip` digest `sha256:c493e33a0dc4eba23a8686efdaba55f59755ad6ade3564aebd9d13f4c65e2e0c`, identical to `ZAPRET_ZIP_SHA256`. Verified by downloading the archive (7 959 200 bytes, digest matches) and re-running `_verify_zip_sha256`.
- The real archive contents (what lands on disk): `winws.exe` (223 232 B), `WinDivert.dll` (47 616 B), `WinDivert64.sys` (94 144 B), `cygwin1.dll` (2 954 293 B), `killall.exe`, `ip2net.exe`, `mdig.exe` — all selected by the `"x86_64" in name` filter and extracted **flat** into `~/.nedotify/zapret/`.
- `cmd.exe` quote handling of the elevated command line was tested with `CreateProcessW` on the exact raw string the app builds: the `> "log" 2>&1` redirect works as intended (both stdout and stderr land in `zapret.log`). **No finding here.**
- WMIC is **absent** on this machine (`Get-Command wmic` → not found; Windows NT 10.0.26200) → the primary PID-discovery path is dead on current Windows.

### 2. Findings

#### F-WN-26-1  [P0] — The "update" path installs an **unverified** archive and later executes it elevated

- **File:** `services/zapret_service.py:976-981` (root cause), `:44-51` (helper), `:927-939` (API-supplied URL), `:39-41` (docstring claim), `:895-898` (the only path that really verifies)
- **Confirmed:** yes
- **Description:** The pinned SHA-256 is only applied when the download URL is byte-identical to the hard-coded one. The GitHub API supplies `browser_download_url` for the *latest* release; the moment upstream publishes a new tag the URL differs from `ZAPRET_ZIP_URL`, `expected_hash` becomes `""`, and `_verify_zip_sha256()` **returns True for an empty expected hash** — i.e. "not verified" is treated as "verified". The archive is then extracted into `~/.nedotify/zapret/` and, on the next start, launched **as Administrator** via `ShellExecuteW("runas")`.
- **Cause:** "no pin ⇒ accept" is encoded in the verifier's return value (`return True  # No pinned hash — verification not possible`) and the caller only supplies a pin for one exact URL.
- **Trigger conditions:** the user clicks "Обновить Zapret" (or autoupdate is on) after zapret publishes a release newer than the pinned `v72.13`. As of this review the GitHub "latest" tag still *is* `v72.13` (the pinned one, so the check still passes today) — the defect arms itself at the next upstream release, i.e. exactly the case the update button exists for. A compromised release asset, a hijacked upstream account, or a TLS-level attack on the download at that moment yields arbitrary code executed with admin rights.
- **User impact:** silent remote code execution as Administrator on the user's machine.
- **Evidence:**
  ```python
  41: ZAPRET_ZIP_SHA256 = "c493e33a0dc4eba23a8686efdaba55f59755ad6ade3564aebd9d13f4c65e2e0c"
  48:     if not expected_sha256:
  49:         return True  # No pinned hash — verification not possible
  ...
  976:                 # Verify integrity: pinned hash exists only for the bundled release.
  977:                 expected_hash = ZAPRET_ZIP_SHA256 if zip_url == ZAPRET_ZIP_URL else ""
  978:                 if not _verify_zip_sha256(zip_bytes, expected_hash):
  ```
- **Reproduction / verification:** probe `wn26_probe.py` → `_verify_zip_sha256(b"garbage", "")` → `True`; `_verify_zip_sha256(b"garbage")` → `False`. Code path: `update_zapret()` → `get_latest_release_info()` returns `("v73.0", "https://github.com/bol-van/zapret/releases/download/v73.0/zapret-v73.0.zip")` → `expected_hash == ""` → verification skipped → `_extract_zip()` writes the payload → `start()` → `_launch_elevated()`.
- **Suggested fix:** keep a per-version hash table in the source and refuse to install a version with no pinned digest; make the verifier fail closed (`return False` when no pin is supplied); never derive the download URL from the API response — build it from the pinned tag.
- **Fix side effects:** a new zapret release can no longer be installed until a hash is added to the source (intended); users on autoupdate keep the old binary until the app is updated.
- **Discovered by:** B

#### F-WN-26-2  [P1] — The elevated launch runs an executable **and its DLLs** from a user-writable directory (local privilege escalation)

- **File:** `services/zapret_service.py:320` (install dir), `:839-866` (extraction), `:1270-1285` (elevated launch), `:126-174` (PE shape check)
- **Confirmed:** yes
- **Description:** The bundle is extracted flat into `C:\Users\<user>\.nedotify\zapret\` — a directory with the user's ACL — and the elevated command is `cmd.exe /c ""C:\Users\<user>\.nedotify\zapret\winws.exe" …"` executed through `ShellExecuteW(..., "runas", ...)`. The same directory also holds `WinDivert.dll` and `cygwin1.dll`, which the elevated `winws.exe` loads from its own directory, and `WinDivert64.sys`, the kernel driver it installs. Any process running as the user can replace `winws.exe` or `WinDivert.dll` and the next launch of the app executes the replacement **as Administrator**.
- **Cause:** the trust boundary is placed on the *shape* of the file (`is_valid_windows_binary` = MZ + `PE\0\0` + size floor) instead of on the *integrity of the location*. The launcher validates the path (`validate_zapret_binary`) but the path it validates is itself user-writable.
- **Trigger conditions:** any user-level code on the machine (a malicious installer, a cracked tool, an XSS in any app running as the user) writes `winws.exe`/`WinDivert.dll` into `~/.nedotify/zapret/`. The app then launches it elevated — the window is indefinite, not a millisecond TOCTOU: the planted file survives between app runs and is picked up by `find_binary()` on the next start, and `update_zapret()` even re-launches it after an update.
- **User impact:** privilege escalation from "user" to "Administrator" without any UAC prompt being attributable to the user's own action (the UAC dialog says "cmd.exe"/"winws.exe", which reads as the app's own helper).
- **Evidence:**
  ```python
  320:         self.app_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "zapret")
  ...
  857:                     target_path = os.path.join(self.app_dir, filename)
  863:                     tmp_path = target_path + ".part"
  864:                     with open(tmp_path, "wb") as f:
  865:                         f.write(z.read(name))
  866:                     os.replace(tmp_path, target_path)
  ...
  1283:         cmd_params = f'/c ""{exe}" {params} > "{self.log_file}" 2>&1"'
  1285:         ret = self._shell_execute_elevated(comspec, cmd_params, os.path.dirname(exe))
  ```
  Real extracted set (verified against the official v72.13 archive): `winws.exe, WinDivert.dll, WinDivert64.sys, cygwin1.dll, killall.exe, ip2net.exe, mdig.exe` — all in the same user-writable folder.
- **Reproduction / verification:** (1) place any PE-shaped file as `~/.nedotify/zapret/winws.exe` (or overwrite `WinDivert.dll`); (2) enable Zapret in the UI; (3) `_launch_elevated` → `ShellExecuteW("runas", cmd.exe, '/c ""…\zapret\winws.exe" …"')` → the substitute runs as Administrator. `validate_zapret_binary` (L222‑262) accepts it because it only checks drive letter, root containment, file name and PE shape.
- **Suggested fix:** install into a directory created and owned by the elevated process (e.g. `%ProgramData%\NeDotify\zapret` with an admin-only DACL) and keep the user-writable cache out of the launch path; re-verify a pinned SHA-256 of `winws.exe`/`WinDivert.dll`/`WinDivert64.sys` immediately before each launch; hold the file open (or re-hash after opening) to shrink the swap window.
- **Fix side effects:** the first install then needs its own elevation (a UAC prompt at first use); a per-user portable mode would have to be dropped or explicitly marked as unsafe.
- **Discovered by:** B

#### F-WN-26-3  [P1] — Self-deadlock on the non-reentrant `_update_lock`: the Zapret update can hang forever

- **File:** `services/zapret_service.py:317` (`self._update_lock = threading.Lock()`), `:960` (`with self._update_lock:` in `update_zapret`), `:1008` (`self.start(...)` called **inside** that `with`), `:1099` (`download_binaries()` inside `start`), `:890` (`with self._update_lock:` in `download_binaries`)
- **Confirmed:** yes (reproduced)
- **Description:** `update_zapret()` holds `_update_lock` for its whole body and calls `start()`; `start()` may call `download_binaries()`, which tries to take the same **non-reentrant** `threading.Lock` → the thread blocks forever and the lock is never released, so every later `download_binaries()`/`update_zapret()` in the session blocks too.
- **Cause:** a plain `Lock` used as a mutual-exclusion token across a call graph that is not lock-free (re-entrant acquisition on the same thread).
- **Trigger conditions:** (a) the bypass is running, (b) the user clicks "Обновить Zapret", (c) the freshly extracted `winws.exe` is not a valid PE → `start()` takes the "binary unusable → re-download" branch. Condition (c) is much more likely now that F‑WΝ‑26‑1 lets an unverified archive through.
- **User impact:** the "Обновить" button spins forever (the JS promise never resolves, the button stays disabled), the bridge thread is stuck, and Zapret can no longer be installed or updated until the app is restarted.
- **Evidence:**
  ```python
  317:         self._update_lock = threading.Lock()
  ...
  960:         with self._update_lock:
  ...
  1008:                     self.start(mode=mode, custom_args=custom_args, binary_path=bin_path)
  ...
  1099:                 ok, dl_msg = self.download_binaries()
  ...
  890:         with self._update_lock:
  ```
- **Reproduction / verification:** probe `wn26_probe3.py` (in `%TEMP%`, repo untouched): `is_running` forced True, `_extract_zip` forced to write a header-only stub → result: `update_zapret returned within 12 s? False`, `_update_lock locked? True`, with the stuck stack:
  ```
  zapret_service.py:1008 in update_zapret -> self.start(...)
  zapret_service.py:1099 in start        -> self.download_binaries()
  zapret_service.py:890  in download_binaries -> with self._update_lock:
  ```
- **Suggested fix:** use `threading.RLock()` for `_update_lock`, or split `download_binaries()` into a public wrapper (takes the lock) and a `_download_binaries_locked()` used by the nested call.
- **Fix side effects:** an RLock no longer prevents a second *thread* from downloading concurrently — keep the `_update_lock` scope or add a separate "download in progress" flag if that matters.
- **Discovered by:** B

#### F-WN-26-4  [P1] — The elevated `cmd.exe` is started without `/d` and with an environment-supplied path: two escalation primitives on the admin launch

- **File:** `services/zapret_service.py:1282-1285`, `:1243-1248` (`ShellExecuteW` with the `"runas"` verb)
- **Confirmed:** code facts confirmed; the escalation consequences are **hypothesis** (not reproduced on this machine — see "Reproduction")
- **Description:** The elevated process is `cmd.exe` launched with `ShellExecuteW(None, "runas", comspec, params, cwd, 0)`. Two problems: (a) `params` starts with `/c`, so the **elevated** command interpreter honours `HKCU\Software\Microsoft\Command Processor\AutoRun` — a value any user-level process can write, which then executes with administrator rights (MS KB310158 documents `/d` as the suppression switch); (b) `comspec = os.environ.get("COMSPEC", "cmd.exe")` falls back to the **bare name** `cmd.exe`, which `ShellExecuteW` resolves through the shell search order (the current directory is searched) — a `cmd.exe` planted in the working directory is then launched elevated. The working directory for the elevated launch is `os.path.dirname(exe)` = `~/.nedotify/zapret`, i.e. the user-writable folder of F‑WΝ‑26‑2.
- **Cause:** the launcher reuses the ordinary command interpreter for an elevated execution without hardening it (`/d`, absolute system path, no reliance on `PATH`/`COMSPEC` from an untrusted environment).
- **Trigger conditions:** any user-level write access to `HKCU\...\Command Processor\AutoRun` or to the working directory of the elevated launch.
- **User impact:** user-level code execution with administrator rights, using the app's UAC prompt as the trigger.
- **Evidence:**
  ```python
  1282:         comspec = os.environ.get("COMSPEC", "cmd.exe")
  1283:         cmd_params = f'/c ""{exe}" {params} > "{self.log_file}" 2>&1"'
  1285:         ret = self._shell_execute_elevated(comspec, cmd_params, os.path.dirname(exe))
  ...
  1248:                 return shell_execute(owner, "runas", exe, params, cwd, 0)
  ```
- **Reproduction / verification:** *Missing evidence:* an end-to-end AutoRun-based elevation was not attempted on this machine (it would install a kernel driver / modify the user's system — out of bounds for a review). What is verified: the command line built at `:1283` starts with `/c` and contains no `/d`; the `runas` verb is used at `:1248`; `COMSPEC` is read from the environment at `:1282` with a relative fallback. Confirming the escalation needs a throwaway VM: set `HKCU\Software\Microsoft\Command Processor\AutoRun=calc.exe`, enable Zapret, and observe whether the elevated `cmd.exe` runs it; and drop `cmd.exe` into the launch CWD to check the search-order resolution.
- **Suggested fix:** build the parameters as `/d /c "…"`; use the absolute `%SystemRoot%\System32\cmd.exe` (ignore `COMSPEC`); keep the launch CWD out of the user-writable bundle directory (see F‑WΝ‑26‑2).
- **Fix side effects:** `/d` also disables the user's own cmd AutoRun for this one invocation — irrelevant for a helper process.
- **Discovered by:** B

#### F-WN-26-5  [P2] — Stopping the bypass can raise an unsolicited UAC prompt during app shutdown, and `stop()` is unbounded

- **File:** `services/zapret_service.py:700-711` (elevated fallback kill), `:1376-1393` (`stop()` loop), `:1336-1407` (`stop()`), `core/app.py:553-554` (`cleanup` → `zapret.stop()`)
- **Confirmed:** yes (code path; the UAC prompt itself was not triggered on this machine)
- **Description:** The bypass normally runs **elevated** (WinDivert needs admin), so the plain `taskkill /FI "IMAGENAME eq winws*" /PID n` cannot kill it. `_kill_pid` then escalates: `ShellExecuteW(None, "runas", "taskkill.exe", '/F /FI "IMAGENAME eq winws*" /PID n', None, 0)` → a UAC prompt while the user is closing the app. If the prompt is declined, `stop()` returns "Не удалось остановить процесс Zapret" and the elevated helper keeps running. The same call chain runs `tasklist`/`wmic`/`powershell` scans (timeouts 3 s + 4 s + 6 s) plus 1.5 s + 3 s + 2 s of waits, with no overall deadline — `cleanup()` waits for it.
- **Cause:** the kill path assumes it can terminate an elevated process from an unelevated process and escalates on demand instead of the elevated side owning its own lifetime.
- **Trigger conditions:** the user quits the app (or toggles Zapret off) while the elevated `winws.exe` is running.
- **User impact:** an unexplained UAC dialog at exit; a long, apparently hung shutdown (up to ~15 s by the declared timeouts); a refused prompt leaves the DPI bypass active with no UI left to turn it off.
- **Evidence:**
  ```python
  700:                 # If still alive (e.g. elevated winws started under admin rights), try elevated taskkill
  702:                     import ctypes
  703:                     ret = ctypes.windll.shell32.ShellExecuteW(
  704:                         None, "runas", "taskkill.exe", f'/F /FI "IMAGENAME eq winws*" /PID {pid}', None, 0
  ```
- **Reproduction / verification:** start Zapret (elevated), then quit the app and watch for the UAC dialog; decline it and check that `winws.exe` is still running and that `~/.nedotify/zapret/run.pid` is preserved (the code deliberately keeps it, `:1383-1393`).
- **Suggested fix:** let the elevated side own the lifetime (the elevated `cmd.exe` can kill its child on exit, or the app can install the helper under a scheduled/service handle); bound `stop()` with a single deadline and report "still running" instead of blocking the shutdown.
- **Fix side effects:** without the elevated kill the app can no longer stop a helper it does not own → the helper needs a self-terminate mechanism, which adds a second moving part.
- **Discovered by:** B

#### F-WN-26-6  [P2] — The bypass survives an app crash; nothing restores the machine state

- **File:** `services/zapret_service.py` (whole module — no watchdog / no `atexit`), `main.py:573-580` (`cleanup()` only after `webview.start()` returns), `core/app.py:508-554`
- **Confirmed:** yes
- **Description:** `cleanup()` — the only thing that stops `winws.exe` — runs after the WebView loop returns. If the app is killed (Task Manager "End task", a hard crash, a power loss), the elevated `winws.exe`, the WinDivert kernel driver and the machine-wide WFP filters stay installed, with no UI to turn them off. The module does keep `~/.nedotify/zapret/run.pid` + `run.cmd`, and `is_running()` re-adopts that PID on the next launch (`_is_our_winws_process` checks the image name **and** the exe path, so PID reuse is not a false positive) — so re-adoption on the next start works, but only if the user starts the app again.
- **Cause:** the side effect lives in a separate, elevated, detached process whose lifetime is not tied to the app's; there is no job object, no `atexit`/`RegisterWaitForSingleObject`, and the helper itself is never asked to die with the parent.
- **Trigger conditions:** any abnormal termination of the app while the bypass is active.
- **User impact:** the machine keeps a network-filtering kernel driver and a DPI-desync filter after the app is gone; the user may attribute the resulting network behaviour to "the app is still running".
- **Evidence:** `core/app.py:553-554` (`_step("zapret.stop", self.zapret.stop)`) is the only stop site; `main.py:575` calls `app_core.cleanup()` only on the normal return path of `webview.start()`; `services/zapret_service.py` contains no watchdog, no `atexit` registration and no job-object handling.
- **Reproduction / verification:** enable Zapret, then end the app process from Task Manager (or `taskkill /F /PID <app>`); `tasklist | findstr winws` still shows the helper and `netstat`/`Get-NetAdapter` show the WinDivert filter still active until the helper is killed or the machine reboots.
- **Suggested fix:** launch the helper under a Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, or have the elevated helper watch its parent and exit with it; additionally ship a "repair" action that runs the bundled `killall.exe` to unload the driver.
- **Fix side effects:** a job object requires the helper to be created in a way that survives the elevation handoff (the current `cmd.exe /c` wrapper would have to change).
- **Discovered by:** B

#### F-WN-26-7  [P2] — Discord RPC: `stop()` does not stop an in-flight connect → a stale "now playing" presence can outlive the app

- **File:** `core/services/discord_rpc.py:68-85` (`_connect` thread), `:174-183` (`stop`), `core/app.py:549-550` (`cleanup` → `discord_rpc.stop`)
- **Confirmed:** yes (race by code reading)
- **Description:** `start()` spawns a daemon thread that does `self.rpc = Presence(...)`, `self.rpc.connect()`, `self.connected = True`. `stop()` closes and nulls `self.rpc` and clears `self.connected`, but it neither sets a "shutting down" flag nor joins the thread. If `_connect` is between `Presence()` and `connect()` when `stop()` runs, it completes afterwards and re-installs `self.rpc`/`self.connected = True` → a live Discord IPC connection and a presence payload that says the app is playing, after the app has decided to disconnect (i.e. while it is exiting).
- **Cause:** `stop()` and the connect thread share `self.rpc`/`self.connected` without a shutdown flag or a join; `self.connected = True` at `:72` is also written outside `self._lock` while every reader takes the lock.
- **Trigger conditions:** the app exits (or the user toggles Discord RPC off) within the connect window (Discord starting up at the same time as the app is the most likely case).
- **User impact:** Discord keeps showing "NeDotify — <track>" as active after the app has quit, until the IPC socket dies or Discord times it out; toggling the setting off appears not to work.
- **Evidence:**
  ```python
  68:         def _connect():
  69:             try:
  70:                 self.rpc = Presence(self.client_id)
  71:                 self.rpc.connect()
  72:                 self.connected = True
  ...
  85:         threading.Thread(target=_connect, daemon=True).start()
  ...
  174:     def stop(self):
  175:         """Disconnect Discord RPC."""
  176:         self.clear_presence()
  177:         if self.rpc:
  178:             try:
  179:                 self.rpc.close()
  182:             self.rpc = None
  183:             self.connected = False
  ```
- **Reproduction / verification:** start Discord and the app at the same time, or call `discord_rpc.start()` and `discord_rpc.stop()` back-to-back in a loop with a `time.sleep` between them; assert `service.connected is False` and `service.rpc is None` after `stop()` returns — the assertion fails intermittently. *(Not run in this session: it would require a live Discord client; the code path above is the evidence.)*
- **Suggested fix:** add a `_stopped` flag checked inside `_connect` before assigning `self.rpc`/`self.connected`, hold `self._lock` for the assignment, and join the connect thread in `stop()` (bounded).
- **Fix side effects:** joining adds up to the connect timeout to shutdown; bound it.
- **Discovered by:** B

#### F-WN-26-8  [P2] — Process discovery shells out to `tasklist` + (removed) `wmic` + PowerShell on every call

- **File:** `services/zapret_service.py:557-594` (`_scan_all_winws_pids`), `:596-663` (`_scan_pids_with`), `:756-778` (`is_running`), `:1336-1407` (`stop`), `:1063-1150` (`start`)
- **Confirmed:** yes (measured)
- **Description:** `is_running()` — called from `start()` (while holding `_lock`), `stop()`, `update_zapret()` and the status refresh — shells out to `tasklist`, then `wmic`, then PowerShell CIM. `wmic` **no longer exists** on current Windows (verified: `Get-Command wmic` → not found on build 26200), so the primary discovery path always fails and the PowerShell fallback (declared timeout 6 s) runs every time. Measured on this machine: `_scan_all_winws_pids()` = **912 ms**, `_scan_pids_with(sig)` = **670 ms** — every enable/disable cycle spawns several processes and takes seconds on a loaded machine.
- **Cause:** process enumeration is implemented by shelling out to three different command-line tools instead of using the Win32 API, and the fallback chain is not re-validated against current Windows versions.
- **Trigger conditions:** every toggle of the bypass, every `update_zapret`, every status refresh, and every `stop()` (which also runs the scan twice).
- **User impact:** the bridge call takes 1–3+ s (the UI button stays disabled meanwhile — the pywebview bridge serves the call on a bridge thread, `core/api.py:64`, so the window itself does not freeze); on a slow/loaded machine the declared 4 s + 6 s timeouts can make a toggle feel hung, and `cleanup()` inherits the same delay.
- **Evidence:**
  ```python
  562:         out = _check_output_text('tasklist /FO CSV /NH', timeout=3.0, shell=True)
  ...
  581:             ps_cmd = 'Get-Process -Name winws,zapret -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'
  ...
  608:         out = _check_output_text(
  609:             'wmic process where "name=\'winws.exe\'" get ProcessId,CommandLine /FORMAT:CSV',
  610:             timeout=4.0, shell=True
  ```
- **Reproduction / verification:** probe `wn26_perf.py` (this machine): `_scan_all_winws_pids (tasklist + powershell fallback): 912 ms`; `_scan_pids_with('--wf-tcp=80,443') (wmic + powershell fallback): 670 ms`. `Get-Command wmic` → not found.
- **Suggested fix:** enumerate processes with `CreateToolhelp32Snapshot` + `QueryFullProcessImageNameW` (the module already uses the latter), drop the WMIC path, and cache the scan result for a second or two.
- **Fix side effects:** the Win32 path must reproduce the current "is it *our* winws" semantics (image name + exe path under the app dir), which is already implemented in `_is_our_winws_process`.
- **Discovered by:** B

#### F-WN-26-9  [P2] — The download has no size limit and is fully buffered in memory

- **File:** `services/zapret_service.py:833-837` (`_download_zip`), `:888-913` (`download_binaries`), `:956-1013` (`update_zapret`)
- **Confirmed:** yes
- **Description:** `_download_zip()` does `resp.read()` with no `Content-Length` check and no streaming cap, so the whole archive is held in RAM and then again in a `BytesIO` inside `zipfile.ZipFile(io.BytesIO(zip_bytes))`. Combined with F‑WΝ‑26‑1 (the URL comes from the network, the size is not pinned) this is an unbounded memory allocation driven by a remote response.
- **Cause:** the downloader has no size budget and no streaming extraction.
- **Trigger conditions:** a hostile or broken endpoint answers with a multi-gigabyte body.
- **User impact:** the app (and the bridge thread performing the update) consumes all available memory and can be killed by the OOM killer / trigger the "app is not responding" state.
- **Evidence:**
  ```python
  833:     def _download_zip(self, url: str, timeout: float = 40.0) -> bytes:
  835:         req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
  836:         with urllib.request.urlopen(req, timeout=timeout) as resp:
  837:             return resp.read()
  ```
- **Reproduction / verification:** point `_download_zip` at an endpoint that streams a large body and observe the process RSS grow by the response size (no cap in the code path); the real archive is 7 959 200 bytes, so a legitimate download is unaffected.
- **Suggested fix:** cap the download (e.g. 64 MiB) while streaming, and extract member-by-member from the file instead of a `BytesIO` copy.
- **Fix side effects:** none for the current bundle size.
- **Discovered by:** B

#### F-WN-26-10  [P3] — The PE "machine type" gate is a no-op and contradicts its own docstring

- **File:** `services/zapret_service.py:126-174` (validator), `:171-174` (the gate), `:136-138` (the claim)
- **Confirmed:** yes
- **Description:** The validator documents three gates, the third being "Machine type — 0x8664 (x64) or a real nonzero stamp. zapret ships x64; an unmapped stamp means the header was fabricated rather than linked." The implementation is `return machine in (0, _PE_MACHINE_AMD64) or machine > 0` — true for **every** non-negative machine value, so the gate does not exist. The repository's own test acknowledges the behaviour but keeps the misleading name (`test_fabricated_machine_type_is_rejected` asserts the value is accepted).
- **Cause:** the permissive branch (`or machine > 0`) swallows the check the docstring describes.
- **Trigger conditions:** every validation.
- **User impact:** a fabricated PE header with a nonsense machine stamp is accepted; the real protection is the MZ/`PE\0\0`/size gate, so the practical impact is limited — but the documented contract is false and a future reader may rely on it.
- **Evidence:**
  ```python
  171:     machine = int.from_bytes(head[e_lfanew + 4:e_lfanew + 6], "little")
  172:     # 0x0000 shows up in images built without a machine stamp; accept anything
  173:     # that carries the NT signature rather than rejecting a working binary.
  174:     return machine in (0, _PE_MACHINE_AMD64) or machine > 0
  ```
- **Reproduction / verification:** `tests/test_zapret_binary_integrity.py:104-110` — a PE with `machine=0x1234` is asserted to be **valid**; the docstring at `:136-138` claims the opposite.
- **Suggested fix:** either implement the check (`machine == _PE_MACHINE_AMD64`) or delete the claim and the dead branch.
- **Fix side effects:** a strict check would reject a legitimate 32-bit zapret build — the current bundle is x64 only, but keep the permissive behaviour if a 32-bit bundle is ever shipped.
- **Discovered by:** B

#### F-WN-26-11  [P3] — The status cache is read and written outside the class lock (violates the repo's lock rule) and can never be observed fresh

- **File:** `services/zapret_service.py:1411-1428` (`get_status`), `:1437-1475` (`_build_status`), `:338-341` (cache fields)
- **Confirmed:** yes (code reading)
- **Description:** `_build_status()` assigns `self._status_cache` **under** `self._lock`, but `get_status()` tests and initialises the same field **outside** the lock (`if self._status_cache is None: self._status_cache = {...}`). A refresh that completes between the test and the assignment is overwritten by the "Определение статуса…" placeholder. This directly contradicts the repository rule that "a new shared field joins its class's existing lock". Separately, `get_status()` returns the *cached* value and only *triggers* a background refresh, so the first call after the settings panel opens always answers with the placeholder; the UI (`ui/web_new_v2/js/settings.js:1996-2018`) fetches the status exactly once and never polls → the toggle is rendered from a stale answer.
- **Cause:** the "instant status, background refresh" design has no way for a caller to await a fresh value, and the cache initialisation was placed outside the lock.
- **Trigger conditions:** the first `get_zapret_status()` call after startup (the common case), and any concurrent refresh.
- **User impact:** the Zapret panel shows "Zapret отключен" / "Определение статуса..." until the panel is reopened, and the user may re-toggle an already-running bypass. (The "never re-reads" half of this belongs to WN‑30; the service-side half — no awaitable fresh status, lock violation — is here.)
- **Evidence:**
  ```python
  1414:         with self._lock:
  1415:             if self._status_cache and (now - self._status_cache_time) < self._status_ttl:
  1416:                 return dict(self._status_cache)
  1417:         if self._status_cache is None:
  1418:             self._status_cache = { ... "message": "Определение статуса...", ... }
  1427:         self._refresh_status_async()
  1428:         return dict(self._status_cache)
  ```
- **Reproduction / verification:** call `svc.get_status()` twice in a row while a refresh thread is running; the second answer may still be the placeholder. Deterministic reproduction: call `get_status()` on a fresh service and assert `status["message"] != "Определение статуса..."` — it fails until a background refresh has completed *and* the caller re-reads.
- **Suggested fix:** move the placeholder initialisation inside `with self._lock:`; expose an optional `refresh`/`wait` parameter (or a status-changed event) so a caller can obtain a fresh value in one round trip.
- **Fix side effects:** a synchronous refresh would block the bridge for up to ~1 s (the scan) — the event/callback variant avoids that.
- **Discovered by:** B

#### F-WN-26-12  [P3] — `find_binary()` returns unvalidated, ambient paths; the normal launch path skips the policy the elevated path enforces

- **File:** `services/zapret_service.py:732-752` (`find_binary`), `:748-750` (the existence-only check), `:1160-1173` (`Popen` without validation), `:1270` (elevated path **does** validate)
- **Confirmed:** yes
- **Description:** `find_binary()` accepts any existing file at `<cwd>/bin/winws.exe`, `<cwd>/zapret/winws.exe`, `<app_dir>/{winws.exe,zapret.exe,bin/winws.exe}` — no name policy, no root policy, no PE check. The elevated path re-validates (`validate_zapret_binary(exe, self.app_dir, extra_roots=[self.base_dir])`), but the ordinary `Popen` path does not, so the ambient candidates are launched as-is. `base_dir` is `sys._MEIPASS` or the **repo root** in a dev checkout, so in dev mode a file under the repository (or the CWD inside it) also passes the elevated check.
- **Cause:** two different trust policies for the same decision (custom path → validated; discovered candidates → not), and a root list that includes a user-writable directory.
- **Trigger conditions:** the app is started with a working directory the user can write to (a per-user install directory, a shell launch with `cd`), and a `winws.exe`/`zapret.exe` is placed there.
- **User impact:** the app executes a file it did not install (code execution as the user; in dev mode possibly elevated). The `binary_path` setting has the opposite problem: any path outside the two allowed roots is rejected outright, so a legitimate custom install is unusable and the user only learns this from a toast.
- **Evidence:**
  ```python
  740:         candidates = [
  741:             os.path.join(self.app_dir, "winws.exe"),
  ...
  744:             os.path.join(os.getcwd(), "bin", "winws.exe"),
  745:             os.path.join(os.getcwd(), "zapret", "winws.exe")
  746:         ]
  748:         for c in candidates:
  749:             if os.path.exists(c):
  750:                 return c
  ```
- **Reproduction / verification:** create `%CWD%\zapret\winws.exe` (any PE-shaped file), start the app from that directory and enable Zapret → `find_binary()` returns it (the CWD candidate precedes nothing but is checked) and `subprocess.Popen` runs it; `_launch_elevated` would reject it only because the CWD is not under `app_dir`/`base_dir`.
- **Suggested fix:** run every candidate through `validate_zapret_binary` (roots + approved name + PE) and drop the CWD-relative candidates in a frozen build.
- **Fix side effects:** a dev checkout that keeps the bundle in `<repo>/zapret/` would need `base_dir` to stay an accepted root — it already is.
- **Discovered by:** B

#### F-WN-26-13  [P3] — The argument grammar is a shape check, not an option allow-list: arbitrary local files can be opened by the elevated helper

- **File:** `services/zapret_service.py:90` (`_ALLOWED_ARG_RE`), `:203-219` (`sanitize_zapret_args`), `:1110-1130` (custom/preset path), `:1275-1281` (elevated use)
- **Confirmed:** yes
- **Description:** Every token of the form `--name[=value]` is accepted, whatever the option is. Upstream zapret options such as `--hostlist=<file>`, `--ipset=<file>`, `--dpi-desync-repeats-file=<file>` make the (elevated) `winws.exe` open an arbitrary local path; the grammar also allows `/` and `\` in values, so absolute paths pass. Shell metacharacters are correctly rejected (see §3), so there is **no** command injection — the residual capability is "read an arbitrary file as the elevated user", whose content is not returned to the app but does influence the traffic the bypass touches.
- **Cause:** the sanitiser validates the *syntax* of a token, not the *vocabulary* of options the app is willing to forward.
- **Trigger conditions:** `mode == "custom"` with a `custom_args` value — reachable through the bridge method `toggle_zapret(enabled, mode, custom_args, binary_path)` (`core/api.py:3796-3806`), which persists whatever it is given, although the current UI exposes no "custom" mode (`ui/web_new_v2/index.html:1900-1905`) and no argument field.
- **User impact:** a script able to call the bridge (e.g. an XSS in the WebView) can make the elevated helper read arbitrary files; the current UI cannot trigger it.
- **Evidence:**
  ```python
  90: _ALLOWED_ARG_RE = re.compile(r'^--[A-Za-z0-9][A-Za-z0-9\-]*(=[A-Za-z0-9,.:_/\-\\ ]*)?$')
  ```
  Probe output: `--hostlist=C:\Windows\win.ini` → **accepted**; `--foo=bar&calc`, `--foo=bar|calc`, `--foo=bar>out.txt`, `--foo=bar\`calc\``, `--foo=bar%PATH%`, `--foo=bar^&calc`, `--hostlist="a b"` → **rejected**.
- **Reproduction / verification:** probe `wn26_probe.py` §2 (`sanitize_zapret_args` over 13 payloads) — results quoted above.
- **Suggested fix:** replace the regex with an allow-list mapping option name → value grammar (the four presets' options plus the file-valued ones explicitly excluded), so unknown options never reach the elevated process.
- **Fix side effects:** users who hand-tuned `custom_args` (via the bridge, not the UI) would find some options rejected.
- **Discovered by:** B

#### F-WN-26-14  [P3] — Discord RPC is opt-out: the app connects to Discord and publishes the track by default

- **File:** `core/services/discord_rpc.py:42-45` (`is_enabled`, default `True`), `core/app.py:146-147` (`discord_rpc.start()` at boot), `core/api.py:1229-1236` (payload with title/artist)
- **Confirmed:** yes
- **Description:** The default value of `app.discord_rpc_enabled` is `True`, the service connects to the local Discord IPC socket during `AppCore` construction, and the first track played is published (title, artist, playback position, duration) to Discord without any explicit opt-in. The payload also carries a fixed GitHub link.
- **Cause:** the privacy-relevant default is "on"; the setting is only reachable in the settings panel.
- **Trigger conditions:** every launch.
- **User impact:** the user's listening history is disclosed to a third-party service by default; a user who never opened the settings panel does not know this is happening.
- **Evidence:**
  ```python
  42:     def is_enabled(self) -> bool:
  43:         if self.settings:
  44:             return bool(self.settings.get("app", "discord_rpc_enabled", True))
  45:         return True
  ```
  ```python
  146:         self.discord_rpc = DiscordRPCService(self.settings)
  147:         self.discord_rpc.start()
  ```
- **Reproduction / verification:** start the app with a fresh profile and a running Discord client, play a track, and observe the presence in Discord; `settings.get("app","discord_rpc_enabled")` is `True` by default.
- **Suggested fix:** default the flag to `False` and surface an explicit opt-in on the first launch (or at least in the onboarding panel).
- **Fix side effects:** existing users who rely on the presence would have to switch it on once.
- **Discovered by:** B

### 3. Clean areas

Checked and found correct:

- **The pinned SHA-256 is genuine.** `ZAPRET_ZIP_SHA256` equals the GitHub release digest of `zapret-v72.13.zip`; downloading the archive and running `_verify_zip_sha256` returns `True`. The hash check *is* performed **before** extraction on the pinned path (`download_binaries`, `:895-900`). The defect is only that the pin is not applied to other versions (F‑WΝ‑26‑1).
- **ZIP-slip is not possible.** `_extract_zip` writes `os.path.basename(name)` (`:844`) into `self.app_dir`, so `../../x86_64/evil.dll` and `..\..\x86_64\evil2.exe` land as `evil.dll` / `evil2.exe` inside the zapret folder and nothing lands above it — verified empirically with a crafted archive (probe §3).
- **Command injection through `custom_args` is not possible.** `sanitize_zapret_args` uses `shlex.split(..., posix=False)` and a strict token grammar; `&`, `|`, `>`, `<`, backticks, `%VAR%`, `^`, quotes are all rejected (probe §2). The elevated command is built with `subprocess.list2cmdline` and quoted paths.
- **The elevated `cmd.exe` command line parses correctly.** Verified with `CreateProcessW` on the exact raw string built at `:1283`: the `> "zapret.log" 2>&1` redirect captures **both** stdout and stderr in `zapret.log` (no stray `zapret.log 2>&1` file, no lost stderr).
- **The bypass is host-scoped, as the commit claims.** All four presets carry `--hostlist-domains={hosts}` with `ZAPRET_SCOPED_HOSTS`; upstream zapret v72.13 documents `--hostlist-domains=<domain_list>` as *"comma separated fixed domain list"* — so the scoping is real and the syntax is correct. The `dpi-desync=fake,split2` combination is a 1st/2nd-phase strategy, so the hostlist filter does not need `--ipcache-hostname`. (The residual — the WinDivert driver and the `--wf-tcp=80,443` WFP filter remain machine-wide, and the desync applies to *any* process that talks to those domains, e.g. the user's browser — is inherent to zapret and is documented in the module comment at `:53-59`.)
- **All `shell=True` call sites are injection-safe.** The five uses (`:280`, `:458-461`, `:562`, `:608-611`, `:682-695`) either pass a constant command string or interpolate an `int` PID.
- **No pipe deadlock.** The child is launched with `stdout=DEVNULL` and `stderr=<file handle>` — no pipes to drain. The log handle is closed on stop and on an instant crash (`:1175`, `:1185`, `:1354`); the log is rotated above 1 MiB (`:788-789`).
- **PID identity is checked properly.** `_is_our_winws_process` verifies the image name (`_ALLOWED_BINARY_NAMES`) **and** the executable path against the app dir / base dir / CWD, so a recycled PID belonging to another process is not killed. `stop()` never uses `taskkill /IM` and keeps the pidfile when termination fails, so the driver lock is not silently forgotten.
- **The process is stopped on a clean exit.** `core/app.py:553-554` → `zapret.stop()`; `main.py:575` → `app_core.cleanup()` after the WebView loop ends. (Only a crash escapes it — F‑WΝ‑26‑6.)
- **`check_internet` is not on a hot path.** It is called only from `_build_status`, which runs on the dedicated background status thread (`_refresh_status_async`), with a 2.5 s TTL cache; measured at 321 ms on a connected machine, worst case ~6 s (4 hosts × 1.5 s) off-line. It never blocks the bridge or the UI thread.
- **The Discord RPC update path is event-driven and bounded.** There is no timer loop: `update_presence` is called from `_on_track_changed` and `report_state` (play/pause/stopped) only; `report_position` — the frequent 1-per-tick call — does not touch Discord. A failed connect does not loop: `start()` returns early while `self._connecting` is set, so at most one connect attempt is in flight.
- **The `RLock` choice in `DiscordRPCService` is correct and documented** (`core/services/discord_rpc.py:32-37`): `update_presence()` holds the lock and calls `start()`, which re-acquires it — a plain `Lock` would self-deadlock on the first track change.

### 4. Coverage gaps

- **Not reproduced on this machine:** the AutoRun/`COMSPEC` escalation (F‑WΝ‑26‑4) and the Discord-RPC connect/stop race (F‑WΝ‑26‑7). Both would require either elevated execution that installs a kernel driver, or a live Discord client. The code paths and the missing evidence are stated per finding.
- **Not executed:** `winws.exe` itself (the extracted binary was only parsed, never launched) — deliberately, because a successful launch installs the WinDivert driver and modifies the machine's network stack. The claim that the non-elevated launch fails and falls back to `ShellExecuteW("runas")` therefore rests on the code path (`:1174-1177`, `:1181-1194`), not on an observed run. Related open question for Role A: `_looks_like_elevation_needed` (`:814-819`) matches `"access denied"` but not the Windows wording `"access is denied"` — if winws emits the latter, the app would report a crash instead of elevating. Capturing winws's real stderr on a non-elevated run would settle it.
- **pywebview is not installed in `.venv_win`**, so the bridge dispatch model was taken from the repository's own documented understanding (`core/api.py:63-67`: "pywebview serves the call on a bridge thread"). No claim in this report depends on the UI thread being free — only on the bridge call's duration.
- **`~/.nedotify/` was not touched.** All probes redirected `HOME`/`USERPROFILE` to a temp directory before importing the module (`ZapretService.__init__` creates `~/.nedotify/zapret` and `~/.nedotify/logs`); the archive/PE experiments were written under `%TEMP%\opencode\`.
- **Git history was read for intent only** (`a328835` "scope the bypass"); no file in the repository was modified.

### 5. Architecture improvements (ARCH)

- **ARCH-1 — `core/services/discord_rpc.py` is in the wrong layer.** `core/services/` currently holds `recommendation.py` (pure scoring core) and `discord_rpc.py` (a full lifecycle service with threads, a socket client and start/stop). `services/` holds the other feature services (`zapret_service.py`, `catalog_service.py`, `artist_service.py`, …). `core/app.py:30` imports one of them and `:33` the other. *Direction:* move `discord_rpc.py` to `services/` (it is a peer of `zapret_service.py`) and keep `core/services/` for pure logic; or, if `core/services/` is meant to be the service layer, move `core/services/recommendation.py` out and rename the package. The current split makes "where does a service live?" unanswerable without reading the area map.
- **ARCH-2 — `services/zapret_service.py` is five responsibilities in 1328 lines.** Download+hash+extract (`:833-1013`), binary/PE/path policy (`:44-262`), argument grammar (`:90`, `:203-219`), Windows process discovery (`:395-663`), process lifecycle incl. elevation (`:1063-1407`), status caching (`:1411-1475`). *Direction:* split into `zapret_bundle.py` (download/verify/extract), `zapret_binary.py` (PE/path policy), `zapret_args.py` (grammar + presets), `win_process.py` (enumeration), `zapret_runner.py` (launch/elevate/kill) and keep `ZapretService` as the façade. The seams are already visible in the code — every helper has exactly one responsibility — they are simply not separated.
- **ARCH-3 — Two different command-construction mechanisms carry the same security invariant.** The normal launch uses `Popen([exe] + tokens)` (`:1167`), the elevated launch builds a `cmd /c` **string** with `list2cmdline` + a hand-written redirect (`:1281-1283`). The "no shell metacharacters" property therefore has to hold in two places, and only the string path depends on cmd.exe's quoting rules. *Direction:* one `build_argv()` → one `spawn(argv)` seam, with the elevation handled by a fixed, hard-coded wrapper (no user data in the command line at all — the args would be passed via the environment or a file, not on the command line).
- **ARCH-4 — `ZapretService` is not testable without a real subprocess.** The existing tests have to monkey-patch four methods to exercise `start()` (`tests/test_zapret_binary_integrity.py:196-202`) and re-implement `ctypes.windll` to test the UAC path (`tests/test_zapret_uac_window.py:31-38`). *Direction:* inject a `ProcessRunner` / `Elevator` / `FileSystem` seam (as `core/proxy.py` and `core/downloader.py` already do for their I/O) so that launch, kill and elevation can be tested without a real process or a real UAC prompt. This is also what would make F‑WΝ‑26‑3 (the lock inversion) a unit test instead of a timing-dependent integration case.
- **ARCH-5 — The status model has no "await fresh value" contract.** `get_status()` is a cache read that *triggers* a background refresh (`:1411-1428`); the UI must poll to converge, and the current UI polls once. *Direction:* either return a future/generator, or emit a `zapret_status_changed` event (the bridge already has an event channel) so the panel updates when the refresh lands.
- **ARCH-6 — Generic helpers live in the feature module.** `check_internet()` (`:287-304`) and `INTERNET_CHECK_HOSTS` are a generic connectivity probe, not zapret logic; the same module also owns the PE parser (`:126-174`) and the cmd.exe quoting (`:1281`). Moving them into `utils/` (the repo's existing home for cross-cutting helpers) would make the zapret module smaller and the helpers reusable/testable in isolation.
- **ARCH-7 — `check_for_updates()` returns a network-supplied `download_url` that the app then executes.** `get_latest_release_info()` (`:927-939`) parses the GitHub API response and returns `browser_download_url`; `check_for_updates()` (`:944-954`) hands it to the UI as `download_url`, and `update_zapret()` downloads from it. The API response is treated as trusted configuration. *Direction:* the service should own the URL construction from a *pinned tag* plus a *pinned hash*, and the API should only be used as a "is there a newer tag?" oracle — that is the same trust inversion that produced F‑WΝ‑26‑1.
