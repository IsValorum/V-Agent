"""Exercise the Windows update handoff with disposable executables, never a real install."""
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, 'agent')
import app_updates

CSC = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'


@unittest.skipUnless(sys.platform == 'win32' and CSC.is_file(), 'Windows .NET compiler required')
class UpdateHelperWindowsTests(unittest.TestCase):
    def test_waits_for_shutdown_installs_silently_and_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'fake.cs'
            source.write_text('using System;using System.IO;using System.Reflection;'
                '[assembly:AssemblyVersion("9.0.0.0")][assembly:AssemblyInformationalVersion("9.0.0")]'
                'class P{static int Main(string[] a){File.WriteAllText(Environment.GetEnvironmentVariable('
                'a.Length>0?"TEST_INSTALL":"TEST_START"),String.Join(" ",a));return 0;}}')
            for name in ('setup.exe', 'V-Agent.exe'):
                subprocess.run([str(CSC), '/nologo', '/target:exe', '/out:' + str(root / name), str(source)],
                               check=True, capture_output=True)
            sleepers = [subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(2)'],
                                         creationflags=subprocess.CREATE_NO_WINDOW) for _ in range(2)]
            env = os.environ.copy()
            env.update(V_AGENT_UPDATE_DESKTOP_PID=str(sleepers[0].pid), V_AGENT_UPDATE_CORE_PID=str(sleepers[1].pid),
                       V_AGENT_UPDATE_INSTALLER=str(root / 'setup.exe'),
                       V_AGENT_UPDATE_SHA256=hashlib.sha256((root / 'setup.exe').read_bytes()).hexdigest(),
                       V_AGENT_UPDATE_EXE=str(root / 'V-Agent.exe'), V_AGENT_UPDATE_VERSION='9.0.0',
                       V_AGENT_UPDATE_LOG=str(root / 'update.log'), TEST_INSTALL=str(root / 'installed'),
                       TEST_START=str(root / 'started'))
            # A failed test must not display a modal dialog on the developer's desktop.
            script = app_updates.UPDATE_HELPER.replace(
                "try { Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show($message, 'V-Agent', 'OK', 'Error') | Out-Null } catch {}", '')
            encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
            helper = subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                      env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertFalse((root / 'installed').exists())
            helper.wait(timeout=25)
            for process in sleepers:
                process.wait(timeout=5)
            for _ in range(50):
                if (root / 'started').exists():
                    break
                time.sleep(.1)
            log = (root / 'update.log').read_text() if (root / 'update.log').exists() else 'No update log.'
            self.assertTrue((root / 'installed').exists(), log)
            self.assertEqual((root / 'installed').read_text(), '/S /UPDATE')
            self.assertTrue((root / 'started').exists(), log)
