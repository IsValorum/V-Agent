import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=['agent','.']
import sandbox_exec
import pc_mcp
from access_policy import AccessPolicy
from tool_approvals import needs_approval


class IsolatedCommandTests(unittest.TestCase):
    def test_unavailable_never_launches_host_command(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sandbox_exec,'status',return_value={'available':False,'reason':'test'}),patch.object(sandbox_exec,'_launch',side_effect=AssertionError('must not execute')):
            with self.assertRaisesRegex(RuntimeError,'not run'):
                pc_mcp.call('shell_run',{'command':'echo should-not-run'},policy=AccessPolicy(Path(folder)))

    def test_missing_command_explains_what_is_available(self):
        hint=sandbox_exec._hint(1,'"ls" no se reconoce como un comando interno o externo')
        self.assertIn('fs_list',hint);self.assertIn('Full PC access',hint)
        self.assertEqual(sandbox_exec._hint(1,'Traceback: ZeroDivisionError'),'')

    @unittest.skipUnless(os.name=='nt' and sandbox_exec._BINARY.is_file(),'Windows MXC runtime required')
    def test_isolated_python_runs_without_host_access(self):
        if not sandbox_exec.status()['available']:self.skipTest('MXC unavailable')
        if 'python' not in sandbox_exec.runtimes():self.skipTest('No installed Python found')
        with tempfile.TemporaryDirectory(prefix='val-isolation-py-') as folder:
            Path(folder,'calc.py').write_text('import math\nprint(math.factorial(20))\n',encoding='utf8')
            result=pc_mcp.call('shell_run',{'command':'python calc.py'},policy=AccessPolicy(Path(folder)))
            self.assertIn('2432902008176640000',result)

    def test_light_profile_always_approves_commands(self):
        for mode in ('ask','auto','run'):
            self.assertTrue(needs_approval(mode,'pc__shell_run',{'command':'echo test'},'light'))

    @unittest.skipUnless(os.name=='nt' and sandbox_exec._BINARY.is_file(),'Windows MXC runtime required')
    def test_real_isolation_blocks_outside_read_and_write(self):
        capability=sandbox_exec.status()
        if not capability['available']:self.skipTest('MXC unavailable: '+capability.get('reason',''))
        with tempfile.TemporaryDirectory(prefix='val-isolation-test-') as folder:
            root=Path(folder);inside=root/'work';outside=root/'outside';inside.mkdir();outside.mkdir()
            secret=outside/'secret.txt';secret.write_text('VAL_SECRET_CANARY',encoding='utf8')
            command=f'echo allowed>inside.txt\ntype "{secret}"\necho denied>"{outside / "not-created.txt"}"\nexit /b 0'
            result=pc_mcp.call('shell_run',{'command':command},policy=AccessPolicy(inside))
            self.assertTrue((inside/'inside.txt').is_file())
            self.assertFalse((outside/'not-created.txt').exists())
            self.assertNotIn('VAL_SECRET_CANARY',result)
            with self.assertRaisesRegex(ValueError,'Only CMD'):
                pc_mcp.call('shell_run',{'command':'echo x','shell':'powershell'},policy=AccessPolicy(inside))

    @unittest.skipUnless(os.name=='nt' and sandbox_exec._BINARY.is_file(),'Windows MXC runtime required')
    def test_isolated_process_cannot_reach_local_network(self):
        import http.server,threading,urllib.request
        if not sandbox_exec.status()['available']:self.skipTest('MXC unavailable')
        class Handler(http.server.BaseHTTPRequestHandler):
            hits=0
            def do_GET(self):
                type(self).hits+=1;self.send_response(200);self.end_headers();self.wfile.write(b'positive')
            def log_message(self,*args):pass
        server=http.server.HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/'
            self.assertEqual(urllib.request.urlopen(url,timeout=2).read(),b'positive');Handler.hits=0
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(RuntimeError):sandbox_exec.run(Path(folder),f'curl.exe --silent --max-time 3 {url}')
            self.assertEqual(Handler.hits,0)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

    @unittest.skipUnless(os.name=='nt','Hard link check targets Windows')
    def test_hardlinks_are_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);outside=root/'outside.txt';outside.write_text('x');work=root/'work';work.mkdir()
            os.link(outside,work/'linked.txt')
            with self.assertRaisesRegex(ValueError,'hard-linked'):sandbox_exec._scan(work)

if __name__=='__main__':unittest.main()
