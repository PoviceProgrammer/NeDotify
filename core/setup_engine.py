"""Windows tool preparation, shared by onboarding and the download manager.

Adapted architectural ideas from rootscripts/Riff's MIT-licensed tools.js:
per-user tools, architecture-specific official assets, checksums and resumable
transfers. Installation here uses versioned directories and an atomic manifest,
so a failed update never replaces the last working executable. See third-party
notices for the upstream copyright notice.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import threading
import time
from urllib.parse import urlparse
import uuid
import zipfile

logger = logging.getLogger(__name__)
_REPOS = {"yt_dlp": "yt-dlp/yt-dlp", "ffmpeg": "yt-dlp/FFmpeg-Builds"}
_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
_FORMATS = {"source", "mp3", "m4a", "opus", "flac", "wav"}
_QUALITIES = {"best", "320", "256", "192", "128"}


def resolve_managed_tool(name, profile_dir=None):
    """Resolve a verified managed executable without starting setup or networking."""
    if name not in {"yt_dlp", "ffmpeg", "ffprobe"}:
        return None
    tools = (Path(profile_dir) if profile_dir else Path.home() / ".nedotify") / "tools"
    tools = tools.resolve()
    try:
        manifest = json.loads((tools / "state.json").read_text(encoding="utf-8"))
        owner = "yt_dlp" if name == "yt_dlp" else "ffmpeg"
        value = manifest["tools"][owner]["paths"][name]
        if not isinstance(value, str):
            return None
        path = (tools / value).resolve()
        if manifest.get("schema_version") == 1 and path.is_relative_to(tools) and path.is_file():
            return str(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


class SetupDependencyError(RuntimeError):
    def __init__(self, code: str, message: str, recoverable: bool = True):
        super().__init__(message)
        self.code, self.message, self.recoverable = code, message, recoverable

    def as_dict(self):
        return {"code": self.code, "message": self.message, "recoverable": self.recoverable}


class SetupEngine:
    """One preparation worker and a lease gate around executable replacement."""

    def __init__(self, settings, emit=None, profile_dir=None, http_session=None):
        self.settings = settings
        self._emit = emit
        self.profile = Path(profile_dir or (Path.home() / ".nedotify")).resolve()
        self.tools_dir = self.profile / "tools"
        self._manifest_path = self.tools_dir / "state.json"
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._leases = 0
        self._updating = False
        self._worker = None
        self._session = http_session
        self._owns_session = http_session is None
        self._manifest = self._read_manifest()
        self._operation = {"id": None, "status": "idle", "tool": "", "percent": None,
                           "downloaded_bytes": 0, "total_bytes": None, "error": None}
        self._last_progress = 0.0
        self._updates = {}
        self._sources = {}
        self._auto_update_started = False
        self._maintenance_worker = None
        self._closed = False

    def _read_manifest(self):
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            if data.get("schema_version") == 1 and isinstance(data.get("tools"), dict) and all(
                isinstance(record, dict) and isinstance(record.get("paths", {}), dict)
                and isinstance(record.get("hashes", {}), dict) and isinstance(record.get("sizes", {}), dict)
                and isinstance(record.get("versions", {}), dict) for record in data["tools"].values()
            ):
                return data
        except (OSError, ValueError, AttributeError):
            pass
        return {"schema_version": 1, "tools": {}}

    def _write_manifest(self, data):
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._manifest_path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            self._replace(temporary, self._manifest_path, cancellable=False)
        finally:
            temporary.unlink(missing_ok=True)

    def _replace(self, source, destination, cancellable=True):
        # Windows scanners and a just-exited executable may briefly retain a
        # handle. Retry only sharing/permission failures; never fall back to
        # non-atomic copying over a working installation.
        for attempt in range(5):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                if cancellable:
                    if self._cancel.wait(.1 * 2 ** attempt):
                        self._check_cancelled()
                else:
                    time.sleep(.1 * 2 ** attempt)

    def _managed_path(self, name):
        owner = "yt_dlp" if name == "yt_dlp" else "ffmpeg"
        record = self._manifest.get("tools", {}).get(owner, {})
        value = record.get("paths", {}).get(name)
        if not isinstance(value, str):
            return None
        path = (self.tools_dir / value).resolve()
        if path.is_relative_to(self.tools_dir) and path.is_file():
            return str(path)
        return None

    def _resolve_tool(self, name):
        managed = self._managed_path(name)
        if managed:
            return managed, "managed"
        filename = ("yt-dlp" if name == "yt_dlp" else name) + (".exe" if sys.platform == "win32" else "")
        locations = [Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])),
                     Path(sys.executable).parent]
        for directory in locations:
            path = directory / filename
            if path.is_file():
                return str(path.resolve()), "bundled"
        external = shutil.which(filename) or (shutil.which(filename[:-4]) if filename.endswith(".exe") else None)
        return (str(Path(external).resolve()), "system") if external else (None, None)

    @staticmethod
    def _module_version(name):
        try:
            if importlib.util.find_spec(name) is None:
                return None
            try:
                return importlib.metadata.version(name.replace("_", "-"))
            except importlib.metadata.PackageNotFoundError:
                return "bundled"
        except (ImportError, ValueError, AttributeError):
            return None

    @staticmethod
    def _probe(path, tool):
        try:
            result = subprocess.run([path, "--version" if tool == "yt_dlp" else "-version"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            first = (result.stdout or "").splitlines()[0] if result.stdout else ""
            if result.returncode or not first or (tool != "yt_dlp" and not first.lower().startswith(tool + " version")):
                return False, "Не удалось проверить версию компонента"
            return True, first[:160]
        except (OSError, subprocess.SubprocessError):
            return False, "Компонент не запускается или повреждён"

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _dependency(self, name, deep=False):
        path, source = self._resolve_tool(name)
        module = self._module_version("yt_dlp") if name == "yt_dlp" else None
        available = bool(path or module)
        owner = "yt_dlp" if name == "yt_dlp" else "ffmpeg"
        record = self._manifest.get("tools", {}).get(owner, {})
        version = module if not path else record.get("versions", {}).get(name, record.get("version", ""))
        error = ""
        if path and source == "managed":
            expected_size = record.get("sizes", {}).get(name)
            try:
                if expected_size is not None and Path(path).stat().st_size != expected_size:
                    available, error = False, "Размер компонента изменён. Нужна проверка или восстановление."
            except OSError:
                available, error = False, "Компонент недоступен. Нужна проверка или восстановление."
        if deep and path:
            available, version = self._probe(path, name)
            if not available:
                error = version
            if available and source == "managed":
                expected = self._manifest.get("tools", {}).get(owner, {}).get("hashes", {}).get(name)
                try:
                    if expected and self._sha256(path) != expected:
                        available, error = False, "Проверка целостности компонента не пройдена"
                except OSError:
                    available, error = False, "Нет доступа к файлу компонента"
        if name == "yt_dlp" and not available and module:
            # A stale PATH console wrapper must not disable the Python backend
            # that is already shipped with the application.
            available, path, source, version, error = True, None, "python", module, ""
        return {"available": available, "path": path, "source": source or ("python" if module else None),
                "version": version or "", "module_available": bool(module), "error": error}

    def _download_settings(self):
        get = self.settings.get
        directory = get("downloads", "directory", "") or str(self.profile / "downloads")
        return {"directory": directory, "format": get("downloads", "format", "source"),
                "quality": get("downloads", "quality", "best"),
                "max_concurrent": get("downloads", "max_concurrent", 2),
                "fragment_concurrency": get("downloads", "fragment_concurrency", 2),
                "embed_metadata": get("downloads", "embed_metadata", True),
                "embed_cover": get("downloads", "embed_cover", True),
                "auto_update_tools": get("downloads", "auto_update_tools", False),
                "scan_folders": get("general", "scan_folders", [])}

    @staticmethod
    def _directory_status(value, deep=False, create=False):
        try:
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise OSError("Выберите абсолютный путь к папке")
            if create:
                path.mkdir(parents=True, exist_ok=True)
            parent = path
            while not parent.exists() and parent.parent != parent:
                parent = parent.parent
            if not parent.is_dir() or (path.exists() and not path.is_dir()):
                raise OSError("Путь не является папкой")
            writable = os.access(parent, os.W_OK)
            if deep and writable and path.is_dir():
                with tempfile.TemporaryFile(dir=path):
                    pass
            return {"path": str(path), "available": writable, "exists": path.is_dir(),
                    "error": "" if writable else "Нет прав на запись в папку"}
        except (OSError, ValueError, TypeError) as error:
            return {"path": str(value), "available": False, "exists": False, "error": str(error)}

    def get_status(self, deep=False, check_sources=False):
        # Deep probing stays outside the lock: it never holds up a cancel or a
        # download starting while another UI asks for diagnostic information.
        dependencies = {name: self._dependency(name, deep) for name in ("yt_dlp", "ffmpeg", "ffprobe")}
        settings = self._download_settings()
        directory = self._directory_status(settings["directory"], deep)
        issues = [{"code": f"missing_{name}", "message": dependency["error"] or f"Не найден {name.replace('_', '-')}",
                   "recoverable": True} for name, dependency in dependencies.items() if not dependency["available"]]
        components = {name: bool(self._module_version(name)) for name in ("requests", "mutagen", "webview")}
        for name, available in components.items():
            if not available:
                issues.append({"code": "missing_python_component", "component": name,
                               "message": f"Отсутствует компонент приложения {name}. Восстановите установку NeDotify.", "recoverable": False})
        if not directory["available"]:
            issues.append({"code": "download_directory", "message": directory["error"], "recoverable": True})
        with self._lock:
            snapshot = {"ready": not issues, "dependencies": dependencies, "python_components": components,
                        "paths": {f"{name}_path": dependency["path"] for name, dependency in dependencies.items()},
                        "issues": issues, "updating": self._updating, "active_downloads": self._leases,
                        "operation": copy.deepcopy(self._operation), "settings": settings, "directory": directory,
                        "updates": copy.deepcopy(self._updates), "sources": copy.deepcopy(self._sources)}
        if check_sources:
            snapshot["sources"] = self.check_sources()
        return snapshot

    @contextmanager
    def acquire_download_tools(self, require_ffmpeg=False, require_yt_dlp=True):
        with self._lock:
            if self._updating:
                raise SetupDependencyError("dependencies_busy", "Компоненты обновляются. Повторите скачивание после подготовки.")
            ytdlp = self._dependency("yt_dlp")
            ffmpeg = self._dependency("ffmpeg")
            probe = self._dependency("ffprobe")
            if require_yt_dlp and not ytdlp["available"]:
                raise SetupDependencyError("missing_yt_dlp", "Не найден yt-dlp. Восстановите компоненты в настройках подготовки.")
            if require_ffmpeg and not ffmpeg["available"]:
                raise SetupDependencyError("missing_ffmpeg", "Для выбранного формата нужен FFmpeg. Восстановите компоненты в настройках.")
            self._leases += 1
            managed_record = self._manifest.get("tools", {}).get("yt_dlp", {})
            module_version = self._module_version("yt_dlp")
            managed_version = managed_record.get("version", "")
            module_numbers = tuple(int(n) for n in re.findall(r"\d+", module_version or ""))
            managed_numbers = tuple(int(n) for n in re.findall(r"\d+", managed_version))
            prefer_executable = ytdlp["source"] == "managed" and ytdlp["available"] and (
                not module_numbers or managed_numbers > module_numbers or managed_record.get("prefer_executable") is True)
            tools = {"yt_dlp_path": ytdlp["path"] if ytdlp["available"] else None,
                     "yt_dlp_module": ytdlp["module_available"],
                     "prefer_executable": prefer_executable,
                     "ffmpeg_path": ffmpeg["path"] if ffmpeg["available"] else None,
                     "ffprobe_path": probe["path"] if probe["available"] else None}
        try:
            yield tools
        finally:
            with self._lock:
                self._leases -= 1

    def configure(self, options):
        if not isinstance(options, dict):
            return {"success": False, "error": "Некорректные параметры настройки"}
        changes = []
        if "directory" in options:
            directory = self._directory_status(options["directory"], deep=True, create=True)
            if not directory["available"]:
                return {"success": False, "error": directory["error"]}
            changes.append(("downloads", "directory", directory["path"]))
        if "library_directory" in options and options["library_directory"]:
            directory = self._directory_status(options["library_directory"], deep=True, create=True)
            if not directory["available"]:
                return {"success": False, "error": directory["error"]}
            existing = self.settings.get("general", "scan_folders", []) or []
            folders = list(dict.fromkeys([*existing, directory["path"]]))
            changes.append(("general", "scan_folders", folders))
        for key, choices in (("format", _FORMATS), ("quality", _QUALITIES)):
            if key in options:
                if not isinstance(options[key], str) or options[key] not in choices:
                    return {"success": False, "error": "Недопустимое качество или формат"}
                changes.append(("downloads", key, options[key]))
        for key in ("max_concurrent", "fragment_concurrency"):
            if key in options:
                value = options[key]
                if type(value) is not int or not 1 <= value <= 4:
                    return {"success": False, "error": "Число параллельных загрузок должно быть от 1 до 4"}
                changes.append(("downloads", key, value))
        for key in ("embed_metadata", "embed_cover", "auto_update_tools"):
            if key in options:
                if type(options[key]) is not bool:
                    return {"success": False, "error": "Некорректный переключатель"}
                changes.append(("downloads", key, options[key]))
        with self._lock:
            previous = [(category, key, self.settings.get(category, key)) for category, key, _ in changes]
            try:
                for category, key, value in changes:
                    self.settings.set(category, key, value)
                flush = getattr(self.settings, "sync_flush_now", None)
                if flush and not flush():
                    raise OSError("Не удалось сохранить настройки на диск")
            except Exception:
                for category, key, value in previous:
                    self.settings.set(category, key, value)
                return {"success": False, "error": "Не удалось сохранить настройки на диск"}
        return {"success": True, "settings": self._download_settings()}

    def _http(self):
        if self._session is None:
            import requests
            from requests.adapters import HTTPAdapter
            session = requests.Session()
            session.headers.update({"User-Agent": "NeDotify-Setup/1", "Accept": "application/vnd.github+json"})
            session.mount("https://", HTTPAdapter(pool_connections=2, pool_maxsize=2, pool_block=True))
            proxy = self.settings.get("auth", "proxy_url", "")
            if isinstance(proxy, str) and urlparse(proxy).scheme in {"http", "https", "socks5", "socks5h"}:
                session.proxies.update({"http": proxy, "https": proxy})
            self._session = session
        return self._session

    def _check_cancelled(self):
        if self._cancel.is_set():
            raise SetupDependencyError("setup_cancelled", "Подготовка отменена")

    def _release(self, tool):
        self._check_cancelled()
        repo = _REPOS[tool]
        data = None
        for attempt in range(3):
            response = None
            try:
                response = self._http().get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=(5, 15))
                response.raise_for_status()
                data = response.json()
                break
            except Exception:
                self._check_cancelled()
                if attempt == 2:
                    raise SetupDependencyError("release_unavailable", "Сервер компонентов недоступен. Проверьте сеть и повторите подготовку.") from None
                if self._cancel.wait(.5 * (attempt + 1)):
                    self._check_cancelled()
            finally:
                if response is not None:
                    response.close()
        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            raise SetupDependencyError("invalid_release", "Сервер не предоставил стабильную версию компонента")
        if (not isinstance(data.get("assets"), list) or not isinstance(data.get("tag_name"), str)
                or not data["tag_name"] or type(data.get("id")) is not int or data["id"] <= 0):
            raise SetupDependencyError("invalid_release", "Не удалось прочитать список файлов релиза")
        return data

    @staticmethod
    def _asset(release, name):
        asset = next((a for a in release["assets"] if a.get("name") == name), None)
        if not asset:
            raise SetupDependencyError("asset_unavailable", f"В релизе отсутствует {name}")
        parsed = urlparse(asset.get("browser_download_url", ""))
        if (parsed.scheme != "https" or parsed.hostname != "github.com"
                or not any(parsed.path.startswith(f"/{repo}/releases/download/") for repo in _REPOS.values())):
            raise SetupDependencyError("untrusted_source", "Источник компонента не прошёл проверку")
        return asset

    @staticmethod
    def _asset_name(tool):
        machine = platform.machine().lower()
        if sys.platform == "linux":
            if machine in {"amd64", "x86_64"}:
                return "yt-dlp_linux" if tool == "yt_dlp" else "ffmpeg-master-latest-linux64-gpl.tar.xz"
            if machine in {"arm64", "aarch64"}:
                return "yt-dlp_linux_aarch64" if tool == "yt_dlp" else "ffmpeg-master-latest-linuxarm64-gpl.tar.xz"
            raise SetupDependencyError("unsupported_architecture", "Установите ffmpeg и yt-dlp средствами вашего дистрибутива", False)
        if sys.platform != "win32":
            raise SetupDependencyError("unsupported_platform", "Для этой платформы нет проверенных сборок", False)
        if machine in {"arm64", "aarch64"}:
            return "yt-dlp_arm64.exe" if tool == "yt_dlp" else "ffmpeg-master-latest-winarm64-gpl.zip"
        if machine in {"amd64", "x86_64"}:
            return "yt-dlp.exe" if tool == "yt_dlp" else "ffmpeg-master-latest-win64-gpl.zip"
        if tool == "yt_dlp" and machine in {"x86", "i386", "i686"}:
            return "yt-dlp_x86.exe"
        raise SetupDependencyError("unsupported_architecture", "Для этой архитектуры нет проверенной сборки компонента", False)

    def _verified_response(self, url, **kwargs):
        # Validate every redirect rather than allowing an official URL to send
        # installer bytes to an arbitrary or downgraded destination.
        for _ in range(7):
            self._check_cancelled()
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in _DOWNLOAD_HOSTS or parsed.username or parsed.password:
                raise SetupDependencyError("untrusted_source", "Непроверенный адрес загрузки компонента")
            response = self._http().get(url, allow_redirects=False, timeout=(5, 20), **kwargs)
            if response.status_code in {301, 302, 303, 307, 308}:
                from urllib.parse import urljoin
                target = response.headers.get("Location")
                response.close()
                if not target:
                    break
                url = urljoin(url, target)
                continue
            response.raise_for_status()
            return response
        raise SetupDependencyError("redirect_limit", "Слишком много перенаправлений при загрузке")

    def _checksum(self, release, tool, asset):
        filename = "SHA2-256SUMS" if tool == "yt_dlp" else "checksums.sha256"
        sums = self._asset(release, filename)
        response = self._verified_response(sums["browser_download_url"], stream=True)
        try:
            content = bytearray()
            for chunk in response.iter_content(65536):
                self._check_cancelled()
                content.extend(chunk)
                if len(content) > 2 * 1024 * 1024:
                    raise SetupDependencyError("invalid_checksum", "Некорректный файл контрольных сумм")
        finally:
            response.close()
        for line in content.decode("utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(?:\./)?(.+)", line.strip())
            if match and match[2] == asset["name"]:
                digest = match[1].lower()
                api_digest = asset.get("digest")
                if api_digest and api_digest != "sha256:" + digest:
                    raise SetupDependencyError("invalid_checksum", "Контрольные суммы релиза не совпадают")
                return digest
        raise SetupDependencyError("missing_checksum", "Для компонента не опубликована контрольная сумма")

    def _progress(self, **values):
        force = values.pop("force", False)
        with self._lock:
            self._operation.update(values)
            now = time.monotonic()
            if now - self._last_progress < .1 and not force:
                return
            self._last_progress = now
            payload = copy.deepcopy(self._operation)
        if self._emit:
            try:
                self._emit("setup_progress", payload)
            except Exception:
                logger.debug("Setup progress could not be delivered", exc_info=True)

    def _download(self, asset, destination, digest):
        total = asset.get("size")
        if not isinstance(total, int) or total <= 0 or total > 750 * 1024 * 1024:
            raise SetupDependencyError("invalid_asset_size", "Некорректный размер компонента")
        free = shutil.disk_usage(destination.parent).free
        if free < total * 3 + 32 * 1024 * 1024:
            raise SetupDependencyError("insufficient_space", "Недостаточно свободного места для установки компонента")
        last_error = None
        for attempt in range(3):
            self._check_cancelled()
            offset = destination.stat().st_size if destination.exists() else 0
            if offset >= total:
                if offset == total and self._sha256(destination) == digest:
                    return
                destination.unlink(missing_ok=True)
                offset = 0
            response = None
            try:
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                response = self._verified_response(asset["browser_download_url"], stream=True, headers=headers)
                if response.status_code == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not match or int(match[1]) != offset or int(match[3]) != total or int(match[2]) != total - 1:
                        raise SetupDependencyError("invalid_range", "Сервер вернул некорректный диапазон файла")
                elif response.status_code == 200:
                    offset = 0
                else:
                    raise SetupDependencyError("invalid_response", "Некорректный ответ сервера компонентов")
                done = offset
                with destination.open("ab" if offset else "wb") as handle:
                    for chunk in response.iter_content(256 * 1024):
                        self._check_cancelled()
                        if not chunk:
                            continue
                        done += len(chunk)
                        if done > total:
                            raise SetupDependencyError("invalid_asset_size", "Полученный компонент превышает заявленный размер")
                        handle.write(chunk)
                        self._progress(status="downloading", downloaded_bytes=done, total_bytes=total, percent=round(done / total * 100, 1))
                if done != total:
                    raise OSError("Получен неполный файл компонента")
                if self._sha256(destination) != digest:
                    destination.unlink(missing_ok=True)
                    raise SetupDependencyError("checksum_mismatch", "Контрольная сумма скачанного компонента не совпадает")
                return
            except SetupDependencyError:
                raise
            except Exception as error:
                last_error = error
                if self._cancel.wait(.5 * (attempt + 1)):
                    self._check_cancelled()
            finally:
                if response is not None:
                    response.close()
        raise SetupDependencyError("download_failed", "Не удалось скачать компонент. Проверьте сеть и повторите подготовку.") from last_error

    def _install(self, tool):
        release = self._release(tool)
        asset = self._asset(release, self._asset_name(tool))
        digest = self._checksum(release, tool, asset)
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        stage_root = self.tools_dir / ".staging"
        stage_root.mkdir(exist_ok=True)
        archive = stage_root / (digest + ".part")
        self._download(asset, archive, digest)
        self._progress(status="verifying", percent=None)
        stage = Path(tempfile.mkdtemp(prefix=f"{tool}-", dir=stage_root))
        paths = {}
        try:
            if tool == "yt_dlp":
                target = stage / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
                shutil.copyfile(archive, target)
                if sys.platform == "linux":
                    target.chmod(0o700)
                paths[tool] = target
            elif sys.platform == "linux":
                # Read individual regular members into fixed destinations. Never
                # tar.extractall: archive paths and symlinks are untrusted.
                with tarfile.open(archive, "r:xz") as bundle:
                    entries = bundle.getmembers()
                    for name in ("ffmpeg", "ffprobe"):
                        matches = [entry for entry in entries if entry.name.rsplit("/", 1)[-1] == name]
                        if len(matches) != 1 or not matches[0].isfile() or not 0 < matches[0].size <= 300 * 1024 * 1024:
                            raise SetupDependencyError("invalid_archive", f"Не удалось найти безопасный {name} в архиве")
                        target = stage / name
                        with bundle.extractfile(matches[0]) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output, 1024 * 1024)
                        target.chmod(0o700)
                        paths[name] = target
                    notices = [entry for entry in entries if entry.isfile() and re.search(r"(?:^|/)(?:LICENSE|COPYING)(?:\.[^/]*)?$", entry.name, re.I) and entry.size < 2 * 1024 * 1024]
                    for index, entry in enumerate(notices):
                        with bundle.extractfile(entry) as source:
                            (stage / f"LICENSE-{index}.txt").write_bytes(source.read(2 * 1024 * 1024))
            else:
                # Extract only the two expected binaries and license notices.
                # Never extract archive paths, symlinks, or executable extras.
                with zipfile.ZipFile(archive) as zipped:
                    for name in ("ffmpeg", "ffprobe"):
                        matches = [entry for entry in zipped.infolist() if entry.filename.replace("\\", "/").split("/")[-1].lower() == name + ".exe"]
                        if len(matches) != 1 or matches[0].file_size > 300 * 1024 * 1024:
                            raise SetupDependencyError("invalid_archive", f"Не удалось найти безопасный {name} в архиве")
                        target = stage / (name + ".exe")
                        with zipped.open(matches[0]) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output, 1024 * 1024)
                        paths[name] = target
                    notices = [entry for entry in zipped.infolist() if re.search(r"(?:^|/)(?:LICENSE|COPYING)(?:\.[^/]*)?$", entry.filename, re.I) and entry.file_size < 2 * 1024 * 1024]
                    for index, entry in enumerate(notices):
                        (stage / f"LICENSE-{index}.txt").write_bytes(zipped.read(entry))
            versions = {}
            for name, path in paths.items():
                self._check_cancelled()
                valid, version = self._probe(str(path), name)
                if not valid:
                    raise SetupDependencyError("component_verification_failed", f"Проверка {name} после установки не пройдена")
                versions[name] = version
            identity = f"{release.get('id', 'release')}-{digest[:16]}-{uuid.uuid4().hex[:8]}"
            destination = self.tools_dir / tool / identity
            destination.parent.mkdir(exist_ok=True)
            self._check_cancelled()
            self._replace(stage, destination)
            installed = {name: destination / path.name for name, path in paths.items()}
            record = {"version": release["tag_name"], "release_id": release.get("id"),
                      "asset": asset["name"], "asset_sha256": digest, "installed_at": time.time(),
                      "prefer_executable": bool(tool == "yt_dlp" and self._operation.get("update")),
                      "source_url": f"https://github.com/{_REPOS[tool]}",
                      "paths": {name: str(path.relative_to(self.tools_dir)) for name, path in installed.items()},
                      "hashes": {name: self._sha256(path) for name, path in installed.items()},
                      "sizes": {name: path.stat().st_size for name, path in installed.items()}, "versions": versions}
            with self._lock:
                # start_repair reserves _updating before the network starts, so
                # no new download can obtain a lease between verification and
                # this final manifest swap.
                if self._leases:
                    raise SetupDependencyError("dependencies_busy", "Компоненты используются загрузчиком")
                old = copy.deepcopy(self._manifest)
                updated = copy.deepcopy(old)
                previous = updated["tools"].get(tool)
                if previous:
                    record["previous"] = {key: value for key, value in previous.items() if key != "previous"}
                updated["tools"][tool] = record
                self._write_manifest(updated)
                self._manifest = updated
                for name, path in installed.items():
                    valid, _ = self._probe(str(path), name)
                    if not valid:
                        self._write_manifest(old)
                        self._manifest = old
                        raise SetupDependencyError("update_rolled_back", "Обновление не запускается. Восстановлена предыдущая версия.")
            archive.unlink(missing_ok=True)
            self._prune_versions(tool)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def _prune_versions(self, tool):
        record = self._manifest.get("tools", {}).get(tool, {})
        keep = set()
        for version in (record, record.get("previous", {})):
            for value in version.get("paths", {}).values():
                if isinstance(value, str):
                    keep.add((self.tools_dir / value).resolve().parent)
        owner = (self.tools_dir / tool).resolve()
        if not owner.is_dir():
            return
        for directory in owner.iterdir():
            resolved = directory.resolve()
            if (directory.is_dir() and not directory.is_symlink() and resolved.is_relative_to(owner)
                    and resolved not in keep and re.fullmatch(r"\d+-[0-9a-f]{16}-[0-9a-f]{8}", directory.name)):
                try:
                    shutil.rmtree(resolved)
                except OSError:
                    logger.debug("Old managed tool version remains in use")

    def start_repair(self, tools=None, update=False):
        if type(update) is not bool or (tools is not None and (not isinstance(tools, list) or any(not isinstance(tool, str) or tool not in _REPOS for tool in tools))):
            return {"success": False, "error": "Неизвестный компонент"}
        if tools is not None:
            tools = list(dict.fromkeys(tools))
        with self._lock:
            if self._closed:
                return {"success": False, "code": "setup_closed", "error": "Приложение завершает работу"}
            if self._updating or self._leases:
                return {"success": False, "code": "dependencies_busy", "error": "Дождитесь завершения активных загрузок или подготовки"}
            self._updating = True
            self._cancel.clear()
            operation_id = uuid.uuid4().hex
            self._operation = {"id": operation_id, "status": "checking", "tool": "", "percent": None,
                               "downloaded_bytes": 0, "total_bytes": None, "error": None, "update": update}
            worker = threading.Thread(target=self._repair_worker, args=(tools, update), name="SetupWorker", daemon=True)
            self._worker = worker
            worker.start()
        return {"success": True, "operation_id": operation_id}

    def _repair_worker(self, requested, update):
        try:
            status = self.get_status(deep=True)
            tools = requested if requested is not None else [name for name in _REPOS if update or not status["dependencies"][name]["available"]]
            if not status["dependencies"]["ffprobe"]["available"] and "ffmpeg" not in tools:
                tools = [*tools, "ffmpeg"]
            for tool in tools:
                self._check_cancelled()
                self._progress(tool=tool, status="resolving", percent=None, downloaded_bytes=0, total_bytes=None, force=True)
                self._install(tool)
            self._check_cancelled()
            directory = self._directory_status(self._download_settings()["directory"], deep=True, create=True)
            if not directory["available"]:
                raise SetupDependencyError("download_directory", directory["error"])
            self._progress(status="completed", tool="", percent=100, force=True)
        except SetupDependencyError as error:
            self._progress(status="cancelled" if error.code == "setup_cancelled" else "failed", error=error.as_dict(), percent=None, force=True)
        except Exception as error:
            logger.warning("Component preparation failed: %s", type(error).__name__)
            self._progress(status="failed", error={"code": "setup_failed", "message": "Не удалось подготовить компоненты. Проверьте сеть, права и свободное место.", "recoverable": True}, percent=None, force=True)
        finally:
            with self._lock:
                self._updating = False
            if self._emit:
                try:
                    self._emit("setup_status", self.get_status())
                except Exception:
                    logger.debug("Setup status could not be delivered", exc_info=True)

    def cancel(self):
        self._cancel.set()
        return {"success": True, "cancelling": self._updating}

    def check_updates(self):
        with self._lock:
            if self._closed:
                raise SetupDependencyError("setup_closed", "Приложение завершает работу")
            if not self._updating:
                self._cancel.clear()
        updates = {}
        for tool in _REPOS:
            release = self._release(tool)
            asset = self._asset(release, self._asset_name(tool))
            installed = self._manifest.get("tools", {}).get(tool, {})
            digest = asset.get("digest", "")
            changed = bool(digest and digest != "sha256:" + installed.get("asset_sha256", ""))
            updates[tool] = {"version": release["tag_name"], "available": changed or installed.get("release_id") != release.get("id") or installed.get("asset") != asset["name"], "checked_at": time.time()}
        with self._lock:
            self._updates = updates
        return copy.deepcopy(updates)

    def maybe_auto_update(self):
        """One background check per process, only after the user opted in.

        Call after the window is ready. Busy downloads make it defer to the next
        launch or a manual check; this never creates a periodic retry timer.
        """
        with self._lock:
            if self._closed:
                return {"success": True, "started": False, "reason": "closed"}
            if self.settings.get("downloads", "auto_update_tools", False) is not True:
                return {"success": True, "started": False, "reason": "disabled"}
            if self._auto_update_started or self._updating or self._leases:
                return {"success": True, "started": False, "reason": "busy_or_checked"}
            self._auto_update_started = True
            worker = threading.Thread(target=self._auto_update, name="SetupUpdateCheck", daemon=True)
            self._maintenance_worker = worker
            worker.start()
        return {"success": True, "started": True}

    def _auto_update(self):
        try:
            updates = self.check_updates()
            self._check_cancelled()
            changed = [name for name, value in updates.items() if value["available"]]
            if changed:
                self.start_repair(changed, update=True)
        except Exception as error:
            logger.info("Optional component update check skipped: %s", type(error).__name__)

    def check_sources(self):
        with self._lock:
            if self._closed:
                return {}
            if not self._updating:
                self._cancel.clear()
        sources = {}
        for name, url in (("youtube", "https://www.youtube.com/"), ("soundcloud", "https://soundcloud.com/"), ("spotify", "https://open.spotify.com/")):
            self._check_cancelled()
            try:
                response = self._http().get(url, timeout=(3, 5), stream=True)
                try:
                    sources[name] = {"available": response.status_code < 400, "status_code": response.status_code}
                finally:
                    response.close()
            except Exception:
                sources[name] = {"available": False, "message": "Источник недоступен из текущей сети"}
        with self._lock:
            self._sources = sources
        return copy.deepcopy(sources)

    def shutdown(self, timeout=5):
        """Cancel preparation and drain its owned workers within one deadline."""
        with self._lock:
            self._closed = True
            self._cancel.set()
            workers = [self._worker, self._maintenance_worker]
        deadline = time.monotonic() + max(0, timeout)
        for worker in workers:
            if worker and worker is not threading.current_thread():
                worker.join(timeout=max(0, deadline - time.monotonic()))
        drained = not any(worker and worker.is_alive() for worker in workers)
        if drained and self._session is not None and self._owns_session:
            self._session.close()
        return drained

    def close(self):
        return self.shutdown(timeout=2)
