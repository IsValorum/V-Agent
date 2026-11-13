"""Host-side approvals. No added model instructions and no scope escalation."""
import threading
import time
import uuid
import re

SAFE={'pc__fs_list','pc__fs_read','pc__doc_read','pc__project_map','pc__sys_info','duckduckgo__web_search','duckduckgo__web_visit','hf__hf_account'}
# Read-only and confined to the isolated conversation folder: asking for each one only trains
# users to click "allow" without reading. Network reads are excluded: they send data out.
LOCAL_READS={'pc__fs_list','pc__fs_read','pc__doc_read','pc__fs_search','pc__project_map','pc__file_history','pc__sys_info'}
# Also read-only in "Confirm changes": the status of jobs already approved, and what the agent's own
# browser shows (not its cookies or network log). Opening pages, clicking and typing still ask.
AUTO_READS=LOCAL_READS|{'pc__job_list','pc__job_status','pc__job_wait','autobrowser__text','autobrowser__snapshot',
                        'autobrowser__tabs','autobrowser__screenshot','autobrowser__wait'}
SENSITIVE=re.compile(r'(?i)(?:\.env|credential|secret|token|id_rsa|password|\.pem|\.key\b)')
def needs_approval(mode,name,args,agent_profile=None,full_access=False):
    # "Automatic" (run) is the user's explicit choice: no profile adds prompts behind it.
    if mode=='run':return False
    if agent_profile=="light" and name=="pc__console" and args.get("action","run")=="run":return True
    if agent_profile=="light" and name=="pc__shell_run":return True
    if agent_profile=="light" and name=="pc__code_check" and args.get("run") and args.get("check") not in (None,"","syntax"):return True
    args=args if isinstance(args,dict) else {}
    # Every argument that names a file: copy/move use desde/destino/destination, not only path.
    sensitive=any(SENSITIVE.search(str(args.get(key) or '')) for key in ('path','desde','destino','destination'))
    # file_history restores with `revision` and then overwrites the file: a write, never a read.
    restore=name=='pc__file_history' and bool(args.get('revision'))
    if mode=='ask':
        if restore:return True
        if not full_access and not sensitive and name in LOCAL_READS:return False
        if not full_access and name=='pc__code_check' and not args.get('run'):return False
        return True
    if mode!='auto':return False
    # "Confirm changes": reads run, changes ask. It used to ask for searching files and listing
    # versions, which "Ask every time" allows: the looser mode was stricter for those reads.
    if restore:return True
    if sensitive and name in LOCAL_READS:return True
    if name in SAFE or name in AUTO_READS:return False
    if name=='pc__code_check' and (not args.get('run') or args.get('check') in (None,'','syntax')):return False
    if name=='pc__console' and args.get('action')=='status':return False
    return True

class Approvals:
    """Pending prompts plus "always in this chat" grants, kept in memory only (gone on restart)."""
    def __init__(self):self.lock=threading.RLock();self.pending={};self.grants=set()
    def create(self,name,args,conversation=None):
        ident=uuid.uuid4().hex
        with self.lock:self.pending[ident]={'event':threading.Event(),'allowed':False,'name':name,'conversation':conversation}
        return {'type':'approval','id':ident,'name':name,'args':args,'rememberable':conversation is not None}
    def granted(self,conversation,name):
        with self.lock:return conversation is not None and (conversation,name) in self.grants
    def resolve(self,ident,allowed,remember=False):
        if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid approval id.')
        if type(allowed) is not bool or type(remember) is not bool:raise ValueError('Invalid approval.')
        with self.lock:
            item=self.pending.get(ident)
            if item is None:raise ValueError('Approval expired.')
            if allowed and remember and item['conversation'] is not None:self.grants.add((item['conversation'],item['name']))
            item['allowed']=allowed;item['event'].set()
    def wait(self,ident,cancel):
        with self.lock:item=self.pending[ident]
        try:
            deadline=time.monotonic()+600
            while not item['event'].wait(.1):
                if cancel.is_set() or time.monotonic()>deadline:return False
            return item['allowed'] and not cancel.is_set()
        finally:
            with self.lock:self.pending.pop(ident,None)

APPROVALS=Approvals()
