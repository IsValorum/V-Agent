"""Tests for Project Maya Option A integration, llama.cpp update fix, engine uninstall, and 5-language i18n."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

TMP = str(Path(tempfile.mkdtemp(prefix='va-maya-')).resolve())
os.environ['STRATA_AGENT_DATA'] = TMP
sys.path[:0] = ['agent', '.']

import engine_recommendations  # noqa: E402
import engine_updates  # noqa: E402
import maya_engine  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _InlineThread:
    def __init__(self, target=None, args=(), kwargs=None, **_):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


class LlamaUpdateAndUninstallTests(unittest.TestCase):
    def setUp(self):
        import threading
        self.folder = Path(tempfile.mkdtemp(prefix='case-', dir=TMP))
        self.addCleanup(shutil.rmtree, self.folder, True)
        inline = types.SimpleNamespace(Thread=_InlineThread, RLock=threading.RLock, Lock=threading.Lock)
        for p in (
            patch.object(engine_updates, 'DATA_ROOT', self.folder),
            patch.object(engine_updates, 'threading', inline),
            patch.object(engine_updates.time, 'sleep', return_value=None),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.updates = engine_updates.Updates(lambda: {})

    def _asset(self, repo: str, name: str, body: bytes) -> dict:
        return {
            'name': name,
            'size': len(body),
            'digest': 'sha256:' + hashlib.sha256(body).hexdigest(),
            'browser_download_url': f'https://github.com/{repo}/releases/download/tag/{name}',
        }

    def test_winerror_retry_on_first_attempt_and_clear_progress(self):
        repo = engine_updates.FEEDS['llama-cuda'][0]
        main_zip = _zipped({'llama-server.exe': b'server-v2'})
        dep_zip = _zipped({'cudart64_12.dll': b'cudart-12.4'})
        main_asset = self._asset(repo, 'llama-b2-bin-win-cuda-12.4-x64.zip', main_zip)
        dep_asset = self._asset(repo, 'cudart-llama-bin-win-cuda-12.4-x64.zip', dep_zip)
        bodies = {
            main_asset['browser_download_url']: main_zip,
            dep_asset['browser_download_url']: dep_zip,
        }
        self.updates.state['releases']['llama-cuda'] = {
            'tag': 'b2',
            'current': '',
            'available': True,
            'asset': main_asset,
            'dependencies': [dep_asset],
        }

        calls = {'n': 0}

        def flaky_verify(*_a, **_kw):
            calls['n'] += 1
            if calls['n'] == 1:
                err = PermissionError('Access denied / AV lock')
                err.winerror = 32
                raise err
            return types.SimpleNamespace(returncode=0, stdout='version b2', stderr='')

        with patch.object(engine_updates.urllib.request, 'urlopen', lambda req, timeout=0: _Resp(bodies[req.full_url])), \
             patch.object(engine_updates.subprocess, 'run', side_effect=flaky_verify):
            self.updates.install('llama-cuda')

        self.assertEqual(calls['n'], 2)
        self.assertEqual(self.updates.progress['phase'], 'complete')
        self.assertFalse(self.updates.installing)
        self.assertNotIn('error', self.updates.state)
        self.assertEqual(engine_updates.active_installations()['llama-cuda']['tag'], 'b2')
        self.assertFalse(self.updates.state['releases']['llama-cuda']['available'])

        # Reuse cached cudart on next install and skip existing destination without crashing
        main_zip_b3 = _zipped({'llama-server.exe': b'server-v3', 'cudart64_12.dll': b'cudart-12.4'})
        main_asset_b3 = self._asset(repo, 'llama-b3-bin-win-cuda-12.4-x64.zip', main_zip_b3)
        bodies[main_asset_b3['browser_download_url']] = main_zip_b3
        self.updates.state['releases']['llama-cuda'] = {
            'tag': 'b3',
            'current': 'b2',
            'available': True,
            'asset': main_asset_b3,
            'dependencies': [dep_asset],
        }
        phases = []

        def track_verify(*_a, **_kw):
            phases.append(self.updates.progress.get('phase') if self.updates.progress else None)
            return types.SimpleNamespace(returncode=0, stdout='version b3', stderr='')

        with patch.object(engine_updates.urllib.request, 'urlopen', lambda req, timeout=0: _Resp(bodies[req.full_url])), \
             patch.object(engine_updates.subprocess, 'run', side_effect=track_verify):
            self.updates.install('llama-cuda')

        self.assertEqual(phases, ['verify'])
        self.assertEqual(self.updates.progress['phase'], 'complete')
        self.assertFalse(self.updates.installing)
        self.assertEqual(engine_updates.active_installations()['llama-cuda']['tag'], 'b3')

    def test_persistent_lock_records_error_keeps_previous_and_resets_progress(self):
        repo = engine_updates.FEEDS['llama-cuda'][0]
        body_b1 = _zipped({'llama-server.exe': b'b1'})
        a1 = self._asset(repo, 'llama-b1-bin-win-cuda-12.4-x64.zip', body_b1)
        body_b2 = _zipped({'llama-server.exe': b'b2'})
        a2 = self._asset(repo, 'llama-b2-bin-win-cuda-12.4-x64.zip', body_b2)
        bodies = {a1['browser_download_url']: body_b1, a2['browser_download_url']: body_b2}

        self.updates.state['releases']['llama-cuda'] = {'tag': 'b1', 'asset': a1, 'dependencies': []}
        ok = types.SimpleNamespace(returncode=0, stdout='ok', stderr='')
        with patch.object(urllib.request, 'urlopen', lambda req, timeout=0: _Resp(bodies[req.full_url])), \
             patch.object(subprocess, 'run', return_value=ok):
            self.updates.install('llama-cuda')

        self.updates.state['releases']['llama-cuda'] = {'tag': 'b2', 'current': 'b1', 'available': True, 'asset': a2, 'dependencies': []}
        locked = PermissionError('Sharing violation')
        locked.winerror = 32
        with patch.object(urllib.request, 'urlopen', lambda req, timeout=0: _Resp(bodies[req.full_url])), \
             patch.object(subprocess, 'run', side_effect=locked):
            self.updates.install('llama-cuda')

        self.assertEqual(self.updates.progress['phase'], 'error')
        self.assertFalse(self.updates.installing)
        self.assertIn('se conserva el motor anterior', self.updates.state.get('error', ''))
        self.assertEqual(engine_updates.active_installations()['llama-cuda']['tag'], 'b1')

    def test_uninstall_removes_llama_and_preserves_maya_checkouts(self):
        repo = engine_updates.FEEDS['llama-cpu'][0]
        body = _zipped({'llama-server.exe': b'cpu'})
        asset = self._asset(repo, 'llama-b1-bin-win-cpu-x64.zip', body)
        self.updates.state['releases']['llama-cpu'] = {'tag': 'b1', 'asset': asset, 'dependencies': []}
        ok = types.SimpleNamespace(returncode=0, stdout='ok', stderr='')
        with patch.object(urllib.request, 'urlopen', lambda req, timeout=0: _Resp(body)), \
             patch.object(subprocess, 'run', return_value=ok):
            self.updates.install('llama-cpu')

        self.assertIn('llama-cpu', engine_updates.active_installations())
        snap = self.updates.uninstall('llama-cpu')
        self.assertNotIn('llama-cpu', engine_updates.active_installations())
        self.assertFalse((self.folder / 'engine-updates' / 'llama-cpu').exists())
        self.assertEqual(snap['operation'], 'Eliminado: llama-cpu')
        with self.assertRaises(ValueError):
            self.updates.uninstall('llama-cpu')

        # Both Maya folders are unlinked and keep all user assets.
        managed = self.folder / 'engines' / 'project-maya'
        managed.mkdir(parents=True)
        (managed / 'maya.py').write_text('print("ok")', encoding='utf8')
        (managed / 'serve').mkdir()
        (managed / 'serve' / 'server.py').write_text('print("srv")', encoding='utf8')

        external = self.folder / 'user-custom-maya'
        external.mkdir(parents=True)
        (external / 'maya.py').write_text('print("ext")', encoding='utf8')
        (external / 'serve').mkdir()
        (external / 'serve' / 'server.py').write_text('print("srv")', encoding='utf8')

        with patch.object(maya_engine, 'MANAGED_ROOT', managed):
            res_managed = maya_engine.uninstall_installation(managed)
            self.assertFalse(res_managed['removed_files'])
            self.assertTrue((managed / 'maya.py').exists())
            self.assertIsNone(maya_engine.resolve_root())
            self.assertEqual(maya_engine.resolve_root(managed),managed.resolve())

            res_external = maya_engine.uninstall_installation(external)
            self.assertFalse(res_external['removed_files'])
            self.assertTrue(res_external['unlinked_external'])
            self.assertTrue(external.exists())


class MayaPrerequisitesTests(unittest.TestCase):
    def test_nvidia_cc_vs2026_cuda132_amd_pagefile_and_intel(self):
        tmp = Path(tempfile.mkdtemp(prefix='maya-pre-', dir=TMP))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'maya.py').write_text('#', encoding='utf8')
        (tmp / 'serve').mkdir()
        (tmp / 'serve' / 'server.py').write_text('#', encoding='utf8')

        base_patches = (
            patch.object(maya_engine.shutil, 'which', side_effect=lambda cmd: cmd if cmd in ('git', 'cmake', 'ninja') else None),
            patch.object(maya_engine, '_run_probe', side_effect=lambda cmd, timeout=6: (
                (0, 'git version 2.45.0', '') if 'git' in cmd[0]
                else (0, '3.11.9', '') if '--version' in cmd and not ('cmake' in ' '.join(cmd) or 'ninja' in ' '.join(cmd))
                else (0, 'cmake version 3.29.0', '') if 'cmake' in ' '.join(cmd)
                else (0, '1.12.0', '') if 'ninja' in ' '.join(cmd)
                else (1, '', '')
            )),
        )

        with base_patches[0], base_patches[1], \
             patch.object(maya_engine, '_detect_visual_studio', return_value={'installed': True, 'detail': 'VS 18 BuildTools', 'major': 18}), \
             patch.object(maya_engine, '_detect_cuda_toolkit', return_value={'installed': True, 'version': '12.8', 'tuple': (12, 8), 'path': 'nvcc.exe'}):
            pre_mismatch = maya_engine.check_prerequisites(
                profile={'gpus': [{'name': 'NVIDIA RTX 4090', 'vendor': 'NVIDIA', 'cuda_capability': 8.9}]},
                maya_root=tmp,
            )
            self.assertTrue(pre_mismatch['hardware_supported'])
            self.assertFalse(pre_mismatch['ready_to_build'])
            cuda_chk = next(c for c in pre_mismatch['checks'] if c['id'] == 'cuda')
            self.assertFalse(cuda_chk['ok'])
            self.assertIn('CUDA 13.2+', cuda_chk['detail'])

        with base_patches[0], base_patches[1], \
             patch.object(maya_engine, '_detect_visual_studio', return_value={'installed': True, 'detail': 'VS 18 BuildTools', 'major': 18}), \
             patch.object(maya_engine, '_detect_cuda_toolkit', return_value={'installed': True, 'version': '13.2', 'tuple': (13, 2), 'path': 'nvcc.exe'}):
            pre_ok = maya_engine.check_prerequisites(
                profile={'gpus': [{'name': 'NVIDIA RTX 4090', 'vendor': 'NVIDIA', 'cuda_capability': 8.9}]},
                maya_root=tmp,
            )
            self.assertTrue(pre_ok['ready_to_build'])

        with base_patches[0], base_patches[1], \
             patch.object(maya_engine, '_detect_visual_studio', return_value={'installed': True, 'detail': 'VS 2022 BuildTools', 'major': 17}), \
             patch.object(maya_engine, '_detect_cuda_toolkit', return_value={'installed': True, 'version': '12.8', 'tuple': (12, 8), 'path': 'nvcc.exe'}):
            pre_old_gpu = maya_engine.check_prerequisites(
                profile={'gpus': [{'name': 'NVIDIA GTX 1080', 'vendor': 'NVIDIA', 'cuda_capability': 6.1}]},
                maya_root=tmp,
            )
            self.assertFalse(pre_old_gpu['hardware_supported'])
            self.assertFalse(pre_old_gpu['ready_to_build'])

            pre_intel = maya_engine.check_prerequisites(
                profile={'gpus': [{'name': 'Intel Arc A770', 'vendor': 'Intel'}]},
                maya_root=tmp,
            )
            self.assertFalse(pre_intel['hardware_supported'])
            gpu_chk = next(c for c in pre_intel['checks'] if c['id'] == 'gpu')
            self.assertIn('no compatible con Maya', gpu_chk['detail'])

        with base_patches[0], base_patches[1], \
             patch.object(maya_engine, '_detect_visual_studio', return_value={'installed': True, 'detail': 'VS 2022 BuildTools', 'major': 17}), \
             patch.object(maya_engine, '_detect_rocm_hip', return_value={'installed': True, 'detail': 'rocm-sdk (7.14.1rc20260401)'}):
            pre_amd_low_pf = maya_engine.check_prerequisites(
                profile={'gpus': [{'name': 'AMD Radeon RX 7900 XTX', 'vendor': 'AMD'}]},
                maya_root=tmp,
                page_file_override=8.0,
            )
            self.assertTrue(pre_amd_low_pf['hardware_supported'])
            self.assertTrue(pre_amd_low_pf['ready_to_build'])  # page file is advisory (required=False)
            pf_chk = next(c for c in pre_amd_low_pf['checks'] if c['id'] == 'pagefile')
            self.assertFalse(pf_chk['ok'])
            self.assertFalse(pf_chk['required'])

    def test_release_check_and_fast_forward_update(self):
        rel_payload = json.dumps([{'tag_name': 'v0.9.0', 'prerelease': False, 'body': 'Changelog', 'html_url': 'https://github.com/mw00/project-maya/releases/tag/v0.9.0'}]).encode('utf8')
        with patch.object(maya_engine.urllib.request, 'urlopen', side_effect=lambda *a, **kw: _Resp(rel_payload)):
            # Not installed: available=False (never push Maya if not installed)
            uninstalled = maya_engine.check_latest_release('')
            self.assertTrue(uninstalled['source_only'])
            self.assertIsNone(uninstalled['asset'])
            self.assertFalse(uninstalled['available'])

            outdated = maya_engine.check_latest_release('0.8.0')
            self.assertTrue(outdated['available'])
            self.assertEqual(outdated['tag'], 'v0.9.0')

        tmp = Path(tempfile.mkdtemp(prefix='maya-git-', dir=TMP))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / '.git').mkdir()
        (tmp / 'maya.py').write_text('#', encoding='utf8')
        (tmp / 'serve').mkdir()
        (tmp / 'serve' / 'server.py').write_text('#', encoding='utf8')

        seen_cmds = []

        def fake_git(cmd, **_kw):
            seen_cmds.append(cmd)
            if 'get-url' in cmd:
                return types.SimpleNamespace(returncode=0, stdout=maya_engine.MAYA_GIT_URL, stderr='')
            if 'rev-parse' in cmd:
                return types.SimpleNamespace(returncode=0, stdout='true' if '--is-shallow-repository' in cmd else 'same-sha', stderr='')
            return types.SimpleNamespace(returncode=0, stdout='', stderr='')

        with patch.object(maya_engine.shutil, 'which', return_value='git'), \
             patch.object(maya_engine.subprocess, 'run', side_effect=fake_git):
            out = maya_engine.clone_or_update_repo(tmp, tag='v0.9.0')
        self.assertEqual(out['action'], 'updated')
        self.assertEqual(out['tag'], 'v0.9.0')
        self.assertTrue(any('merge' in c and '--ff-only' in c for c in seen_cmds))
        self.assertTrue(any('--unshallow' in c and maya_engine.MAYA_GIT_URL in c for c in seen_cmds))


class MayaFamilyConfigsTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='maya-cfg-', dir=TMP))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _write_cfg(self, name: str, data: dict) -> Path:
        p = self.dir / name
        p.write_text(json.dumps(data, indent=2), encoding='utf8')
        return p

    def test_glm_and_glm_dsa_locked_streaming_and_text_only(self):
        p_flash = self._write_cfg('maya-glm-5.3-flash.json', {
            'model_name': 'GLM-5.3-Flash',
            'exe': 'build/maya.exe',
            'args': ['--max-context', '32768', '--parallel', '1', '--dflash', 'drafter.gguf'],
            'vision': {'mmproj': 'v.gguf', 'resident': False},
        })
        updated = maya_engine.apply_family_settings(p_flash, {
            'context': 65536,
            'gpus': '0,1',
            'parallel': 4,
            'reserve_mib': '2048',
            'draft': 'dflash2',
            'expert_cache': '12',
            'prefill': '512',
            'kv_streaming': True,
            'kv_resident': 32768,
            'vision_resident': True,
            'turbo': True,
            'ablate': True,
        })
        self.assertEqual(updated['family'], 'glm')
        self.assertEqual(updated['gpus'], '0,1')
        self.assertNotIn('turbo',updated['schema']['fields'])
        self.assertTrue(updated['kv_streaming'])
        self.assertTrue(updated['vision_resident'])
        raw = json.loads(p_flash.read_text(encoding='utf8'))
        self.assertEqual(raw['gpu'], [0, 1])
        self.assertNotIn('--turbo', raw['args'])
        self.assertIn('--dflash drafter.gguf', ' '.join(raw['args']))
        self.assertNotIn('--draft', raw['args'])
        self.assertIn('--kv-resident 32768', ' '.join(raw['args']))
        self.assertFalse(maya_engine.apply_family_settings(p_flash, {'images': False})['images'])
        self.assertTrue(maya_engine.apply_family_settings(p_flash, {'images': True})['images'])

        p_dsa = self._write_cfg('maya-glm-5.3-744b.json', {
            'model_name': 'GLM-5.3-744B-DSA',
            'exe': 'build/maya.exe',
            'args': ['--glm-pack', 'dsa'],
        })
        dsa = maya_engine.apply_family_settings(p_dsa, {'kv_streaming': True, 'images': True, 'draft': 'mtp'})
        self.assertEqual(dsa['family'], 'glm_dsa')
        self.assertTrue(dsa['schema']['kv_streaming_locked'])
        self.assertFalse(dsa['kv_streaming'])
        self.assertFalse(dsa['images'])

    def test_deepseek_minimax_and_qwen_configs_and_discovery(self):
        sub = self.dir / 'configs'
        sub.mkdir()
        p_ds = self._write_cfg('configs/maya-deepseek-v4.1-flash.json', {
            'model_name': 'DeepSeek-V4.1-Flash-1017',
            'exe': 'build/maya-ds4.exe',
            'args': [],
        })
        ds = maya_engine.apply_family_settings(p_ds, {
            'fast_prefill': True,
            'draft': 'on',
            'dspark_conf': '0.85',
            'tp': '2',
            'mmap': 'off',
            'prefill_chunk': '1024',
            'cpu_threads': '8',
            'prompt_lookup': '4',
            'images': True,
        })
        self.assertEqual(ds['family'], 'deepseek')
        self.assertTrue(ds['fast_prefill'])
        self.assertEqual(ds['dspark_conf'], '0.85')
        self.assertEqual(ds['mmap'], 'off')
        self.assertTrue(ds['images'])

        p_mm = self._write_cfg('maya-minimax-m3.1-flash.json', {
            'model_name': 'MiniMax-M3.1-Flash',
            'exe': 'build/maya-mm3.exe',
            'args': [],
        })
        mm = maya_engine.apply_family_settings(p_mm, {
            'kv_cache': 'int8',
            'reserve_gb': '4',
            'cache_gb': '16',
            'prefill_chunk': '512',
            'kv_streaming': True,
            'kv_resident': '',
        })
        self.assertEqual(mm['family'], 'minimax')
        self.assertEqual(mm['kv_cache'], 'int8')
        self.assertEqual(mm['reserve_gb'], '4')
        self.assertEqual(mm['cache_gb'], '16')

        p_qw = self._write_cfg('maya-qwen-3.8-flash-next.json', {
            'model_name': 'Qwen-3.8-Flash-Next',
            'exe': 'build/maya.exe',
            'args': ['--mtp','mtp.gguf'],
        })
        qw = maya_engine.apply_family_settings(p_qw, {
            'ram_gb': '64',
            'kv': 'int8',
            'draft': 'none',
        })
        self.assertEqual(qw['family'], 'qwen')
        self.assertEqual(qw['ram_gb'], '64')
        self.assertEqual(qw['env'].get('MAYA_EXPERT_RAM_GB'), '64')
        self.assertEqual(qw['kv'], 'int8')
        self.assertEqual(qw['draft'], 'none')
        qw_args=json.loads(p_qw.read_text(encoding='utf8'))['args']
        self.assertIn('--mtp mtp.gguf', ' '.join(qw_args))
        self.assertIn('--mtp-max-t 1', ' '.join(qw_args))
        self.assertEqual(maya_engine.apply_family_settings(p_qw, {'draft':'mtp'})['draft'], 'mtp')

        with self.assertRaises(ValueError):
            maya_engine.apply_family_settings(p_qw, {'env': {'BAD KEY': '1'}})

        found = maya_engine.list_configs(self.dir)
        self.assertEqual(len(found), 3)


class NonForcedAndTranslationsTests(unittest.TestCase):
    def test_onboarding_and_recommendations_never_force_maya(self):
        rec = engine_recommendations.recommend(
            {'gpus': [{'name': 'NVIDIA RTX 4090', 'vendor': 'NVIDIA', 'cuda_capability': 8.9, 'vram_mib': 24576, 'driver': '570.0'}]},
            {'maya': {'tag': 'v0.9.0', 'current': '', 'source_only': True, 'repository': 'mw00/project-maya'}},
        )
        maya_row = next(r for r in rec['engines'] if r['key'] == 'maya')
        self.assertFalse(maya_row['recommended'])
        self.assertEqual(maya_row['status'], 'optional')
        self.assertEqual(maya_row['asset'], '')

        tour_js = (ROOT / 'agent' / 'ui' / 'app' / 'tour.js').read_text(encoding='utf8')
        self.assertIn("if(chosenKey==='maya')", tour_js)
        self.assertNotIn("recommendedKey='maya'", tour_js)
        self.assertIn("'/api/harness/maya/status'", tour_js)

    def test_locales_and_dynamic_i18n_cover_all_five_languages(self):
        locales = json.loads((ROOT / 'agent' / 'ui' / 'locales.json').read_text(encoding='utf8'))
        for key, langs in locales.items():
            for code in ('en', 'pt', 'fr', 'de'):
                self.assertTrue(isinstance(langs.get(code), str) and langs[code].strip(), f'Missing {code} for {key!r}')

        node = ROOT / 'runtime' / 'node.exe'
        if not node.is_file():
            node = Path(shutil.which('node') or 'node')
        probe = """
        const fs = require('fs');
        const vm = require('vm');
        const locales = JSON.parse(fs.readFileSync('agent/ui/locales.json', 'utf8'));
        const context = {
          window: {},
          document: { documentElement: {} },
          localStorage: { setItem(){} },
          fetch: async () => ({ ok: true, json: async () => locales }),
        };
        vm.runInNewContext(fs.readFileSync('agent/ui/standalone/i18n.js', 'utf8'), context);
        const samples = [
          'Instalado: v1.0',
          'Oficial: v1.2',
          'Nueva versión disponible: v1.3',
          'CUDA 12.8 con VS 2026: necesita CUDA 13.2+',
          '8.0 GB asignados',
          '8.0 GB: amplía el archivo de paginación en Windows para GPUs AMD',
          'Instala rocm[libraries,devel]==7.14.1rc20260401 o HIP_PATH',
          'Project Maya necesita GPU NVIDIA (CC 7.0 o superior) o AMD Radeon compatible',
          'Faltan requisitos para compilar Project Maya: Git, CMake 3.24+.',
          'No se pudo clonar Project Maya: error de red',
          'No se pudo actualizar la copia de Project Maya: conflicto',
          'La compilación de Project Maya falló: exit 1',
          'Compilando Project Maya (CUDA)…',
          'Variable de entorno no válida: BAD KEY',
          'Instalar elegido · Project Maya (Compilación local opcional)',
        ];
        (async () => {
          const ui = context.window.VALI18n;
          const ptCognates = new Set([
            'Instalado: v1.0',
            'Oficial: v1.2',
            'Compilando Project Maya (CUDA)…',
          ]);
          await ui.init('en');
          for (const lang of ['en', 'pt', 'fr', 'de']) {
            ui.setLanguage(lang);
            for (const s of samples) {
              const out = ui.t(s);
              if (!out || (out === s && !(lang === 'pt' && ptCognates.has(s)))) {
                throw new Error(`Untranslated for ${lang}: ${s} -> ${out}`);
              }
            }
          }
          console.log('DYNAMIC_I18N_OK');
        })().catch(e => { console.error(e); process.exitCode = 1; });
        """
        proc = subprocess.run(
            [str(node), '-e', probe],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding='utf8',
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn('DYNAMIC_I18N_OK', proc.stdout)


class EngineManagerMayaTests(unittest.TestCase):
    def test_maya_load_uses_selected_binary_without_editing_source_config(self):
        import engine_manager
        import threading

        with tempfile.TemporaryDirectory(dir=TMP) as folder:
            root = Path(folder)
            (root / 'maya.py').touch()
            (root / 'serve').mkdir()
            (root / 'serve' / 'server.py').touch()
            (root / 'tokenizer').mkdir()
            (root / 'tokenizer' / 'vocab.json').touch()
            custom = root / 'custom' / 'maya-ds4.exe'
            custom.parent.mkdir()
            custom.touch()
            original = {'model_name':'Test','installer':{'family':'deepseek'},'tokenizer':'tokenizer',
                        'args':['--max-context','32768'],'exe':'build/maya-ds4.exe'}
            path = root / 'maya-test.json'
            path.write_text(json.dumps(original),encoding='utf8')
            manager = engine_manager.EngineManager.__new__(engine_manager.EngineManager)
            manager.settings = {'active':'maya','maya':{'root':str(root),'executable':str(custom)}}
            manager.kind = 'maya'
            manager.loaded = manager.process = None
            manager.llama_key = 'test'
            prep = types.SimpleNamespace(begin=lambda *a:None, update=lambda **kw:None,
                                         check_cancelled=lambda:None, finish=lambda:None,
                                         cancelled=threading.Event())
            process = types.SimpleNamespace(poll=lambda:0)
            with patch.object(engine_manager,'DATA_ROOT',root), patch.object(engine_manager,'LOG_ROOT',root), \
                 patch('socket.socket') as socket_factory, patch.object(manager,'maya_health',return_value={
                     'status':'ok','model':'Test','max_context':8192}), \
                 patch.object(engine_manager.subprocess,'Popen',return_value=types.SimpleNamespace(poll=lambda:None)) as spawn:
                socket_factory.return_value.__enter__.return_value.connect_ex.return_value=1
                manager.load({'id':'maya--test','config':str(path)},16384,prep)
                argv=spawn.call_args.args[0]
                self.assertIn('--parent-pipe',argv)
                runtime_config=manager._maya_run_config
                launch=json.loads(runtime_config.read_text(encoding='utf8'))
                self.assertEqual(Path(launch['exe']).resolve(),custom.resolve())
                self.assertEqual(launch['args'],['--max-context','16384'])
                self.assertEqual(json.loads(path.read_text(encoding='utf8')),original)
                self.assertEqual(manager.loaded_context,8192)
                manager.process=process
                manager.stop()
                self.assertFalse(runtime_config.exists())

    def test_configure_maya_and_thinking_policy(self):
        import engine_manager
        import thinking_policy

        cap = thinking_policy.capability({'id': 'maya-glm'}, kind='maya')
        self.assertIn('max', cap['choices'])
        payload={}
        thinking_policy.apply(payload,'max',cap)
        self.assertEqual(payload['reasoning_effort'],'max')

        folder = Path(tempfile.mkdtemp(prefix='em-maya-', dir=TMP))
        self.addCleanup(shutil.rmtree, folder, True)
        valid_root = folder / 'project-maya'
        valid_root.mkdir()
        (valid_root / 'maya.py').write_text('#', encoding='utf8')
        (valid_root / 'serve').mkdir()
        (valid_root / 'serve' / 'server.py').write_text('#', encoding='utf8')

        mgr = engine_manager.EngineManager.__new__(engine_manager.EngineManager)
        mgr.file = folder / 'engines.json'
        mgr.settings = {'active': 'strata', 'llama': {}, 'maya': {}}
        mgr.kind = 'strata'
        mgr.loaded = None
        mgr.snapshot = lambda: dict(mgr.settings)

        with self.assertRaises(ValueError):
            mgr.configure({'engine': 'maya', 'maya_root': str(folder / 'missing')})

        bad_root = folder / 'not-maya'
        bad_root.mkdir()
        with self.assertRaises(ValueError):
            mgr.configure({'engine': 'maya', 'maya_root': str(bad_root)})

        mgr.configure({'engine': 'maya', 'maya_root': str(valid_root), 'maya_backend': 'cuda'})
        self.assertEqual(mgr.kind, 'maya')
        self.assertEqual(Path(mgr.settings['maya']['root']).resolve(), valid_root.resolve())
        self.assertEqual(mgr.settings['maya']['backend'], 'cuda')

    def test_ui_exposes_intermediate_update_overlay_and_four_engine_custom_pickers(self):
        tour_js = (ROOT / 'agent' / 'ui' / 'app' / 'tour.js').read_text(encoding='utf8')
        self.assertIn('appUpdateOverlay', tour_js)
        self.assertIn('Instalando nueva actualización de V-Agent…', tour_js)
        ec_js = (ROOT / 'agent' / 'ui' / 'app' / 'engine-controls.js').read_text(encoding='utf8')
        for elem_id in (
            'strataVariant', 'strataCustom', 'strataExecutable', 'browseStrata',
            'rustVariant', 'rustCustom', 'rustExecutable', 'browseRust',
            'llamaVariant', 'llamaCustom', 'llamaExecutable', 'browseLlama',
            'mayaRoot', 'mayaExecutable', 'browseMayaExe', 'addCustomEngine',
        ):
            self.assertIn(elem_id, ec_js, f'Missing {elem_id} in engine-controls.js')


if __name__ == '__main__':
    unittest.main()


class MayaAgentIntegrationTests(unittest.TestCase):
    def test_max_reasoning_level_is_kept(self):
        # GLM and DeepSeek builds of Maya top out at "max"; V-Agent rejected it and reset it on start.
        from model_preferences import ModelPreferences
        with tempfile.TemporaryDirectory() as folder:
            store = ModelPreferences(Path(folder) / 'prefs.json')
            store.save('maya--abc', {'effort': 'max'})
            self.assertEqual(store.records['maya--abc']['effort'], 'max')
        startup = (ROOT / 'agent' / 'ui' / 'app' / 'startup.js').read_text(encoding='utf-8')
        self.assertIn('"xhigh","max"].includes(S.effort)', startup)
        self.assertIn("max:'Máximo'", (ROOT / 'agent' / 'ui' / 'app' / 'shell.js').read_text(encoding='utf-8'))

    def test_tool_budget_finds_a_tokenizer_relative_to_the_maya_checkout(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import agent
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tokenizer').mkdir()
            (root / 'tokenizer' / 'vocab.json').write_text('{}', encoding='utf-8')
            (root / 'configs').mkdir()
            for config in (root / 'maya-a.json', root / 'configs' / 'maya-b.json'):
                config.write_text(json.dumps({'tokenizer': 'tokenizer'}), encoding='utf-8')
                agent._TOKENIZADORES_MEDIDOS.clear()
                with patch.object(agent, 'selected_model', return_value={'config': str(config)}):
                    self.assertEqual(Path(agent.tokenizer_del_modelo('maya--x')).resolve(), (root / 'tokenizer').resolve())
            (root / 'maya-c.json').write_text(json.dumps({}), encoding='utf-8')
            agent._TOKENIZADORES_MEDIDOS.clear()
            with patch.object(agent, 'selected_model', return_value={'config': str(root / 'maya-c.json')}):
                self.assertIsNone(agent.tokenizer_del_modelo('maya--y'))
