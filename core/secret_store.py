"""Linux credential storage; SQLite contains references or authenticated ciphertext.

Prefer the desktop's Secret Service (GNOME Keyring/KWallet). Sessions without
a keyring use a Fernet key in a private 0700 directory / 0600 file. This protects
database exports, but does not protect against processes running as the user.
There is deliberately no plaintext or base64-only write fallback.
"""
import hashlib
import logging
import os
from pathlib import Path
import stat
import threading

logger = logging.getLogger(__name__)
_lock = threading.RLock()
KEYRING_PREFIX = 'dpapi:keyring:'
FILE_PREFIX = 'dpapi:fernet:'


def _keyring():
    import keyring
    backend = keyring.get_keyring()
    # Reject plaintext/keyrings.alt and fail backends even if configured as
    # the user's default. Only use an actual Secret Service on Linux.
    module = type(backend).__module__
    if not module.startswith(('keyring.backends.SecretService', 'keyring.backends.kwallet')):
        raise RuntimeError('A secure desktop keyring is unavailable')
    return backend


def _file_cipher(create):
    from cryptography.fernet import Fernet
    directory = Path.home() / '.nedotify' / 'secrets'
    if directory.is_symlink():
        raise RuntimeError('Credential directory must not be a symlink')
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        os.chmod(directory, 0o700)
    path = directory / 'key'
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        if not create:
            raise
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except FileExistsError:
            fd = os.open(path, flags)
        else:
            with os.fdopen(fd, 'wb') as output:
                output.write(Fernet.generate_key())
                output.flush()
                os.fsync(output.fileno())
            fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != 44:
            raise RuntimeError('Invalid credential key file')
        if os.name != 'nt':
            if info.st_uid != os.getuid():
                raise RuntimeError('Credential key belongs to another user')
            os.fchmod(source.fileno(), 0o600)
        key = source.read(45)
    return Fernet(key)


def encrypt(text):
    if not isinstance(text, str) or not text or text.startswith((KEYRING_PREFIX, FILE_PREFIX)):
        return text
    with _lock:
        identity = hashlib.sha256(text.encode('utf-8')).hexdigest()
        try:
            backend = _keyring()
            backend.set_password('NeDotify', identity, text)
            return KEYRING_PREFIX + identity
        except Exception:
            logger.debug('Desktop keyring unavailable; using private encrypted credential store')
        return FILE_PREFIX + _file_cipher(create=True).encrypt(text.encode('utf-8')).decode('ascii')


def decrypt(value):
    if not isinstance(value, str):
        return value
    try:
        with _lock:
            if value.startswith(KEYRING_PREFIX):
                return _keyring().get_password('NeDotify', value[len(KEYRING_PREFIX):]) or ''
            if value.startswith(FILE_PREFIX):
                return _file_cipher(create=False).decrypt(value[len(FILE_PREFIX):].encode('ascii')).decode('utf-8')
    except Exception:
        # Keep the original row intact. A locked desktop keyring must never
        # erase an otherwise valid credential on load.
        logger.warning('Stored credential is unavailable; unlock the desktop keyring or restore the profile key')
        return ''
    return value
