"""Dev-only Windows PDH GPU samples, scoped to a benchmark process tree."""
import ctypes
from ctypes import wintypes
import os
import re


class _Number(ctypes.Union):
    _fields_ = [('longValue', wintypes.LONG), ('doubleValue', ctypes.c_double),
                ('largeValue', ctypes.c_longlong), ('text', ctypes.c_void_p)]


class _Value(ctypes.Structure):
    _fields_ = [('status', wintypes.DWORD), ('number', _Number)]


class _Item(ctypes.Structure):
    _fields_ = [('name', wintypes.LPWSTR), ('value', _Value)]


class WindowsGpuSampler:
    """Uses English counter paths regardless of Windows display language.

    Engine percentages are per engine, not percentages of a single global GPU.
    The busiest process/adapter/engine is reported separately from their sum.
    """
    PATHS = {
        'engines': r'\GPU Engine(*)\Utilization Percentage',
        'dedicated_bytes': r'\GPU Process Memory(*)\Dedicated Usage',
        'shared_bytes': r'\GPU Process Memory(*)\Shared Usage',
    }

    def __init__(self):
        self.error = None
        self.query = wintypes.HANDLE()
        self.counters = {}
        if os.name != 'nt':
            self.error = 'Windows GPU counters unavailable'
            return
        self.pdh = ctypes.WinDLL('pdh')
        self.pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wintypes.HANDLE)]
        self.pdh.PdhOpenQueryW.restype = wintypes.LONG
        self.pdh.PdhAddEnglishCounterW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wintypes.HANDLE)]
        self.pdh.PdhAddEnglishCounterW.restype = wintypes.LONG
        self.pdh.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
        self.pdh.PdhCollectQueryData.restype = wintypes.LONG
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.pdh.PdhGetFormattedCounterArrayW.restype = wintypes.LONG
        self.pdh.PdhCloseQuery.argtypes = [wintypes.HANDLE]
        self.pdh.PdhCloseQuery.restype = wintypes.LONG
        status = self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query))
        if status:
            self.error = f'PdhOpenQuery 0x{status & 0xffffffff:08x}'
            return
        for name, path in self.PATHS.items():
            handle = wintypes.HANDLE()
            status = self.pdh.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(handle))
            if status:
                self.error = f'PdhAddEnglishCounter {name} 0x{status & 0xffffffff:08x}'
                self.close()
                return
            self.counters[name] = handle
        self.pdh.PdhCollectQueryData(self.query)

    def _values(self, handle, pids):
        size, count = wintypes.DWORD(), wintypes.DWORD()
        status = self.pdh.PdhGetFormattedCounterArrayW(handle, 0x200, ctypes.byref(size), ctypes.byref(count), None)
        if status & 0xffffffff not in (0, 0x800007D2) or not size.value:
            return []
        buffer = ctypes.create_string_buffer(size.value)
        status = self.pdh.PdhGetFormattedCounterArrayW(handle, 0x200, ctypes.byref(size), ctypes.byref(count), buffer)
        if status:
            return []
        items = ctypes.cast(buffer, ctypes.POINTER(_Item))
        result = []
        for index in range(count.value):
            item = items[index]
            name = item.name or ''
            match = re.search(r'(?:^|_)pid_(\d+)', name)
            if match and int(match.group(1)) in pids and item.value.status in (0, 1):
                result.append((name, item.value.number.doubleValue))
        return result

    def sample(self, pids):
        if self.error or not self.query:
            return {'available': False, 'error': self.error}
        status = self.pdh.PdhCollectQueryData(self.query)
        if status:
            return {'available': False, 'error': f'PdhCollect 0x{status & 0xffffffff:08x}'}
        engines = self._values(self.counters['engines'], pids)
        dedicated = self._values(self.counters['dedicated_bytes'], pids)
        shared = self._values(self.counters['shared_bytes'], pids)
        return {'available': True, 'engine_instances': len(engines),
                'busiest_engine_pct': max((v for _, v in engines), default=0.0),
                'engine_pct_sum': sum(v for _, v in engines),
                'dedicated_mib': sum(v for _, v in dedicated) / 1048576,
                'shared_mib': sum(v for _, v in shared) / 1048576}

    def close(self):
        if self.query:
            self.pdh.PdhCloseQuery(self.query)
            self.query = wintypes.HANDLE()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
