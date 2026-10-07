"""Static check for function-local imports that shadow a module-level name.

`import threading` inside a function makes `threading` a LOCAL name for the
whole function body. Any earlier use of it then raises
`UnboundLocalError: cannot access local variable ...`, which in
`core/proxy.py:do_GET` killed every proxied stream request right at the
cache-tag line.
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {
    ".venv_win", ".venv_win_backup", ".venv", "__pycache__", ".git",
    "tests", ".test_runs", "node_modules", "tools",
}


def module_level_imports(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
    return names


def _own_body(fn):
    """Walk a function's own body, NOT descending into nested defs/lambdas.

    A nested function's local import only shadows within itself, so including it
    would flag every helper that merely imports os.
    """
    stack = list(fn.body)
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    stack = [n for n in stack if not isinstance(n, nested)]
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, nested):
                continue
            stack.append(child)


def local_imports(fn):
    out = set()
    for node in _own_body(fn):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for a in sub.names:
                    out.add((a.asname or a.name).split(".")[0])
    return out


def used_before(fn, name):
    """(use_line, import_line) of the first own-body Name load before the import."""
    first_import = None
    for node in _own_body(fn):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for a in sub.names:
                    n = (a.asname or a.name).split(".")[0]
                    if n == name and (first_import is None or sub.lineno < first_import):
                        first_import = sub.lineno
    if first_import is None:
        return None, None
    for node in _own_body(fn):
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Name)
                and sub.id == name
                and isinstance(sub.ctx, ast.Load)
                and sub.lineno < first_import
            ):
                return sub.lineno, first_import
    return None, None


def main():
    findings = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for file_name in filenames:
            if not file_name.endswith(".py"):
                continue
            path = os.path.join(dirpath, file_name)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except Exception:
                continue
            mod_names = module_level_imports(tree)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for name in local_imports(node) & mod_names:
                    before, imp_line = used_before(node, name)
                    if before is not None:
                        rel = os.path.relpath(path, ROOT)
                        findings.append((rel, node.name, name, before, imp_line))

    if not findings:
        print("OK: no shadowing function-local imports")
        return 0

    print("SHADOWING function-local imports (UnboundLocalError risk):")
    for rel, fn, name, use_line, imp_line in findings:
        print(
            f"  {rel}: {fn}() uses '{name}' at line {use_line} "
            f"but imports it locally at line {imp_line}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
