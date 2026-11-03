import importlib.util
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lock_checker_scans_production_roots_and_only_known_locks(tmp_path):
    module = _load("check_lock_nesting")
    assert module.ROOT == ROOT
    assert module.SCAN_PATHS == ("core", "services", "audio", "utils", "main.py")

    source = '''
import threading
class Example:
    def __init__(self):
        self.lock = threading.Lock()
        self.safe = threading.RLock()
        self.conn = object()
    def outer(self):
        with self.lock:
            self.inner()
    def inner(self):
        with self.lock:
            pass
    def nested(self):
        with self.safe:
            self.other()
    def other(self):
        with self.safe:
            pass
    def transaction(self):
        with self.conn:
            self.other()
'''
    import ast

    fixture = tmp_path / "fixture.py"
    fixture.write_text(source, encoding="utf-8")
    tree = ast.parse(source)
    scan = module.ClassScan(str(fixture))
    scan.visit(tree)
    assert scan.findings == [("Example", "outer", "inner", "lock")]


def test_shadow_checker_ignores_imports_nested_in_another_scope():
    module = _load("check_shadow_imports")
    import ast

    tree = ast.parse('''
import os
def clean():
    os.getcwd()
    def nested():
        import os
        return os.name
def broken():
    os.getcwd()
    import os
''')
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert module.local_imports(functions["clean"]) == set()
    assert module.used_before(functions["clean"], "os") == (None, None)
    assert module.local_imports(functions["broken"]) == {"os"}
    assert module.used_before(functions["broken"], "os")[0] < module.used_before(functions["broken"], "os")[1]


def _source_manifest_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "tools").mkdir()
    (root / "tests").mkdir()
    (root / "ui" / "web_new_v2" / "js").mkdir(parents=True)
    (root / "tests" / "test_one.py").write_text("pass\n", encoding="utf-8")
    (root / "ui" / "web_new_v2" / "js" / "one.js").write_text("void 0;\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "sources": {
            "desktop_tests": ["tests/test_one.py"],
            "desktop_ui_modules": ["ui/web_new_v2/js/one.js"],
        },
    }
    (root / "tools" / "source_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "tests/test_one.py", "ui/web_new_v2/js/one.js",
                    "tools/source_manifest.json"], cwd=root, check=True)
    return root


def test_source_manifest_checker_passes_complete_tracked_synthetic_checkout(tmp_path):
    module = _load("check_source_manifest")
    root = _source_manifest_repo(tmp_path)
    assert module.validate(root, require_tracked=True) == []


def test_source_manifest_checker_detects_omitted_and_missing_expected_files(tmp_path):
    module = _load("check_source_manifest")
    root = _source_manifest_repo(tmp_path)
    (root / "tests" / "test_two.py").write_text("pass\n", encoding="utf-8")
    errors = module.validate(root)
    assert any("Unlisted desktop_tests source file: tests/test_two.py" in error
               for error in errors)
    (root / "ui" / "web_new_v2" / "js" / "one.js").unlink()
    errors = module.validate(root)
    assert any("Manifest path is missing from checkout: ui/web_new_v2/js/one.js" in error
               for error in errors)


def test_source_manifest_checker_rejects_untracked_local_sources(tmp_path):
    module = _load("check_source_manifest")
    root = _source_manifest_repo(tmp_path)
    path = root / "tests" / "local_only.py"
    path.write_text("pass\n", encoding="utf-8")
    manifest_path = root / "tools" / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"]["desktop_tests"].append("tests/local_only.py")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    errors = module.validate(root, require_tracked=True)
    assert any("Untracked source file" in error and "tests/local_only.py" in error
               for error in errors)
