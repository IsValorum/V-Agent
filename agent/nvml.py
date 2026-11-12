"""NVIDIA GPU readings through the driver's own library (nvml.dll), loaded once.

`nvidia-smi` costs a new process per reading (tens of milliseconds of CPU on Windows, every few
seconds, also while the engine is generating). NVML answers the same questions in microseconds from
the already-loaded driver. When the library is missing or fails, callers fall back to nvidia-smi.
"""
import ctypes
import os
import threading
from pathlib import Path

_lock = threading.Lock()
_lib = None        # ctypes library once initialised; False when unavailable
_handles = []


class _Utilization(ctypes.Structure):
    _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]


class _Memory(ctypes.Structure):
    _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]


class _MemoryV2(ctypes.Structure):
    # v2 separates the driver's reserved memory from "used", as nvidia-smi shows it.
    _fields_ = [('version', ctypes.c_uint), ('total', ctypes.c_ulonglong), ('reserved', ctypes.c_ulonglong),
                ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]


def _load():
    global _lib, _handles
    if _lib is not None:
        return _lib
    _lib = False
    if os.name != 'nt':
        return _lib
    system = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'nvml.dll'
    legacy = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'NVIDIA Corporation' / 'NVSMI' / 'nvml.dll'
    for candidate in (system, legacy):
        if not candidate.is_file():
            continue
        try:
            lib = ctypes.WinDLL(str(candidate))
            if lib.nvmlInit_v2() != 0:
                continue
            count = ctypes.c_uint()
            if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
                continue
            handles = []
            for index in range(count.value):
                handle = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle)) == 0:
                    handles.append(handle)
            if handles:
                _lib, _handles = lib, handles
                break
        except (OSError, AttributeError):
            continue
    return _lib


def sample():
    """The most-used NVIDIA device as {'name','util','vram_mib','vram_total_mib','temp','power'},
    or None when NVML is not available (use nvidia-smi then)."""
    with _lock:
        lib = _load()
        if not lib:
            return None
        devices = []
        for handle in _handles:
            name = ctypes.create_string_buffer(96)
            util, memory, temp, power = _Utilization(), _Memory(), ctypes.c_uint(), ctypes.c_uint()
            device = {'name': name.value.decode('utf-8', 'replace') if lib.nvmlDeviceGetName(handle, name, 96) == 0 else '',
                      'util': float(util.gpu) if lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util)) == 0 else None,
                      'vram_mib': None, 'vram_total_mib': None,
                      'temp': float(temp.value) if lib.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp)) == 0 else None,
                      'power': round(power.value / 1000, 2) if lib.nvmlDeviceGetPowerUsage(handle, ctypes.byref(power)) == 0 else None}
            v2 = _MemoryV2(version=ctypes.sizeof(_MemoryV2) | (2 << 24))
            try:
                ok_v2 = lib.nvmlDeviceGetMemoryInfo_v2(handle, ctypes.byref(v2)) == 0
            except AttributeError:
                ok_v2 = False  # older driver
            if ok_v2:
                device['vram_mib'], device['vram_total_mib'] = float(v2.used // 2**20), float(v2.total // 2**20)
            elif lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) == 0:
                device['vram_mib'], device['vram_total_mib'] = float(memory.used // 2**20), float(memory.total // 2**20)
            devices.append(device)
        return max(devices, key=lambda d: d['vram_mib'] or 0) if devices else None
