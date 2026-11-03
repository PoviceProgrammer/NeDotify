# Windows audit remediation — integration test contracts

Scope: test fixtures and regression contracts in `tests/conftest.py`,
`tests/test_api_audit_b.py`, `tests/test_emit_thread_safety.py`,
`tests/test_measured_listening.py`, and `tests/test_db_core_fixes_f2.py`.
Production files were outside this subtask. No application or GUI was launched.

## Updated contracts

| Finding / area | Test change |
|---|---|
| AUD-004, AUD-005, AUD-358 — shared URL safety | DNS cache expiry, bound, host separation, and concurrent warm-cache behavior now exercise `utils.url_safety`; proxy identity and the API compatibility wrapper are checked against the shared guard. The old API-private cache is no longer used by these assertions. |
| AUD-008 — storage clear boundary | `clear_storage("all")` must be confirmed. The confirmed path test places one downloaded track inside the redirected app downloads directory, one outside it, and one local track; only the app-owned download may be removed. |
| AUD-112 — cache quota units | Tests use explicit GB (`quota_gb` / `cache_quota_gb`) and MB (`cache_size_mb`) inputs. A value of 500 GB remains 500 GB; no magnitude heuristic is assumed. |
| AUD-515 / AUD-517 — playback resolution | Resolver tests use a real active queue row and await the returned Future. Online playback runs through the real `AudioEngine` callback with only its resolver stubbed. Missing local paths are rejected before queue insertion; recovered cache files and direct existing file paths are tested through the resolver callback. |
| AUD-020 — test profile isolation | The shared core fixture now contains a real `AudioEngine` linked to its `app_core`, while retaining the fixture's temporary DB and settings/provider stubs. Existing autouse HOME/USERPROFILE redirection remains in force. |
| AUD-533 — bridge cleanup fixture | The cleanup test stubs both shared service executors so teardown does not permanently shut down global pools for later tests. |
| Emit FIFO | Tests wait on a `threading.Event` signaled by the fake window after `evaluate_js`; queued delivery is no longer assumed synchronous. |
| Measured listening | The helper places the current track in the real engine queue and points it at a temporary existing file before calling `_on_track_changed`, ensuring a ready stream without invoking a provider. |

## Verification

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_emit_thread_safety.py tests/test_measured_listening.py tests/test_api_audit_b.py tests/test_db_core_fixes_f2.py tests/test_api_search.py
```

Result: **135 passed**. The test output includes expected settings-flush
warnings from tests that deliberately simulate closed or failed database
writers. No test used a live provider or opened the application window.

The audit's resolver and storage changes are exercised at the bridge/engine
boundary, but this test report does not claim manual WebView playback or UI
confirmation-dialog verification.
