"""Static check for self-deadlocking non-reentrant locks.

A method that holds `self.<lock>` and then calls a sibling method that takes
the same lock deadlocks forever. Three of those shipped in this project
(AppCore._service_lock, DiscordRPCService._lock and a Lock used across
evaluate_js) and each froze the UI, so the pattern is worth failing on.
"""
import ast
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SKIP = {
    ".venv_win", ".venv_win_backup", ".venv", "__pycache__", ".git",
    "tests", ".test_runs", "node_modules",
}


def locks_taken(node):
    """(lock attr, lineno range) for every `with self.<lock>` in this function."""
    out = []
    for sub in ast.walk(node):
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


def lock_kinds(path):
    """Map attribute name -> 'Lock' | 'RLock' for the locks defined in a file."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return {}
    kinds = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            name = None
            if isinstance(fn, ast.Attribute) and fn.attr in ("Lock", "RLock"):
                name = fn.attr
            elif isinstance(fn, ast.Name) and fn.id in ("Lock", "RLock"):
                name = fn.id
            if not name:
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                    kinds[tgt.attr] = name
    return kinds


def methods_called_in_span(fn, names, lo, hi):
    """Sibling-method calls that occur inside the given line range."""
    out = set()
    for sub in ast.walk(fn):
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
                if self.kinds.get(lock) == "RLock":
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
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except Exception:
                continue
            scan = ClassScan(path)
            scan.visit(tree)
            for cls, caller, other, lock in scan.findings:
                scan_findings.append((os.path.relpath(path, ROOT), cls, caller, other, lock))

    if not scan_findings:
        print("OK: no nested-lock self-deadlock patterns")
        return 0

    print("POTENTIAL self-deadlocks (non-reentrant Lock held across a same-lock call):")
    for rel, cls, caller, other, lock in scan_findings:
        print(f"  {rel}: {cls}.{caller}() holds self.{lock} and calls {other}()")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
