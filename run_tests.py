"""Entry point for the AURA Music test suite.

Delegates entirely to pytest so that pytest.ini (testpaths, markers, addopts)
is the single source of truth for what runs.
"""

import sys

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main([]))
