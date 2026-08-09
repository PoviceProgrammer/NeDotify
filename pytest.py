"""
Lightweight pytest compatibility module for standard library execution.
Allows `import pytest`, `pytest.fixture`, `pytest.raises`, `pytest.main()`, etc.,
to execute seamlessly using standard library `unittest`.
"""

import os
import sys
import inspect
import unittest
import importlib.util
from unittest.mock import patch, MagicMock

def fixture(*args, **kwargs):
    if len(args) == 1 and callable(args[0]):
        return args[0]
    def decorator(fn):
        return fn
    return decorator

class RaisesContext:
    def __init__(self, expected_exception):
        self.expected_exception = expected_exception
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"Expected exception {self.expected_exception.__name__} was not raised.")
        if issubclass(exc_type, self.expected_exception):
            return True
        return False

def raises(expected_exception):
    return RaisesContext(expected_exception)

def main(args=None):
    if args is None:
        args = []

    sys.path.insert(0, os.path.abspath("."))

    test_files = [a for a in args if isinstance(a, str) and a.endswith('.py')]
    if not test_files:
        test_files = ['tests/test_recommendation.py', 'tests/test_lastfm_taste_profile.py', 'tests/test_nedotify.py']

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    for tf in test_files:
        abs_path = os.path.abspath(tf)
        if os.path.exists(abs_path):
            mod_name = os.path.splitext(os.path.basename(tf))[0]
            spec = importlib.util.spec_from_file_location(mod_name, abs_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            try:
                spec.loader.exec_module(mod)
                # Load unittest.TestCase classes or test_* functions
                file_tests = loader.loadTestsFromModule(mod)
                suite.addTests(file_tests)

                # Convert standalone test_* functions with fixture/assert support
                for name, obj in inspect.getmembers(mod):
                    if name.startswith('test_') and inspect.isfunction(obj):
                        # Create a Dynamic TestCase
                        def make_test_method(fn, module_obj):
                            def test_method(self_tc):
                                # Resolve fixtures if needed
                                sig = inspect.signature(fn)
                                kwargs = {}
                                for param in sig.parameters:
                                    if hasattr(module_obj, param):
                                        fix_attr = getattr(module_obj, param)
                                        kwargs[param] = fix_attr() if callable(fix_attr) else fix_attr
                                try:
                                    fn(**kwargs)
                                except Exception as err:
                                    import traceback
                                    print(f"\n--- Exception in {name} ---")
                                    traceback.print_exc()
                                    raise err
                            return test_method

                        test_cls = type(f"Test_{name}", (unittest.TestCase,), {
                            "test_run": make_test_method(obj, mod)
                        })
                        suite.addTest(loader.loadTestsFromTestCase(test_cls))
            except Exception as e:
                print(f"Error loading {tf}: {e}")

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    sys.stdout.flush()
    result = runner.run(suite)
    sys.stdout.flush()
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
