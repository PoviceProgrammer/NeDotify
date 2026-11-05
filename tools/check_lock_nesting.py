"""Static check for self-deadlocking non-reentrant locks.

A method that holds `self.<lock>` and then calls a sibling method that takes
the same lock deadlocks forever. Three of those shipped in this project
(AppCore._service_lock, DiscordRPCService._lock and a Lock used across
evaluate_js) and each froze the UI, so the pattern is worth failing on.
"""
import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_PATHS = ("core", "services", "audio", "utils", "main.py")
SKIP = {
    ".venv_win", ".venv_win_backup", ".venv", "__pycache__", ".git",
    "tests", ".test_runs", "node_modules",
}


def locks_taken(node):
    """(lock attr, lineno range) for every `with self.<lock>` in this function."""
    out = []
    for sub in _own_body(node):
        if isinstance(sub, (ast.With, ast.AsyncWith)):
            for item in sub.items:
                ctx = item.context_expr
                if (
                    isinstance(ctx, ast.Attribute)
                    and isinstance(ctx.value, ast.Name)
                    and ctx.value.id == "self"
                ):
                    out.append((ctx.attr, sub.lineno, sub.end_lineno))
    return out


def _own_body(fn):
    """Visit this function's statements without entering nested scopes."""
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    stack = list(reversed(fn.body))
    while stack:
        node = stack.pop()
        if isinstance(node, nested):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def lock_kinds(path):
    """Map attribute name -> 'Lock' | 'RLock' for the locks defined in a file."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return {}
    threading_names = {"threading"}
    lock_names = {"Lock", "RLock"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "threading":
                    threading_names.add(alias.asname or "threading")
        elif isinstance(node, ast.ImportFrom) and node.module == "threading":
            for alias in node.names:
                if alias.name in lock_names:
                    lock_names.add(alias.asname or alias.name)

    def lock_type(call):
        if not isinstance(call, ast.Call):
            return None
        fn = call.func
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            if fn.value.id in threading_names and fn.attr in ("Lock", "RLock"):
                return fn.attr
        if isinstance(fn, ast.Name) and fn.id in lock_names:
            return "RLock" if fn.id.lower().endswith("rlock") else "Lock"
        return None

    kinds = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            name = lock_type(node.value)
            if not name:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                    kinds[tgt.attr] = name
                elif isinstance(tgt, ast.Name):
                    kinds[tgt.id] = name
    return kinds


def methods_called_in_span(fn, names, lo, hi):
    """Sibling-method calls that occur inside the given line range."""
    out = set()
    for sub in _own_body(fn):
        if not (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id == "self"
            and sub.func.attr in names
        ):
            continue
        if lo <= sub.lineno <= (hi or lo):
            out.add(sub.func.attr)
    return out


class ClassScan(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.kinds = lock_kinds(path)
        self.findings = []

    def visit_ClassDef(self, node):
        methods = {
            item.name: item
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name, fn in methods.items():
            for lock, lo, hi in locks_taken(fn):
                if self.kinds.get(lock) != "Lock":
                    continue  # reentrant: safe
                called = methods_called_in_span(fn, methods, lo, hi)
                for other in called:
                    if other == name:
                        continue
                    if any(l == lock for l, _, _ in locks_taken(methods[other])):
                        self.findings.append((node.name, name, other, lock))
        self.generic_visit(node)


def main():
    scan_findings = []
    for relative in SCAN_PATHS:
        root = ROOT / relative
        if root.is_file():
            paths = [root]
        elif root.is_dir():
            paths = []
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP]
                paths.extend(Path(dirpath) / fn for fn in filenames if fn.endswith(".py"))
        else:
            continue
        for path in paths:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            scan = ClassScan(str(path))
            scan.visit(tree)
            for cls, caller, other, lock in scan.findings:
                scan_findings.append((path.relative_to(ROOT).as_posix(), cls, caller, other, lock))

    if not scan_findings:
        print("OK: no nested-lock self-deadlock patterns")
        return 0

    print("POTENTIAL self-deadlocks (non-reentrant Lock held across a same-lock call):")
    for rel, cls, caller, other, lock in scan_findings:
        print(f"  {rel}: {cls}.{caller}() holds self.{lock} and calls {other}()")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
