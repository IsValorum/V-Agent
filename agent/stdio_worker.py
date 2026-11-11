"""Cancellable stdio MCP transport with optional serial worker reuse."""
from collections import deque
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import queue


def serve_worker(execute):
    """One JSON request/result per line. Access scope is supplied afresh per call."""
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    for line in sys.stdin:
        result=execute(json.loads(line))
        print(json.dumps(result,ensure_ascii=False),flush=True)


class _Worker:
    def __init__(self,script):
        self.process=subprocess.Popen(__import__('runtime_paths').command('hf' if Path(script).stem=='hf_mcp' else 'pc','--mcp-worker'),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf-8',errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
            start_new_session=os.name!='nt')
        self.responses=queue.Queue()
        self.errors=deque(maxlen=16)
        def read():
            try:
                for line in self.process.stdout:self.responses.put(line)
            finally:
                self.process.stdout.close()
                self.responses.put(None)
        def errors():
            try:
                for line in self.process.stderr:self.errors.append(line[-1000:])
            finally:self.process.stderr.close()
        threading.Thread(target=read,daemon=True).start()
        threading.Thread(target=errors,daemon=True).start()

    def request(self,params,timeout):
        self.process.stdin.write(json.dumps(params,ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        try:line=self.responses.get(timeout=timeout)
        except queue.Empty:raise ValueError('Operation timed out. Check existing changes before retrying.') from None
        if line is None:raise ValueError('Tool worker stopped: '+''.join(self.errors)[-1000:])
        result=json.loads(line)
        if not isinstance(result,dict):raise ValueError('Invalid tool worker response.')
        return result


def serve(script, tools, name, version, timeout, protocol='2025-06-18',persistent=False):
    active = {}
    lock = threading.Lock()
    output_lock = threading.Lock()
    serial = threading.Semaphore(1)
    worker = None

    def send(message):
        with output_lock:
            try:
                print(json.dumps(message, ensure_ascii=False), flush=True)
            except (BrokenPipeError, OSError):
                pass

    def stop(process):
        if process is None:
            return
        try:
            if process.poll() is not None:
                pass
            elif os.name == 'nt':
                killer = str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/taskkill.exe')
                subprocess.run([killer, '/F', '/T', '/PID', str(process.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:pass
        if process.stdin is not None and not process.stdin.closed:
            try:process.stdin.close()
            except (OSError,ValueError):pass

    def execute(request, slot):
        nonlocal worker
        process = None
        acquired = False
        keep_worker = False
        try:
            while not acquired:
                if slot['cancel'].is_set():
                    raise ValueError('Operation cancelled before execution.')
                acquired = serial.acquire(timeout=.1)
            if slot['cancel'].is_set():
                raise ValueError('Operation cancelled before execution.')
            with lock:
                if slot['cancel'].is_set():
                    raise ValueError('Operation cancelled before execution.')
                if persistent:
                    if worker is None or worker.process.poll() is not None:worker=_Worker(script)
                    process=worker.process
                else:
                    process = subprocess.Popen([sys.executable, str(script), '--mcp-worker'],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding='utf-8', errors='replace',
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                        start_new_session=os.name != 'nt')
                slot['process'] = process
                cancelled = slot['cancel'].is_set()
            if cancelled:
                stop(process)
            if persistent:
                result=worker.request(request.get('params') or {},timeout)
            else:
                try:
                    out, err = process.communicate(json.dumps(request.get('params') or {}), timeout=timeout)
                except subprocess.TimeoutExpired:
                    stop(process)
                    process.communicate(timeout=5)
                    raise ValueError('Operation timed out. Check existing changes before retrying.')
                if process.returncode:raise ValueError('Tool worker stopped: '+err[-1000:])
                result = json.loads(out)
            if slot['cancel'].is_set():
                raise ValueError('Operation cancelled. Changes already completed are preserved; check state before retrying.')
            if not isinstance(result, dict):
                raise ValueError('Invalid tool worker response.')
            keep_worker=persistent
        except Exception as error:
            result = {'isError':True, 'content':[{'type':'text','text':str(error)}]}
        finally:
            if process is not None and (not keep_worker or slot['cancel'].is_set()):
                stop(process)
            with lock:
                if worker is not None and worker.process is process and process.poll() is not None:worker=None
                active.pop(request['id'], None)
            if acquired:
                serial.release()
        send({'jsonrpc':'2.0','id':request['id'],'result':result})

    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
            except ValueError:
                continue
            if not isinstance(request, dict):
                continue
            ident, method = request.get('id'), request.get('method')
            if method == 'notifications/cancelled':
                with lock:
                    slot = active.get((request.get('params') or {}).get('requestId'))
                    if slot:
                        slot['cancel'].set()
                        process = slot.get('process')
                    else:
                        process = None
                stop(process)
                continue
            if ident is None or isinstance(ident, (dict,list)):
                continue
            if method == 'tools/call':
                slot = {'cancel':threading.Event()}
                with lock:
                    duplicate = ident in active
                    if not duplicate:
                        active[ident] = slot
                if duplicate:
                    send({'jsonrpc':'2.0','id':ident,'error':{'code':-32600,'message':'Duplicate active request ID.'}})
                    continue
                threading.Thread(target=execute, args=(request,slot), daemon=True).start()
                continue
            if method == 'initialize':
                result = {'protocolVersion':protocol,'capabilities':{'tools':{}},'serverInfo':{'name':name,'version':version}}
            elif method == 'tools/list':
                result = {'tools':tools}
            elif method == 'ping':
                result = {}
            else:
                send({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Unknown method.'}})
                continue
            send({'jsonrpc':'2.0','id':ident,'result':result})
    finally:
        with lock:
            slots = list(active.values())
            for slot in slots:
                slot['cancel'].set()
        for slot in slots:
            stop(slot.get('process'))
        if worker is not None:stop(worker.process)
