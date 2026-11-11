import io,json,sys,tempfile,time,unittest,zipfile,hashlib
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'agent')]
import engine_updates as updates
from agent_profiles import tools_for_profile,PROFILES,filter_enabled,external_allowed

def wait(service):
    deadline=time.monotonic()+3
    while service.busy and time.monotonic()<deadline:time.sleep(.01)
    assert not service.busy

class ProfileUpdateTests(unittest.TestCase):
    def test_profiles_never_remove_manually_selected_tools_or_parameters(self):
        tools=[{'function':{'name':name,'parameters':{'properties':{'path':{'type':'string'}}},'description':'Original'}} for name in ['pc__web_render','pc__fs_edit','hf__hf_transfer','duckduckgo__web_visit']]
        for profile in PROFILES:
            result=tools_for_profile(tools,profile)
            self.assertEqual([t['function']['name'] for t in result],[t['function']['name'] for t in tools])
            self.assertEqual([t['function']['parameters'] for t in result],[t['function']['parameters'] for t in tools])
            self.assertEqual(PROFILES[profile]['rounds'],50)
    def test_light_mode_keeps_only_basic_tools_and_never_external_mcp(self):
        enabled={'web_search','fs_read','browser','shell_run','console','hf_account','sys_info'}
        self.assertEqual(filter_enabled(enabled,'light',True),{'web_search','fs_read','sys_info','console','shell_run'})
        self.assertFalse(external_allowed('light',True))
        self.assertNotIn('http_request',filter_enabled({'http_request','download','open','navigate'},'light',True))
        self.assertIn('http_request',filter_enabled({'http_request','download'},'balanced',True))
        self.assertNotIn('start',filter_enabled(set(),'advanced',True))
        self.assertIn('job_wait',filter_enabled({'job_wait'},'balanced',True))
        self.assertNotIn('job_wait',filter_enabled(set(),'light',True))
        self.assertTrue(external_allowed('balanced',True))
        self.assertFalse(external_allowed('balanced',False))
    def test_advanced_mode_preserves_optional_selection_and_gates_admin(self):
        selected={'browser','hf_transfer','shell_run','console'}
        sandbox=filter_enabled(selected,'advanced',False)
        self.assertIn('browser',sandbox);self.assertIn('hf_transfer',sandbox);self.assertIn('shell_run',sandbox);self.assertNotIn('console',sandbox)
        full=filter_enabled(selected,'advanced',True)
        self.assertIn('shell_run',full);self.assertIn('console',full);self.assertIn('browser',full)
        self.assertNotIn('start',full);self.assertNotIn('screen_capture',full);self.assertIn('job_wait',full)
        enabled=filter_enabled(selected|{'start','screen_capture'},'advanced',True)
        self.assertIn('start',enabled);self.assertIn('screen_capture',enabled)
        self.assertNotIn('start',sandbox);self.assertNotIn('screen_capture',sandbox);self.assertNotIn('job_wait',sandbox)
    def test_archive_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside.exe',b'no')
            with self.assertRaises(ValueError):updates.extract_zip(archive,Path(tmp)/'bin')
    def test_official_nightly_detection_install_digest_and_rollback(self):
        binary=io.BytesIO()
        with zipfile.ZipFile(binary,'w') as z:z.writestr('llama-server.exe',b'fake test binary')
        raw=binary.getvalue();asset={'name':'llama-b999-bin-win-cpu-x64.zip','size':len(raw),'browser_download_url':'https://github.com/ggml-org/llama.cpp/releases/download/b999/test.zip','digest':'sha256:'+hashlib.sha256(raw).hexdigest()}
        release={'tag_name':'b999','draft':False,'prerelease':True,'html_url':'https://github.com/ggml-org/llama.cpp/releases/tag/b999','assets':[asset]}
        def download(request,**kwargs):return io.BytesIO(json.dumps([release]).encode() if 'api.github.com' in request.full_url else raw)
        with tempfile.TemporaryDirectory() as tmp,patch.object(updates,'DATA_ROOT',Path(tmp)),patch.object(updates.urllib.request,'urlopen',download),patch.object(updates.subprocess,'run',return_value=type('Result',(),{'returncode':0})()):
            service=updates.Updates(lambda:{'cpu':{'build':'b123'}});service.check(True);wait(service)
            self.assertTrue(service.state['releases']['llama-cpu']['available'])
            self.assertTrue(service.state['releases']['llama-cpu']['development'])
            service.install('llama-cpu');wait(service)
            self.assertEqual(service.snapshot()['progress']['received'],len(raw));self.assertEqual(service.snapshot()['progress']['phase'],'complete');self.assertFalse(service.state.get('error'));self.assertTrue(Path(updates.active_installations()['llama-cpu']['executable']).is_file())
            service.rollback('llama-cpu');self.assertNotIn('llama-cpu',updates.active_installations());self.assertTrue(service.state['releases']['llama-cpu']['available'])
    def test_syntax_check_never_executes_a_project_command(self):
        import pc_mcp,diagnostics
        from access_policy import AccessPolicy
        with tempfile.TemporaryDirectory() as tmp,patch.object(diagnostics,'inspect',side_effect=AssertionError('Unexpected command execution')):
            Path(tmp,'test.py').write_text('def add(a,b):\n    return a+b\n')
            result=json.loads(pc_mcp.call('code_check',{'path':'test.py','check':'syntax','run':True},policy=AccessPolicy(tmp)))
            self.assertTrue(result['ok']);self.assertFalse(result['info']['runtime_checked'])

    def test_strata_update_verifies_text_output(self):
        binary=io.BytesIO()
        with zipfile.ZipFile(binary,'w') as archive:archive.writestr('strata-poly.exe',b'fake binary')
        raw=binary.getvalue()
        asset={'name':'strata-poly-windows-x64-test.zip','size':len(raw),'browser_download_url':'https://github.com/simplexai-labs/PolyStrata/releases/download/v1/test.zip'}
        result=type('Result',(),{'returncode':0,'stdout':'Usage: strata-poly','stderr':''})()
        with tempfile.TemporaryDirectory() as tmp,patch.object(updates,'DATA_ROOT',Path(tmp)),patch.object(updates.urllib.request,'urlopen',return_value=io.BytesIO(raw)),patch.object(updates.subprocess,'run',return_value=result) as run:
            service=updates.Updates(lambda:{})
            service.state['releases']={'strata':{'tag':'v1','asset':asset,'dependencies':[]}}
            service.install('strata');wait(service)
            self.assertFalse(service.state.get('error'))
            self.assertEqual(service.snapshot()['progress']['phase'],'complete')
            self.assertTrue(run.call_args.kwargs['text'])

if __name__=='__main__':unittest.main()
