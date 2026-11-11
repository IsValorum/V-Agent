import sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from local_console import Console

class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.console=Console()
    def tearDown(self):
        self.console.close();self.tmp.cleanup()
    def wait(self,predicate,timeout=25):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=self.console.snapshot()
            if predicate(state):return state
            time.sleep(0.05)
        self.fail('Console state did not settle: '+repr(self.console.snapshot()))
    def run_command(self,command,shell='powershell'):
        self.console.start(command,shell,self.tmp.name)
        return self.wait(lambda state:not state['running'])
    def test_powershell_output_utf8_and_exit_code(self):
        final=self.run_command("Write-Output 'hola, ñandú'")
        self.assertIn('hola, ñandú',final['run_text'])
        self.assertEqual(final['exit_code'],0)
        self.assertIn('PS ',final['text'])
    def test_session_persists_between_commands(self):
        self.run_command("Write-Output 'primera'")
        final=self.run_command("Write-Output 'segunda'")
        self.assertIn('segunda',final['run_text'])
        self.assertNotIn('primera',final['run_text'])
        self.assertIn('segunda',final['text'])
    def test_native_exit_code_is_reported(self):
        final=self.run_command('cmd /c exit 7')
        self.assertEqual(final['exit_code'],7)
    def test_cmd_output_and_cwd(self):
        final=self.run_command('echo raiz','cmd')
        self.assertIn('raiz',final['run_text'].lower())
        final=self.run_command('cd','cmd')
        self.assertIn(str(self.tmp.name).lower(),final['run_text'].lower())
        self.assertEqual(final['exit_code'],0)
    def test_rejects_second_command(self):
        self.console.start('Start-Sleep -Seconds 20','powershell',self.tmp.name)
        with self.assertRaises(ValueError):self.console.start("Write-Output 'second'",'powershell',self.tmp.name)
        self.console.stop()
        state=self.wait(lambda item:not item['running'],10)
        self.assertFalse(state['running'])
        final=self.run_command("Write-Output 'después de detener'")
        self.assertIn('después de detener',final['run_text'])
    def test_clear_requires_finished_command(self):
        self.run_command("Write-Output 'lista'")
        state=self.console.clear()
        self.assertEqual(state['text'],'')
        self.assertEqual(state['run_text'],'')
        self.assertIsNone(state['id'])
        self.console.start('Start-Sleep -Seconds 20','powershell',self.tmp.name)
        with self.assertRaises(ValueError):self.console.clear()
        self.console.stop()
    def test_invalid_requests(self):
        for command,shell in [('', 'powershell'),('x','bash'),('x'*16001,'powershell'),(None,'powershell')]:
            with self.assertRaises(ValueError):self.console.start(command,shell,self.tmp.name)

if __name__=='__main__':unittest.main()
