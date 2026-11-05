"""Offline regression tests for benchmark and packaging helpers."""

from __future__ import annotations

from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.bench.cdp import CDPError, WSClient  # noqa: E402
from tools.bench.run_pyprof import _link_parents  # noqa: E402
from tools.bench.api_stubs import install_benchmark_api_stubs  # noqa: E402
from tools.bench import scenarios  # noqa: E402
from tools.bench.scenarios import scenario_download, scenario_play, scenario_idle_states  # noqa: E402
from tools.bench.run_bench import aggregate  # noqa: E402
from tools.bench.paths import results_dir, visual_artifacts_dir  # noqa: E402
from tools.visual_guard import run_guard  # noqa: E402
LINUX_PACKAGING = runpy.run_path(str(ROOT / "packaging/linux_support.py"))


def test_native_cdp_transport_preserves_protocol_result_and_evaluation_errors(monkeypatch):
    import json
    import pytest
    from tools.bench.cdp import NativeWebViewClient

    class Func:
        def __class_getitem__(cls, item):
            return lambda fn: fn

    monkeypatch.setitem(sys.modules, 'System', SimpleNamespace(Func=Func, Object=object))
    commands = []
    response = {'result': {'type': 'number', 'value': 42}}

    def send(method, params):
        commands.append((method, json.loads(params)))
        return SimpleNamespace(IsCompleted=True, GetAwaiter=lambda:
            SimpleNamespace(GetResult=lambda: json.dumps(response)))

    control = SimpleNamespace(Invoke=lambda fn: fn(), CoreWebView2=SimpleNamespace(
        CallDevToolsProtocolMethodAsync=send))
    client = NativeWebViewClient(SimpleNamespace(native=SimpleNamespace(
        browser=SimpleNamespace(webview=control))))
    assert client.evaluate('6 * 7', await_promise=True) == 42
    assert commands == [('Runtime.evaluate', {
        'expression': '6 * 7', 'awaitPromise': True, 'returnByValue': True})]
    response.clear()
    response['exceptionDetails'] = {'text': 'Uncaught failure'}
    with pytest.raises(CDPError, match='Uncaught failure'):
        client.evaluate('throw new Error()')


def test_benchmark_readiness_waits_for_completion_event_not_init_entry():
    import json
    from tools.bench.bench_child import READY_HOOK_JS
    from tests.jsdom import run_node
    run_node('''
        import assert from 'node:assert/strict';
        globalThis.window = new EventTarget();
        window._nedotifyInitialized = true;
        eval(''' + json.dumps(READY_HOOK_JS) + ''');
        assert.equal(window.__benchAppReady, false);
        window.dispatchEvent(new Event('nedotify:app_ready'));
        assert.equal(window.__benchAppReady, true);
        assert.equal(typeof window.__benchAppReadyMs, 'number');
    ''')


def test_cdp_evaluate_surfaces_nested_runtime_exception():
    client = WSClient("ws://localhost:9222/devtools/page/test")
    client.call = lambda *args, **kwargs: {
        "result": {
            "result": {"type": "undefined"},
            "exceptionDetails": {"text": "Uncaught", "exception": {"description": "boom"}},
        }
    }
    try:
        client.evaluate("throw new Error('boom')")
    except CDPError as exc:
        assert "JS exception" in str(exc)
        assert "boom" in str(exc)
    else:
        raise AssertionError("Runtime.evaluate exceptionDetails was ignored")


def test_visual_capture_waits_only_for_visible_images():
    import json
    from tests.jsdom import run_node
    from tools.visual_guard.capture import _SETTLE_JS
    run_node('''
        import assert from 'node:assert/strict';
        globalThis.window = {devicePixelRatio: 2, innerWidth: 800, innerHeight: 600, dispatchEvent(){}};
        globalThis.innerWidth = 800;
        globalThis.innerHeight = 600;
        globalThis.requestAnimationFrame = fn => fn();
        globalThis.setTimeout = fn => { queueMicrotask(fn); return 1; };
        globalThis.clearTimeout = () => {};
        let listeners = 0;
        const rect = {width: 50, height: 50, top: 0, left: 0, bottom: 50, right: 50};
        const img = (complete, box) => ({complete,
          getBoundingClientRect: () => box,
          addEventListener: () => { listeners++; }, removeEventListener: () => {}});
        let entrancesFinished = 0, loopsPaused = 0;
        const entrance = {effect:{getComputedTiming:()=>({endTime:200})},finish(){entrancesFinished++;}};
        const loop = {effect:{getComputedTiming:()=>({endTime:Infinity})},pause(){loopsPaused++;}};
        globalThis.document = {dispatchEvent(){}, getAnimations: () => [entrance,loop], fonts: {ready: Promise.resolve(), status: 'loaded'},
          images: [img(true, rect), img(false, {...rect, top: 900, bottom: 950}),
                   img(false, {...rect, width: 0, height: 0})]};
        const settled = await eval(''' + json.dumps(_SETTLE_JS) + ''');
        assert.equal(settled.images, 1);
        assert.equal(settled.incomplete, 0);
        assert.equal(listeners, 0);
        assert.equal(entrancesFinished, 1);
        assert.equal(loopsPaused, 1);
        assert.equal(loop.currentTime, 0);
        document.images.push(img(false, rect));
        const timedOut = await eval(''' + json.dumps(_SETTLE_JS) + ''');
        assert.equal(timedOut.incomplete, 1);
        assert.equal(listeners, 2);
    ''')


def test_benchmark_aggregate_excludes_failed_repetitions():
    summary = aggregate([
        {"ok": True, "cold_start": {"elapsed": 10}, "child": {}},
        {"ok": False, "error": "failed", "cold_start": {"elapsed": 999}, "child": {}},
        {"ok": True, "cold_start": {"elapsed": 20}, "child": {}},
    ])
    assert summary["n_runs"] == 3
    assert summary["n_successful"] == 2
    assert summary["n_failed"] == 1
    assert summary["failures"] == ["failed"]
    assert summary["medians"]["cold_start.elapsed"] == 15


def test_packaging_spec_anchors_resources_and_collects_native_curl_libraries():
    spec = (ROOT / "setup_pyinstaller.spec").read_text(encoding="utf-8")
    assert "ROOT = Path(SPECPATH)" in spec
    assert 'ROOT / "icon.png"' in spec
    assert "binaries=binaries" in spec
    assert 'collect_dynamic_libs("curl_cffi")' in spec
    assert 'support["native_tools"]()' in spec
    assets = LINUX_PACKAGING["collect_ui_datas"](ROOT)
    assert any(path.endswith(".webp") for path, _ in assets)
    assert not any("backgrounds" in Path(path).parts and Path(path).suffix.lower() in {".jpg", ".jpeg"}
                   for path, _ in assets)


def test_native_tools_fail_closed_for_wrong_platform_missing_tools_and_windows_binaries(tmp_path, monkeypatch):
    import pytest
    native_tools = LINUX_PACKAGING["native_tools"]
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="on Linux"):
        native_tools()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(native_tools.__globals__["shutil"], "which", lambda _: None)
    with pytest.raises(RuntimeError, match="ELF ffmpeg"):
        native_tools()
    binary = tmp_path / "ffmpeg.exe"
    binary.write_bytes(b"MZ" + b"\0" * 128)
    monkeypatch.setattr(native_tools.__globals__["shutil"], "which", lambda _: str(binary))
    with pytest.raises(RuntimeError, match="ELF ffmpeg"):
        native_tools()


def test_installer_has_stable_identity_and_does_not_delete_install_folder():
    assert not (ROOT / "installer.iss").exists()
    desktop = ROOT / "packaging/org.nedotify.NeDotify.desktop"
    assert "Name=NeDotify" in desktop.read_text(encoding="utf-8")
    assert "Exec=/opt/nedotify/NeDotify" in desktop.read_text(encoding="utf-8")
    assert LINUX_PACKAGING["MANAGED_MARKER"] == "nedotify.linux.install.v1"
    # Updates select a new immutable release; the previous one stays available.
    source = (ROOT / "packaging/linux_support.py").read_text(encoding="utf-8")
    assert 'os.replace(pending, appdir / "current")' in source
    assert "shutil.rmtree(release" not in source


def test_benchmark_list_includes_every_supported_scenario():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "bench" / "run_bench.py"), "--list"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    listed = completed.stdout.split(":", 1)[1].split(",")
    expected = {"startup", "idle", "idle_states", "cpu_attribution", "scroll", "search", "feed", "play", "download", "audio", "combo"}
    assert {part.strip() for part in listed} == expected


def test_import_time_postorder_is_linked_to_parent_indices():
    rows = [
        {"name": "pkg.child", "depth": 2},
        {"name": "pkg", "depth": 1},
        {"name": "other", "depth": 1},
        {"name": "root", "depth": 0},
    ]
    _link_parents(rows)
    assert rows[0]["parent"] == 1
    assert rows[1]["parent"] == 3
    assert rows[2]["parent"] == 3
    assert rows[3]["parent"] is None


def test_visual_capture_writes_current_without_deleting_goldens():
    source = (ROOT / "tools" / "visual_guard" / "run_guard.py").read_text(encoding="utf-8")
    assert "capture(CURRENT, themes" in source
    assert "shutil.rmtree(GOLDENS" not in source


def test_generated_artifacts_default_to_temp_and_accept_explicit_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("NEDOTIFY_BENCH_OUT", raising=False)
    monkeypatch.delenv("NEDOTIFY_VISUAL_GUARD_OUT", raising=False)
    assert "NeDotify" in str(results_dir())
    assert "temp" in str(results_dir()).lower()
    assert visual_artifacts_dir() == results_dir().parent.parent / "visual_guard"

    bench_out = tmp_path / "bench"
    visual_out = tmp_path / "visual"
    monkeypatch.setenv("NEDOTIFY_BENCH_OUT", str(bench_out))
    monkeypatch.setenv("NEDOTIFY_VISUAL_GUARD_OUT", str(visual_out))
    assert results_dir() == bench_out.resolve()
    assert visual_artifacts_dir() == visual_out.resolve()


def test_capture_machine_manifest_records_reproducibility_inputs(monkeypatch):
    monkeypatch.setattr(run_guard, "_display_adapters", lambda: [{"name": "GPU", "driver_version": "1"}])
    monkeypatch.setattr(run_guard, "_webview2_runtime_version", lambda: "123.0")
    manifest = run_guard.capture_machine_manifest(["dark"], ["home"], [(1280, 720)], [1])
    assert manifest["schema"] == "nedotify.visual-capture-machine.v1"
    assert manifest["os"]
    assert manifest["python"]
    assert manifest["webview2_runtime"] == "123.0"
    assert manifest["display_adapters"][0]["name"] == "GPU"
    assert manifest["bundled_font_sha256"]
    assert manifest["themes"] == ["dark"]
    assert manifest["viewports"] == [[1280, 720]]


def test_benchmark_api_stubs_emit_search_feed_and_download_contracts(tmp_path):
    tracks = [
        {"id": 1, "source": "local", "file_path": str(tmp_path / "bench-audio.wav")},
        {"id": 2, "source": "youtube", "source_id": "fixture-2"},
    ]

    class Db:
        def get_library_page(self, limit=200, offset=0):
            return tracks[offset:offset + limit]

        def get_all_tracks(self):
            return tracks

        def get_track(self, track_id):
            return next((row for row in tracks if row["id"] == track_id), None)

        def mark_track_downloaded(self, track_id, path):
            next(row for row in tracks if row["id"] == track_id)["file_path"] = path

    class Api:
        def __init__(self):
            self._core = SimpleNamespace(db=Db())
            self.events = []

        def _emit(self, name, payload):
            self.events.append((name, payload))

    install_benchmark_api_stubs(Api, tmp_path)
    api = Api()
    assert api.search("fixture", "all")["tracks"] == tracks
    assert api.events[-1][0] == "search_completed"
    assert api.get_feed(1)["status"] == "pending"
    assert api.events[-1][0] == "feed_ready"
    assert api.download_track(tracks[1]) is True
    assert api.events[-1][0] == "download_complete"
    assert Path(tracks[1]["file_path"]).is_file()


class FakeCdpContext:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.sampler = SimpleNamespace(
            start=lambda: None, stop=lambda: [], samples=[], _last={},
            summary=lambda warmup=0: {}, _prime=lambda: None,
        )

    def js_async(self, expression, args_fmt="", timeout=60):
        self.calls.append((expression, args_fmt, timeout))
        return self.results.pop(0)

    def js(self, expression):
        return 0

    def perf_metrics(self):
        return {}


def test_new_play_download_and_idle_scenarios_report_real_completion_contracts(monkeypatch):
    play_ctx = FakeCdpContext([{"playing": True, "track_id": 1}])
    play = scenario_play(play_ctx)
    assert play["playing"] is True
    assert "silent local WAV" in play["fixture"]

    download_ctx = FakeCdpContext([{"completed": True, "track_id": 2}])
    download = scenario_download(download_ctx)
    assert download["completed"] is True
    assert "scratch-profile" in download["fixture"]

    # Keep this hermetic: the scenario's native window controls are not used
    # by the failure path and must not enumerate or manipulate desktop windows.
    monkeypatch.setattr(scenarios, "find_main_window", lambda: None)
    monkeypatch.setattr(scenarios.time, "sleep", lambda _seconds: None)
    idle_ctx = FakeCdpContext([{"playing": False, "error": "no wav"}])
    result = scenario_idle_states(idle_ctx, seconds=0.01)
    assert result["error"] == "no wav"
    assert "visible_idle" in result["states"]



def test_scroll_prepares_visible_collection_and_measures_its_real_scrollport():
    calls=[]
    class Context:
        def js_async(self,code,**kwargs):
            calls.append((code,kwargs))
            if code==scenarios.PREPARE_SCROLL_JS:return {'selector':'#actual-scrollport','mountedRows':40,'collectionLabel':'2000 треков'}
            return {'medianFrameMs':16.7,'derivedFps':59.9,'p95FrameMs':20,'worstFrameMs':25,'longFramesOver50ms':0,'scrollHeight':104000}
    result=scenarios.scenario_scroll(Context(),'#lib-active-tracks','library',1)
    assert calls[0][0]==scenarios.PREPARE_SCROLL_JS
    assert calls[1][1]['args_fmt']==repr('#actual-scrollport')
    assert result['mountedRows']==40 and result['collectionLabel']=='2000 треков'
    assert result['scrollHeight']==104000


def test_nested_scenario_failures_are_not_reported_as_successful_measurements():
    result={'scroll':[{'medianFrameMs':16.7},{'error':'list is hidden'}],'play':{'error':None}}
    assert scenarios.scenario_errors(result)==['data.scroll[1]: list is hidden']


def test_benchmark_search_preserves_request_identity(tmp_path):
    class Api:
        def __init__(self):
            self.events=[]
            self._core=SimpleNamespace(db=SimpleNamespace(get_library_page=lambda **kw:[]))
        def _emit(self,name,payload):self.events.append((name,payload))
    install_benchmark_api_stubs(Api,tmp_path)
    api=Api();api.search('Benchmark','all',None,'request-7')
    assert [p['request_id'] for _,p in api.events]==['request-7','request-7']
