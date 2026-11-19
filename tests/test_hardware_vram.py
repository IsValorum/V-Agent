"""Issue #1: Win32_VideoController.AdapterRAM is a uint32, so every GPU with 4 GB or more read 4095 MiB."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

import hardware_stats  # noqa: E402

WMI = [{'Name': 'GameViewer Virtual Display Adapter', 'DriverVersion': '1.0', 'AdapterRAM': None},
       {'Name': 'AMD Radeon RX 6700 XT', 'DriverVersion': '32.0.21045.26001', 'AdapterRAM': 4294967295},
       {'Name': 'Intel(R) UHD Graphics', 'DriverVersion': '31.0', 'AdapterRAM': 2147479552}]


def wmi(*_args, **_kwargs):
    return subprocess.CompletedProcess([], 0, json.dumps(WMI), '')


class WideVram(unittest.TestCase):
    def gpus(self, registry, dxgi):
        with patch.object(hardware_stats.os, 'name', 'nt'), patch.object(hardware_stats.subprocess, 'run', wmi), \
                patch.object(hardware_stats, '_registry_adapters', return_value=registry), \
                patch.object(hardware_stats, '_dxgi_adapters', return_value=dxgi):
            return {g['name']: (g['vram_mib'], g['source']) for g in hardware_stats._wmi_gpus()}

    def test_the_registry_size_replaces_the_capped_wmi_value(self):
        found = self.gpus([('AMD Radeon RX 6700 XT', 12288)], [('AMD Radeon RX 6700 XT', 12272)])
        self.assertEqual(found['AMD Radeon RX 6700 XT'], (12288, 'registry'))
        self.assertEqual(found['GameViewer Virtual Display Adapter'], (None, 'wmi'))

    def test_dxgi_when_the_driver_writes_no_registry_size(self):
        self.assertEqual(self.gpus([], [('AMD Radeon RX 6700 XT', 12272)])['AMD Radeon RX 6700 XT'], (12272, 'dxgi'))

    def test_an_integrated_gpu_keeps_its_shared_memory(self):
        # DXGI reports only the iGPU's small dedicated carve-out: it must not shrink what WMI reports.
        self.assertEqual(self.gpus([], [('Intel(R) UHD Graphics', 128)])['Intel(R) UHD Graphics'], (2048, 'wmi'))

    def test_without_any_64_bit_source_wmi_is_kept(self):
        self.assertEqual(self.gpus([], [])['AMD Radeon RX 6700 XT'], (4096, 'wmi'))


if __name__ == '__main__':
    unittest.main()
