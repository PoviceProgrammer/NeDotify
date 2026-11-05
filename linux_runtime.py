"""Linux process setup; no GUI imports before Qt's environment is configured."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import stat
import sys


def configure_environment():
    if not sys.platform.startswith('linux'):
        return
    os.environ.setdefault('PYWEBVIEW_GUI', 'qt')
    os.environ.setdefault('QT_API', 'pyqt6')
    flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '')
    if '--autoplay-policy=' not in flags:
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = (
            flags + ' --autoplay-policy=no-user-gesture-required').strip()
    # Native binaries are built on Linux, never copied from the Windows app.
    if getattr(sys, 'frozen', False):
        bundled = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent)) / 'bin'
        if bundled.is_dir():
            os.environ['PATH'] = str(bundled) + os.pathsep + os.environ.get('PATH', '')


class InstanceLock:
    """Atomic per-profile advisory lock; stale PID text never blocks a launch.

    The inode is kept after release. Unlinking a locked file lets another
    process lock a different inode and bypass mutual exclusion.
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else Path.home() / '.nedotify' / 'instance.lock'
        self._file = None

    def acquire(self):
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise PermissionError('Instance lock must be a regular file owned by the current user')
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return False
            self._file = os.fdopen(fd, 'r+', encoding='ascii')
            self._file.seek(0)
            self._file.truncate()
            self._file.write(str(os.getpid()))
            self._file.flush()
            return True
        except Exception:
            if self._file is None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise

    def release(self):
        if self._file is not None:
            import fcntl
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None


def install_qt_capture():
    """Create a queued screenshot endpoint for the opt-in native QA harness.

    Screenshots use QWidget.grab on the Qt UI thread. No HTTP eval/debug route
    is added to the privileged application origin.
    """
    if not os.environ.get('NEDOTIFY_VALIDATION_OUTPUT'):
        return
    from webview.platforms import qt
    from qtpy.QtCore import QObject, Signal, Slot

    class Capture(QObject):
        requested = Signal(str)

        def __init__(self, native):
            super().__init__(native)
            self.native = native
            self.requested.connect(self.save)

        @Slot(str)
        def save(self, path):
            if not self.native.grab().save(path):
                logging.error('Native screenshot could not be saved: %s', path)

    original = qt.BrowserView.__init__

    def initialize(native, window):
        original(native, window)
        native._nedotify_capture = Capture(native)

    qt.BrowserView.__init__ = initialize
