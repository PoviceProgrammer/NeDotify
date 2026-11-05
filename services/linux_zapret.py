"""App-scoped Linux Zapret transport using upstream tpws in SOCKS mode.

No root, firewall edits or foreign-process termination. TCP provider/CDN traffic
uses the shared session proxy; system-wide UDP/Discord voice needs a separately
administered nfqws service. Release archives are verified against GitHub SHA256.
"""
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import socket
import subprocess
import tarfile
import threading
import time
from urllib.parse import urlparse, urljoin

from utils.linux_proxy import set_endpoint

logger = logging.getLogger(__name__)
_REPO = 'bol-van/zapret'
_HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
_MACHINES = {'x86_64': ('linux-x86_64', 62), 'amd64': ('linux-x86_64', 62),
             'aarch64': ('linux-arm64', 183), 'arm64': ('linux-arm64', 183)}
_CUSTOM = re.compile(r'--(?:split-pos|oob|disorder|methodeol|hostcase|hostspell|hostnospace|hostpad|tlsrec|tlsrec-pos|new|filter-tcp|filter-l7)(?:=[A-Za-z0-9_,.+:-]{1,160})?')


class LinuxZapretService:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager
        self.process = None
        self._lock = threading.RLock()
        self._update_lock = threading.RLock()
        self._generation = 0
        self._event_callback = None
        self._auto_update_started = False
        self._port = None
        self._last_mode = 'youtube_discord'
        self._last_args = ''
        self._last_binary = None
        self.app_dir = str(Path.home() / '.nedotify' / 'zapret-linux')
        self.log_file = str(Path.home() / '.nedotify' / 'logs' / 'zapret-linux.log')
        self._log_handle = None

    def _set_elevation_window(self, provider):
        # Kept for the shared lifecycle interface; Linux tpws is unprivileged.
        pass

    def set_event_callback(self, callback):
        self._event_callback = callback

    def _emit_event(self, name, payload):
        if self._event_callback:
            self._event_callback(name, payload)

    @staticmethod
    def _valid_binary(path):
        try:
            path = Path(path).resolve(strict=True)
            if path.name != 'tpws' or not path.is_file() or not os.access(path, os.X_OK):
                return False
            with path.open('rb') as source:
                header = source.read(20)
            machine = _MACHINES.get(platform.machine().lower())
            return bool(machine and len(header) == 20 and header[:4] == b'\x7fELF'
                        and int.from_bytes(header[18:20], 'little' if header[5] == 1 else 'big') == machine[1])
        except (OSError, ValueError):
            return False

    def find_binary(self, custom_path=None):
        for value in (custom_path, str(Path(self.app_dir) / 'tpws'), shutil.which('tpws')):
            if value and self._valid_binary(value):
                return str(Path(value).resolve())
        return None

    def is_running(self):
        with self._lock:
            return self.process is not None and self.process.poll() is None

    def get_local_version(self):
        try:
            return str(json.loads((Path(self.app_dir) / 'version.json').read_text())['version'])
        except (OSError, ValueError, KeyError):
            return 'system' if self.find_binary() else ''

    @staticmethod
    def _release():
        import requests
        response = requests.get(f'https://api.github.com/repos/{_REPO}/releases/latest', timeout=(5, 15),
                                headers={'User-Agent': 'NeDotify-Linux', 'Accept': 'application/vnd.github+json'})
        try:
            response.raise_for_status()
            data = response.json()
        finally:
            response.close()
        if not isinstance(data, dict) or data.get('draft') or data.get('prerelease') or not re.fullmatch(r'v[\d.]+', str(data.get('tag_name', ''))):
            raise ValueError('Не удалось проверить официальный релиз Zapret')
        return data

    @staticmethod
    def _download(url, size, digest):
        import requests
        for _ in range(7):
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname not in _HOSTS or parsed.username or parsed.password:
                raise ValueError('Непроверенный источник Zapret')
            response = requests.get(url, allow_redirects=False, stream=True, timeout=(5, 30))
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_content(256 * 1024):
                    content.extend(chunk)
                    if len(content) > size:
                        raise ValueError('Размер архива Zapret превышает ожидаемый')
                if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError('Контрольная сумма Zapret не совпадает')
                return bytes(content)
            finally:
                response.close()
        raise ValueError('Слишком много перенаправлений Zapret')

    def check_for_updates(self):
        try:
            release = self._release()
            version = release['tag_name']
            return {'update_available': version != self.get_local_version(), 'latest_version': version,
                    'current_version': self.get_local_version(), 'message': 'Linux tpws: ' + version,
                    'release_url': release.get('html_url', '')}
        except Exception as exc:
            return {'update_available': False, 'error': str(exc), 'message': 'Не удалось проверить обновление Linux tpws'}

    def update_zapret(self, force=False):
        with self._update_lock:
            if self.is_running():
                return False, 'Остановите Zapret перед обновлением Linux tpws'
            try:
                machine = _MACHINES.get(platform.machine().lower())
                if not machine:
                    return False, 'Для этой архитектуры установите tpws средствами дистрибутива'
                release = self._release()
                tag = release['tag_name']
                name = 'zapret-' + tag + '.tar.gz'
                asset = next((item for item in release.get('assets', []) if item.get('name') == name), None)
                if not asset or not re.fullmatch(r'sha256:[a-f0-9]{64}', str(asset.get('digest', ''))):
                    return False, 'Для релиза нет проверенной SHA256-сборки Linux'
                size = asset.get('size')
                if type(size) is not int or not 0 < size <= 64 * 1024 * 1024:
                    return False, 'Некорректный размер архива Linux tpws'
                url = asset.get('browser_download_url', '')
                if not url.startswith(f'https://github.com/{_REPO}/releases/download/'):
                    return False, 'Непроверенный URL Linux tpws'
                content = self._download(url, size, asset['digest'][7:])
                directory = Path(self.app_dir)
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
                    matches = [entry for entry in archive.getmembers() if entry.name.endswith('/binaries/' + machine[0] + '/tpws')]
                    if len(matches) != 1 or not matches[0].isfile() or not 0 < matches[0].size < 10 * 1024 * 1024:
                        return False, 'В архиве не найден корректный Linux tpws'
                    temporary = directory / 'tpws.new'
                    with archive.extractfile(matches[0]) as source, temporary.open('wb') as output:
                        shutil.copyfileobj(source, output)
                        output.flush()
                        os.fsync(output.fileno())
                    temporary.chmod(0o700)
                    candidate = temporary
                    with candidate.open('rb') as source:
                        header = source.read(20)
                    if header[:4] != b'\x7fELF' or int.from_bytes(header[18:20], 'little' if header[5] == 1 else 'big') != machine[1]:
                        candidate.unlink(missing_ok=True)
                        return False, 'Архитектура Linux tpws не совпадает'
                    os.replace(candidate, directory / 'tpws')
                    for entry in archive.getmembers():
                        if entry.isfile() and entry.name.rsplit('/', 1)[-1] in ('LICENSE', 'COPYING') and entry.size < 1024 * 1024:
                            with archive.extractfile(entry) as source:
                                (directory / 'LICENSE.txt').write_bytes(source.read(1024 * 1024))
                            break
                manifest = directory / 'version.json.tmp'
                manifest.write_text(json.dumps({'version': tag, 'asset_sha256': asset['digest'][7:]}), encoding='utf-8')
                os.replace(manifest, directory / 'version.json')
                return True, 'Linux tpws обновлён: ' + tag
            except Exception as exc:
                logger.warning('Linux tpws update failed: %s', type(exc).__name__)
                return False, 'Не удалось обновить Linux tpws: ' + str(exc)

    download_binaries = update_zapret

    def auto_update_in_background(self):
        if self._auto_update_started or not self.settings or not self.settings.get('zapret', 'autoupdate', False):
            return
        self._auto_update_started = True
        threading.Thread(target=self.update_zapret, name='LinuxZapretUpdate', daemon=True).start()

    def start(self, mode='youtube_discord', custom_args='', binary_path=None):
        with self._lock:
            if self.is_running():
                return True, 'Linux tpws уже запущен'
            self._generation += 1
            generation = self._generation
        try:
            arguments = shlex.split(str(custom_args or '')) if custom_args else ['--split-pos=1,midsld', '--disorder']
            if any(not _CUSTOM.fullmatch(argument) for argument in arguments):
                return False, 'Linux использует параметры tpws (например --split-pos=1,midsld --disorder); параметры winws не поддерживаются'
            executable = self.find_binary(binary_path)
            if not executable:
                if binary_path:
                    return False, 'Выберите исполняемый Linux-файл tpws подходящей архитектуры'
                success, message = self.update_zapret()
                if not success:
                    return success, message
                executable = self.find_binary()
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            log = Path(self.log_file)
            log.parent.mkdir(parents=True, exist_ok=True)
            if log.exists() and log.stat().st_size > 1024 * 1024:
                os.replace(log, log.with_suffix('.log.old'))
            with self._lock:
                if generation != self._generation:
                    return False, 'Запуск отменён'
                self._log_handle = log.open('ab')
                process = subprocess.Popen([executable, '--socks', '--bind-addr=127.0.0.1', f'--port={port}', *arguments],
                    stdin=subprocess.DEVNULL, stdout=self._log_handle, stderr=subprocess.STDOUT, start_new_session=True)
                self.process = process
                self._port = port
            deadline = time.monotonic() + 3
            ready = False
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2):
                        ready = True
                        break
                except OSError:
                    time.sleep(.05)
            if not ready:
                self.stop()
                return False, 'Linux tpws не открыл SOCKS-порт. См. ~/.nedotify/logs/zapret-linux.log'
            with self._lock:
                if generation != self._generation:
                    return False, 'Запуск отменён'
                set_endpoint(port)
                self._last_mode, self._last_args, self._last_binary = mode, custom_args, binary_path
            def watch():
                code = process.wait()
                with self._lock:
                    if generation != self._generation:
                        return
                    set_endpoint(None)
                    self.process = None
                self._emit_event('zapret_crashed', {'message': f'Linux tpws завершился ({code}). См. zapret-linux.log'})
            threading.Thread(target=watch, name='LinuxZapretWatch', daemon=True).start()
            return True, 'Linux tpws запущен для TCP-трафика NeDotify; работу обхода проверьте на вашей сети'
        except Exception as exc:
            self.stop()
            return False, 'Ошибка запуска Linux tpws: ' + str(exc)

    def stop(self):
        with self._lock:
            self._generation += 1
            process, self.process = self.process, None
            set_endpoint(None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(2)
        with self._lock:
            if self._log_handle:
                self._log_handle.close()
                self._log_handle = None
        return True, 'Linux tpws остановлен'

    def get_status(self):
        executable = self.find_binary()
        running = self.is_running()
        return {'binary_found': bool(executable), 'binary_path': executable or '', 'running': running,
                'version': self.get_local_version(), 'has_internet': None, 'pending_update': '',
                'message': ('Linux tpws запущен (только TCP NeDotify)' if running else 'Linux tpws отключен'),
                'platform': 'linux', 'transport': 'tpws-socks', 'system_wide': False}
