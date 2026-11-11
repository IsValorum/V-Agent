import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import hardware_stats as h

class HardwareTests(unittest.TestCase):
    def test_partial_values_and_multiple_devices(self):
        out=h.parse_nvidia('"GPU, secondary", N/A, 12, 6000, N/A, [Not Supported]\nMain GPU, 7, 1000, 8000, 42, 15.5\n')
        self.assertEqual(out['name'],'Main GPU');self.assertEqual(out['vram_mib'],1000);self.assertEqual(out['power'],15.5)
        partial=h.parse_nvidia('Some GPU, N/A, 12, 6000, N/A, N/A')
        self.assertEqual(partial['vram_mib'],12);self.assertIsNone(partial['power'])
        self.assertEqual(h.parse_nvidia('invalid'),{})
    def test_host_sample_returns_memory_and_disk_without_gpu(self):
        h.snapshot();result=h.snapshot()
        self.assertGreater(result['ram']['total_gib'],0)
        self.assertIn('gpu',result)
        self.assertIn('read_mbs',result['disk'])

if __name__=='__main__':unittest.main()
