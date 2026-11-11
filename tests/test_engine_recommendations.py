import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
from engine_recommendations import recommend


def release(tag, asset):
    return {'tag': tag, 'available': True, 'current': 'old', 'asset': {'name': asset, 'size': 10}, 'dependencies': []}


class RecommendationTests(unittest.TestCase):
    def test_nvidia_cuda_and_strata_are_recommended(self):
        profile = {'gpus': [{'name': 'RTX 4050', 'vendor': 'NVIDIA', 'driver': '621.01', 'vram_mib': 6141, 'cuda_capability': 8.9}]}
        rows = recommend(profile, {'llama-cuda': release('b12242', 'cuda.zip'), 'llama-cpu': release('b12242', 'cpu.zip'), 'strata': release('v0.1.45', 'strata.zip'), 'rust': release('v1.2.1', 'strata.exe')})['engines']
        by_key = {row['key']: row for row in rows}
        self.assertTrue(by_key['llama-cuda']['recommended'])
        self.assertTrue(by_key['strata']['recommended'])
        self.assertTrue(by_key['rust']['recommended'])
        self.assertFalse(by_key['llama-cpu']['recommended'])
        self.assertEqual(by_key['llama-cuda']['asset'], 'cuda.zip')

    def test_cpu_without_dedicated_gpu(self):
        for profile in ({'gpus': []}, {'gpus': [{'name': 'Intel(R) Arc(TM) Graphics', 'vendor': 'Intel'}]}):
            by_key = {row['key']: row for row in recommend(profile, {})['engines']}
            self.assertTrue(by_key['llama-cpu']['recommended'])
            self.assertFalse(by_key['llama-cuda']['recommended'])
            self.assertFalse(by_key['strata']['recommended'])

    def test_vulkan_for_amd_intel_arc_or_old_nvidia_driver(self):
        for gpu in ({'name': 'AMD Radeon RX 7600', 'vendor': 'AMD'}, {'name': 'Intel(R) Arc(TM) A770 Graphics', 'vendor': 'Intel'},
                    {'name': 'RTX 3050', 'vendor': 'NVIDIA', 'driver': '500.1', 'vram_mib': 4096, 'cuda_capability': 8.6}):
            result = recommend({'gpus': [gpu]}, {})
            by_key = {row['key']: row for row in result['engines']}
            self.assertTrue(by_key['llama-vulkan']['recommended'], gpu['name'])
            self.assertEqual(result['variant'], 'vulkan')

if __name__ == '__main__':
    unittest.main()
