"""Canonical chat -> model history; independent of HTML and browser storage."""
import copy
import json

def model_history(history):
    """The same rules as conversationForModel in the interface (ui/app/composer.js); keep both in step."""
    result=[]
    last_user=max((i for i,m in enumerate(history) if m.get('role')=='user'),default=-1)
    for index,message in enumerate(history):
        if message.get('compacted'):
            info=message.get('compacted') if isinstance(message.get('compacted'),dict) else {}
            label=info.get('method_label') or info.get('method') or 'API'
            result.append({'role':'user','content':f"Compressed prior context ({label}):\n\n{message.get('content','')}"})
            result.append({'role':'assistant','content':'Understood. I will continue using this compressed context.'})
            continue
        if message.get('role')=='assistant' and isinstance(message.get('model_turn'),list):
            # The rounds exactly as the engine saw them: a local engine reuses its cache up to the first change.
            result.extend(copy.deepcopy(message['model_turn']))
            for call in message.get('tool_trace') or []:
                if call.get('recovery'):
                    result.append({'role':'assistant','content':'Manual file recovery: '+str(call['recovery'].get('path',''))+' '+str(call['recovery'].get('result',''))})
            final=message.get('model_final') if isinstance(message.get('model_final'),dict) else None
            content=(final or {}).get('content','') if final else message.get('content') or ''
            reasoning=(final or {}).get('reasoning_content','') if final else ''
            if content or reasoning:
                result.append({'role':'assistant','content':content,**({'reasoning_content':reasoning} if reasoning else {})})
            continue
        if message.get('role')=='assistant':
            groups={}
            for offset,call in enumerate(message.get('tool_trace') or []):
                if call.get('recovery'):
                    result.append({'role':'assistant','content':'Manual file recovery: '+str(call['recovery'].get('path',''))+' '+str(call['recovery'].get('result',''))})
                    continue
                if call.get('executed') is not True or 'result' not in call:continue
                if not isinstance(call.get('args'),dict):continue
                groups.setdefault(call.get('round',offset),[]).append((offset,call))
            for calls in groups.values():
                tools=[];results=[]
                for offset,call in calls:
                    ident='history_'+str(index)+'_'+str(offset)
                    args={key:value for key,value in call['args'].items() if not key.startswith('_pc_')}
                    tools.append({'id':ident,'type':'function','function':{'name':call['name'],'arguments':json.dumps(args,ensure_ascii=False)}})
                    results.append({'role':'tool','tool_call_id':ident,'content':call.get('model_result',str(call['result']))})
                result.append({'role':'assistant','content':'','tool_calls':tools});result.extend(results)
        if message.get('role')!='assistant' or message.get('content') or message.get('reasoning_content'):
            clean={key:copy.deepcopy(message[key]) for key in ('role','content','reasoning_content') if key in message}
            if message.get('role')=='user' and message.get('images'):
                clean['content']=[{'type':'text','text':message.get('content') or ''},*[{'type':'image_url','image_url':{'url':image['url']}} for image in message['images']]]
            # What the core added to this message when the engine read it (date, recovery note). Not on the
            # latest user message: that one is being answered now and gets this turn's own.
            suffix=message.get('model_suffix')
            if message.get('role')=='user' and index!=last_user and suffix:
                if isinstance(clean.get('content'),list):clean['content']=clean['content']+(copy.deepcopy(suffix) if isinstance(suffix,list) else [{'type':'text','text':str(suffix)}])
                elif isinstance(suffix,str):clean['content']=str(clean.get('content') or '')+suffix
            result.append(clean)
    return result
