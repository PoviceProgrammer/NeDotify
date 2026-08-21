"""Shared pytest configuration for the AURA Music suite.

Two jobs:

1. Make the repository root importable so ``core``/``services``/``audio``/``utils``
   resolve no matter which directory pytest was launched from.
2. Shrink ``socketserver.BaseServer.serve_forever``'s default poll interval.
   Several suites start a real ``HTTPServer`` (the local stream proxy and mock
   upstreams) per test.  ``BaseServer.shutdown()`` blocks until the serving loop
   notices the shutdown flag, which with the stdlib default of 0.5s dominated the
   whole suite runtime.  Only the polling granularity changes - behaviour is
   identical.
"""

import os
import socketserver
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_ORIGINAL_SERVE_FOREVER = socketserver.BaseServer.serve_forever


def _fast_poll_serve_forever(self, poll_interval=0.02):
    return _ORIGINAL_SERVE_FOREVER(self, poll_interval)


socketserver.BaseServer.serve_forever = _fast_poll_serve_forever
