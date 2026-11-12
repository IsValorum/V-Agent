"""Low-overhead host telemetry independent of the selected inference engine."""
import csv
import io
import json
import os
import platform
from pathlib import Path
from runtime_paths import DATA_ROOT
import shutil
import subprocess
import threading
import time
import psutil

_lock = threading.Lock()
_disk = None
_gpu = {}
_gpu_at = 0.0
_gpu_running = False


def _number(value):
    try:
        n = float(value.strip())
        return n if 0 <= n < float('inf') else None
    except (ValueError, AttributeError):
        return None


def parse_nvidia(text):
    devices = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        name, util, used, total, temp, power = (part.strip() for part in row[:6])
        values = {'name': name, 'util': _number(util), 'vram_mib': _number(used),
                  'vram_total_mib': _number(total), 'temp': _number(temp), 'power': _number(power)}
        if any(values[k] is not None for k in ('util', 'vram_mib', 'vram_total_mib', 'temp', 'power')):
            devices.append(values)
    # Report the most-used device, never add together incompatible cards.
    return max(devices, key=lambda d: d['vram_mib'] or 0) if devices else {}


def _nvidia_command():
    command = shutil.which('nvidia-smi')
    if command:
        return command
    system = os.environ.get('SystemRoot', r'C:\Windows')
    for path in (Path(system)/'System32'/'nvidia-smi.exe', Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'NVIDIA Corporation'/'NVSMI'/'nvidia-smi.exe'):
        if path.is_file():
            return str(path)
    return None


def _sample_gpu():
    global _gpu, _gpu_at, _gpu_running
    result = {}
    try:
        import nvml
        result = nvml.sample()  # microseconds, no process; None when NVML is unavailable
    except Exception:
        result = None
    try:
        command = None if result is not None else _nvidia_command()
        result = result or {}
        if command:
            proc = subprocess.run([command, '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw', '--format=csv,noheader,nounits'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if proc.returncode == 0:
                result = parse_nvidia(proc.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        with _lock:
            _gpu, _gpu_at, _gpu_running = result, time.monotonic(), False


def snapshot():
    global _disk, _gpu_running
    result = {}
    try:
        vm = psutil.virtual_memory()
        result['ram'] = {'used_gib': round((vm.total-vm.available)/2**30, 1), 'total_gib': round(vm.total/2**30, 1)}
    except (OSError, ValueError):
        pass
    try:
        counters, now = psutil.disk_io_counters(), time.monotonic()
        with _lock:
            prior = _disk
            if counters:
                _disk = (now, counters.read_bytes, counters.write_bytes)
                if prior and now > prior[0] and counters.read_bytes >= prior[1] and counters.write_bytes >= prior[2]:
                    result['disk'] = {'read_mbs': round((counters.read_bytes-prior[1])/(now-prior[0])/2**20, 1), 'write_mbs': round((counters.write_bytes-prior[2])/(now-prior[0])/2**20, 1)}
    except (OSError, ValueError, AttributeError):
        pass
    with _lock:
        result['gpu'] = dict(_gpu)
        if not _gpu_running and time.monotonic()-_gpu_at >= 5:
            _gpu_running = True
            threading.Thread(target=_sample_gpu, name='val-hardware-gpu', daemon=True).start()
    return result


_profile = None
_profile_at = 0.0
_profile_lock = threading.Lock()


def _cpu_name():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            return str(winreg.QueryValueEx(key, 'ProcessorNameString')[0]).strip()
    except (ImportError, OSError, ValueError):
        return platform.processor() or platform.machine() or 'CPU'


def _windows_build():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as key:
            product, build = str(winreg.QueryValueEx(key,'ProductName')[0]), str(winreg.QueryValueEx(key,'CurrentBuild')[0])
            # Windows 11 still writes "Windows 10" in ProductName; build 22000 and later is Windows 11.
            if product.startswith('Windows 10') and build.isdigit() and int(build) >= 22000:
                product = 'Windows 11' + product[len('Windows 10'):]
            return {'product':product, 'build':build, 'display':str(winreg.QueryValueEx(key,'DisplayVersion')[0])}
    except (ImportError, OSError, ValueError):
        return {}


def _nvidia_profile():
    command=_nvidia_command()
    if not command:
        return []
    try:
        proc=subprocess.run([command,'--query-gpu=name,driver_version,memory.total,compute_cap','--format=csv,noheader,nounits'],
                            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=5,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if proc.returncode:
            return []
        result=[]
        for row in csv.reader(io.StringIO(proc.stdout)):
            if len(row)<4:continue
            name,driver,memory,cap=(part.strip() for part in row[:4])
            try:vram=int(float(memory))
            except ValueError:vram=0
            try:capability=float(cap)
            except ValueError:capability=None
            if name:
                result.append({'name':name,'vendor':'NVIDIA','driver':driver,'vram_mib':vram or None,'cuda_capability':capability,'source':'nvidia-smi'})
        return result
    except (OSError,subprocess.SubprocessError,ValueError):
        return []


def _wmi_gpus():
    if os.name!='nt':
        return []
    script='Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM | ConvertTo-Json -Compress'
    try:
        proc=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,
                            encoding='utf-8',errors='replace',timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if proc.returncode or not proc.stdout.strip():return []
        data=json.loads(proc.stdout)
        if isinstance(data,dict):data=[data]
        result=[]
        for item in data if isinstance(data,list) else []:
            name=str(item.get('Name') or '').strip()
            if not name or 'basic display' in name.lower():continue
            try:vram=round(int(item.get('AdapterRAM') or 0)/2**20) or None
            except (TypeError,ValueError):vram=None
            vendor='NVIDIA' if 'nvidia' in name.lower() else 'AMD' if 'amd' in name.lower() or 'radeon' in name.lower() else 'Intel' if 'intel' in name.lower() else 'Other'
            result.append({'name':name,'vendor':vendor,'driver':str(item.get('DriverVersion') or ''),'vram_mib':vram,'cuda_capability':None,'source':'wmi'})
        return result
    except (OSError,subprocess.SubprocessError,ValueError,json.JSONDecodeError):
        return []


def profile_snapshot(max_age=60.0):
    """Static host facts for engine recommendations, cached to keep polling cheap."""
    global _profile,_profile_at
    with _profile_lock:
        if _profile is not None and time.monotonic()-_profile_at<max_age:
            return _profile
        gpus=_nvidia_profile() or _wmi_gpus()
        try:
            vm=psutil.virtual_memory();disk=psutil.disk_usage(str(DATA_ROOT))
            memory={'total_gib':round(vm.total/2**30,1),'available_gib':round(vm.available/2**30,1)}
            disk_info={'total_gib':round(disk.total/2**30,1),'free_gib':round(disk.free/2**30,1)}
        except (OSError,ValueError,AttributeError):
            memory={};disk_info={}
        primary=max(gpus,key=lambda item:item.get('vram_mib') or 0) if gpus else {}
        _profile={'os':{**_windows_build(),'release':platform.release(),'version':platform.version(),'arch':platform.machine()},
                  'cpu':{'name':_cpu_name(),'physical':psutil.cpu_count(logical=False),'logical':psutil.cpu_count(logical=True)},
                  'ram':memory,'gpus':gpus,'primary_gpu':primary,'disk':disk_info}
        _profile_at=time.monotonic()
        return _profile
