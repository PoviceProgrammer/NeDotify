"""Stable user-facing error categories without exposing provider internals."""

import errno
import sqlite3
import re


def redact_download_error(error):
    """Retain useful provider diagnostics without signed URLs or credentials."""
    value = re.sub(r'https?://[^\s\]"\']+', '<media-url>', str(error or ''))
    value = re.sub(r'(?i)((?:authorization|cookie|password|token|secret|api[_-]?key)\s*[:=]\s*)[^\s,;]+', r'\1<redacted>', value)
    return value[:1500]


def describe_error(error, operation=''):
    message = str(error or '').lower()
    code = getattr(error, 'code', '')
    if code in ('missing_yt_dlp', 'missing_ffmpeg', 'missing_ffprobe', 'dependencies_busy'):
        return {'code': code, 'title': 'Компоненты скачивания недоступны', 'message': str(error), 'action': 'setup'}
    if 'flac доступен только' in message:
        return {'code': 'lossy_source', 'title': 'Источник не lossless', 'message': 'FLAC не улучшит качество этого источника. Выберите оригинал, MP3, M4A или Opus.', 'action': 'setup'}
    number = getattr(error, 'errno', None)
    if isinstance(error, sqlite3.Error):
        return {'code': 'database', 'title': 'Не удалось обновить библиотеку', 'message': 'Повторите действие. Если ошибка сохраняется, перезапустите приложение.', 'action': 'retry'}
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return {'code': 'invalid_input', 'title': 'Проверьте введённые данные', 'message': 'Не удалось выполнить действие с этими параметрами.', 'action': None}
    if number == errno.ENOSPC or any(word in message for word in ('disk full', 'not enough space', 'no space left', 'недостаточно места')):
        return {'code': 'disk_full', 'title': 'Не хватает места на диске', 'message': 'Освободите место и повторите загрузку.', 'action': 'storage'}
    if isinstance(error, FileNotFoundError) or any(word in message for word in ('file not found', 'файл не найден', 'аудиофайл не найден', 'файл перемещён')):
        return {'code': 'file_missing', 'title': 'Аудиофайл не найден', 'message': 'Файл мог быть перемещён или удалён. Проверьте папку с музыкой.', 'action': 'library'}
    if isinstance(error, PermissionError) or any(word in message for word in ('permission denied', 'access denied', 'доступ запрещён')):
        return {'code': 'permission', 'title': 'Нет доступа к файлу', 'message': 'Проверьте доступ к папке и не открыт ли файл другой программой.', 'action': 'retry'}
    if any(word in message for word in ('offline', 'timeout', 'timed out', 'connection', 'network', 'ssl', 'dns', 'сеть', 'соединени')):
        return {'code': 'network', 'title': 'Не удалось подключиться к источнику', 'message': 'Проверьте интернет или повторите попытку позже.', 'action': 'retry'}
    if any(word in message for word in ('403', '404', 'unavailable', 'private video', 'not available', 'copyright', 'недоступен', 'ограничен')):
        return {'code': 'unavailable', 'title': 'Трек недоступен у источника', 'message': 'Попробуйте другую запись или повторите поиск.', 'action': 'search'}
    title = 'Не удалось скачать трек' if 'download' in operation else 'Не удалось выполнить действие'
    return {'code': 'unexpected', 'title': title, 'message': 'Попробуйте ещё раз. Подробности сохранены в журнале приложения.', 'action': 'retry'}
