"""Map detected host hardware to the exact official engine assets to install.

Decision table (Windows x64):
  * NVIDIA GPU with a driver new enough for llama.cpp's CUDA 12.4 build  -> llama.cpp CUDA
  * Discrete AMD Radeon / Intel Arc GPU, or NVIDIA with an older driver   -> llama.cpp Vulkan
  * Integrated graphics only, or no GPU                                   -> llama.cpp CPU (Vulkan offered)
Strata (NVIDIA + CUDA 13 driver) and Strata Rust are listed with their own requirements.
"""
import re

CUDA_LLAMA_MIN_DRIVER = 551.61
CUDA_STRATA_MIN_DRIVER = 580.0
STRATA_ARCHS = {7.5, 8.0, 8.6, 8.9, 12.0}
ENGINE_NAMES = {
    'llama-cuda': 'llama.cpp · CUDA 12.4',
    'llama-vulkan': 'llama.cpp · Vulkan',
    'llama-cpu': 'llama.cpp · CPU',
    'strata': 'Strata · PolyStrata',
    'rust': 'Strata Rust',
}
LLAMA_VARIANT = {'llama-cuda': 'cuda', 'llama-vulkan': 'vulkan', 'llama-cpu': 'cpu'}


def _driver(value):
    match = re.match(r'\s*(\d+(?:\.\d+)?)', str(value or ''))
    return float(match[1]) if match else 0.0


def _nvidia(profile):
    for item in profile.get('gpus') or []:
        if str(item.get('vendor', '')).lower() == 'nvidia' or 'nvidia' in str(item.get('name', '')).lower():
            return item
    return {}


def _discrete_vulkan_gpu(profile):
    """A non-NVIDIA GPU worth offloading to: Radeon RX/Pro, Intel Arc. Integrated graphics are not."""
    for item in profile.get('gpus') or []:
        name = str(item.get('name') or '').lower()
        vendor = str(item.get('vendor') or '').lower()
        # Discrete parts carry a model number ("Radeon RX 7600", "Arc(TM) A770"); integrated ones are
        # reported as plain "Radeon(TM) Graphics" / "Arc(TM) Graphics" and stay on the CPU build.
        if vendor == 'amd' and re.search(r'\brx\s*\d{3,4}|\bpro\s*w\d{3,4}|instinct|vega\s*\d{2}', name):
            return item
        if vendor == 'intel' and re.search(r'arc(\(tm\))?\s*[ab]\d{3}', name):
            return item
    return {}


def _asset(releases, key):
    release = (releases or {}).get(key) or {}
    asset = release.get('asset') or {}
    dependencies = release.get('dependencies') or []
    return release, asset, dependencies


def _entry(key, recommended, reason, releases, required_driver=None):
    release, asset, dependencies = _asset(releases, key)
    tag = release.get('tag') or ''
    current = str(release.get('current') or '')
    if release.get('error'):
        status = 'check'
    elif release.get('message') and not release.get('asset'):
        status = 'missing'
    elif not tag:
        status = 'check'
    elif current and tag.lstrip('v') == current.lstrip('v'):
        status = 'installed'
    elif release.get('available'):
        status = 'available'
    else:
        status = 'installed' if current else 'check'
    return {
        'key': key,
        'name': ENGINE_NAMES[key],
        'recommended': bool(recommended),
        'reason': reason,
        'tag': tag,
        'current': current,
        'status': status,
        'available': bool(release.get('available')),
        'asset': asset.get('name') or '',
        'asset_size': asset.get('size') or 0,
        'dependencies': [item.get('name') for item in dependencies if item.get('name')],
        'repository': release.get('repository') or '',
        'url': release.get('url') or '',
        'required_driver': required_driver,
    }


def best_llama(profile):
    """The llama.cpp build this machine should use: 'llama-cuda', 'llama-vulkan' or 'llama-cpu'."""
    profile = profile or {}
    gpu = _nvidia(profile)
    if gpu and _driver(gpu.get('driver')) >= CUDA_LLAMA_MIN_DRIVER:
        return 'llama-cuda'
    if gpu or _discrete_vulkan_gpu(profile):
        return 'llama-vulkan'
    return 'llama-cpu'


def recommend(profile, releases):
    """Return one row per official engine, with the recommended variant first."""
    profile = profile or {}
    gpu = _nvidia(profile)
    other = _discrete_vulkan_gpu(profile)
    driver = _driver(gpu.get('driver'))
    capability = gpu.get('cuda_capability')
    vram = gpu.get('vram_mib') or 0
    nvidia = bool(gpu)
    best = best_llama(profile)
    strata = nvidia and driver >= CUDA_STRATA_MIN_DRIVER and (capability is None or float(capability) in STRATA_ARCHS)
    if nvidia:
        gpu_facts = f"{gpu.get('name')} · {vram / 1024:.1f} GB VRAM · driver {gpu.get('driver') or '?'}" + (f" · CC {capability}" if capability is not None else '')
    elif other:
        gpu_facts = f"{other.get('name')}" + (f" · {other['vram_mib'] / 1024:.1f} GB" if other.get('vram_mib') else '')
    else:
        gpu_facts = 'No dedicated GPU detected'
    rows = [
        _entry('llama-cuda', best == 'llama-cuda',
               gpu_facts + ('' if best == 'llama-cuda' else (f' · needs NVIDIA driver {CUDA_LLAMA_MIN_DRIVER:.2f} or newer' if nvidia else ' · needs an NVIDIA GPU')),
               releases, CUDA_LLAMA_MIN_DRIVER),
        _entry('llama-vulkan', best == 'llama-vulkan',
               (gpu_facts + ' · Vulkan runs on AMD, Intel Arc and NVIDIA GPUs') if best == 'llama-vulkan'
               else 'Alternative GPU build for AMD, Intel Arc and NVIDIA (Vulkan)', releases, None),
        _entry('llama-cpu', best == 'llama-cpu',
               'Works on any Windows x64 PC' + (' · best choice without a dedicated GPU' if best == 'llama-cpu' else ' · fallback'),
               releases, None),
        _entry('strata', strata,
               (gpu_facts if nvidia else 'Strata Poly prebuilt needs an NVIDIA GPU and a CUDA 13 driver')
               + ('' if strata else ' · not recommended for this GPU/driver'), releases, CUDA_STRATA_MIN_DRIVER),
        _entry('rust', True, 'Strata Rust is the Qwen3.5/3.6 backend; install when using those model families', releases, None),
    ]
    order = {'llama-cuda': 0, 'llama-vulkan': 1, 'llama-cpu': 2, 'strata': 3, 'rust': 4}
    rows.sort(key=lambda row: (not row['recommended'], order.get(row['key'], 9)))
    summary = gpu_facts + ' · ' + {'llama-cuda': 'llama.cpp CUDA recommended', 'llama-vulkan': 'llama.cpp Vulkan recommended',
                                    'llama-cpu': 'llama.cpp CPU recommended'}[best]
    return {'profile': profile, 'engines': rows, 'summary': summary, 'best': best, 'variant': LLAMA_VARIANT[best]}
