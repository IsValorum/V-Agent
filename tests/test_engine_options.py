"""Engine options (Advanced → Engine options): catalog, validation, arguments, translations."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

if 'STRATA_AGENT_DATA' not in os.environ:
    os.environ['STRATA_AGENT_DATA'] = tempfile.mkdtemp(prefix='va-test-')
sys.path[:0] = ['agent', '.']
import engine_options as E  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LLAMA_HELP = """
-t,    --threads N                      number of CPU threads
-fa,   --flash-attn [on|off|auto]       set Flash Attention use
-kvo,  --kv-offload, -nkvo, --no-kv-offload
-ctv,  --cache-type-v TYPE              KV cache data type for V
-lm,   --load-mode MODE                 model loading mode
                                        - mlock: force system to keep model in RAM
--rope-freq-scale N                     RoPE frequency scaling factor
"""


class CatalogTests(unittest.TestCase):
    def test_only_flags_the_executable_lists_are_offered(self):
        keys = {o['key'] for o in E.catalog('llama', LLAMA_HELP)['options']}
        self.assertTrue({'threads', 'flash_attn', 'kv_offload', 'load_mode', 'rope_freq_scale'} <= keys)
        self.assertNotIn('cache_type_v', keys)  # llama.cpp refuses K and V caches of different formats
        # "mlock" only appears inside --load-mode's description: not an option of this build.
        self.assertNotIn('mlock', keys)
        self.assertNotIn('tensor_split', keys)
        self.assertEqual(E.catalog('maya', LLAMA_HELP)['options'], [])

    def test_keys_are_unique_per_engine_and_none_duplicates_a_flag_v_agent_sets(self):
        # What V-Agent's own controls already pass to each engine.
        managed = {'llama': {'--ctx-size', '--parallel', '--n-gpu-layers', '--cache-type-k', '--batch-size', '--ubatch-size', '--fit',
                             '--n-cpu-moe', '--ctx-checkpoints', '--mmproj', '--chat-template-file', '--model', '--api-key',
                             '--host', '--port', '--jinja', '--alias', '--fit-target', '--cache-type-v'},
                   'strata': {'--max-context', '--kv', '--prompt-cache', '--vram-reserve-mib', '--expert-profile', '--model',
                              '--no-draft', '--draft-model'},
                   'rust': {'--model', '--addr', '--gpu', '--ctx', '--kv', '--api-key'}}
        for kind, options in E.CATALOG.items():
            keys = [o['key'] for o in options]
            self.assertEqual(len(keys), len(set(keys)), kind)
            self.assertFalse({o['flag'] for o in options} & managed[kind], kind)
            for option in options:
                self.assertIn(option['group'], dict(E.GROUPS), option['key'])

    def test_every_text_has_its_five_translations(self):
        locales = json.loads((ROOT / 'agent' / 'ui' / 'locales.json').read_text(encoding='utf-8'))
        phrases = {label for _, label in E.GROUPS}
        for options in E.CATALOG.values():
            for option in options:
                phrases |= {option['label'], option['help'], *(option.get('labels') or {}).values()}
        missing = sorted(p for p in phrases if any(not (locales.get(p) or {}).get(code) for code in ('en', 'pt', 'fr', 'de')))
        self.assertEqual(missing, [])


class ValidationTests(unittest.TestCase):
    def test_values_are_checked_and_empty_means_engine_default(self):
        saved = E.validate({'flash_attn': 'off', 'threads': 8, 'kv_offload': False, 'rope_freq_scale': 0.25, 'lora': 'C:/a.gguf'})
        self.assertEqual(saved, {'flash_attn': 'off', 'threads': 8, 'kv_offload': False, 'rope_freq_scale': 0.25, 'lora': 'C:/a.gguf'})
        self.assertEqual(E.validate({'threads': None, 'lora': ''}, saved), {'flash_attn': 'off', 'kv_offload': False, 'rope_freq_scale': 0.25})
        for bad in ({'threads': 0}, {'threads': 2.5}, {'threads': True}, {'flash_attn': 'maybe'}, {'kv_offload': 'yes'},
                    {'tensor_split': '3;1'}, {'nonsense': 1}, {'mtp': 99}):
            with self.assertRaises(ValueError, msg=bad):
                E.validate(bad)

    def test_model_preferences_keep_engine_options(self):
        from model_preferences import ModelPreferences
        with tempfile.TemporaryDirectory() as folder:
            store = ModelPreferences(Path(folder) / 'prefs.json')
            store.save('llama--x', {'engine': {'flash_attn': 'on', 'threads': 6}})
            store.save('llama--x', {'engine': {'threads': None}})
            self.assertEqual(store.records['llama--x']['engine'], {'flash_attn': 'on'})
            with self.assertRaises(ValueError):
                store.save('llama--x', {'engine': {'threads': -3}})


class ConflictTests(unittest.TestCase):
    def test_quantized_kv_cache_needs_flash_attention(self):
        self.assertIsNotNone(E.conflicts('llama', {'flash_attn': 'off'}, 'q8_0'))
        self.assertIsNone(E.conflicts('llama', {'flash_attn': 'auto'}, 'q8_0'))
        self.assertIsNone(E.conflicts('llama', {'flash_attn': 'off'}, 'fp16'))
        self.assertIsNone(E.conflicts('rust', {'flash_attn': 'off'}, 'q8_0'))


class ArgumentTests(unittest.TestCase):
    def test_arguments_per_kind_and_unsupported_skipped(self):
        args = E.arguments('llama', {'flash_attn': 'on', 'threads': 6, 'kv_offload': False, 'tensor_split': '3,1'}, LLAMA_HELP)
        self.assertEqual(args, ['--flash-attn', 'on', '--threads', '6', '--no-kv-offload'])
        rust_help = '--mtp [<N>]\n--backend <BACKEND>\n--threads <THREADS>\n--llama-numerics\n'
        self.assertEqual(E.arguments('rust', {'mtp': 3, 'backend': 'vulkan', 'llama_numerics': True, 'fixed_experts': True}, rust_help),
                         ['--mtp', '3', '--backend', 'vulkan', '--llama-numerics'])

    def test_strata_config_keeps_its_own_flags_and_forgets_cleared_ones(self):
        strata_help = '  --threads N   x\n  --kv-whole   x\n  --lookup N   x\n'
        config = ['--model', 'm.gguf', '--max-context', '8192', '--lookup', '4']
        args, applied = E.apply('strata', config, {'threads': 12, 'kv_whole': True}, strata_help)
        self.assertEqual(args, ['--model', 'm.gguf', '--max-context', '8192', '--lookup', '4', '--threads', '12', '--kv-whole'])
        # Back to the engine default: only what V-Agent applied before is removed; --lookup (the config's own) stays.
        args, applied = E.apply('strata', args, {}, strata_help, applied)
        self.assertEqual(args, ['--model', 'm.gguf', '--max-context', '8192', '--lookup', '4'])
        self.assertEqual(applied, [])


if __name__ == '__main__':
    unittest.main()
