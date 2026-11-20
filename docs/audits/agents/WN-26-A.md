## AREA WN-26 — Zapret (network bypass) & Discord RPC — ROLE A

### 1. Scope reviewed

**Files opened (physical 1-based line ranges, read in full):**

- `services/zapret_service.py` — L1–1475 (whole file; 1328 non-empty lines). Focus points: `_verify_zip_sha256` L44–51, `_read_header` L111–123, `is_valid_windows_binary` L126–174, `binary_integrity_error` L177–200, `sanitize_zapret_args` L203–219, `validate_zapret_binary` L222–262, `_check_output_text` L269–284, `check_internet` L287–304, `ZapretService` L307–1475 (`__init__` L307–341, pid/process identity L345–594, `_scan_pids_with` L596–663, `_kill_pid` L665–728, `find_binary` L732–752, `is_running` L756–778, download/update L833–1059, `start`/`_launch`/`_launch_elevated` L1063–1334, `stop` L1336–1407, `get_status`/`_build_status` L1411–1475).
- `core/services/discord_rpc.py` — L1–183 (whole file; 161 non-empty lines).
- `core/api.py` — L485–529 (offline interception of `check_zapret_update`/`update_zapret`), L1215–1274 (`_on_track_changed` → Discord), L1360–1419 (`report_state` → Discord), L3780–3899 (`toggle_zapret`, `toggle_discord_rpc`, `get_discord_rpc_status`, `get_zapret_status`, `check_zapret_update`, `update_zapret`).
- `core/app.py` — L100–279 (`__init__` wiring, `start_zapret_if_enabled`), L500–586 (`cleanup()`).
- `main.py` — L380–499 (window/loaded/`on_loaded` → zapret autostart thread), L495–584 (watchdog restart path, `app_core.cleanup()` on exit).
- `ui/web_new_v2/index.html` L1875–1934 (Zapret settings panel markup), `ui/web_new_v2/js/settings.js` L1845–2034 (`setupZapretPanel`, `applyZapret`, status fetch), L201–210 (Discord toggle).
- `tests/test_zapret_binary_integrity.py` — L1–375 (read to separate "intended" behaviour from defects).
- `.venv_win/Lib/site-packages/pypresence/baseclient.py`, `presence.py`, `utils.py` — the installed client (4.6.2) that `core/services/discord_rpc.py` drives.
- `setup_pyinstaller.spec` L104–105 (`console=False` → the shipped app is a windowed/GUI process).
- `git log`/`git show 54af23d` on `services/zapret_service.py` (the "reject a header-only PE" change) to establish intent.

**Callees traced into other areas (attributed there, not here):**

- `core/api.py` L502 — `check_zapret_update`/`update_zapret` are short-circuited in offline mode → **WN-10**.
- `core/api.py` L3807 — `is_running()` is called synchronously on the bridge thread inside `toggle_zapret` → the *call-site* cost is WN-10; the scanning cost itself is mine (F-WN-26-5).
- `core/api.py` L3849 `get_zapret_status` → returns the service's cached dict without polling → the UI half of F-WN-26-6 is **WN-30**; the placeholder dict is mine.
- `core/app.py` L147 `discord_rpc.start()` at construction, L549–550 `discord_rpc.stop()` in cleanup → lifecycle is WN-02; the RPC client defects are mine.
- `core/app.py` L236–294 `start_zapret_if_enabled` + `main.py` L404 → autostart gating is WN-02/WN-01; the orphan-process consequence is mine (F-WN-26-16).
- `setup_pyinstaller.spec` `console=False` → WN-01; cited here only as the precondition for F-WN-26-4.
- `ui/web_new_v2/js/settings.js` L1881/L1996 → WN-30.

---

### 2. Findings

#### F-WN-26-1  [P1] — The update path downloads and extracts an archive whose SHA-256 is never verified
- **File:** `services/zapret_service.py:44-51`, `services/zapret_service.py:956-981`, `services/zapret_service.py:927-942`
- **Confirmed:** yes
- **Description:** `_verify_zip_sha256()` returns `True` when the expected digest is empty ("No pinned hash — verification not possible"). `update_zapret()` computes `expected_hash = ZAPRET_ZIP_SHA256 if zip_url == ZAPRET_ZIP_URL else ""`. `get_latest_release_info()` returns the `browser_download_url` of the **first `.zip` asset of the latest GitHub release** — for every release newer than the pinned `v72.13` that URL differs from `ZAPRET_ZIP_URL`, so `expected_hash` is `""` and the archive is accepted with **zero integrity checking**. The pinned digest therefore protects only the *first* install (`download_binaries()`, which always uses the pinned URL); the "Обновить" button and the background auto-update install an arbitrary archive.
- **Cause:** a missing pin is treated as "verification impossible → allow", and the update path never pins the URL it actually downloads (it takes the URL from a remote JSON response instead of from the pinned constant).
- **Trigger conditions:** a release newer than v72.13 exists and the user clicks "Обновить" (or `autoupdate` is on and the bypass is not running → `auto_update_in_background()` → `update_zapret(force=True)`).
- **User impact:** the module's own contract ("verified before extraction… If it ever mismatches, the bundle is refused (no extraction, no launch)") does not hold on the update path. The unverified archive's `x86_64/*.exe` members are written into `~/.nedotify/zapret` and `zapret.exe`/`winws.exe` from there can be launched **elevated** (`_launch_elevated` → `ShellExecuteW(..., "runas", exe, ...)`), so a tampered release asset becomes admin-level code execution.
- **Evidence:**
  ```python
  # L44-51
  def _verify_zip_sha256(zip_bytes: bytes, expected_sha256: str = ZAPRET_ZIP_SHA256) -> bool:
      ...
      if not expected_sha256:
          return True  # No pinned hash — verification not possible
      digest = hashlib.sha256(zip_bytes).hexdigest()
      return hmac.compare_digest(digest, expected_sha256)

  # L974-981
  zip_bytes = self._download_zip(zip_url, timeout=40.0)
  # Verify integrity: pinned hash exists only for the bundled release.
  expected_hash = ZAPRET_ZIP_SHA256 if zip_url == ZAPRET_ZIP_URL else ""
  if not _verify_zip_sha256(zip_bytes, expected_hash):
  ```
  and L936-939:
  ```python
  for a in data.get("assets", []):
      if a.get("name", "").endswith(".zip"):
          return tag, a.get("browser_download_url")
  ```
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" -c "from services.zapret_service import _verify_zip_sha256; print(_verify_zip_sha256(b'garbage',''))"` → `True`. The only path in which `update_zapret` reaches the pinned digest is when the *latest* release still equals `v72.13` **and** the local binary is missing (otherwise L969 returns early) — i.e. the check is effectively dead for every real update.
- **Suggested fix:** keep a digest per release tag (map tag → sha256) and refuse to install an archive whose tag is not pinned; derive the download URL from the pinned constant pattern rather than from the API payload, and validate the API payload's `browser_download_url` against the expected `github.com/bol-van/zapret/releases/download/<tag>/...` shape.
- **Fix side effects:** a brand-new upstream release would be un-installable until a hash is added → need a "trust on first use + publish the digest" path or a signed manifest; refusing unknown tags removes the "just click update" convenience.
- **Discovered by:** A

#### F-WN-26-2  [P1] — "Update Zapret" is a silent no-op: the installed binary is never replaced, but the version is bumped anyway
- **File:** `services/zapret_service.py:839-866` (gate at L861-862), `services/zapret_service.py:956-1010` (L988, L997, L1010)
- **Confirmed:** yes (executed)
- **Description:** `_extract_zip()` skips any archive member whose target file *already* passes `is_valid_windows_binary()`:
  ```python
  target_path = os.path.join(self.app_dir, filename)
  if is_valid_windows_binary(target_path):
      continue
  tmp_path = target_path + ".part"
  ...
  os.replace(tmp_path, target_path)
  ```
  On an update the existing `~/.nedotify/zapret/winws.exe` is valid → the new archive's copy is **discarded**. `update_zapret()` then writes the new tag into `version.json` (L997) and returns `(True, "Zapret успешно обновлен до версии {latest_tag}!")` (L1010). The guard was introduced for the "do not replace a working binary with an empty entry" case (pinned by `tests/test_zapret_binary_integrity.py:294-306`) but it has no notion of *which* version is installed.
- **Cause:** the "is the target still good?" test is used where "is the target the same version as the archive?" is needed.
- **Trigger conditions:** every update after the first successful install (i.e. whenever `winws.exe` is already on disk and valid).
- **User impact:** the UI shows the new version badge and the toast "Zapret успешно обновлен до версии vX!", but the **old** binary keeps running; `check_for_updates()` then reports "no update available" forever. The user can never obtain a newer zapret through the app's own update button.
- **Evidence:** see the code above; plus L997 `self._write_version_info(latest_tag)` executed unconditionally after a no-op extraction.
- **Reproduction / verification:** probe script (temp dir, `_extract_zip` bound to a stub with `app_dir`): archive containing `zapret-v72.99/x86_64/winws.exe` with body `NEWVERSION`, existing target with body `OLDVERSION` → after extraction: `still OLD? True`, `contains NEW?: False`, `size on disk: 4160` (unchanged).
- **Suggested fix:** decide "replace" by comparing the extracted file with the installed one (size + digest, or a version resource / per-release marker), and validate the *extracted* content before `os.replace`, keeping the "never overwrite a good binary with an empty/garbage one" rule.
- **Fix side effects:** the overwrite now really happens, so a corrupt archive can destroy a working binary → keep the pre-replace `is_valid_windows_binary()` check on the **new** content, and keep a backup of the previous binary.
- **Discovered by:** A

#### F-WN-26-3  [P2] — `update_zapret()` reports success even when the bypass fails to come back up
- **File:** `services/zapret_service.py:983-1010` (L985, L1008, L1010)
- **Confirmed:** yes
- **Description:** when the bypass was running, `update_zapret()` stops it (L985), sleeps 1 s, replaces the binaries, and restarts it — but the result of the restart is **discarded**:
  ```python
  self.start(mode=mode, custom_args=custom_args, binary_path=bin_path)
  ...
  return True, f"Zapret успешно обновлен до версии {latest_tag}!"
  ```
  Additionally the running bypass is stopped **before** the new archive is known to be usable, and there is no rollback: if the extraction/restart fails, the bypass stays off.
- **Cause:** the restart result is not propagated, and the stop/extract/restart sequence has no compensating action.
- **Trigger conditions:** the UAC prompt is declined, WinDivert is busy, the new binary is unusable, or the restart hits the elevation path that cannot find a PID.
- **User impact:** the user is told "Zapret успешно обновлен" while the bypass is silently **off** — the one feature the panel exists for.
- **Evidence:** quoted above (L1008 discards the tuple; L1010 returns `True` unconditionally).
- **Reproduction / verification:** monkeypatch `ZapretService.start` to return `(False, "UAC отклонён")` and call `update_zapret()` with a stubbed `get_latest_release_info`/`_download_zip`/`_extract_zip` → the returned tuple is `(True, "Zapret успешно обновлен до версии …")`.
- **Suggested fix:** capture `ok, msg = self.start(...)` and fold it into the returned message/success flag; validate the extracted binary *before* stopping the running one and roll back on failure.
- **Fix side effects:** a failed restart now surfaces as a failed update → the UI toast text changes (WN-30 may need to distinguish "updated but not restarted").
- **Discovered by:** A

#### F-WN-26-4  [P2] — Console windows flash over the app on every Zapret scan and on every stop
- **File:** `services/zapret_service.py:269-284` (L280), `services/zapret_service.py:458-461`, `services/zapret_service.py:562`, `services/zapret_service.py:608-611`, `services/zapret_service.py:682-685`, `services/zapret_service.py:692-695`
- **Confirmed:** yes
- **Description:** `_check_output_text()` runs `tasklist` / `wmic` / `powershell` and **never** passes `creationflags`:
  ```python
  out = subprocess.check_output(cmd, shell=shell, stderr=subprocess.DEVNULL, timeout=timeout)
  ```
  It is called with `shell=True` for the shell built-ins (`tasklist` L459/L562, `wmic` L609) and list-form for `powershell` (L583/L647) — but on Windows a console child of a console-less parent allocates a **new console** in both cases. The shipped app is a windowed process (`setup_pyinstaller.spec:104 console=False`), so it owns no console → a black window flashes over the UI. The winws launch itself *does* set `creationflags=subprocess.CREATE_NO_WINDOW` (L1172) — the omission is inconsistent. `_kill_pid()` has the same problem (`taskkill` with `shell=True`, L682/L692) and additionally escalates via `ShellExecuteW(None, "runas", "taskkill.exe", …)` (L703-705), which can raise a **UAC prompt while the app is closing**.
- **Cause:** the `shell=True` helper was written for command-line tools and never got the `CREATE_NO_WINDOW` flag; `shell=True` is also unnecessary — every command could be passed as a list.
- **Trigger conditions:** opening the Zapret settings panel (one background status refresh → `tasklist` + possibly `wmic`/`powershell`), every Zapret toggle (`is_running()` scans), and every stop (`taskkill`).
- **User impact:** one or more black console windows flash over the player each time the user touches the Zapret panel — on a "music player" UI this is a visible defect; the UAC prompt at exit is worse.
- **Evidence:** quoted above; contrast with L1167-1173 which sets `creationflags=subprocess.CREATE_NO_WINDOW`.
- **Reproduction / verification:** run the packaged app and open Settings → Zapret; watch for the console window (the scans are also visible in `~/.nedotify/logs/app.log` as "Zapret status refresh"). Static confirmation: `_check_output_text` has no `creationflags` argument at all (L280).
- **Suggested fix:** add `creationflags=subprocess.CREATE_NO_WINDOW` to every Windows subprocess in this module (guard it with `sys.platform == "win32"`), and drop `shell=True` in favour of list-form commands where possible.
- **Fix side effects:** none — the children are pure scanners; hiding their console is the intended behaviour. The elevated `taskkill` fallback should be skipped when the parent is already exiting.
- **Discovered by:** A

#### F-WN-26-5  [P2] — Toggling Zapret blocks the bridge for seconds (wmic + tasklist + PowerShell scans, up to ~3 scans per toggle)
- **File:** `services/zapret_service.py:557-594`, `services/zapret_service.py:596-663`, `services/zapret_service.py:756-778`, `services/zapret_service.py:1138-1150`; `core/api.py:3807`
- **Confirmed:** yes
- **Description:** `is_running()` performs, in order: the pidfile check, then `_scan_pids_with()` (`wmic` with a 4 s timeout, then a PowerShell CIM query with a 6 s timeout), then `_scan_all_winws_pids()` (`tasklist` 3 s, then PowerShell 4 s) — up to ~17 s of subprocess time per call. `start()` calls `is_running()` twice (L1134, L1139) and `AppApi.toggle_zapret()` calls it a third time (`core/api.py:3807`). The elevated launch path adds a 5 s PID-discovery loop (L1296-1321) that itself calls **both** scans on every iteration. All of this runs while `self._lock` is held (L1138), so `stop()` and `get_status()` queue behind it.
- **Cause:** the "is this winws ours?" question is answered by scanning the whole process table with three different tools instead of by the cheap ctypes image-path check that is already implemented (`_get_process_exe_path`, L489-517).
- **Trigger conditions:** any Zapret toggle on a machine where `wmic` is slow (it is deprecated and typically 1–3 s), and any elevated start.
- **User impact:** the "Включить службы Zapret" switch is disabled for the whole call (`ui/web_new_v2/js/settings.js:1881`), so the settings panel appears frozen for many seconds with no feedback; on the elevated path the user may wait 20+ s before the UAC prompt even appears.
- **Evidence:** `services/zapret_service.py:562` `out = _check_output_text('tasklist /FO CSV /NH', timeout=3.0, shell=True)`; `services/zapret_service.py:608-611` `wmic process where "name='winws.exe'" get ProcessId,CommandLine /FORMAT:CSV` (timeout 4.0) with the PowerShell fallback at L646-649 (timeout 6.0); `core/api.py:3807` `is_running = self._core.zapret.is_running()`.
- **Reproduction / verification:** instrument `_check_output_text` to log its duration, then call `toggle_zapret` from the bridge on a machine without zapret running → the call takes the sum of the scan timeouts. Static confirmation: `start()` calls `is_running()` at L1134 and L1139 and the API calls it again at `core/api.py:3807`.
- **Suggested fix:** make the scan result cached for a few seconds and keyed on the pidfile/signature; drop the PowerShell fallbacks (the ctypes `QueryFullProcessImageNameW` + path comparison already answers the question); run the expensive "find our PID" work off the bridge thread.
- **Fix side effects:** a short-lived cache can report "running" for a second or two after the process was killed manually.
- **Discovered by:** A

#### F-WN-26-6  [P2] — The Zapret panel shows a placeholder status on first open; the background refresh never reaches the UI
- **File:** `services/zapret_service.py:1411-1428`, `services/zapret_service.py:1430-1435`, `services/zapret_service.py:1437-1475`
- **Confirmed:** yes
- **Description:** `get_status()` returns a hard-coded placeholder the first time it is called and only *then* starts the refresh:
  ```python
  if self._status_cache is None:
      self._status_cache = {"binary_found": False, "binary_path": "", "running": False,
                           "has_internet": True, "version": "", "message": "Определение статуса...", ...}
  self._refresh_status_async()
  return dict(self._status_cache)
  ```
  The refreshed dict is written to `self._status_cache` by the background thread, but it only becomes visible on the **next** `get_status()` call. The UI calls `get_zapret_status()` exactly once per panel open (`ui/web_new_v2/js/settings.js:1996-2018`) and never polls, so the panel keeps the placeholder until the user closes and reopens it.
- **Cause:** the status is computed asynchronously but the synchronous API returns a value it already knows to be wrong, and there is no completion event (the bridge has no push channel for it).
- **Trigger conditions:** the first time the user opens the Zapret settings panel in a session (the cache is `None` until then — nothing else calls `get_status()` at startup).
- **User impact:** the switch shows OFF, the version badge shows "—" and the status text reads "Определение статуса..." even when the bypass is actually running and a newer version is installed. The user can also click "Обновить" against a version badge that says "—".
- **Evidence:** quoted above; `core/api.py:3846-3858` returns this dict verbatim to the UI.
- **Reproduction / verification:** start the app, open Settings → Zapret for the first time → the panel shows the placeholder; close and reopen the panel → the real state appears (the cache is now warm and < 2.5 s old, or a later call returns the refreshed dict).
- **Suggested fix:** either compute the status synchronously on the first call (bounded by the scan timeouts of F-WN-26-5) or let the service publish the refreshed status to the bridge (`AppApi._emit("zapret_status", status)`) so the UI can update in place.
- **Fix side effects:** a synchronous first call blocks the bridge (F-WN-26-5); the event route needs a new event name on both sides (WN-03/WN-30).
- **Discovered by:** A

#### F-WN-26-7  [P2] — A user-configured `binary_path` that fails validation is silently ignored and a different binary is launched
- **File:** `services/zapret_service.py:732-752`, `services/zapret_service.py:1067-1078`
- **Confirmed:** yes (executed)
- **Description:** `find_binary(custom_path)` returns the custom path **only** if it validates; otherwise it logs a warning, records `self._rejected_binary_path` and *continues* with the default candidate list:
  ```python
  if custom_path:
      if validate_zapret_binary(custom_path, self.app_dir, extra_roots=[self.base_dir]):
          return custom_path
      logger.warning("Rejected binary_path %r: ...", custom_path)
      self._rejected_binary_path = custom_path
  candidates = [ ... os.path.join(self.app_dir, "winws.exe"), ... ]
  for c in candidates:
      if os.path.exists(c):
          return c
  ```
  `start()` only surfaces the rejection when **no** binary was found at all (L1068-1077), so when `~/.nedotify/zapret/winws.exe` exists the user's configured path is dropped without any message and the app reports "Zapret активен".
- **Cause:** the "rejected custom path" signal is stored but not acted upon while a fallback exists.
- **Trigger conditions:** the user points the app at their own winws build that is outside `~/.nedotify/zapret` and outside the app directory (e.g. `D:\tools\winws.exe`), or names it something other than `winws.exe`/`zapret.exe`/`winws`, or puts it on a UNC/network path.
- **User impact:** the app silently runs a *different* binary than the one configured; `get_zapret_status` then returns both the configured `binary_path` (from settings) and the actually used `status["binary_path"]`, so the UI shows a path that is not in use. The user cannot tell why their build is ignored.
- **Evidence:** quoted above; `services/zapret_service.py:737` `logger.warning("Rejected binary_path %r: not an approved winws executable", custom_path)` — a log line only.
- **Reproduction / verification:** probe: `find_binary(<tmp>/notallowed.exe)` with a valid `winws.exe` present in `app_dir` → returns `<tmp>/winws.exe` (the default), i.e. the rejected custom path was silently replaced.
- **Suggested fix:** when an explicit path is supplied and fails validation, fail the start with the existing rejection message (L1074-1077) instead of falling back; keep the fallback only when no path was configured.
- **Fix side effects:** users with a stale path lose the implicit fallback → offer an explicit "use the bundled binary" action in the UI.
- **Discovered by:** A

#### F-WN-26-8  [P2] — The PE machine-type gate is a tautology: a 32-bit, ARM64 or fabricated 4 KiB image passes validation
- **File:** `services/zapret_service.py:126-174` (gate at L171-174), `services/zapret_service.py:100-108`
- **Confirmed:** yes (executed)
- **Description:** the last line of `is_valid_windows_binary()` is
  ```python
  machine = int.from_bytes(head[e_lfanew + 4:e_lfanew + 6], "little")
  return machine in (0, _PE_MACHINE_AMD64) or machine > 0
  ```
  `machine` is an unsigned 16-bit value, so `machine > 0` is true for everything except 0, and 0 is explicitly accepted → **the expression is always true**. The docstring nevertheless advertises "3. Machine type — 0x8664 (x64) or a real nonzero stamp … an unmapped stamp means the header was fabricated rather than linked". The size floor (`_PE_MIN_SIZE = 4 KiB`) does reject the 134-byte header stub (that part of the "reject a header-only PE" fix works), but a **4 KiB fabricated header** — MZ + PE signature at `e_lfanew` and nothing else — passes every gate.
- **Cause:** the machine check was written as a permissive "or" that can never be false; the intended condition (reject anything that is not x64) was never expressed.
- **Trigger conditions:** a wrong-architecture build (i386/ARM64) or a truncated/fabricated file of ≥ 4 KiB reaches `validate_zapret_binary()`.
- **User impact:** the integrity check gives a green light to a binary that cannot work; the failure then surfaces as "Не удалось загрузить драйвер WinDivert" or as the Windows "cannot run this app" dialog — the exact class of failure this function exists to prevent.
- **Evidence:** quoted above; the docstring contradiction is at `services/zapret_service.py:136-138`.
- **Reproduction / verification:** probe results — `32-bit PE (machine=0x014C) accepted? True`; `ARM64 PE (machine=0xAA64) accepted? True`; `4096-byte fabricated header accepted? True`; `134-byte header stub accepted? False`; and `all((m in (0,0x8664) or m > 0) for m in range(0,0x10000))` → `True` (the gate is a no-op for every possible value).
- **Suggested fix:** either enforce `machine == _PE_MACHINE_AMD64` (zapret ships x64 only) or delete the machine clause and correct the docstring so the contract matches the behaviour.
- **Fix side effects:** `tests/test_zapret_binary_integrity.py:104-110` deliberately pins the permissive behaviour ("Machine type is deliberately permissive: only the size gate is load-bearing"), so enforcing x64 requires updating that test — and would reject a genuine 32-bit build, which the docstring calls "a genuine zapret binary". The product decision (is a 32-bit winws supported?) has to be made first.
- **Discovered by:** A

#### F-WN-26-9  [P2] — The elevated winws.exe is executed from a user-writable directory
- **File:** `services/zapret_service.py:320`, `services/zapret_service.py:1264-1293` (L1270, L1283-1285), `services/zapret_service.py:222-262`
- **Confirmed:** yes
- **Description:** the bundle is installed into `~/.nedotify/zapret` (user-writable) and the normal launch path ends in an **elevated** execution:
  ```python
  self.app_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "zapret")
  ...
  ret = self._shell_execute_elevated(comspec, cmd_params, os.path.dirname(exe))   # -> ShellExecuteW(..., "runas", ...)
  ```
  `validate_zapret_binary()` (L222-262) constrains the path to `app_dir`/`base_dir` and to an approved file name, and `is_valid_windows_binary()` proves the file is a PE — but nothing proves that the file is *the* verified file at the moment it is executed. The root check uses `abspath`/`normcase` only (no `realpath`), so a directory junction inside `app_dir` also satisfies it.
- **Cause:** the trust boundary is "a file in the user's own profile directory", which is writable by every process running as that user, while the execution boundary is "administrator".
- **Trigger conditions:** any other process running as the same user replaces `~/.nedotify/zapret\winws.exe` (or `zapret.exe`) between the integrity check and the elevated launch, or before the next launch.
- **User impact:** the next "enable Zapret" runs the substituted file **as administrator** — a local privilege-escalation path opened by a feature the user is invited to enable.
- **Evidence:** quoted above; the module header itself states "winws arguments reach an ELEVATED process" (L87-89).
- **Reproduction / verification:** static (path + elevation are both explicit in the code). Confirmation of the writable location: `self.app_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "zapret")` — the user's own profile, no admin-only ACL is applied at any point (no `icacls`/ACL call exists in the module).
- **Suggested fix:** install/keep the verified binary in a directory that is not writable by the user (e.g. `%ProgramFiles%\NeDotify\zapret`, written by an elevated step) before the elevated launch, or re-verify the digest immediately before `ShellExecuteW` and refuse a mismatch.
- **Fix side effects:** writing into Program Files requires its own elevation step and breaks the "no installer needed" flow; a digest re-check still leaves a TOCTOU window.
- **Discovered by:** A (the security framing may be raised independently by Role B — the root cause is here, in this file.)

#### F-WN-26-10  [P3] — On Windows `sanitize_zapret_args()` cannot accept any argument containing a space or a quote
- **File:** `services/zapret_service.py:203-219` (L213, L216-218), `services/zapret_service.py:87-90`
- **Confirmed:** yes (executed)
- **Description:** the splitter is `shlex.split(raw_args, posix=(sys.platform != "win32"))`, i.e. **non-POSIX mode on Windows**, which splits on whitespace but *keeps* the quote characters and does not treat `\` as an escape. Consequently:
  - `"--filter-tcp=80,443"` → one token that still contains the quotes → the grammar `^--[A-Za-z0-9][A-Za-z0-9\-]*(=[A-Za-z0-9,.:_/\-\\ ]*)?$` rejects it ("Недопустимый аргумент Zapret");
  - `--hostlist-domains=a.com, b.com` → two tokens, the second one (`b.com`) does not start with `--` → rejected.
  The grammar's allowed value charset contains a space (`…\-\\ ]`), but the Windows tokenizer can never produce a token containing a space → that allowance is unreachable on the target platform. The regex also accepts behaviour-changing options verbatim (`--disable-tcp`, `--hostlist=0.0.0.0/0` → the desync is re-scoped to the whole machine), which is intended for the power-user "custom args" field but is nowhere disclosed to the user.
- **Cause:** the grammar was written for POSIX-style tokens while the tokenizer runs in Windows mode; the two do not agree.
- **Trigger conditions:** a user enters a custom argument that contains a space or quotes — a completely normal thing to type for a host list.
- **User impact:** custom mode is limited to single-token arguments; the user gets "Недопустимый аргумент Zapret: '…'" and cannot tell whether the argument was unsafe or merely unsupported.
- **Evidence:** the probe results — `REJECT '"--filter-tcp=80,443"'`, `OK '--disable-tcp'`, `OK '--hostlist=0.0.0.0/0'`, `OK '--hostlist-domains=a.com,b.com'`; and `shlex.split('--hostlist-domains=a.com, b.com', posix=False)` → `['--hostlist-domains=a.com,', 'b.com']`.
- **Suggested fix:** strip surrounding quotes from each token after the Windows split (or use `shlex.split(..., posix=True)` and re-escape for `list2cmdline`), and either remove the space from the grammar or make the splitter preserve it.
- **Fix side effects:** accepting quotes must not weaken the metacharacter rejection — the grammar must still run on the *unquoted* token.
- **Discovered by:** A

#### F-WN-26-11  [P3] — A failed extraction leaves a `.part` file in the Zapret directory
- **File:** `services/zapret_service.py:863-866`
- **Confirmed:** yes (executed)
- **Description:** the atomic write is
  ```python
  tmp_path = target_path + ".part"
  with open(tmp_path, "wb") as f:
      f.write(z.read(name))
  os.replace(tmp_path, target_path)
  ```
  If `z.read()` or `os.replace()` raises (disk full, AV lock, interrupted), the `.part` file stays in `~/.nedotify/zapret`. There is no `try/finally` cleanup. (The happy path is clean — `tests/test_zapret_binary_integrity.py:365-375` pins that no `.part` survives a successful extraction.)
- **Cause:** the temp file is created and renamed without a cleanup path.
- **Trigger conditions:** any I/O error during extraction — most plausibly on a full disk or with an AV scanner holding the file.
- **User impact:** leftover `.part` files accumulate in the user's Zapret directory; a later extraction of the same member overwrites them, so the impact is cosmetic, but the directory the user is told to delete by hand accumulates junk.
- **Evidence:** quoted above.
- **Reproduction / verification:** probe with `os.replace` monkeypatched to raise → `extraction raised: Boom disk error`, `leftover files: ['winws.exe.part']`.
- **Suggested fix:** wrap the write/replace in `try/finally` and remove `tmp_path` on failure (or use `tempfile` + `os.replace` with a `finally: unlink(missing_ok=True)`).
- **Fix side effects:** none.
- **Discovered by:** A

#### F-WN-26-12  [P3] — A wedged Discord IPC stalls the playback path for up to 10 s
- **File:** `core/services/discord_rpc.py:113-162` (L147), `core/api.py:1230-1238`, `core/api.py:1377-1396`; `.venv_win/Lib/site-packages/pypresence/baseclient.py:33-34`, `:93-109`; `pypresence/presence.py:17-76`
- **Confirmed:** yes (source of the installed client); the *stall* is a hypothesis about a wedged Discord
- **Description:** `update_presence()` calls `self.rpc.update(**payload)` **synchronously, while holding `self._lock`**, on the caller's thread. pypresence implements `update()` as `self.loop.run_until_complete(self.read_output())`, and `read_output()` wraps the socket reads in `asyncio.wait_for(..., self.response_timeout)` with `response_timeout = 10` seconds (installed 4.6.2). If Discord accepts the frame but never answers, the call blocks for 10 s and then raises `ResponseTimeout` — the exception is caught (so playback is not broken), but the *stall* is not bounded by the app.
- **Cause:** the RPC round-trip is executed inline on the playback/bridge thread instead of on the service's own worker.
- **Trigger conditions:** Discord running but its IPC endpoint wedged/slow, or Discord being suspended by the OS.
- **User impact:** `play_track` / the play-pause bridge call (`core/api.py:1230`, `:1380`) stalls for ~10 s → the UI shows no response to the play button. The RLock is held for the same period, so `clear_presence()`/`stop()` queue behind it.
- **Evidence:** `core/services/discord_rpc.py:147` `self.rpc.update(**payload)` (inside `with self._lock:` at L96); `pypresence/baseclient.py:34` `self.response_timeout = kwargs.get("response_timeout", 10)` and `:96` `preamble = await asyncio.wait_for(self.sock_reader.read(8), self.response_timeout)`.
- **Reproduction / verification:** monkeypatch `rpc.update` to sleep 10 s and call `DiscordRPCService.update_presence(...)` → the caller blocks for 10 s. Reading the installed pypresence confirms the 10 s ceiling.
- **Suggested fix:** send the presence from a dedicated worker thread (the service already owns a lock) with a short deadline, so a slow Discord can never delay playback.
- **Fix side effects:** an extra thread per service and a possible one-frame lag in the presence.
- **Discovered by:** A

#### F-WN-26-13  [P3] — The Discord connect attempt has no timeout: `_connecting` can stay `True` forever and the RPC never recovers
- **File:** `core/services/discord_rpc.py:51-85` (L64-66, L68-85), `core/api.py:1229-1238`; `pypresence/baseclient.py:144-160`
- **Confirmed:** hypothesis (needs a Discord that accepts the pipe but never completes the handshake)
- **Description:** `start()` sets `self._connecting = True` and spawns `_connect`, which calls `self.rpc.connect()` → `loop.run_until_complete(self.handshake())`. pypresence's handshake reads the 8-byte preamble and the payload **without** `asyncio.wait_for` (`baseclient.py:152-156`), unlike `read_output()` which is bounded. If the pipe is accepted but the peer never answers, `run_until_complete` never returns → `_connect` never reaches its `finally` → `self._connecting` stays `True` forever → every later `start()` returns immediately at `if self.connected or self._connecting: return` (L64-65) → **the presence is dead for the rest of the session**, silently (the only trace is a `logger.debug`).
  The retry policy is also unbounded: every `update_presence()` while disconnected stores `_pending_update` and calls `start()` again (L102-111), i.e. one new thread + one new `Presence` + one new connection attempt per track change, with no backoff and no attempt cap (cheap on Windows, because opening a missing pipe fails immediately with `FileNotFoundError`).
- **Cause:** the connect handshake has no deadline and the "already connecting" flag has no timeout of its own.
- **Trigger conditions:** a Discord instance (or another process squatting `discord-ipc-0`) that accepts the connection but does not answer the handshake.
- **User impact:** the Discord presence silently stops appearing and never recovers until the app is restarted; the user has no indication (status is only exposed through `get_discord_rpc_status`, which the UI does not read).
- **Evidence:** `core/services/discord_rpc.py:63-66` `with self._lock: if self.connected or self._connecting: return; self._connecting = True`; `:82-84` `finally: self._connecting = False` — only reachable if `connect()` returns or raises; `pypresence/baseclient.py:152-156` `preamble = await self.sock_reader.read(8)` (no timeout).
- **Reproduction / verification:** replace `Presence.connect` with a function that blocks forever and call `DiscordRPCService.start()` twice → the second call returns immediately and `service._connecting` stays `True`. What is missing: a live Discord that exhibits the wedge (not reproducible in this environment — no Discord client, and the app must not be run).
- **Suggested fix:** bound the whole connect attempt with a deadline (e.g. `asyncio.wait_for` around the handshake, or `connection_timeout` on the `Presence` constructor) and reset `_connecting` from a watchdog; add exponential backoff to the retry.
- **Fix side effects:** a slow-but-working Discord could be cut off → use a generous deadline (5–10 s) and retry.
- **Discovered by:** A

#### F-WN-26-14  [P3] — Disabling Discord RPC leaves the IPC connection open, so the reported status contradicts itself
- **File:** `core/services/discord_rpc.py:164-172`, `core/services/discord_rpc.py:174-183`; `core/api.py:3818-3844`
- **Confirmed:** yes
- **Description:** `AppApi.toggle_discord_rpc(False)` calls `self._core.discord_rpc.clear_presence()` — it never calls `stop()`. `clear_presence()` only clears the activity; `self.connected` stays `True` and the socket stays open. `get_discord_rpc_status()` then returns `{"enabled": False, "connected": True}`.
- **Cause:** "disabled" is implemented as "presence cleared" rather than "connection closed".
- **Trigger conditions:** the user turns the Discord switch off.
- **User impact:** the bridge reports a contradictory status; `update_presence()` also issues a redundant `rpc.clear()` on every subsequent track change (because `is_enabled()` is False but `self.connected` is still True, L97-100) → one wasted IPC round-trip per track.
- **Evidence:** `core/api.py:3833-3834` `else: self._core.discord_rpc.clear_presence()`; `core/services/discord_rpc.py:164-172` `clear_presence()` does not touch `self.connected`/`self.rpc`; `core/api.py:3843-3844` returns `enabled` and `connected` side by side.
- **Reproduction / verification:** `svc = DiscordRPCService(settings); svc.connected = True; svc.rpc = FakeRpc(); svc.clear_presence()` → `svc.connected` is still `True` and `svc.rpc` is still set.
- **Suggested fix:** `toggle_discord_rpc(False)` should call `discord_rpc.stop()` (or the service should disconnect when `is_enabled()` becomes false), so `connected` reflects reality.
- **Fix side effects:** re-enabling then has to reconnect (one connect attempt, ~ms) — acceptable.
- **Discovered by:** A

#### F-WN-26-15  [P3] — `DiscordRPCService.stop()` races an in-flight connect and can leave the service marked "connected" with no client
- **File:** `core/services/discord_rpc.py:51-85` (L68-85), `core/services/discord_rpc.py:174-183`
- **Confirmed:** yes (code path), timing-dependent
- **Description:** `stop()` does `self.rpc.close(); self.rpc = None; self.connected = False` without waiting for the `_connect` thread. If the connect thread finishes between `self.rpc.connect()` and `self.connected = True` (L71-72), it sets `self.connected = True` on a service whose `self.rpc` is now `None`. The next `update_presence()` takes the `if not self.connected` branch? No — it takes the *connected* branch and calls `self.rpc.update(...)` on `None` → `AttributeError` → caught at L160-162 → `self.connected = False` (self-healing, but the presence is silently dropped).
  Related: `stop()` closes the event loop that the connect thread may be running (`pypresence/presence.py:87-92` `self.loop.close()`), which raises inside the connect thread and is swallowed by the broad `except Exception`.
- **Cause:** `stop()` and the connect thread share `self.connected` / `self.rpc` without a join or a generation counter.
- **Trigger conditions:** the app is closed (or the RPC is toggled) while a connect attempt is in flight — a ~30 s window on a slow Discord.
- **User impact:** the presence is lost for that transition and the service briefly reports a false "connected"; on shutdown the Discord entry may keep the last track until the process exits.
- **Evidence:** `core/services/discord_rpc.py:71-73` `self.rpc.connect(); self.connected = True` (no lock) versus `:176-183` `self.rpc.close(); self.rpc = None; self.connected = False` (no lock, no join).
- **Reproduction / verification:** insert a `time.sleep` between `connect()` and `self.connected = True` in a test double and call `stop()` in that window → after `stop()` returns, `service.connected` flips back to `True` while `service.rpc is None`.
- **Suggested fix:** guard the connect result with a generation/attempt token and set `self.connected`/`self.rpc` under the lock; have `stop()` join the connect thread (bounded) or invalidate the in-flight attempt.
- **Fix side effects:** `stop()` may then block for the connect deadline → bound the join.
- **Discovered by:** A

#### F-WN-26-16  [P3] — An unclean exit leaves the elevated winws.exe and its WinDivert filter running, with no reaping at startup
- **File:** `services/zapret_service.py:1336-1407` (L1341-1353), `core/app.py:508-560` (L534-539, L553-554), `main.py:573-580`
- **Confirmed:** yes (the graceful path is correct; the unclean path has no handler)
- **Description:** the graceful exit path is correct: `main.py:575` → `app_core.cleanup()` → `core/app.py:553-554` `zapret.stop()`, which terminates the child (2 s wait), then kills the recorded PID with `taskkill /PID` (never `/IM`), verifies the image name first, and **keeps the pidfile when the kill fails** so the next launch can find it. But there is no handler for the abnormal exits: a crash, a Task Manager "End task", or the watchdog's `os._exit(3)` (`main.py:539`, which does call `cleanup()`) — for a hard kill the elevated `winws.exe` survives with the WinDivert driver loaded and the DPI-desync filter active for the app's host list until the user kills it manually or reboots. Nothing reaps such an orphan at startup: `start_zapret_if_enabled()` (`core/app.py:236-294`) only starts the bypass when the setting says so; it never checks for an orphan from a previous session. In addition, `stop()`'s elevated fallback (`services/zapret_service.py:703-705`, `ShellExecuteW(None, "runas", "taskkill.exe", …)`) can raise a **UAC prompt while the app is closing**.
- **Cause:** the "kill on exit" contract is implemented only for the graceful path; there is no "reap orphans on start" step and no machine-wide cleanup mechanism.
- **Trigger conditions:** the app is killed while the bypass is running, or the user turns the bypass off in the UI and then kills the app.
- **User impact:** traffic for YouTube/SoundCloud/etc. keeps being desynced after the player is gone, with no indication in the UI; and quitting the player can pop a UAC dialog.
- **Evidence:** `core/app.py:553-554` `_step("zapret.stop", self.zapret.stop)` — the only reaper; `services/zapret_service.py:703-705` the elevated taskkill; `core/app.py:236-294` — the autostart path never looks for an orphan.
- **Reproduction / verification:** start the bypass, kill the app with `Stop-Process -Force`, then `tasklist /FI "IMAGENAME eq winws.exe"` → the elevated process is still listed; the next app start shows it in the Zapret panel as "running" (via the pidfile/`_is_our_winws_process` path) while the setting may say "disabled".
- **Suggested fix:** on startup, compare the pidfile/cmd signature against the "zapret enabled" setting and offer (or perform, with the user's consent) to stop an orphan; suppress the UAC-elevated `taskkill` during shutdown.
- **Fix side effects:** killing an orphan on startup could stop a bypass another instance of the app is using → only do it when the single-instance guard proves this is the only instance.
- **Discovered by:** A

---

### 3. Clean areas

- **`_verify_zip_sha256` itself is sound** (`services/zapret_service.py:44-51`): SHA-256 over the full byte string, compared with `hmac.compare_digest` (constant-time for the hex digests), and the digest is checked **before** extraction in the path where a digest exists — `download_binaries()` verifies at L895 and extracts at L900; `update_zapret()` verifies at L978 and extracts at L988. The defect is the *caller* choosing an empty expectation (F-WN-26-1), not the primitive.
- **No zip-slip.** `_extract_zip()` reduces every member name with `os.path.basename(name)` (L844) before joining it to `self.app_dir`, so an entry named `../../evil.dll` lands as `evil.dll` *inside* `~/.nedotify/zapret`; there is no traversal outside the target directory. Members are additionally filtered to names containing `x86_64` and ending in `.exe`/`.dll`/`.sys` (L843).
- **The extracted artefact is validated before use.** `start()` runs `binary_integrity_error(exe)` (L1093) before any launch and re-downloads once if the binary is broken (L1094-1108); `validate_zapret_binary()` (L222-262) additionally rejects UNC paths, paths without a drive letter, names outside the approved set, and anything outside the allowed roots, before the **elevated** launch (L1270).
- **Shell metacharacters are rejected.** `sanitize_zapret_args()` uses `shlex.split` (not `str.split`) and then validates every token against `_ALLOWED_ARG_RE` (L90, L216-218). Verified by execution: `&`, `|`, `;`, backtick, `$(...)`, `>` and quoted strings are all rejected with "Недопустимый аргумент Zapret". The tokens are handed to `subprocess.Popen` **as a list** (L1167-1173) — no `shell=True` in the launch path — and the elevated path builds its command with `subprocess.list2cmdline(tokens)` (L1281) from the same validated list, so no injection into `cmd /c` is possible.
- **The launch itself does not flash a console.** `subprocess.Popen(..., creationflags=subprocess.CREATE_NO_WINDOW)` (L1172) — the omission is only in the scanner helpers (F-WN-26-4).
- **`_check_output_text` cannot die on console code pages**: it decodes with `out.decode("utf-8", errors="replace")` (L281), so a CP866/CP1251 `tasklist`/`wmic` output cannot raise `UnicodeDecodeError` and silently disable the PID scans; every exception is swallowed and returns `""` (L282-284). All match targets in the module are ASCII.
- **Every subprocess in the module has a timeout** (2.5–6 s) — no unbounded `check_output`/`run`.
- **`check_internet` is bounded and clean**: per-host socket timeout (L293), socket closed in `finally` (L297-303), and it is only ever called from the background status thread (`_build_status`, L1441), never from the bridge.
- **The Zapret process lifecycle on the graceful path is correct**: `stop()` terminates and reaps the child (L1342-1353), then resolves the PID through the pidfile + cmdline signature, re-verifies the image name before killing, uses `taskkill /PID` (never `/IM`) so foreign winws processes are untouched, and preserves the pidfile when a kill fails so the WinDivert driver lock is not silently forgotten (L1383-1393).
- **PID-reuse protection is real**: `_is_our_winws_process()` (L519-555) requires the image name to be in `_ALLOWED_BINARY_NAMES` **and** the executable path (or cmdline signature) to belong to this app before a PID is adopted or killed; `_pid_alive()` uses `OpenProcess`/`GetExitCodeProcess` and treats `ERROR_ACCESS_DENIED` as "alive" (correct for an elevated winws).
- **Lock discipline is sound**: `_lock` is an `RLock`; downloads/updates are serialised by a separate `_update_lock`; the acquisition order is always `_update_lock` → `_lock` (verified in `start()`, `download_binaries()`, `update_zapret()`, `stop()`) — no inversion, hence no deadlock. `get_status()` never blocks the UI: the expensive work happens in `_refresh_status_async()` (L1430-1435) and the result is cached for 2.5 s (L340).
- **The bypass is host-scoped, not machine-wide.** Every preset carries `--hostlist-domains={hosts}` (L81-84) with a fixed provider list (L63-75), and `tests/test_zapret_binary_integrity.py:335-352` pins that; the presets also pass the sanitiser (L355-362).
- **Discord RPC cannot break playback by exception.** `update_presence()` wraps the whole payload build/send in `try/except` (L113-162) and resets `self.connected` on failure; `start()`'s `_connect` catches everything (L79-81); and both call sites in `core/api.py` (L1228-1238, L1376-1396) wrap the call again. A missing `pypresence` module degrades to a single log line (L12-17, L53-57) instead of an exception.
- **The Discord RLock choice is correct and documented**: `update_presence()` → `start()` re-enters the same lock, which would self-deadlock with a plain `Lock` (L32-37).

---

### 4. Coverage gaps

- **The app was not run** (forbidden by the brief), so F-WN-26-4 (console flash) and the UAC-at-exit part of F-WN-26-16 are inferred from `setup_pyinstaller.spec:104 console=False` plus Windows subprocess semantics, not observed on screen. Same for the ~10–40 s bridge stall of F-WN-26-5 (derived from the code's own timeout values and the number of scans per call).
- **The zapret archive was not downloaded** (network + it would write into `~/.nedotify/`), so the actual member layout of the current release is unverified. F-WN-26-2 assumes the new release's `winws.exe` member name (after `basename`) matches the installed file name — true for the release the app installs today (the app works), but a layout change would change *which* files are replaced, not the conclusion that the currently-installed file is never replaced.
- **No live Discord client was available**, so F-WN-26-12/13/15 are derived from the installed `pypresence 4.6.2` source (`baseclient.py`, `presence.py`, `utils.py`) rather than from an observed stall; the "Discord accepts the pipe but never answers" precondition of F-WN-26-13 could not be produced here.
- **WinDivert's actual packet-level behaviour** (whether a host-scoped filter still perturbs other processes) is upstream zapret behaviour and was not measured; the report only assesses what this codebase configures.
- **The single-instance mutex, the installer and the packaging of the zapret bundle** (`installer.iss`, `setup_pyinstaller.spec` datas) were not reviewed — WN-01 — although `console=False` was read as a precondition for F-WN-26-4.
- **The UI half of F-WN-26-6** (no polling of `get_zapret_status`) and of F-WN-26-7 (the status card showing the configured vs. the used path) belongs to WN-30 and was only read, not reviewed.
- **No test file for the Discord service was found** in `tests/` — the reconnect, timeout and stop-race behaviour of `core/services/discord_rpc.py` is entirely unpinned, which is why the three Discord findings are reported from code reading rather than from a failing test.
