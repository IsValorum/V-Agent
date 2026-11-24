"""Project Maya (mw00/project-maya) optional source-built engine integration,
Windows prerequisite inspector, official GitHub tag auto-updater, and
per-family configuration manager for V-Agent.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from runtime_paths import DATA_ROOT
from ui_preferences import atomic_json

MAYA_REPO = 'mw00/project-maya'
MAYA_GIT_URL = 'https://github.com/mw00/project-maya.git'
MAYA_RELEASES_API = f'https://api.github.com/repos/{MAYA_REPO}/releases?per_page=8'
MAYA_TAGS_API = f'https://api.github.com/repos/{MAYA_REPO}/tags?per_page=8'
MAYA_RELEASES_URL = f'https://github.com/{MAYA_REPO}/releases'
THEROCK_ROCM_VERSION = '7.14.1'

MANAGED_ROOT = DATA_ROOT / 'engines' / 'project-maya'

CUDA_MIN_CAPABILITY = 7.0
CUDA_VS2026_MIN_VERSION = (13, 2)
CMAKE_MIN_VERSION = (3, 24)
PYTHON_MIN_VERSION = (3, 10)
AMD_SUPPORTED_ARCHS = {'gfx1100', 'gfx1151', 'gfx1201', 'gfx1101', 'gfx1200', 'gfx1030'}

FAMILY_LABELS = {
    'glm': 'GLM-5.3-Flash',
    'glm_dsa': 'GLM-5.3 744B',
    'deepseek': 'DeepSeek-V4.1-Flash-1017',
    'minimax': 'MiniMax-M3.1-Flash',
    'qwen': 'Qwen-3.8-Flash-Next',
    'generic': 'Project Maya',
}

# Stable setup identifiers from Maya's documented quant catalog.
SETUP_MODELS = {
    'glm-maya-xs': {'name': 'GLM-5.3-Flash · Maya-XS', 'gb': 73.4},
    'minimax-maya-xs': {'name': 'MiniMax-M3.1-Flash · Maya-XS', 'gb': 93},
    'deepseek-maya-xs': {'name': 'DeepSeek-V4.1-Flash · Maya-XS', 'gb': 277},
}


FAMILY_SCHEMA = {
    'glm': {
        'label': FAMILY_LABELS['glm'],
        'fields': ('context', 'gpus', 'parallel', 'reserve_mib', 'draft', 'expert_cache',
                   'prefill', 'kv_streaming', 'kv_resident', 'images', 'vision_resident',
                   'turbo', 'ablate', 'thinking_budget', 'reasoning_effort', 'idle_unload_s', 'env'),
        'draft_options': ('mtp', 'dflash2'),
    },
    'glm_dsa': {
        'label': FAMILY_LABELS['glm_dsa'],
        'fields': ('context', 'gpus', 'parallel', 'reserve_mib', 'draft', 'expert_cache',
                   'prefill', 'kv_streaming', 'kv_resident', 'turbo', 'ablate',
                   'thinking_budget', 'reasoning_effort', 'idle_unload_s', 'env'),
        'draft_options': ('mtp',),
        'kv_streaming_locked': True,
        'text_only': True,
    },
    'deepseek': {
        'label': FAMILY_LABELS['deepseek'],
        'fields': ('context', 'gpus', 'parallel', 'reserve_mib', 'draft', 'dspark_conf',
                   'tp', 'mmap', 'prefill_chunk', 'cpu_threads', 'prompt_lookup', 'fast_prefill',
                   'images', 'ablate', 'thinking_budget', 'reasoning_effort', 'idle_unload_s', 'env'),
        'draft_options': ('on', 'none'),
        'mmap_options': ('auto', 'on', 'off'),
    },
    'minimax': {
        'label': FAMILY_LABELS['minimax'],
        'fields': ('context', 'gpus', 'parallel', 'reserve_gb', 'cache_gb', 'draft', 'dspark_conf',
                   'tp', 'kv_cache', 'kv_streaming', 'kv_resident', 'prefill_chunk', 'cpu_threads',
                   'images', 'ablate', 'thinking_budget', 'reasoning_effort', 'idle_unload_s', 'env'),
        'draft_options': ('on', 'none'),
        'kv_options': ('bf16', 'int8', 'fp8', 'fp4'),
    },
    'qwen': {
        'label': FAMILY_LABELS['qwen'],
        'fields': ('context', 'gpus', 'reserve_mib', 'draft', 'expert_cache', 'prefill',
                   'kv', 'ram_gb', 'images', 'thinking_budget', 'reasoning_effort', 'idle_unload_s', 'env'),
        'draft_options': ('mtp', 'none'),
        'kv_options': ('fp16', 'int8', 'k8v4', 'q4_0'),
    },
    # A family a newer Maya brings that V-Agent has no panel for: only the settings every family shares.
    # Everything else its binary offers shows under the engine's other options (engine_options, kind 'maya').
    'generic': {
        'label': FAMILY_LABELS['generic'],
        'fields': ('context', 'gpus', 'thinking_budget', 'reasoning_effort', 'idle_unload_s', 'env'),
        'draft_options': ('none',),
        'text_only': True,
    },
}
KNOWN_FAMILIES = ('glm', 'glm_dsa', 'deepseek', 'minimax', 'qwen')

EFFORT_OPTIONS = ('none', 'low', 'medium', 'high', 'max')

_WIN_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def _parse_version(text: str):
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', str(text or ''))
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def _run_probe(cmd, timeout=5, cwd=None):
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            creationflags=_WIN_FLAGS,
        )
        return proc.returncode, (proc.stdout or '').strip(), (proc.stderr or '').strip()
    except (OSError, subprocess.SubprocessError):
        return None, '', ''


def is_valid_root(path) -> bool:
    if not path:
        return False
    root = Path(path)
    return (root / 'maya.py').is_file() and (root / 'serve' / 'server.py').is_file()


def resolve_root_from_selection(selection) -> Path | None:
    """Resolve a Project Maya checkout root from a root path, build subfolder, or binary path."""
    if not selection:
        return None
    raw = str(selection).strip().strip('"')
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    probes = [candidate, candidate.parent, candidate.parent.parent, candidate.parent.parent.parent, candidate.parent.parent.parent.parent]
    for probe in probes:
        if is_valid_root(probe):
            return probe.resolve()
    return None


def resolve_root(configured_root=None) -> Path | None:
    candidates = []
    if configured_root:
        resolved = resolve_root_from_selection(configured_root)
        if resolved:
            return resolved
        candidates.append(Path(str(configured_root)).expanduser())
    if not (MANAGED_ROOT.parent / '.maya-unlinked').exists():
        candidates.append(MANAGED_ROOT)
    for item in candidates:
        if is_valid_root(item):
            return item.resolve()
    return None


def find_binaries(root: Path | None, extra_exe=None) -> dict[str, str]:
    found = {}
    if extra_exe:
        exe_path = Path(str(extra_exe).strip().strip('"')).expanduser()
        if exe_path.is_file():
            resolved = str(exe_path.resolve())
            stem = exe_path.stem.lower()
            found[stem] = resolved
            if 'vision' not in stem and 'maya' not in found:
                found['maya'] = resolved
            found['custom'] = resolved
    if not root or not Path(root).is_dir():
        return found
    root = Path(root)
    search_dirs = [
        root,
        root / 'bin',
        root / 'out',
        root / 'dist',
        root / 'build',
        root / 'build' / 'Release',
        root / 'build' / 'RelWithDebInfo',
        root / 'build' / 'bin',
        root / 'build' / 'bin' / 'Release',
        root / 'build-cuda',
        root / 'build-cuda' / 'Release',
        root / 'build-hip',
        root / 'build-hip' / 'Release',
        root / 'build-vision' / 'bin',
        root / 'build-vision' / 'bin' / 'Release',
        root / 'engine',
    ]
    if extra_exe:
        exe_dir = Path(str(extra_exe).strip().strip('"')).expanduser().parent
        if exe_dir.is_dir():
            search_dirs.insert(0, exe_dir)
    names = ('maya.exe', 'maya-ds4.exe', 'maya-mm3.exe', 'maya-vision.exe', 'maya', 'maya-ds4', 'maya-mm3', 'maya-vision')
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for name in names:
            candidate = directory / name
            key = Path(name).stem
            if candidate.is_file() and key not in found:
                found[key] = str(candidate.resolve())
    return found


def find_python(root: Path | None, extra_python=None) -> str:
    if extra_python:
        candidate = Path(str(extra_python).strip().strip('"')).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
    if root:
        for rel in (
            'venv/Scripts/python.exe',
            '.venv/Scripts/python.exe',
            'env/Scripts/python.exe',
            '.conda/python.exe',
            'venv/bin/python',
            '.venv/bin/python',
            'env/bin/python',
        ):
            candidate = Path(root) / rel
            if candidate.is_file():
                return str(candidate.resolve())
    for name in ('python', 'python3', 'py'):
        candidate = shutil.which(name)
        if candidate and 'windowsapps' not in candidate.lower():
            return candidate
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        python_home = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Python'
        for folder in sorted(python_home.glob('Python*'), reverse=True):
            candidate = folder / 'python.exe'
            if candidate.is_file():
                return str(candidate)
    return '' if getattr(sys, 'frozen', False) else sys.executable


def installed_version(root: Path | None) -> str:
    if not root or not is_valid_root(root):
        return ''
    root = Path(root)
    if (root / '.git').exists():
        rc, out, _ = _run_probe(['git', '-C', str(root), 'describe', '--tags', '--exact-match'])
        if rc == 0 and out:
            return out.strip()
        rc, out, _ = _run_probe(['git', '-C', str(root), 'rev-parse', '--short', 'HEAD'])
        if rc == 0 and out:
            return out.strip()
    version_file = root / 'VERSION'
    if version_file.is_file():
        return version_file.read_text(encoding='utf-8-sig').strip()
    server_py = root / 'serve' / 'server.py'
    try:
        head = server_py.read_text(encoding='utf-8', errors='replace')[:12000]
        match = re.search(r'MAYA_VERSION\s*=\s*["\']([^"\']+)["\']', head)
        if match:
            return match.group(1).strip()
    except OSError:
        pass
    return ''


def windows_page_file_gb() -> float | None:
    if os.name != 'nt':
        return None
    try:
        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ('dwLength', ctypes.c_uint32),
                ('dwMemoryLoad', ctypes.c_uint32),
                ('ullTotalPhys', ctypes.c_uint64),
                ('ullAvailPhys', ctypes.c_uint64),
                ('ullTotalPageFile', ctypes.c_uint64),
                ('ullAvailPageFile', ctypes.c_uint64),
                ('ullTotalVirtual', ctypes.c_uint64),
                ('ullAvailVirtual', ctypes.c_uint64),
                ('ullAvailExtendedVirtual', ctypes.c_uint64),
            ]
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return round(max(0.0, (status.ullTotalPageFile - status.ullTotalPhys) / 2**30), 1)
    except Exception:
        return None


def _detect_visual_studio():
    if os.name != 'nt':
        return {'installed': False, 'detail': '', 'major': 0}
    pf86 = os.environ.get('ProgramFiles(x86)') or r'C:\Program Files (x86)'
    vswhere = Path(pf86) / 'Microsoft Visual Studio' / 'Installer' / 'vswhere.exe'
    if vswhere.is_file():
        rc, out, _ = _run_probe([
            str(vswhere), '-latest', '-products', '*',
            '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
            '-format', 'json',
        ])
        if rc == 0 and out:
            try:
                rows = json.loads(out)
                if isinstance(rows, list) and rows:
                    item = rows[0]
                    ver = str(item.get('installationVersion') or '')
                    major = int(ver.split('.')[0]) if ver.split('.')[0].isdigit() else 0
                    name = str(item.get('displayName') or f'Visual Studio {ver}').strip()
                    return {'installed': True, 'detail': f'{name} ({ver})' if ver else name, 'major': major}
            except (ValueError, TypeError):
                pass
    for year, major in (('18', 18), ('2022', 17), ('17', 17)):
        for edition in ('BuildTools', 'Community', 'Professional', 'Enterprise'):
            candidate = Path(pf86) / 'Microsoft Visual Studio' / year / edition / 'VC' / 'Auxiliary' / 'Build' / 'vcvars64.bat'
            if candidate.is_file():
                return {'installed': True, 'detail': f'VS {year} {edition}', 'major': major}
            pf = os.environ.get('ProgramFiles') or r'C:\Program Files'
            candidate64 = Path(pf) / 'Microsoft Visual Studio' / year / edition / 'VC' / 'Auxiliary' / 'Build' / 'vcvars64.bat'
            if candidate64.is_file():
                return {'installed': True, 'detail': f'VS {year} {edition}', 'major': major}
    return {'installed': False, 'detail': '', 'major': 0}


def _detect_cuda_toolkit():
    nvcc = shutil.which('nvcc')
    if not nvcc and os.environ.get('CUDA_PATH'):
        candidate = Path(os.environ['CUDA_PATH']) / 'bin' / ('nvcc.exe' if os.name == 'nt' else 'nvcc')
        if candidate.is_file():
            nvcc = str(candidate)
    if os.name == 'nt':
        base = Path(os.environ.get('ProgramFiles') or r'C:\Program Files') / 'NVIDIA GPU Computing Toolkit' / 'CUDA'
        if base.is_dir():
            for folder in sorted(base.iterdir(), key=lambda p: _parse_version(p.name) or (), reverse=True):
                candidate = folder / 'bin' / 'nvcc.exe'
                if candidate.is_file() and (_parse_version(folder.name) or ()) > (_parse_version(nvcc or '') or ()):
                    nvcc = str(candidate)
                    break
    if not nvcc:
        return {'installed': False, 'version': '', 'tuple': None, 'path': ''}
    rc, out, _ = _run_probe([nvcc, '--version'])
    ver = _parse_version(out) if rc == 0 else None
    ver_str = '.'.join(str(x) for x in ver[:2]) if ver else ''
    return {'installed': True, 'version': ver_str, 'tuple': ver, 'path': nvcc}


def _detect_rocm_hip(maya_python: str | None = None):
    hip_path = os.environ.get('HIP_PATH') or ''
    if hip_path and (Path(hip_path) / 'bin').is_dir():
        return {'installed': True, 'detail': f'HIP_PATH ({hip_path})'}
    for exe in (maya_python,):
        if not exe:
            continue
        rc, out, _ = _run_probe([exe, '-c', "import importlib.util;print('1' if importlib.util.find_spec('rocm_sdk') else '')"])
        if rc == 0 and out.strip() == '1':
            return {'installed': True, 'detail': f'rocm-sdk ({THEROCK_ROCM_VERSION})'}
    return {'installed': False, 'detail': ''}


def _classify_gpus(profile: dict):
    nvidia = None
    amd = None
    intel = None
    for gpu in (profile or {}).get('gpus') or []:
        vendor = str(gpu.get('vendor') or '').lower()
        name = str(gpu.get('name') or '')
        if (vendor == 'nvidia' or 'nvidia' in name.lower()) and not nvidia:
            nvidia = gpu
        elif (vendor == 'amd' or 'amd' in name.lower() or 'radeon' in name.lower()) and not amd:
            amd = gpu
        elif (vendor == 'intel' or 'intel' in name.lower()) and not intel:
            intel = gpu
    return nvidia, amd, intel


def check_prerequisites(profile: dict | None = None, maya_root=None, backend: str = 'auto', page_file_override: float | None = None) -> dict:
    """Inspect all Windows build & runtime prerequisites for Project Maya without modifying or downloading anything."""
    if profile is None:
        try:
            import hardware_stats
            profile = hardware_stats.profile_snapshot()
        except Exception:
            profile = {}
    root = resolve_root(maya_root)
    binaries = find_binaries(root)
    py_exe = find_python(root)
    nvidia, amd, intel = _classify_gpus(profile)

    nv_cap = None
    if nvidia and nvidia.get('cuda_capability') is not None:
        try:
            nv_cap = float(nvidia['cuda_capability'])
        except (TypeError, ValueError):
            nv_cap = None
    cuda_hw_ok = bool(nvidia) and (nv_cap is None or nv_cap >= CUDA_MIN_CAPABILITY)
    amd_hw_ok = bool(amd)
    if backend not in ('auto', 'cuda', 'hip'):
        backend = 'auto'
    resolved_backend = backend
    if resolved_backend == 'auto':
        resolved_backend = 'cuda' if cuda_hw_ok else ('hip' if amd_hw_ok else ('cuda' if nvidia else 'none'))

    git_bin = shutil.which('git')
    git_rc, git_out, _ = _run_probe([git_bin, '--version']) if git_bin else (None, '', '')
    git_ok = bool(git_bin and git_rc == 0)

    py_rc, py_ver_out, _ = _run_probe([py_exe, '--version']) if py_exe else (None, '', '')
    py_ver = _parse_version(py_ver_out) if py_rc == 0 else None
    py_ok = bool(py_ver and py_ver >= PYTHON_MIN_VERSION)

    cmake_bin = shutil.which('cmake')
    if not cmake_bin and py_exe:
        rc_mod, _, _ = _run_probe([py_exe, '-m', 'cmake', '--version'])
        if rc_mod == 0:
            cmake_bin = f'{py_exe} -m cmake'
    if cmake_bin and ' -m cmake' not in cmake_bin:
        cm_rc, cm_out, _ = _run_probe([cmake_bin, '--version'])
    elif cmake_bin:
        cm_rc, cm_out, _ = _run_probe([py_exe, '-m', 'cmake', '--version'])
    else:
        cm_rc, cm_out = None, ''
    cm_ver = _parse_version(cm_out) if cm_rc == 0 else None
    cm_ok = bool(cm_ver and cm_ver >= CMAKE_MIN_VERSION)

    ninja_ok = bool(shutil.which('ninja'))
    if not ninja_ok and py_exe:
        nj_rc, _, _ = _run_probe([py_exe, '-m', 'ninja', '--version'])
        ninja_ok = nj_rc == 0

    vs = _detect_visual_studio()
    cuda_tk = _detect_cuda_toolkit()
    rocm_hip = _detect_rocm_hip(py_exe)
    page_gb = page_file_override if page_file_override is not None else windows_page_file_gb()

    checks = []
    if resolved_backend == 'cuda' or (resolved_backend == 'none' and not amd_hw_ok):
        hw_ok = cuda_hw_ok
        hw_detail = (
            f"{nvidia.get('name')} (CC {nv_cap})" if nvidia and nv_cap is not None
            else (nvidia.get('name') if nvidia else ('GPU Intel detectada · no compatible con Maya' if intel else 'No se detectó GPU NVIDIA o AMD compatible'))
        )
        checks.append({'id': 'gpu', 'label': 'GPU NVIDIA (CC >= 7.0)', 'ok': hw_ok, 'required': True, 'detail': hw_detail})
    else:
        checks.append({'id': 'gpu', 'label': 'GPU AMD Radeon compatible (HIP/ROCm)', 'ok': amd_hw_ok, 'required': True,
                       'detail': amd.get('name', 'Radeon') if amd else 'No se detectó GPU AMD compatible'})

    checks.append({'id': 'git', 'label': 'Git', 'ok': git_ok, 'required': True, 'detail': git_out if git_ok else 'Instala Git para Windows'})
    checks.append({'id': 'python', 'label': 'Python 3.10+', 'ok': py_ok, 'required': True, 'detail': py_ver_out if py_ok else 'Instala Python 3.10 o superior'})
    checks.append({'id': 'cmake', 'label': 'CMake 3.24+', 'ok': cm_ok, 'required': True, 'detail': '.'.join(map(str, cm_ver[:3])) if cm_ok else 'Instala CMake 3.24 o superior'})
    checks.append({'id': 'vs', 'label': 'Visual Studio Build Tools C++ (2022/2026)', 'ok': bool(vs['installed']), 'required': True,
                   'detail': vs['detail'] if vs['installed'] else 'Instala Desktop development with C++'})

    if resolved_backend == 'cuda':
        vs2026_mismatch = bool(cuda_tk['installed'] and vs['major'] >= 18 and cuda_tk['tuple'] and cuda_tk['tuple'][:2] < CUDA_VS2026_MIN_VERSION)
        cuda_ok = bool(cuda_tk['installed'] and not vs2026_mismatch)
        if vs2026_mismatch:
            cuda_detail = f"CUDA {cuda_tk['version']} con VS 2026: necesita CUDA 13.2+"
        elif cuda_tk['installed']:
            cuda_detail = f"CUDA {cuda_tk['version']}"
        else:
            cuda_detail = 'Instala NVIDIA CUDA Toolkit (nvcc)'
        checks.append({'id': 'cuda', 'label': 'NVIDIA CUDA Toolkit (nvcc)', 'ok': cuda_ok, 'required': True, 'detail': cuda_detail})
    elif resolved_backend == 'hip':
        rocm_ok = bool(rocm_hip['installed'])
        checks.append({'id': 'rocm', 'label': f'AMD ROCm SDK / HIP ({THEROCK_ROCM_VERSION})', 'ok': rocm_ok, 'required': True,
                       'detail': rocm_hip['detail'] if rocm_ok else f'Instala rocm[libraries,devel]=={THEROCK_ROCM_VERSION} o HIP_PATH'})
        if page_gb is not None:
            pf_ok = page_gb >= 16.0
            checks.append({'id': 'pagefile', 'label': 'Archivo de paginación de Windows (>= 16 GB)', 'ok': pf_ok, 'required': False,
                           'detail': f'{page_gb} GB asignados' if pf_ok else f'{page_gb} GB: amplía el archivo de paginación en Windows para GPUs AMD'})

    checks.append({'id': 'ninja', 'label': 'Ninja (recomendado)', 'ok': ninja_ok, 'required': False,
                   'detail': 'Disponible' if ninja_ok else 'Opcional; acelera la compilación'})
    checks.append({'id': 'repo', 'label': 'Código fuente oficial de Project Maya', 'ok': root is not None, 'required': True,
                   'detail': str(root) if root else 'Pulsa Clonar repositorio oficial o elige tu carpeta de Project Maya'})
    built_ok = any(k in binaries for k in ('maya', 'maya-ds4', 'maya-mm3'))
    checks.append({'id': 'binary', 'label': 'Motores compilados en este equipo', 'ok': built_ok, 'required': True,
                   'detail': ', '.join(sorted(binaries)) if built_ok else 'Pendiente de compilar en este equipo'})

    if resolved_backend == 'cuda' and page_gb is not None and nvidia:
        vram_mib = nvidia.get('vram_total_mib') or nvidia.get('vram_mib') or 0
        recommended = int(float(vram_mib) / 1024 + 8.999)
        checks.append({'id': 'pagefile', 'label': 'Archivo de paginación de Windows',
                       'ok': page_gb >= recommended, 'required': False,
                       'detail': f'{page_gb:g} GB · {recommended} GB recomendados'})

    hardware_supported = cuda_hw_ok if resolved_backend == 'cuda' else amd_hw_ok if resolved_backend == 'hip' else False
    tools_ok = all(item['ok'] for item in checks if item['required'] and item['id'] not in ('repo', 'binary'))
    ready_to_build = bool(hardware_supported and tools_ok and root is not None)
    ready_to_run = bool(hardware_supported and root is not None and built_ok and py_ok)

    if not hardware_supported:
        note = 'Project Maya no incluye backend Vulkan ni solo CPU: necesita GPU NVIDIA (CC >= 7.0) o AMD Radeon compatible.'
    elif ready_to_run:
        note = 'Project Maya está listo para ejecutar modelos compatibles en este equipo.'
    elif ready_to_build:
        note = 'Todos los requisitos de compilación están listos. Puedes compilar Project Maya en este equipo.'
    else:
        note = 'Instala los requisitos marcados antes de compilar Project Maya en este equipo.'

    return {
        'backend': resolved_backend,
        'requested_backend': backend,
        'hardware_supported': hardware_supported,
        'ready_to_build': ready_to_build,
        'can_setup': bool(hardware_supported and root and py_ok),
        'ready_to_run': ready_to_run,
        'root': str(root) if root else '',
        'python': py_exe,
        'version': installed_version(root),
        'binaries': binaries,
        'page_file_gb': page_gb,
        'checks': checks,
        'note': note,
    }


def check_latest_release(current_version: str = '') -> dict:
    """Query mw00/project-maya official GitHub releases (falling back to tags)."""
    import app_updates
    headers = {
        'User-Agent': 'V-Agent/' + app_updates.VERSION,
        'Accept': 'application/vnd.github+json',
        'Accept-Encoding': 'identity',
    }
    try:
        req = urllib.request.Request(MAYA_RELEASES_API, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            rows = json.load(response)
        # The highest version, straight to it (not the first in GitHub's list, not one step at a time).
        eligible = [r for r in (rows or []) if isinstance(r, dict) and not r.get('draft') and not r.get('prerelease')]
        release = max(eligible, key=lambda r: (_parse_version(r.get('tag_name')) or (), str(r.get('published_at') or '')), default=None)
        if release:
            tag = str(release.get('tag_name') or '')
            available = bool(_parse_version(tag) and _parse_version(current_version) and _parse_version(tag) > _parse_version(current_version))
            return {
                'tag': tag,
                'development': bool(release.get('prerelease')),
                'current': current_version,
                'available': available,
                'source_only': True,
                'notes': str(release.get('body') or '')[:100000],
                'url': release.get('html_url') or MAYA_RELEASES_URL,
                'repository': MAYA_REPO,
                'asset': None,
                'dependencies': [],
            }
        req_tags = urllib.request.Request(MAYA_TAGS_API, headers=headers)
        with urllib.request.urlopen(req_tags, timeout=15) as response:
            tags = json.load(response)
        # GitHub lists tags by name, not by version: pick the highest version.
        named = [t for t in (tags or []) if isinstance(t, dict) and t.get('name') and _parse_version(t['name'])]
        first = max(named, key=lambda t: _parse_version(t['name']), default=None)
        if not first:
            return {'available': False, 'source_only': True, 'message': 'No hay un precompilado compatible publicado.', 'repository': MAYA_REPO}
        tag = str(first['name'])
        available = bool(_parse_version(tag) and _parse_version(current_version) and _parse_version(tag) > _parse_version(current_version))
        return {
            'tag': tag,
            'development': False,
            'current': current_version,
            'available': available,
            'source_only': True,
            'notes': '',
            'url': f'https://github.com/{MAYA_REPO}/releases/tag/{urllib.parse.quote(tag)}',
            'repository': MAYA_REPO,
            'asset': None,
            'dependencies': [],
        }
    except Exception as error:
        return {'available': False, 'source_only': True, 'error': str(error), 'repository': MAYA_REPO}


def clone_or_update_repo(target_root=None, tag: str = '') -> dict:
    """Clone mw00/project-maya into target_root or fast-forward an existing clone to official tag."""
    if build_status()['building']:
        raise ValueError('Espera a que termine la configuración de Project Maya.')
    if tag and not re.fullmatch(r'v?\d+\.\d+\.\d+(?:[-.][A-Za-z0-9.]+)?', tag):
        raise ValueError('Etiqueta de Project Maya no válida.')
    if not shutil.which('git'):
        raise ValueError('Git no está instalado en este equipo.')
    dest = Path(target_root).expanduser() if target_root else MANAGED_ROOT
    dest = dest.resolve()
    if not dest.exists() or not (dest / '.git').exists():
        if dest.exists() and any(dest.iterdir()):
            raise ValueError('La carpeta elegida no está vacía ni es un repositorio Git de Project Maya.')
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ['git', 'clone', '--depth', '1']
        if tag:
            cmd += ['--branch', tag]
        cmd += [MAYA_GIT_URL, str(dest)]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600, creationflags=_WIN_FLAGS)
        if proc.returncode:
            detail = (proc.stderr or proc.stdout or '').strip().splitlines()
            raise ValueError('No se pudo clonar Project Maya' + (f': {detail[-1][:180]}' if detail else '.'))
        if dest == MANAGED_ROOT.resolve():
            (MANAGED_ROOT.parent / '.maya-unlinked').unlink(missing_ok=True)
        return {'root': str(dest), 'version': installed_version(dest), 'action': 'cloned'}

    if not is_valid_root(dest):
        raise ValueError('La carpeta no contiene Project Maya (maya.py y serve/server.py).')
    origin_rc, origin, _ = _run_probe(['git', '-C', str(dest), 'remote', 'get-url', 'origin'])
    normalized = origin.rstrip('/').removesuffix('.git').lower()
    if origin_rc != 0 or normalized not in (
        'https://github.com/mw00/project-maya', 'git@github.com:mw00/project-maya',
        'ssh://git@github.com/mw00/project-maya',
    ):
        raise ValueError('La carpeta no usa el repositorio oficial de Project Maya.')
    if not tag:
        tag = check_latest_release(installed_version(dest)).get('tag', '')
    if not re.fullmatch(r'v?\d+\.\d+\.\d+(?:[-.][A-Za-z0-9.]+)?', tag):
        raise ValueError('No se pudo obtener una versión oficial de Project Maya.')
    rc, shallow, _ = _run_probe(['git', '-C', str(dest), 'rev-parse', '--is-shallow-repository'])
    fetch_flags = ['--unshallow'] if rc == 0 and shallow == 'true' else []
    dirty_rc, dirty, _ = _run_probe(['git', '-C', str(dest), 'status', '--porcelain', '--untracked-files=no'])
    if dirty_rc != 0 or dirty:
        raise ValueError('La copia de Maya tiene cambios de código locales. Revísalos antes de actualizar.')
    ref = f'refs/tags/{tag}'
    prior_rc, prior, _ = _run_probe(['git', '-C', str(dest), 'rev-parse', 'HEAD'])
    if prior_rc != 0 or not prior:
        raise ValueError('No se pudo comprobar la revisión local de Project Maya.')
    for argv in (['fetch', *fetch_flags, MAYA_GIT_URL, f'{ref}:{ref}'], ['merge', '--ff-only', ref]):
        code, out, err = _run_probe(['git', '-C', str(dest), *argv], timeout=600)
        if code != 0:
            raise ValueError('No se pudo actualizar Project Maya: ' + ((err or out)[-500:] or 'Git no respondió.'))
    rc, head, _ = _run_probe(['git', '-C', str(dest), 'rev-parse', 'HEAD'])
    target_rc, target, _ = _run_probe(['git', '-C', str(dest), 'rev-parse', f'{ref}^{{commit}}'])
    if rc != 0 or target_rc != 0 or not head or head != target:
        raise ValueError('La copia local no quedó en la etiqueta solicitada. Revisa la rama local.')
    if head != prior:
        (dest / '.v-agent-maya-needs-setup').touch()
    if dest == MANAGED_ROOT.resolve():
        (MANAGED_ROOT.parent / '.maya-unlinked').unlink(missing_ok=True)
    return {'root': str(dest), 'version': tag, 'action': 'updated', 'tag': tag}


def uninstall_installation(configured_root=None) -> dict:
    """Unlink discovery without touching the user's checkout, settings or weights."""
    if build_status()['building']:
        raise ValueError('Espera a que termine la configuración de Project Maya.')
    root = resolve_root(configured_root)
    if root is None:
        raise ValueError('Project Maya no está vinculado.')
    if root == MANAGED_ROOT.resolve():
        MANAGED_ROOT.parent.mkdir(parents=True, exist_ok=True)
        (MANAGED_ROOT.parent / '.maya-unlinked').touch()
    return {'uninstalled': True, 'removed_files': False, 'unlinked_external': root != MANAGED_ROOT.resolve()}


_BUILD_LOCK = threading.RLock()
_BUILD_STATE = {'building': False, 'operation': '', 'error': '', 'tail': '', 'guided': False}
_SETUP_PROCESS = None


def build_status() -> dict:
    with _BUILD_LOCK:
        state = dict(_BUILD_STATE)
    if state['guided']:
        from runtime_paths import log_tail
        raw = log_tail(DATA_ROOT / 'logs' / 'maya-setup.log', 5000)
        raw = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw)
        raw = re.sub(r'(?i)\b(?:hf_[A-Za-z0-9_]{12,}|bearer\s+[\w.~-]+)', '[hidden]', raw)
        state['tail'] = '\n'.join(raw.splitlines()[-18:])
    return state


def cancel_setup() -> dict:
    with _BUILD_LOCK:
        if not _BUILD_STATE['building']:
            raise ValueError('No hay una preparación de Maya que se pueda cancelar.')
        process = _SETUP_PROCESS
        if process and process.poll() is None:
            result = subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=_WIN_FLAGS, timeout=10)
            if result.returncode and process.poll() is None:
                raise ValueError('No se pudo cancelar la preparación de Maya.')
        _BUILD_STATE['cancelled'] = True
    return build_status()


def setup_arguments(backend, model, options):
    """Translate V-Agent's form into the supported Maya setup CLI switches."""
    if backend not in ('auto', 'cuda', 'hip'):
        raise ValueError('Backend de Maya no válido.')
    if not isinstance(options, dict) or set(options) - {'source','source_dir','models_dir','gpus','context','vision','drafting'}:
        raise ValueError('Opciones de preparación de Maya no válidas.')
    if not isinstance(model, str) or (model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,95}', model)):
        raise ValueError('Identificador de modelo de Maya no válido.')
    source = options.get('source', 'catalog')
    if source not in ('catalog', 'gguf', 'local') or (source == 'catalog' and not model):
        raise ValueError('Elige un modelo de Project Maya.')
    if source == 'gguf' and model:
        raise ValueError('La importación GGUF de GLM usa los archivos de la carpeta elegida.')
    args = ['--setup', '--no-start', '--plain', '--yes']
    if backend != 'auto':
        args += ['--backend', backend]
    if model:
        args += ['--model', model]
    if source == 'catalog':
        args.append('--download-model')
    for field, flag, required in (
        ('source_dir', '--gguf-dir' if source == 'gguf' else '--model-dir', source != 'catalog'),
        ('models_dir', '--models-dir', False),
    ):
        value = options.get(field, '')
        if field == 'source_dir' and not required:
            continue
        if value or required:
            if not isinstance(value, str) or not value or not Path(value).is_absolute() or not Path(value).is_dir():
                raise ValueError('Elige una carpeta existente para los modelos de Maya.')
            args += [flag, str(Path(value).resolve())]
    gpus = options.get('gpus', '')
    if gpus:
        if not isinstance(gpus, str) or not re.fullmatch(r'\d{1,2}(?:\s*,\s*\d{1,2}){0,15}', gpus):
            raise ValueError('Indica los índices de GPU separados por comas.')
        gpu_ids = [int(i) for i in gpus.split(',')]
        if len(set(gpu_ids)) != len(gpu_ids):
            raise ValueError('Indica los índices de GPU separados por comas.')
        args += ['--gpus', ','.join(map(str, gpu_ids))]
    context = options.get('context')
    if context is not None:
        if type(context) is not int or not 8192 <= context <= 1048576:
            raise ValueError('Contexto de Maya fuera de rango (8192–1048576).')
        args += ['--context', str(context)]
    vision = options.get('vision', True)
    drafting = options.get('drafting','on')
    if type(vision) is not bool or drafting not in ('on','off','measure'):
        raise ValueError('Opciones de preparación de Maya no válidas.')
    if not vision:
        args.append('--no-vision')
    args += ['--drafting', drafting]
    return args


def start_build(maya_root, backend: str = 'auto', model: str = '', options=None) -> dict:
    """Run the engine's setup as a private child process with no interactive console."""
    root = resolve_root(maya_root)
    if not root:
        raise ValueError('No se encontró la carpeta de Project Maya.')
    args = setup_arguments(backend, model, {} if options is None else options)
    interpreter = find_python(root)
    if not interpreter:
        raise ValueError('Instala Python 3.10 o superior para preparar Project Maya.')
    venv = root / '.venv'
    venv_python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    log_target = DATA_ROOT / 'logs' / 'maya-setup.log'
    log_target.parent.mkdir(parents=True, exist_ok=True)
    with _BUILD_LOCK:
        if _BUILD_STATE['building']:
            raise ValueError('Project Maya ya se está configurando.')
        log_target.write_bytes(b'')
        _BUILD_STATE.update(building=True, operation='Configurando Project Maya…', error='',
                            guided=True, cancelled=False, exit_code=None)

    def run_step(argv, log):
        global _SETUP_PROCESS
        with _BUILD_LOCK:
            if _BUILD_STATE['cancelled']:
                return None
            _SETUP_PROCESS = process = subprocess.Popen(
                argv, cwd=root, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, creationflags=_WIN_FLAGS,
            )
        try:
            return process.wait()
        finally:
            with _BUILD_LOCK:
                _SETUP_PROCESS = None

    def prepare():
        code = None
        error = ''
        try:
            with log_target.open('ab') as log:
                code = 0
                if not venv_python.is_file():
                    code = run_step([interpreter, '-m', 'venv', str(venv)], log)
                if code == 0:
                    code = run_step([str(venv_python), '-u', str(root / 'maya.py'), *args], log)
            if code not in (None, 0):
                error = 'No se pudo preparar el modelo de Maya. Revisa el registro.'
            elif code == 0:
                if not list_configs(root):
                    error = 'Maya no dejó un modelo configurado. Revisa maya-setup.log.'
                else:
                    (root / '.v-agent-maya-needs-setup').unlink(missing_ok=True)
        except OSError as exc:
            with log_target.open('ab') as log:
                log.write(str(exc).encode('utf8', errors='replace'))
            error = 'No se pudo preparar el modelo de Maya. Revisa el registro.'
        finally:
            with _BUILD_LOCK:
                cancelled = _BUILD_STATE['cancelled']
                operation = '' if error else 'Configuración de Project Maya terminada.'
                if cancelled:
                    operation = 'Preparación de Maya cancelada.'
                _BUILD_STATE.update(building=False, operation=operation,
                                    error='' if cancelled else error, exit_code=code)

    threading.Thread(target=prepare, name='maya-setup', daemon=True).start()
    return build_status()


# ---------------------------------------------------------------------------- config inspection & editing

def _flag_value(args: list[str], flag: str, default=None):
    for i, item in enumerate(args):
        if item == flag and i + 1 < len(args):
            return args[i + 1]
        if item.startswith(flag + '='):
            return item.split('=', 1)[1]
    return default


def _has_flag(args: list[str], flag: str) -> bool:
    return any(item == flag or item.startswith(flag + '=') for item in args)


def _set_flag(args: list[str], flag: str, value) -> list[str]:
    out = _del_flag(args, flag)
    if value not in (None, ''):
        out += [flag, str(value)]
    return out


def _del_flag(args: list[str], *flags: str) -> list[str]:
    out = []
    skip = False
    for item in args:
        if skip:
            skip = False
            continue
        if item in flags:
            skip = True
            continue
        if any(item.startswith(f + '=') for f in flags):
            continue
        out.append(item)
    return out


def config_family(cfg: dict, path: Path | None = None) -> str:
    exe_name = Path(str(cfg.get('exe') or '')).stem.lower()
    args = [str(x) for x in cfg.get('args') or []]
    model_name = str(cfg.get('model_name') or (path.stem if path else '')).lower()
    pack = str(_flag_value(args, '--pack', '') or _flag_value(args, '--glm-pack', '') or '').lower()
    installer = cfg.get('installer')
    family = installer.get('family') if isinstance(installer, dict) else None
    family = str(family).strip().lower().replace('-', '_') if family else None
    if family and family not in KNOWN_FAMILIES:
        # the installer names a family this V-Agent does not know: never guess one of the known panels for it
        return 'generic'
    if family == 'minimax' or 'mm3' in exe_name or 'minimax' in model_name or 'mm3' in pack:
        return 'minimax'
    if family == 'qwen' or '--ple-gguf' in args or 'qwen' in model_name or 'cyber' in model_name:
        return 'qwen'
    if family == 'deepseek' or '--pack' in args or 'ds4' in exe_name or 'deepseek' in model_name or 'ds4' in pack:
        return 'deepseek'
    if family in ('glm-dsa','glm_dsa'):
        return 'glm_dsa'
    if 'glm' in model_name or _has_flag(args, '--glm-pack') or 'glm' in pack:
        if '744' in model_name or 'dsa' in model_name or 'dsa' in pack or ('glm-5.3' in model_name and 'flash' not in model_name):
            return 'glm_dsa'
        return 'glm'
    return 'glm'


def _gpu_text(val) -> str:
    if val is None or val == '':
        return ''
    if isinstance(val, (list, tuple)):
        return ','.join(str(x).strip() for x in val if str(x).strip() != '')
    return str(val).strip()


def _parse_gpu_value(text):
    raw = str(text or '').strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(',') if p.strip() != '']
    for p in parts:
        if not p.isdigit():
            raise ValueError('Las GPUs de Maya deben ser índices numéricos separados por comas (ej. 0 o 0,1).')
    if len(parts) == 1:
        return int(parts[0])
    return [int(p) for p in parts]


def _on_off(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value or '').strip().lower()
    if s in ('1', 'on', 'true', 'yes', 'si'):
        return True
    if s in ('0', 'off', 'false', 'no', ''):
        return False
    return default


def describe_config(path: Path) -> dict:
    cfg = _read_json(path, {})
    if not isinstance(cfg, dict) or not cfg:
        raise ValueError('Archivo de configuración de Maya no válido.')
    if not cfg.get('exe') or not isinstance(cfg.get('args'), list):
        raise ValueError('Configuración de Project Maya incompleta.')
    args = [str(x) for x in cfg['args']]
    family = config_family(cfg, path)
    schema = FAMILY_SCHEMA[family]
    env = dict(cfg.get('env') or {}) if isinstance(cfg.get('env'), dict) else {}

    ctx = int(cfg.get('context') or _flag_value(args, '--max-context', 32768) or 32768)
    parallel = int(_flag_value(args, '--parallel', 1) or 1)
    reserve_mib = _flag_value(args, '--vram-reserve-mib' if family in ('glm', 'glm_dsa', 'qwen') else '--reserve-mib', '')
    schema = dict(schema)
    schema['effort_options'] = {
        'glm': ('none', 'low', 'high', 'max'), 'glm_dsa': ('none', 'low', 'high', 'max'),
        'deepseek': ('none', 'high', 'max'), 'minimax': ('none', 'low', 'medium', 'high', 'xhigh'),
        'qwen': ('low', 'medium', 'xhigh'),
    }.get(family, ('none', 'low', 'medium', 'high', 'max'))
    if family == 'glm':
        draft = 'dflash2' if _flag_value(args, '--dflash') else 'mtp'
        if not (_flag_value(args, '--dflash') or cfg.get('_val_dflash')):
            schema['draft_options'] = ('mtp',)
    elif family == 'glm_dsa':
        draft = 'mtp'
    elif family == 'qwen':
        mtp = _flag_value(args, '--mtp')
        draft = 'mtp' if mtp and _flag_value(args, '--mtp-max-t') != '1' else 'none'
        if not mtp:
            schema['draft_options'] = ('none',)
    else:
        draft = 'on' if str(_flag_value(args, '--dspark', 'none' if family == 'minimax' else 'on')).lower() == 'on' else 'none'
    if family in ('deepseek', 'minimax'):
        images = _on_off(_flag_value(args, '--vision', 'on' if family == 'deepseek' else 'off'))
    else:
        images = not schema.get('text_only') and isinstance(cfg.get('vision'), dict)
        if not (images or isinstance(cfg.get('vision_off'), dict)):
            schema['fields'] = tuple(field for field in schema['fields'] if field not in ('images', 'vision_resident'))
    hidden = {'turbo'} | ({'kv_resident'} if schema.get('kv_streaming_locked') else set())
    schema['fields'] = tuple(field for field in schema['fields'] if field not in hidden)
    ablate = cfg.get('ablate')
    if not isinstance(ablate, dict):
        schema['fields'] = tuple(field for field in schema['fields'] if field != 'ablate')

    values = {
        'family': family,
        'family_label': schema['label'],
        'model_name': str(cfg.get('model_name') or path.stem),
        'config_path': str(path),
        'exe': str(cfg.get('exe') or ''),
        'context': ctx,
        'gpus': _gpu_text(cfg.get('gpu')),
        'parallel': parallel,
        'reserve_mib': str(reserve_mib or ''),
        'reserve_gb': str(_flag_value(args, '--reserve-gb', '') or ''),
        'cache_gb': str(_flag_value(args, '--cache-gb', '') or ''),
        'draft': draft,
        'dspark_conf': str(_flag_value(args, '--dspark-conf', '') or ''),
        'tp': str(_flag_value(args, '--tp', '') or ''),
        'mmap': str(_flag_value(args, '--mmap-experts', 'auto') or 'auto'),
        'prefill': str(_flag_value(args, '--prefill', 'auto') or 'auto'),
        'prefill_chunk': str(_flag_value(args, '--prefill-chunk' if family == 'deepseek' else '--chunk', '') or ''),
        'cpu_threads': str(_flag_value(args, '--cpu-threads', '') or ''),
        'prompt_lookup': str(_flag_value(args, '--suffix-draft', '3') or '3'),
        'fast_prefill': bool(cfg.get('fast_prefill', False)),
        'expert_cache': str(_flag_value(args, '--expert-cache', 'auto') or 'auto'),
        'kv': str(_flag_value(args, '--kv', 'fp16') or 'fp16'),
        'kv_cache': str(_flag_value(args, '--kv-cache', 'int8') or 'int8'),
        'kv_streaming': False if schema.get('kv_streaming_locked') else _on_off(_flag_value(args, '--kv-streaming', 'on' if _flag_value(args, '--kv-resident') else 'off')),
        'kv_resident': str(_flag_value(args, '--kv-resident', '') or ''),
        'ram_gb': str(env.get('MAYA_EXPERT_RAM_GB') or env.get('STRATA_EXPERT_RAM_GB') or ''),
        'images': images,
        'vision_resident': bool((cfg.get('vision') or {}).get('resident')) if isinstance(cfg.get('vision'), dict) else False,
        'turbo': bool(cfg.get('turbo', _has_flag(args, '--turbo'))),
        'ablate': bool(isinstance(ablate, dict) and ablate.get('default')),
        'thinking_budget': int(cfg.get('thinking_budget') or 0),
        'reasoning_effort': str(cfg.get('reasoning_effort') or 'default'),
        'idle_unload_s': float(cfg.get('idle_unload_s') or 0),
        'env': env,
    }
    return {
        **values,
        'schema': schema,
        'serve_command': ['python', '-m', 'serve.server', '--engine', 'maya', '--config', str(path)],
    }


def apply_family_settings(path: Path, updates: dict) -> dict:
    """Validate and persist per-family Project Maya settings directly inside its maya-*.json file."""
    if not isinstance(updates, dict):
        raise ValueError('Configuración de Maya no válida.')
    cfg = _read_json(path, {})
    if not isinstance(cfg, dict) or not cfg:
        raise ValueError('No se encontró la configuración de Maya.')
    family = config_family(cfg, path)
    schema = describe_config(path)['schema']
    updates = {key: value for key, value in updates.items() if key in schema['fields']}
    args = [str(x) for x in cfg.get('args') or []]
    env = dict(cfg.get('env') or {}) if isinstance(cfg.get('env'), dict) else {}

    if 'context' in updates and updates['context'] is not None:
        ctx = int(updates['context'])
        if not 2048 <= ctx <= 1048576:
            raise ValueError('Contexto de Maya fuera de rango (2048–1048576).')
        cfg['context'] = ctx
        args = _set_flag(args, '--max-context', ctx)

    if 'gpus' in updates:
        gpu_val = _parse_gpu_value(updates.get('gpus'))
        if gpu_val is None:
            cfg.pop('gpu', None)
        else:
            cfg['gpu'] = gpu_val

    if 'parallel' in updates and updates['parallel'] not in (None, ''):
        par = int(updates['parallel'])
        if not 1 <= par <= 8:
            raise ValueError('Paralelismo de Maya fuera de rango (1–8).')
        args = _set_flag(args, '--parallel', par)

    if 'reserve_mib' in updates:
        raw = str(updates.get('reserve_mib') or '').strip()
        flag = '--vram-reserve-mib' if family in ('glm', 'glm_dsa', 'qwen') else '--reserve-mib'
        if raw and not raw.isdigit():
            raise ValueError('La reserva de VRAM debe indicarse en MiB enteros.')
        args = _set_flag(args, flag, raw or None)

    if 'reserve_gb' in updates and family == 'minimax':
        raw = str(updates.get('reserve_gb') or '').strip()
        if raw and not 0 <= float(raw) <= 4096:
            raise ValueError('El ajuste de memoria debe estar entre 0 y 4096 GB.')
        args = _set_flag(args, '--reserve-gb', raw or None)

    if 'cache_gb' in updates and family == 'minimax':
        raw = str(updates.get('cache_gb') or '').strip()
        if raw and not 0 <= float(raw) <= 4096:
            raise ValueError('El ajuste de memoria debe estar entre 0 y 4096 GB.')
        args = _set_flag(args, '--cache-gb', raw or None)

    if 'draft' in updates and updates['draft'] is not None:
        draft = str(updates['draft']).strip().lower()
        allowed = schema.get('draft_options', ())
        if draft not in allowed:
            raise ValueError('Opción de draft no admitida por esta familia de Maya.')
        if family == 'qwen':
            # The path is needed even with Qwen's speculative decoding turned off.
            args = _set_flag(args, '--mtp-max-t', '1' if draft == 'none' and _flag_value(args, '--mtp') else None)
        elif family == 'glm':
            target = _flag_value(args, '--dflash') or cfg.get('_val_dflash')
            if target:
                cfg['_val_dflash'] = target
            args = _set_flag(args, '--dflash', target if draft == 'dflash2' else None)
        elif family in ('deepseek', 'minimax'):
            args = _set_flag(args, '--dspark', 'none' if draft == 'none' else 'on')

    if 'dspark_conf' in updates and family in ('deepseek', 'minimax'):
        raw = str(updates.get('dspark_conf') or '').strip()
        if raw:
            val = float(raw)
            if not 0.0 <= val <= 1.0:
                raise ValueError('El umbral DSpark debe estar entre 0 y 1.')
        args = _set_flag(args, '--dspark-conf', raw or None)

    if 'tp' in updates and family in ('deepseek', 'minimax'):
        raw = str(updates.get('tp') or '').strip()
        if raw and (not raw.isdigit() or not 1 <= int(raw) <= 16):
            raise ValueError('Tensor parallel (--tp) debe ser un entero entre 1 y 16.')
        args = _set_flag(args, '--tp', raw or None)

    if 'mmap' in updates and family == 'deepseek':
        mmap = str(updates.get('mmap') or 'auto').strip().lower()
        if mmap not in schema['mmap_options']:
            raise ValueError('Opción mmap no válida para DeepSeek.')
        args = _set_flag(args, '--mmap-experts', None if mmap == 'auto' else mmap)

    if 'expert_cache' in updates and family in ('glm', 'glm_dsa', 'qwen'):
        raw = str(updates.get('expert_cache') or 'auto').strip().lower()
        if raw != 'auto' and not raw.isdigit():
            raise ValueError('La caché de expertos debe ser "auto" o un número entero.')
        args = _set_flag(args, '--expert-cache', None if raw == 'auto' else raw)

    if 'prefill' in updates and family in ('glm', 'glm_dsa', 'qwen'):
        raw = str(updates.get('prefill') or 'auto').strip().lower()
        if raw != 'auto' and not raw.isdigit():
            raise ValueError('Prefill debe ser "auto" o un entero.')
        args = _set_flag(args, '--prefill', None if raw == 'auto' else raw)

    if 'prefill_chunk' in updates and family in ('deepseek', 'minimax'):
        raw = str(updates.get('prefill_chunk') or '').strip()
        if raw and not raw.isdigit():
            raise ValueError('El tamaño de chunk prefill debe ser entero.')
        flag = '--prefill-chunk' if family == 'deepseek' else '--chunk'
        args = _set_flag(args, flag, raw or None)

    if 'cpu_threads' in updates and family in ('deepseek', 'minimax'):
        raw = str(updates.get('cpu_threads') or '').strip()
        if raw and (not raw.isdigit() or not 1 <= int(raw) <= 512):
            raise ValueError('Los hilos de CPU deben estar entre 1 y 512.')
        args = _set_flag(args, '--cpu-threads', raw or None)

    if 'prompt_lookup' in updates and family == 'deepseek':
        raw = str(updates.get('prompt_lookup') or '').strip()
        if raw and (not raw.isdigit() or not 0 <= int(raw) <= 16):
            raise ValueError('Lookup de prompt (--suffix-draft) debe estar entre 0 y 16.')
        args = _set_flag(args, '--suffix-draft', raw or None)

    if 'fast_prefill' in updates and family == 'deepseek':
        cfg['fast_prefill'] = bool(updates['fast_prefill'])

    if 'kv' in updates and family == 'qwen':
        kv = str(updates.get('kv') or 'fp16').strip().lower()
        if kv not in schema['kv_options']:
            raise ValueError('Formato KV no admitido por Qwen en Maya.')
        args = _set_flag(args, '--kv', kv)

    if 'kv_cache' in updates and family == 'minimax':
        kv = str(updates.get('kv_cache') or 'fp16').strip().lower()
        if kv not in schema['kv_options']:
            raise ValueError('Formato KV no admitido por MiniMax en Maya.')
        args = _set_flag(args, '--kv-cache', kv)

    if 'kv_streaming' in updates:
        if schema.get('kv_streaming_locked'):
            args = _set_flag(args, '--kv-streaming', 'off')
        elif family in ('glm', 'minimax'):
            args = _set_flag(args, '--kv-streaming', 'on' if updates['kv_streaming'] else 'off')

    if 'kv_resident' in updates and family in ('glm', 'minimax'):
        raw = str(updates['kv_resident'] or '').strip()
        if raw and (not raw.isdigit() or not 0 <= int(raw) <= 1048576):
            raise ValueError('La ventana KV debe indicarse en tokens.')
        args = _set_flag(args, '--kv-resident', raw or None)

    if 'images' in updates and not schema.get('text_only'):
        on = bool(updates['images'])
        if family in ('deepseek', 'minimax'):
            args = _set_flag(args, '--vision', 'on' if on else 'off')
        elif on and not cfg.get('vision') and isinstance(cfg.get('vision_off'), dict):
            cfg['vision'] = cfg.pop('vision_off')
        elif not on and isinstance(cfg.get('vision'), dict):
            cfg['vision_off'] = cfg.pop('vision')
        if family == 'qwen':
            args = [arg for arg in args if arg != '--vision']
            if cfg.get('vision'):
                args.append('--vision')

    if 'vision_resident' in updates and isinstance(cfg.get('vision'), dict):
        cfg['vision'] = {**cfg['vision'], 'resident': bool(updates['vision_resident'])}

    if 'ablate' in updates and isinstance(cfg.get('ablate'), dict):
        cfg['ablate']['default'] = bool(updates['ablate'])
        if isinstance(cfg.get('sampling'), dict):
            cfg['sampling'].pop('ablate', None)

    if 'thinking_budget' in updates and updates['thinking_budget'] is not None:
        budget = int(updates['thinking_budget'])
        if budget < 0 or budget > 262144:
            raise ValueError('El presupuesto de pensamiento está fuera de rango.')
        cfg['thinking_budget'] = budget

    if 'reasoning_effort' in updates and updates['reasoning_effort']:
        eff = str(updates['reasoning_effort']).strip().lower()
        if eff == 'default':
            cfg.pop('reasoning_effort', None)
        elif eff in schema['effort_options']:
            cfg['reasoning_effort'] = eff
        else:
            raise ValueError('Nivel de razonamiento no válido para este modelo de Maya.')

    if 'idle_unload_s' in updates and updates['idle_unload_s'] is not None:
        idle = float(updates['idle_unload_s'])
        if not 0 <= idle <= 86400:
            raise ValueError('Tiempo de descarga por inactividad fuera de rango.')
        cfg['idle_unload_s'] = idle

    if 'env' in updates and isinstance(updates['env'], dict):
        cleaned = {}
        for k, v in updates['env'].items():
            key = str(k or '').strip()
            if not key or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
                raise ValueError(f'Variable de entorno no válida: {key}')
            cleaned[key] = str(v)
        env = cleaned
    if 'ram_gb' in updates and family == 'qwen':
        raw_ram = str(updates['ram_gb'] if updates['ram_gb'] is not None else '').strip()
        if raw_ram and not 0 <= float(raw_ram) <= 4096:
            raise ValueError('El ajuste de memoria debe estar entre 0 y 4096 GB.')
        env.pop('STRATA_EXPERT_RAM_GB', None)
        if raw_ram:
            env['MAYA_EXPERT_RAM_GB'] = raw_ram
        else:
            env.pop('MAYA_EXPERT_RAM_GB', None)

    cfg['args'] = args
    if env:
        cfg['env'] = env
    else:
        cfg.pop('env', None)

    atomic_json(path, cfg)
    return describe_config(path)


def list_configs(root: Path | None) -> list[dict]:
    if not root or not Path(root).is_dir():
        return []
    root = Path(root)
    files = sorted(root.glob('maya-*.json'))
    # Also scan immediate config subdirectories such as configs/ or models/ if present.
    for sub in ('configs', 'models'):
        if (root / sub).is_dir():
            files.extend(sorted((root / sub).glob('maya-*.json')))
    seen = set()
    configs = []
    for file in files:
        key = os.path.normcase(str(file.resolve()))
        if key in seen:
            continue
        seen.add(key)
        try:
            info = describe_config(file.resolve())
        except (ValueError, TypeError, OSError):
            continue
        identifier = 'maya--' + hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]
        info['id'] = identifier
        configs.append(info)
    return configs
