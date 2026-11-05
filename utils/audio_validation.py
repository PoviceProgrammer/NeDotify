"""Read audio duration without treating unsupported WebM as corrupt audio."""
import json
import math
import os
import shutil
import struct
import subprocess
import sys


def ffprobe_path():
    try:
        from core.setup_engine import resolve_managed_tool
        managed = resolve_managed_tool('ffprobe')
        if managed:
            return managed
    except (ImportError, OSError, ValueError):
        pass
    bundled = os.path.join(getattr(sys, '_MEIPASS', ''), ('ffprobe.exe' if sys.platform == 'win32' else 'ffprobe'))
    if getattr(sys, '_MEIPASS', None) and os.path.isfile(bundled):
        return bundled
    installed = shutil.which('ffprobe')
    if installed:
        return installed
    return None


def ebml_audio_duration(path):
    """Pure-Python EBML/WebM reader for Segment Duration (0x4489)."""
    with open(path, 'rb') as f:
        if f.read(4) != b'\x1a\x45\xdf\xa3':
            raise ValueError('Не удалось проверить аудиоконтейнер')
        f.seek(0)

        def read_id():
            first = f.read(1)
            if not first:
                return None
            b = first[0]
            if b == 0:
                return None
            mask, length = 0x80, 1
            while not (b & mask) and length <= 4:
                mask >>= 1
                length += 1
            if length > 4:
                return None
            raw = first + f.read(length - 1)
            return int.from_bytes(raw, 'big') if len(raw) == length else None

        def read_size():
            first = f.read(1)
            if not first:
                return None
            b = first[0]
            if b == 0:
                return None
            mask, length = 0x80, 1
            while not (b & mask) and length <= 8:
                mask >>= 1
                length += 1
            if length > 8:
                return None
            val = b & (mask - 1)
            rem = f.read(length - 1)
            if len(rem) < length - 1:
                return None
            for byte in rem:
                val = (val << 8) | byte
            return None if val == (1 << (7 * length)) - 1 else val

        # 1. EBML Header element (0x1A45DFA3)
        eid = read_id()
        esize = read_size()
        if eid != 0x1a45dfa3 or esize is None:
            raise ValueError('Аудиоконтейнер повреждён')
        f.seek(f.tell() + esize)

        # 2. Segment element (0x18538067)
        sid = read_id()
        ssize = read_size()
        if sid != 0x18538067:
            raise ValueError('Аудиоконтейнер повреждён')

        seg_end = (f.tell() + ssize) if ssize is not None else None
        timecode_scale = 1000000
        raw_duration = None
        has_audio_track = False
        track_types = []

        while seg_end is None or f.tell() < seg_end:
            sub_id = read_id()
            if sub_id is None:
                break
            sub_size = read_size()
            pos = f.tell()
            if sub_id == 0x1549a966:  # Segment Info
                if sub_size is not None:
                    info_end = pos + sub_size
                    while f.tell() < info_end:
                        iid = read_id()
                        if iid is None:
                            break
                        isize = read_size()
                        if isize is None:
                            break
                        idata = f.read(isize)
                        if len(idata) < isize:
                            raise ValueError('Аудиоконтейнер повреждён')
                        if iid == 0x2ad7b1:  # TimestampScale / TimecodeScale
                            timecode_scale = int.from_bytes(idata, 'big') or 1000000
                        elif iid == 0x4489:  # Duration (0x4489, float / double)
                            if isize == 4:
                                raw_duration = struct.unpack('>f', idata)[0]
                            elif isize == 8:
                                raw_duration = struct.unpack('>d', idata)[0]
                else:
                    break
            elif sub_id == 0x1654ae6b:  # Tracks
                if sub_size is not None:
                    tracks_end = pos + sub_size
                    while f.tell() < tracks_end:
                        tid = read_id()
                        if tid is None:
                            break
                        tsize = read_size()
                        if tid == 0xae:  # TrackEntry
                            entry_end = f.tell() + (tsize or 0)
                            while tsize is not None and f.tell() < entry_end:
                                eid2 = read_id()
                                if eid2 is None:
                                    break
                                esize2 = read_size()
                                if esize2 is None:
                                    break
                                edata = f.read(esize2)
                                if len(edata) < esize2:
                                    raise ValueError('Аудиоконтейнер повреждён')
                                if eid2 == 0x83:  # TrackType
                                    tt = int.from_bytes(edata, 'big')
                                    track_types.append(tt)
                                    if tt == 2:
                                        has_audio_track = True
                        else:
                            if tsize is not None:
                                f.seek(f.tell() + tsize)
                            else:
                                break
                else:
                    break
            elif sub_id == 0x1f43b675:  # Cluster
                if raw_duration is not None:
                    break
                if sub_size is not None:
                    f.seek(pos + sub_size)
                else:
                    break
            else:
                if sub_size is not None:
                    f.seek(pos + sub_size)
                else:
                    break

        if track_types and not has_audio_track:
            raise ValueError('Контейнер не содержит аудио')
        if raw_duration is None or not math.isfinite(raw_duration) or raw_duration <= 0:
            raise ValueError('Неизвестная длительность аудио')

        dur_sec = (raw_duration * timecode_scale) / 1000000000.0
        return dur_sec


def audio_duration(path):
    import mutagen
    try:
        audio = mutagen.File(path)
        duration = float(getattr(getattr(audio, 'info', None), 'length', 0) or 0)
        if math.isfinite(duration) and duration > 0:
            return duration
    except Exception:
        pass
    # Mutagen has no WebM parser and cannot identify some fragmented M4A
    # streams. Probe these recognizable containers, requiring real audio
    # packets and a complete duration; arbitrary payloads remain rejected.
    with open(path, 'rb') as source:
        header = source.read(16)
    is_ebml = header[:4] == b'\x1a\x45\xdf\xa3'
    is_mp4 = len(header) >= 12 and header[4:8] == b'ftyp'
    if not (is_ebml or is_mp4):
        raise ValueError('Не удалось проверить аудиоконтейнер')
    probe = ffprobe_path()
    if not probe:
        if is_ebml:
            return ebml_audio_duration(path)
        raise ValueError('Для проверки фрагментированного M4A требуется FFprobe')
    try:
        result = subprocess.run(
            [probe, '-v', 'error', '-select_streams', 'a', '-count_packets', '-show_entries',
             'stream=codec_type,duration,nb_read_packets:format=duration', '-of', 'json', os.path.abspath(path)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=12,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        if is_ebml:
            return ebml_audio_duration(path)
        raise ValueError('Не удалось проверить аудиоконтейнер FFprobe') from None
    if result.returncode or result.stderr.strip():
        raise ValueError('Аудиоконтейнер повреждён')
    data = json.loads(result.stdout)
    streams = [stream for stream in data.get('streams', [])
               if stream.get('codec_type') == 'audio' and int(stream.get('nb_read_packets') or 0) > 0]
    if not streams:
        raise ValueError('Контейнер не содержит аудио')
    duration = float((data.get('format') or {}).get('duration') or streams[0].get('duration') or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Неизвестная длительность аудио')
    return duration
