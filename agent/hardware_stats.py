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
    try:
        import nvml
        found=nvml.profile()  # the driver's library: no extra process
        if found:return found
    except Exception:
        pass
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


def _dxgi_adapters():
    """(description, dedicated VRAM in MiB) of each hardware adapter, from DXGI: a 64-bit SIZE_T, right on every
    vendor (Win32_VideoController.AdapterRAM is a uint32 and stops at 4095 MiB)."""
    if os.name!='nt':
        return []
    import ctypes
    from ctypes import wintypes
    class LUID(ctypes.Structure):
        _fields_=[('LowPart',wintypes.DWORD),('HighPart',wintypes.LONG)]
    class DESC1(ctypes.Structure):
        _fields_=[('Description',wintypes.WCHAR*128),('VendorId',wintypes.UINT),('DeviceId',wintypes.UINT),
                  ('SubSysId',wintypes.UINT),('Revision',wintypes.UINT),('DedicatedVideoMemory',ctypes.c_size_t),
                  ('DedicatedSystemMemory',ctypes.c_size_t),('SharedSystemMemory',ctypes.c_size_t),
                  ('AdapterLuid',LUID),('Flags',wintypes.UINT)]
    class GUID(ctypes.Structure):
        _fields_=[('Data1',wintypes.DWORD),('Data2',wintypes.WORD),('Data3',wintypes.WORD),('Data4',ctypes.c_ubyte*8)]
    def method(pointer,index,*argtypes):
        vtable=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.HRESULT,ctypes.c_void_p,*argtypes)(vtable[index])
    result=[]
    try:
        # IID_IDXGIFactory1 {770aae78-f26f-4dba-a829-253c83d1b387}
        iid=GUID(0x770aae78,0xf26f,0x4dba,(ctypes.c_ubyte*8)(0xa8,0x29,0x25,0x3c,0x83,0xd1,0xb3,0x87))
        factory=ctypes.c_void_p()
        if ctypes.WinDLL('dxgi').CreateDXGIFactory1(ctypes.byref(iid),ctypes.byref(factory))!=0 or not factory.value:
            return []
        try:
            for index in range(16):
                adapter=ctypes.c_void_p()
                try:method(factory,12,wintypes.UINT,ctypes.POINTER(ctypes.c_void_p))(factory,index,ctypes.byref(adapter))  # EnumAdapters1
                except OSError:break                                     # DXGI_ERROR_NOT_FOUND: no more adapters
                if not adapter.value:break
                try:
                    desc=DESC1()
                    method(adapter,10,ctypes.POINTER(DESC1))(adapter,ctypes.byref(desc))                          # GetDesc1
                    if not desc.Flags & 2 and desc.DedicatedVideoMemory:   # DXGI_ADAPTER_FLAG_SOFTWARE: skipped
                        result.append((desc.Description,round(desc.DedicatedVideoMemory/2**20)))
                finally:method(adapter,2)(adapter)                       # Release
        finally:method(factory,2)(factory)
    except (OSError,AttributeError,ValueError):
        return result
    return result


def _registry_adapters():
    """(DriverDesc, MiB) from the display class key's HardwareInformation.qwMemorySize (REG_QWORD)."""
    if os.name!='nt':
        return []
    result=[]
    try:
        import winreg
        root=r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,root) as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                sub=winreg.EnumKey(key,index)
                if not sub.isdigit():continue
                try:
                    with winreg.OpenKey(key,sub) as adapter:
                        name=str(winreg.QueryValueEx(adapter,'DriverDesc')[0])
                        size=winreg.QueryValueEx(adapter,'HardwareInformation.qwMemorySize')[0]
                except OSError:continue
                if isinstance(size,bytes):size=int.from_bytes(size[:8],'little')
                if isinstance(size,int) and size>0:result.append((name,round(size/2**20)))
    except (ImportError,OSError):
        return result
    return result


def _vram_64bit():
    """Name -> [MiB, ...] (one per adapter of that name, in order) and the source used."""
    found={}
    # The registry first: the board's memory, the figure Task Manager and nvidia-smi show; DXGI (dedicated
    # memory minus what the system reserves) where the driver writes no qwMemorySize.
    for source,adapters in (('registry',_registry_adapters()),('dxgi',_dxgi_adapters())):
        for name,mib in adapters:
            found.setdefault(source,{}).setdefault(' '.join(name.lower().split()),[]).append(mib)
    return found


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
        result=[];wide=_vram_64bit();used={}
        for item in data if isinstance(data,list) else []:
            name=str(item.get('Name') or '').strip()
            if not name or 'basic display' in name.lower():continue
            try:vram=round(int(item.get('AdapterRAM') or 0)/2**20) or None
            except (TypeError,ValueError):vram=None
            source='wmi'
            # AdapterRAM is a uint32: any card with 4 GB or more reads 4095 MiB (issue #1, a 12 GB RX 6700 XT).
            key=' '.join(name.lower().split())
            for origin in ('registry','dxgi'):
                sizes=wide.get(origin,{}).get(key) or []
                position=used.get((origin,key),0)
                if position<len(sizes):
                    used[(origin,key)]=position+1
                    # Only a larger figure replaces WMI's: an integrated GPU's dedicated carve-out (128 MiB) must
                    # not replace the shared memory WMI reports for it.
                    if sizes[position]>(vram or 0):vram,source=sizes[position],origin
                    break
            vendor='NVIDIA' if 'nvidia' in name.lower() else 'AMD' if 'amd' in name.lower() or 'radeon' in name.lower() else 'Intel' if 'intel' in name.lower() else 'Other'
            result.append({'name':name,'vendor':vendor,'driver':str(item.get('DriverVersion') or ''),'vram_mib':vram,'cuda_capability':None,'source':source})
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
