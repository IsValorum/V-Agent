"""Cached, model-independent checks of the active template/tool transport."""
import hashlib
from functools import lru_cache
from pathlib import Path

from serve.frontend import ChatTemplate, OutputParser


def check_template(path):
    path = Path(path).resolve()
    try:
        native = path.with_name('chat_template.native.jinja')
        fingerprint = hashlib.sha256(path.read_bytes() + b'\x00' + (native.read_bytes() if native.exists() else b'')).hexdigest()
        return dict(_check(str(path), fingerprint))
    except (OSError, ValueError) as error:
        return {'ok': False, 'error': str(error), 'template': str(path)}


@lru_cache(maxsize=48)
def _check(path, fingerprint):
    args = {'path': 'test.html', 'content': '<!doctype html>\n<script>const quote="a\\\\b"; const x={a:[1,2]};</script>\n' + 'x'*4096,
            'label': '001', 'enabled': False, 'count': 3, 'items': [1, 'x'], 'meta': {'key': 'value'}}
    properties = {key: {'type': kind} for key, kind in zip(args, ('string','string','string','boolean','integer','array','object'))}
    tool = {'name': 'pc__contract_probe', 'description': 'Protocol test.', 'parameters': {
        'type': 'object', 'properties': properties, 'required': list(args)}}
    try:
        template = ChatTemplate(path)
        from templates import formato_llamada
        dialect = formato_llamada(Path(path).parent, native=True)
        template_tools = [{'type':'function','function':tool}] if dialect in ('gemma','dsml') else [tool]
        checks = 0
        for compact in (False, True):
            for count in (1, 2):
                marker = 'STRATA_CONTRACT_HISTORY_START'
                messages = [{'role': 'user', 'content': 'Test'}, {'role': 'assistant', 'content': marker,
                    'tool_calls': [{'id':f'probe-{i}','type':'function','function': {'name': tool['name'], 'arguments': args}} for i in range(count)]},
                    *[{'role': 'tool', 'name':tool['name'],'tool_call_id':f'probe-{i}','content': 'PROBE_RESULT'} for i in range(count)], {'role': 'user', 'content': 'Next'}]
                prompt = template.render(messages, tools=template_tools, strata_native_tools=True,
                                         compact_tool_prompt=compact, enable_thinking=False)
                if marker not in prompt:
                    raise ValueError('Template lost assistant history.')
                # Gemma's template places assistant content after calls/results in
                # the same model turn; the content marker is not its call boundary.
                body = (prompt.split('<|turn>model\n',1)[1].split('<|turn>user',1)[0]
                        if dialect == 'gemma' else prompt.split(marker,1)[1].split('PROBE_RESULT',1)[0])
                parser = OutputParser(thinking=False, tools=[tool], stream_tools=True, draft_tools=True, recover=True,call_format=dialect if dialect in ('gemma','glm','dsml','lfm2') else 'function')
                events = []
                for offset in range(0, len(body), 17):
                    events.extend(parser.feed(body[offset:offset+17]))
                events.extend(parser.finish('stop'))
                calls = [event.call for event in events if event.kind == 'tool_call']
                if len(calls) != count or any(call.name != tool['name'] or call.arguments != args for call in calls):
                    raise ValueError('Template/parser mismatch: tool calls or argument values changed.')
                if prompt.count('PROBE_RESULT') != count:
                    raise ValueError('Template lost tool results.')
                checks += 1
        return {'ok': True, 'checks': checks, 'fingerprint': fingerprint, 'template': path, 'kind': 'protocol_only'}
    except Exception as error:
        return {'ok': False, 'error': str(error), 'fingerprint': fingerprint, 'template': path, 'kind': 'protocol_only'}
