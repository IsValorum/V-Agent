"""Canonical chat -> model history; independent of HTML and browser storage."""
import copy
import json

def model_history(history):
    result=[]
    for index,message in enumerate(history):
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
                clean['content']=[{'type':'text','text':message.get('content','')},*[{'type':'image_url','image_url':{'url':image['url']}} for image in message['images']]]
            result.append(clean)
    return result
