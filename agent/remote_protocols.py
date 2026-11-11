"""Translate provider wire formats at the transport boundary, never in the tool loop."""
import json
import re
from urllib.parse import urlsplit


def openai_payload(body,base_url,send_sampling=False):
    body=dict(body)
    for field in ('seed','frequency_penalty','presence_penalty'):body.pop(field,None)
    if not send_sampling:
        body.pop('temperature',None);body.pop('top_p',None)
    if urlsplit(base_url).hostname=='api.openai.com' and 'max_tokens' in body:body['max_completion_tokens']=body.pop('max_tokens')
    return body


def positive_int(value):
    try:
        if isinstance(value, bool):return None
        result=int(value)
        return result if 0<result<=100_000_000 else None
    except (TypeError,ValueError,OverflowError):return None


def model_info(item,overrides):
    identifier=str(item['id'])
    limits=item.get('limits') if isinstance(item.get('limits'),dict) else {};architecture=item.get('top_provider') if isinstance(item.get('top_provider'),dict) else {}
    context=next((n for n in (positive_int(item.get(k)) for k in ('context_length','context_window','max_input_tokens','max_model_len')) if n),None)
    context=context or positive_int(limits.get('context')) or positive_int(architecture.get('context_length'))
    manual=overrides.get(identifier,{})
    return {'id':identifier,'display_name':str(item.get('display_name') or item.get('name') or identifier),
            'context':positive_int(manual.get('context')) or context,
            'reported_context':context,'context_source':'manual' if positive_int(manual.get('context')) else 'provider' if context else 'unknown',
            'max_output_tokens':positive_int(item.get('max_tokens')) or positive_int(item.get('max_output_tokens')),
            'capabilities':item.get('capabilities') if isinstance(item.get('capabilities'),dict) else {}}


def claude_content(content):
    if isinstance(content,str):return [{'type':'text','text':content}] if content else []
    blocks=[]
    for part in content or []:
        if part.get('type')=='text' and part.get('text'):blocks.append({'type':'text','text':part['text']})
        elif part.get('type')=='image_url':
            url=part.get('image_url',{}).get('url','');match=re.fullmatch(r'data:(image/(?:png|jpeg|gif|webp));base64,(.+)',url,re.S)
            blocks.append({'type':'image','source':({'type':'base64','media_type':match[1],'data':match[2]} if match else {'type':'url','url':url})})
    return blocks


def claude_payload(payload,version,output_limit=None):
    system=[];messages=[]
    for message in payload.get('messages',[]):
        role=message.get('role');content=claude_content(message.get('content'))
        if role in ('system','developer'):system.extend(content);continue
        if role=='tool':
            content=[{'type':'tool_result','tool_use_id':message['tool_call_id'],'content':content}];role='user'
        elif role=='assistant':
            for call in message.get('tool_calls') or []:
                function=call['function'];args=function.get('arguments') or '{}'
                if isinstance(args,str):args=json.loads(args)
                if not isinstance(args,dict):raise ValueError('Los argumentos de la herramienta deben ser un objeto JSON.')
                content.append({'type':'tool_use','id':call['id'],'name':function['name'],'input':args})
        if not content:continue
        role='assistant' if role=='assistant' else 'user'
        if messages and messages[-1]['role']==role:messages[-1]['content'].extend(content)
        else:messages.append({'role':role,'content':content})
    limit=positive_int(payload.get('max_tokens')) or min(output_limit or 8192,8192)
    body={'model':payload['model'],'messages':messages,'max_tokens':min(limit,output_limit) if output_limit else limit,'stream':True}
    if system:body['system']=system
    if payload.get('tools'):
        body['tools']=[{'name':t['function']['name'],'description':t['function'].get('description',''),'input_schema':t['function'].get('parameters') or {'type':'object','properties':{}}} for t in payload['tools']]
        choice=payload.get('tool_choice','auto')
        if choice in ('auto','none','required'):body['tool_choice']={'type':{'required':'any'}.get(choice,choice)}
        elif isinstance(choice,dict):body['tool_choice']={'type':'tool','name':choice['function']['name']}
    # The current Claude API removed sampling parameters. Older gateways can opt in to the legacy version.
    if version<'2026-10-21' and 'temperature' in payload:body['temperature']=payload['temperature']
    return body


class ClaudeStream:
    def __init__(self):self.usage={};self.tools={}

    def packet(self,event):
        kind=event.get('type');delta={};finish=None
        if kind=='error':raise ValueError('Claude: '+str(event.get('error',{}).get('message') or 'Error de streaming'))
        if kind=='message_start':
            usage=event.get('message',{}).get('usage',{})
            self.usage={'prompt_tokens':sum(usage.get(k,0) or 0 for k in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens')),'completion_tokens':usage.get('output_tokens',0)}
        elif kind=='content_block_start':
            block=event.get('content_block',{});index=event['index']
            if block.get('type')=='tool_use':
                self.tools[index]=len(self.tools)
                delta={'tool_calls':[{'index':self.tools[index],'id':block['id'],'type':'function','function':{'name':block['name'],'arguments':json.dumps(block['input']) if block.get('input') else ''}}]}
            elif block.get('type')=='text':delta={'content':block.get('text','')}
        elif kind=='content_block_delta':
            part=event.get('delta',{});index=event['index']
            if part.get('type')=='text_delta':delta={'content':part.get('text','')}
            elif part.get('type')=='thinking_delta':delta={'reasoning_content':part.get('thinking','')}
            elif part.get('type')=='input_json_delta' and index in self.tools:delta={'tool_calls':[{'index':self.tools[index],'function':{'arguments':part.get('partial_json','')}}]}
        elif kind=='message_delta':
            if 'output_tokens' in event.get('usage',{}):self.usage['completion_tokens']=event['usage']['output_tokens']
            reason=event.get('delta',{}).get('stop_reason');finish={'tool_use':'tool_calls','max_tokens':'length'}.get(reason,'stop') if reason else None
        elif kind=='message_stop':return b'data: [DONE]\n\n'
        else:return None
        return ('data: '+json.dumps({'choices':[{'index':0,'delta':delta,'finish_reason':finish}],**({'usage':self.usage} if self.usage else {})},ensure_ascii=False)+'\n\n').encode()
