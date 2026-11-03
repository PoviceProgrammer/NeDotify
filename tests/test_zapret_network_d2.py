"""Zapret network/strategy/configuration fixes (audit D-scope: BUG-011, 012,
030, 031, 034, 036, 037, 042).

Hermetic by construction: no real network, no winws, no UAC. DNS tests run a
fake resolver and a fake DoH opener; service status tests fake every system
touchpoint. The winws flag set pinned here was verified against the PINNED
v72.13 sources (docs/readme.en.md, docs/windows.en.md, nfq/nfqws.c,
nfq/params.c, nfq/desync.c at tag v72.13).
"""

import json
import os
import shlex
import socket
import struct
import threading
import time

import pytest

import core.dns_fallback as dns_module
import services.zapret_service as m
from core.dns_fallback import DnsFallback, _looks_poisoned
from services.zapret_service import (
    PRESET_STRATEGIES,
    ZAPRET_SCOPED_HOSTS,
    ZapretService,
    sanitize_zapret_args,
)


# ─── fixtures & fakes ────────────────────────────────────────────────────────


class FakeProc:
    """Popen stand-in: alive forever (tests never wait on it)."""

    def __init__(self, pid=5555):
        self.pid = pid
        self.handle = 0
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0


def _pe_bytes():
    body = m._PE_MIN_SIZE + 64
    out = bytearray(b"MZ" + b"\x00" * 0x3A)
    out += struct.pack("<I", 0x40)
    out += b"PE\0\0" + struct.pack("<H", 0x8664)
    out += b"\x00" * (body - len(out))
    return bytes(out)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    service = ZapretService()
    monkeypatch.setattr(service, "app_dir", str(tmp_path / "zapret"), raising=False)
    monkeypatch.setattr(service, "pid_file",
                        os.path.join(str(tmp_path / "zapret"), "run.pid"), raising=False)
    monkeypatch.setattr(service, "cmd_file",
                        os.path.join(str(tmp_path / "zapret"), "run.cmd"), raising=False)
    os.makedirs(service.app_dir, exist_ok=True)
    monkeypatch.setattr(m, "_global_zapret_guard_acquire", lambda *a, **k: None)
    monkeypatch.setattr(m, "_global_zapret_guard_release", lambda handle: None)
    monkeypatch.setattr(ZapretService, "_classify_running_winws", lambda self: (None, None))
    monkeypatch.setattr(ZapretService, "_get_pending_update", lambda self: "")
    monkeypatch.setattr(ZapretService, "_scan_pids_with", lambda self, sig: [])
    monkeypatch.setattr(ZapretService, "_scan_all_winws_pids", lambda self: [])
    service._launch_confirm_window = 0.0
    return service


def _healthy_binary(svc, monkeypatch):
    path = os.path.join(svc.app_dir, "winws.exe")
    with open(path, "wb") as f:
        f.write(_pe_bytes())
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: path)
    return path


def _fake_launch(monkeypatch, launched):
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(args)
                        or ("started", FakeProc(), "ok"))


# ─── BUG-030: backslash-safe, quote-aware argument splitting ─────────────────


def test_backslashes_survive_the_split():
    # shlex.split(posix=True) silently erased them: a\b arrived as ab.
    toks = sanitize_zapret_args(r"--hostlist-domains=a\b --wf-tcp=80,443")
    assert toks == ["--hostlist-domains=a\\b", "--wf-tcp=80,443"]


def test_multiple_backslashes_survive_verbatim():
    raw = r"--hostlist-domains=a\\b\c"
    assert sanitize_zapret_args(raw) == ["--hostlist-domains=a\\\\b\\c"]


def test_quotes_group_without_escaping():
    toks = sanitize_zapret_args('"--hostlist-domains=a,b" --wf-tcp=80,443')
    assert toks == ["--hostlist-domains=a,b", "--wf-tcp=80,443"]


def test_backslashes_inside_quotes_stay_verbatim():
    raw = '"--hostlist-domains=a\\b,c"'
    assert sanitize_zapret_args(raw) == ["--hostlist-domains=a\\b,c"]


def test_quote_inside_a_token_is_grouping_not_a_error():
    assert sanitize_zapret_args('--dpi-desync="fake,split2"') == ["--dpi-desync=fake,split2"]


def test_unclosed_quote_is_a_hard_error():
    with pytest.raises(ValueError):
        sanitize_zapret_args('"--wf-tcp=80,443')


def test_tab_and_newline_separate_tokens():
    toks = sanitize_zapret_args('--wf-tcp=80,443\t--filter-tcp=80,443\n--new')
    assert toks == ["--wf-tcp=80,443", "--filter-tcp=80,443", "--new"]


def test_whitespace_only_input_is_refused_not_silently_empty():
    # An empty token list would hand winws its default whole-machine filter.
    with pytest.raises(ValueError):
        sanitize_zapret_args("   ")


def test_empty_input_stays_empty():
    assert sanitize_zapret_args("") == []


def test_injection_attempts_still_rejected():
    for raw in ("--hostlist-domains=a;rm -rf /",
                "--wf-tcp=80,443 && evil",
                "--wf-tcp=80,443 | evil",
                "--hostlist-domains=`evil`",
                "--wf-tcp=$(evil)",
                "--hostlist-domains=a\nb"):
        with pytest.raises(ValueError):
            sanitize_zapret_args(raw)


def test_allowlist_still_gates_every_option():
    with pytest.raises(ValueError):
        sanitize_zapret_args("--definitely-not-a-winws-flag=1")
    with pytest.raises(ValueError):
        # File-backed hostlists stay forbidden (unvalidatable content).
        sanitize_zapret_args("--hostlist=C:\\evil\\list.txt")


def test_v7213_verified_l3_flags_accepted():
    # Verified against tag v72.13 docs: --wf-l3 / --filter-l3 exist,
    # --wf-ipv6 does NOT (both L3 protocols are filtered by default).
    assert sanitize_zapret_args("--wf-l3=ipv4,ipv6 --filter-l3=ipv4") == [
        "--wf-l3=ipv4,ipv6", "--filter-l3=ipv4"]
    with pytest.raises(ValueError):
        sanitize_zapret_args("--wf-ipv6=1")


def test_splitter_matches_shlex_byte_for_byte_on_every_preset():
    """D2 review (BUG-030): the hand splitter replaced shlex.split(posix=True);
    on every legitimate preset the two token streams must be IDENTICAL, so no
    preset's meaning can drift because of the parser swap."""
    for name, template in PRESET_STRATEGIES.items():
        raw = template.format(hosts=",".join(ZAPRET_SCOPED_HOSTS))
        assert m._split_winws_args(raw) == shlex.split(raw, posix=True), (
            f"preset {name!r} tokenizes differently under the new splitter")


def test_splitter_matches_shlex_on_plain_custom_args():
    plain = ("--wf-tcp=80,443 --filter-tcp=80,443 --hostlist-domains=example.com "
             "--dpi-desync=fake,split2 --dpi-desync-split-pos=1,5 "
             "--dpi-desync-fooling=badseq --dpi-desync-repeats=6")
    assert m._split_winws_args(plain) == shlex.split(plain, posix=True)


def test_empty_quotes_collapse_into_a_refusal_not_a_launch():
    # `""` alone dequotes to NOTHING: launching with an empty argv would hand
    # winws its default whole-machine filter — refuse instead.
    with pytest.raises(ValueError):
        sanitize_zapret_args('""')


def test_empty_quotes_next_to_a_valid_token_do_not_smuggle_a_token():
    toks = sanitize_zapret_args('--wf-tcp=80,443 ""')
    # The empty token vanishes (it could never pass the grammar anyway) and
    # the surviving tokens are exactly the validated ones.
    assert toks == ["--wf-tcp=80,443"]


def test_value_with_equals_sign_inside_is_rejected():
    # `=` is not in the value character class: a second '=' cannot widen the
    # option name past the allowlist.
    with pytest.raises(ValueError):
        sanitize_zapret_args("--hostlist-domains=a=b")


def test_comma_split_pos_value_passes():
    assert sanitize_zapret_args("--dpi-desync-split-pos=1,5") == [
        "--dpi-desync-split-pos=1,5"]


def test_nested_and_adjacent_quotes_group_like_shlex():
    assert m._split_winws_args('"a""b" --wf-tcp=80,443') == ["ab", "--wf-tcp=80,443"]
    assert m._split_winws_args("--wf-tcp=80,443") == shlex.split("--wf-tcp=80,443")


def test_mixed_quote_styles_are_literal_inside_the_other_quote():
    # A single quote inside double quotes (and vice versa) is content, and the
    # grammar then rejects the metacharacter — no path reaches the launcher.
    with pytest.raises(ValueError):
        sanitize_zapret_args('"--hostlist-domains=a\'b"')
    with pytest.raises(ValueError):
        sanitize_zapret_args("'--hostlist-domains=a\"b'")


def test_long_input_splits_in_one_linear_pass():
    raw = " ".join(["--wf-tcp=80,443"] * 4000)
    toks = m._split_winws_args(raw)
    assert len(toks) == 4000 and toks[0] == "--wf-tcp=80,443"


# ─── BUG-031: custom / unknown modes must not fall back to a preset ──────────


def test_custom_mode_with_empty_args_is_refused(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    launched = []
    _fake_launch(monkeypatch, launched)

    ok, msg = svc.start(mode="custom", custom_args="   ")
    assert ok is False and launched == []
    assert "custom" in msg and "аргумент" in msg


def test_unknown_mode_is_refused_and_lists_available_modes(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    launched = []
    _fake_launch(monkeypatch, launched)

    ok, msg = svc.start(mode="youtube_discord_legacy_v1")
    assert ok is False and launched == []
    for name in list(PRESET_STRATEGIES) + ["custom"]:
        assert name in msg, f"available mode {name!r} must be listed"


def test_empty_mode_string_is_refused_not_silently_defaulted(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    launched = []
    _fake_launch(monkeypatch, launched)
    ok, _ = svc.start(mode="")
    assert ok is False and launched == []


def test_valid_preset_still_launches(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    launched = []
    _fake_launch(monkeypatch, launched)
    ok, _ = svc.start(mode="tcp_udp")
    assert ok is True
    assert len(launched) == 1 and "--filter-udp=443" in launched[0]


def test_unknown_mode_refuses_before_any_binary_download(svc, monkeypatch):
    """D2 (BUG-031 ordering): a stale mode saved in the settings DB must be
    refused BEFORE find_binary()/download_binaries() — the old order made
    autostart pay the full bundle download for a mode it could never launch."""
    downloads = []
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: None)
    monkeypatch.setattr(ZapretService, "download_binaries",
                        lambda self: downloads.append(1) or (True, "downloaded"))

    ok, msg = svc.start(mode="youtube_discord_legacy_v1")
    assert ok is False
    assert "Неизвестный режим" in msg and downloads == []


def test_custom_empty_args_refuse_before_any_binary_download(svc, monkeypatch):
    downloads = []
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: None)
    monkeypatch.setattr(ZapretService, "download_binaries",
                        lambda self: downloads.append(1) or (True, "downloaded"))

    ok, msg = svc.start(mode="custom", custom_args="  ")
    assert ok is False and "custom" in msg and downloads == []


def test_every_legit_saved_mode_still_launches(svc, monkeypatch):
    """Regression for the BUG-031 fail-closed rewrite: every mode value the UI
    or an older build can legitimately persist (all presets + custom with
    valid args) must still start."""
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    launched = []
    _fake_launch(monkeypatch, launched)

    ok_custom_args = ("--wf-tcp=80,443 --filter-tcp=80,443 "
                      "--hostlist-domains=example.com --dpi-desync=fake")
    for mode in list(PRESET_STRATEGIES) + ["custom"]:
        ok, msg = svc.start(mode=mode,
                            custom_args=ok_custom_args if mode == "custom" else "")
        assert ok is True, f"legit saved mode {mode!r} must still launch: {msg}"
    assert len(launched) == len(PRESET_STRATEGIES) + 1


def test_mode_refusal_leaves_the_state_machine_clean(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    _fake_launch(monkeypatch, [])
    ok, _ = svc.start(mode="bogus_mode")
    assert ok is False
    assert svc._state == m._STATE_STOPPED, "a refused start must not wedge STARTING"
    # And the service still accepts a valid command afterwards.
    ok, _ = svc.start(mode="standard")
    assert ok is True and svc._state == m._STATE_RUNNING


# ─── BUG-012: QUIC/UDP coverage, honest preset matrix ────────────────────────

# Every desync mode name winws v72.13 accepts (nfq/desync.c,
# desync_mode_from_string). A preset with anything else would die at launch.
_V72_13_DESYNC_MODES = {
    "fake", "fakeknown", "rst", "rstack", "synack", "syndata",
    "disorder", "split", "split2", "disorder2",
    "multisplit", "multidisorder", "hostfakesplit",
    "ipfrag2", "hopbyhop", "destopt", "ipfrag1", "udplen", "tamper",
}


def _preset_tokens(name):
    return sanitize_zapret_args(
        PRESET_STRATEGIES[name].format(hosts=",".join(ZAPRET_SCOPED_HOSTS)))


def test_every_preset_uses_only_v7213_desync_modes():
    for name in PRESET_STRATEGIES:
        for tok in _preset_tokens(name):
            if tok.startswith("--dpi-desync="):
                modes = tok.split("=", 1)[1].split(",")
                for mode in modes:
                    assert mode in _V72_13_DESYNC_MODES, (
                        f"preset {name!r} uses mode {mode!r} absent from winws v72.13")


def test_original_presets_are_tcp_only():
    for name in ("youtube_discord", "standard", "aggressive", "multisplit"):
        toks = _preset_tokens(name)
        opts = {t.split("=", 1)[0] for t in toks}
        assert "--wf-udp" not in opts and "--filter-udp" not in opts, (
            f"preset {name!r} changed its documented TCP-only coverage")
        assert "--wf-tcp=80,443" in toks and "--filter-tcp=80,443" in toks


def test_tcp_udp_preset_adds_a_quic_profile():
    toks = _preset_tokens("tcp_udp")
    assert "--wf-udp=443" in toks and "--filter-udp=443" in toks
    assert "--new" in toks
    split = toks.index("--new")
    tcp_profile, udp_profile = toks[:split], toks[split + 1:]
    # Profile 1: TCP only, standard strategy, app hostlist pinned.
    assert "--filter-tcp=80,443" in tcp_profile
    assert "--dpi-desync=fake,split2" in tcp_profile
    assert "--filter-udp" not in {t.split("=", 1)[0] for t in tcp_profile}
    # Profile 2: UDP only — the documented v72.13 QUIC shape
    # (readme.en.md: --filter-udp=443 --dpi-desync=fake --dpi-desync-repeats=6).
    assert "--filter-udp=443" in udp_profile
    assert "--dpi-desync=fake" in udp_profile and "--dpi-desync-repeats=6" in udp_profile
    assert "--filter-tcp" not in {t.split("=", 1)[0] for t in udp_profile}
    # Both profiles pin the SAME app hostlist (no unscoped desync).
    hostlists = [t.split("=", 1)[1] for t in toks if t.startswith("--hostlist-domains=")]
    assert hostlists == [",".join(ZAPRET_SCOPED_HOSTS)] * 2


def test_ui_mode_select_offers_exactly_the_presets():
    """BUG-012 UI half (static): every preset must have an <option> and no
    option may name a strategy the service does not know — a value the select
    offers but start() refuses is a silent toggle failure."""
    import re
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             os.pardir, "ui", "web_new_v2", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    select_match = re.search(
        r'<select[^>]*id="select-zapret-mode".*?</select>', html, re.DOTALL)
    assert select_match, "the Zapret mode select disappeared from index.html"
    values = re.findall(r'<option value="([^"]+)"', select_match.group(0))
    assert sorted(values) == sorted(PRESET_STRATEGIES), (
        f"UI options {values} drifted from PRESET_STRATEGIES {sorted(PRESET_STRATEGIES)}")


# ─── BUG-037: the status probe and honest messages ───────────────────────────


def test_status_probe_target_is_inside_the_scoped_hostlist():
    assert m._STATUS_PROBE_HOST in ZAPRET_SCOPED_HOSTS
    assert m._STATUS_PROBE_PORT == 443


def test_probe_reports_true_when_something_listens(monkeypatch):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        monkeypatch.setattr(m, "_STATUS_PROBE_HOST", "127.0.0.1")
        monkeypatch.setattr(m, "_STATUS_PROBE_PORT", srv.getsockname()[1])
        assert m._probe_covered_host(timeout=1.0) is True
    finally:
        srv.close()


def test_probe_reports_false_when_nothing_listens(monkeypatch):
    monkeypatch.setattr(m, "_STATUS_PROBE_HOST", "127.0.0.1")
    monkeypatch.setattr(m, "_STATUS_PROBE_PORT", 1)  # reserved port, no listener
    assert m._probe_covered_host(timeout=0.5) is False


def _running_status_service(svc, monkeypatch, *, running=True, has_net=True,
                            probe=True, version="v72.13", pending=""):
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: "C:\\fake\\winws.exe")
    monkeypatch.setattr(ZapretService, "is_running", lambda self: running)
    monkeypatch.setattr(ZapretService, "get_local_version", lambda self: version)
    monkeypatch.setattr(ZapretService, "_get_pending_update", lambda self: pending)
    monkeypatch.setattr(m, "check_internet", lambda timeout=1.5: has_net)
    monkeypatch.setattr(m, "_probe_covered_host", lambda timeout=1.5: probe)
    return svc


def test_running_status_does_not_claim_the_bypass_works(svc, monkeypatch):
    _running_status_service(svc, monkeypatch, probe=True)
    svc._build_status()
    message = svc._status_cache["message"]
    assert "активен" not in message, "process up ≠ bypass proven"
    assert "v72.13" in message
    assert "вживую" in message, "the honest limitation must be stated"


def test_running_status_reports_unreachable_app_domains(svc, monkeypatch):
    _running_status_service(svc, monkeypatch, probe=False)
    svc._build_status()
    message = svc._status_cache["message"]
    assert "не отвечают" in message
    assert "не работает" in message


# ─── BUG-036: one-shot network issue event ───────────────────────────────────


def test_network_issue_event_fires_once_per_transition(svc, monkeypatch):
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))

    _running_status_service(svc, monkeypatch, has_net=True)
    svc._build_status()  # first observation: baseline, no event
    assert events == []

    monkeypatch.setattr(m, "check_internet", lambda timeout=1.5: False)
    svc._build_status()
    assert [n for n, _ in events] == ["zapret_network_issue"]
    assert events[0][1].get("running") is True and events[0][1].get("message")

    svc._build_status()  # outage persists: no spam
    svc._build_status()
    assert len(events) == 1

    monkeypatch.setattr(m, "check_internet", lambda timeout=1.5: True)
    svc._build_status()  # recovery re-arms the tracker
    monkeypatch.setattr(m, "check_internet", lambda timeout=1.5: False)
    svc._build_status()
    assert len(events) == 2


def test_network_issue_event_does_not_fire_when_stopped(svc, monkeypatch):
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))
    _running_status_service(svc, monkeypatch, running=False, has_net=False)
    svc._build_status()
    assert events == []
    # A later start with broken connectivity is a fresh observation.
    _running_status_service(svc, monkeypatch, running=True, has_net=False)
    svc._build_status()
    assert events == [], "first observation after a restart must not alarm"


def test_first_ever_observation_of_running_without_net_is_not_an_event(svc, monkeypatch):
    """BUG-036 (D2 review): the very first _build_status after app start sees
    `previous is None`, not a True->False transition — it must establish the
    baseline silently, not alarm (D2 test pins the stricter behavior)."""
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))
    _running_status_service(svc, monkeypatch, running=True, has_net=False)
    svc._build_status()
    assert events == []
    assert svc._last_network_ok is False
    # A later recovery -> outage pair DOES fire the one-shot event.
    _running_status_service(svc, monkeypatch, running=True, has_net=True)
    svc._build_status()
    _running_status_service(svc, monkeypatch, running=True, has_net=False)
    svc._build_status()
    assert [n for n, _ in events] == ["zapret_network_issue"]


# ─── BUG-042: monotonic status TTL ───────────────────────────────────────────


def _wait_for(calls, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)


def test_stale_by_monotonic_cache_triggers_refresh(svc, monkeypatch):
    calls = []
    monkeypatch.setattr(ZapretService, "_build_status", lambda self: calls.append(1))
    svc._status_cache = {"running": False, "message": "stale"}
    svc._status_cache_time = time.monotonic() - (svc._status_ttl + 1.0)
    svc.get_status()
    _wait_for(calls)
    assert calls, "a stale cache must trigger a background refresh"
    svc._status_thread.join(2)


def test_fresh_monotonic_cache_is_served_without_refresh(svc, monkeypatch):
    calls = []
    monkeypatch.setattr(ZapretService, "_build_status", lambda self: calls.append(1))
    svc._status_cache = {"running": False, "message": "fresh"}
    svc._status_cache_time = time.monotonic()
    out = svc.get_status()
    assert out["message"] == "fresh"
    time.sleep(0.15)
    assert not calls


def test_backward_wall_clock_jump_cannot_pin_a_stale_cache(svc, monkeypatch):
    """The old wall-clock TTL served a stale cache for the whole duration of a
    backward wall-clock jump (now - stamp stayed negative and below the TTL).
    The monotonic TTL must not even look at time.time(): with the wall clock
    simulated 1 h in the past, a cache older than the TTL on monotonic time is
    still refreshed (a wall-clock TTL would have read the stamp as "in the
    future" and served the stale cache)."""
    calls = []
    monkeypatch.setattr(ZapretService, "_build_status", lambda self: calls.append(1))
    real_time = time.time
    svc._status_cache = {"running": False, "message": "stale"}
    svc._status_cache_time = time.monotonic() - (svc._status_ttl + 1.0)
    monkeypatch.setattr(time, "time", lambda: real_time() - 3600.0)
    try:
        svc.get_status()
        _wait_for(calls)
    finally:
        monkeypatch.undo()
    assert calls, "a backward wall-clock jump must not extend the cache TTL"
    svc._status_thread.join(2)


# ─── BUG-034: DNS sinkhole detection → DoH fallback ──────────────────────────

_PUBLIC = ("142.250.74.110", 443)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return json.dumps(self._payload).encode("utf-8")


class _FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append(request.full_url)
        return _FakeResponse(self.payload)


def _make_fallback(map_by_name, errors=(), doh_payload=None):
    """resolver returns map_by_name[host]; hosts in *errors* raise gaierror."""
    errors = tuple(errors)

    def resolver(host, port=None, family=0, type=0, proto=0, flags=0):
        if host in errors:
            raise socket.gaierror(11001, "getaddrinfo failed")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (map_by_name[host], port or 0))]

    opener = _FakeOpener(doh_payload if doh_payload is not None else
                         {"Answer": [{"name": "x", "type": 1, "TTL": 60, "data": _PUBLIC[0]}]})
    return DnsFallback(resolver, opener=opener), opener


def test_gaierror_still_falls_back_to_doh():
    fb, opener = _make_fallback({_PUBLIC[0]: _PUBLIC[0]}, errors=("youtube.com",))
    result = fb.getaddrinfo("youtube.com", 443)
    assert opener.calls, "hard DNS failure must query DoH"
    assert result[0][4][0] == _PUBLIC[0]


def test_clean_public_answer_skips_doh():
    fb, opener = _make_fallback({"youtube.com": _PUBLIC[0]})
    result = fb.getaddrinfo("youtube.com", 443)
    assert result[0][4][0] == _PUBLIC[0]
    assert opener.calls == [], "a healthy answer must not pay a DoH round-trip"


@pytest.mark.parametrize("poisoned_ip", [
    "127.0.0.1", "0.0.0.0", "10.1.2.3", "172.16.0.9", "192.168.1.1",
    "100.64.0.1", "169.254.1.2", "::1", "fe80::1", "fc00::1",
])
def test_sinkhole_answers_trigger_doh(monkeypatch, poisoned_ip):
    monkeypatch.setattr(dns_module, "_PRIVATE_ADDRESS_ALLOWLIST", frozenset())
    fb, opener = _make_fallback({"youtube.com": poisoned_ip, _PUBLIC[0]: _PUBLIC[0]})
    result = fb.getaddrinfo("youtube.com", 443)
    assert opener.calls, f"{poisoned_ip} must be recognised as a sinkhole answer"
    assert result[0][4][0] == _PUBLIC[0], "the DoH answer must replace the poisoned one"


@pytest.mark.parametrize("poisoned_ip", [
    "::ffff:127.0.0.1",   # loopback in an IPv4-mapped IPv6 mask (D2 review)
    "::ffff:10.0.0.5",    # RFC1918 mapped
    "255.255.255.255",    # broadcast
    "240.0.0.1",          # reserved class E
    "224.0.0.1",          # multicast
    "ff02::1",            # IPv6 multicast
])
def test_mapped_broadcast_and_multicast_answers_trigger_doh(monkeypatch, poisoned_ip):
    monkeypatch.setattr(dns_module, "_PRIVATE_ADDRESS_ALLOWLIST", frozenset())
    fb, opener = _make_fallback({"youtube.com": poisoned_ip, _PUBLIC[0]: _PUBLIC[0]})
    result = fb.getaddrinfo("youtube.com", 443)
    assert opener.calls, f"{poisoned_ip} must be recognised as a sinkhole answer"
    assert result[0][4][0] == _PUBLIC[0]


def test_nat64_prefix_is_not_flagged(monkeypatch):
    """D2 review, documented decision: on an IPv6-only network with DNS64 the
    HONEST OS answer for an A-only domain is 64:ff9b-prefixed — flagging it
    would break those networks for no detection gain."""
    fb, opener = _make_fallback({"youtube.com": "64:ff9b::7f00:1"})
    result = fb.getaddrinfo("youtube.com", 443)
    assert opener.calls == []
    assert result[0][4][0] == "64:ff9b::7f00:1"


def test_doh_answer_is_what_the_cache_serves(monkeypatch):
    """The poisoned OS answer must never be cached: the repeat lookup within
    the DoH TTL is served the DoH answer even though the (still poisoned)
    OS resolver keeps returning the sinkhole."""
    fb, opener = _make_fallback({"youtube.com": "127.0.0.1", _PUBLIC[0]: _PUBLIC[0]})
    first = fb.getaddrinfo("youtube.com", 443)
    second = fb.getaddrinfo("youtube.com", 443)
    assert len(opener.calls) == 1
    assert first[0][4][0] == second[0][4][0] == _PUBLIC[0]


def test_poisoned_answer_is_kept_when_doh_cannot_answer():
    fb, opener = _make_fallback({"youtube.com": "127.0.0.1"},
                                doh_payload={"Answer": []})
    result = fb.getaddrinfo("youtube.com", 443)
    assert opener.calls
    assert result[0][4][0] == "127.0.0.1", "no DoH answer → degrade to the OS result, never raise"


def test_poisoned_lookup_reuses_the_cache():
    fb, opener = _make_fallback({"youtube.com": "127.0.0.1", _PUBLIC[0]: _PUBLIC[0]})
    fb.getaddrinfo("youtube.com", 443)
    fb.getaddrinfo("youtube.com", 443)
    assert len(opener.calls) == 1, "single-flight/cache must serve the repeat"


def test_private_address_allowlist_exempts_a_domain(monkeypatch):
    monkeypatch.setattr(dns_module, "_PRIVATE_ADDRESS_ALLOWLIST",
                        frozenset({"internal.example"}))
    fb, opener = _make_fallback({"internal.example": "10.0.0.5"})
    result = fb.getaddrinfo("internal.example", 443)
    assert opener.calls == []
    assert result[0][4][0] == "10.0.0.5"


def test_single_label_names_never_look_poisoned():
    fb, opener = _make_fallback({"myhost": "127.0.0.1"})
    result = fb.getaddrinfo("myhost", 443)
    assert opener.calls == []
    assert result[0][4][0] == "127.0.0.1"


def test_ip_literal_success_bypasses_the_heuristic():
    fb, opener = _make_fallback({"127.0.0.1": "127.0.0.1"})
    result = fb.getaddrinfo("127.0.0.1", 443)
    assert opener.calls == []
    assert result[0][4][0] == "127.0.0.1"


def test_ip_literal_failure_still_raises_without_doh():
    fb, opener = _make_fallback({}, errors=("127.0.0.1",))
    with pytest.raises(socket.gaierror):
        fb.getaddrinfo("127.0.0.1", 443)
    assert opener.calls == []


def test_heuristic_helpers_directly():
    assert _looks_poisoned("youtube.com",
                           [(socket.AF_INET, 1, 6, "", ("127.0.0.1", 443))]) is True
    assert _looks_poisoned("youtube.com",
                           [(socket.AF_INET, 1, 6, "", (_PUBLIC[0], 443))]) is False
    assert _looks_poisoned("sub.localhost",
                           [(socket.AF_INET, 1, 6, "", ("127.0.0.1", 443))]) is False
    assert _looks_poisoned("youtube.com", []) is False
    # A malformed entry inside the answer tuple must not crash the screen.
    assert _looks_poisoned("youtube.com", [(socket.AF_INET, 1, 6, "", ())]) is False
    assert _looks_poisoned("youtube.com",
                           [(socket.AF_INET, 1, 6, "", ("garbage", 443))]) is False


def test_running_status_stays_neutral_when_the_probe_cannot_run(svc, monkeypatch):
    _running_status_service(svc, monkeypatch, probe=None)
    svc._build_status()
    message = svc._status_cache["message"]
    assert "отвечают" not in message, "an unrun probe must claim nothing"
    assert "вживую" in message and "v72.13" in message
