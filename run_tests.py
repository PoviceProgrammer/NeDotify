"""Entry point for the AURA Music test suite.

Delegates entirely to pytest so that pytest.ini (testpaths, markers, addopts)
is the single source of truth for what runs.
"""

import sys

if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([]))
    except ImportError:
        import unittest
        loader = unittest.TestLoader()
        suite = loader.discover("tests")
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)
