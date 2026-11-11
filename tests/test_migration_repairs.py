import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'agent'),str(ROOT/'tools'),str(ROOT)]
import desktop_runtime
import extensions
import thinking_policy


class MigrationRepairs(unittest.TestCase):
    def test_hub_never_starts_custom_config_without_full_access(self):
        import agent
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'mcp.json'
            path.write_text(json.dumps({'mcpServers':{'pc':{'command':'worker'},'legacy':{'command':'external'}}}),encoding='utf8')
            hub=type('Hub',(),{'settings':{},'servers':{}})()
            with patch.object(agent,'MCP_CONFIG',str(path)),patch.object(agent.ACCESS,'snapshot',return_value={'mode':'sandbox'}),patch.object(extensions,'enabled_configs',return_value={'custom':{'command':'external'}}),patch.object(agent,'hub_from_config',return_value=hub) as factory:
                agent.create_agent_hub()
                self.assertEqual(set(factory.call_args.args[0]['mcpServers']),{'pc'})

    def test_external_servers_stop_when_access_is_revoked(self):
        class Server:
            def __init__(self):self.closed=False
            def close(self):self.closed=True
        builtin=Server();external=Server()
        hub=type('Hub',(),{'servers':{'pc':builtin,'custom':external},'settings':{}})()
        with patch.object(extensions,'enabled_configs',return_value={'custom':{'command':'x'}}):
            extensions.reconcile(hub,False)
        self.assertTrue(external.closed)
        self.assertFalse(builtin.closed)
        self.assertEqual(list(hub.servers),['pc'])

    def test_queued_external_server_does_not_start_after_removal(self):
        class Server:
            started=False
            def start(self):self.started=True
        server=Server();hub=type('Hub',(),{'servers':{}})()
        extensions._start_if_present(hub,'custom',server)
        self.assertFalse(server.started)

    def test_llama_custom_template_and_name_survive_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();gguf=root/'weights.gguf';gguf.write_bytes(b'fake')  # long form (CI temp can be 8.3)
            template=root/'template.jinja';template.write_text('{% if enable_thinking %}yes{% endif %}',encoding='utf8')
            fake=type('GGUF',(),{'metadata':{'general.architecture':'other','other.context_length':32768}})
            with patch.object(desktop_runtime,'DATA_ROOT',root),patch('gguf_reader.GGUFFile',return_value=fake):
                info=desktop_runtime.inspect_llama_import(str(gguf),str(template))
                result=desktop_runtime.register_llama_import(info,'My model')
                config=root/'llama-configs'/(__import__('hashlib').sha256(result['model']['id'].encode()).hexdigest()[:24]+'.json')
                saved=json.loads(config.read_text(encoding='utf8'))
                self.assertEqual(saved['template'],str(template))
                self.assertEqual(json.loads((root/'llama-added.json').read_text(encoding='utf8'))[0]['display_name'],'My model')
                self.assertEqual(info['context'],32768)
                self.assertEqual(thinking_policy.capability({'config':str(config)},'llama')['mode'],'toggle')
                self.assertTrue(desktop_runtime.inspect_llama_import(str(gguf))['already_registered'])

    def test_invalid_custom_template_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);gguf=root/'weights.gguf';gguf.write_bytes(b'fake')
            template=root/'broken.jinja';template.write_text('{% if %}',encoding='utf8')
            fake=type('GGUF',(),{'metadata':{}})
            with patch.object(desktop_runtime,'DATA_ROOT',root),patch('gguf_reader.GGUFFile',return_value=fake):
                with self.assertRaises(ValueError):desktop_runtime.inspect_llama_import(str(gguf),str(template))


if __name__=='__main__':unittest.main()
