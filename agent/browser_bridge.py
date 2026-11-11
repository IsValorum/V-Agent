"""Queue that connects the agent's browser tool with the visible Tauri window."""
import threading
import time
import uuid


class BrowserBridge:
    def __init__(self):
        self.lock = threading.RLock()
        self.pending = {}
        self.dispatched = set()
        self.closed = False

    def request(self, action, args=None, timeout=30):
        if self.closed:
            raise ValueError('El navegador integrado no está disponible.')
        request_id = uuid.uuid4().hex
        event = threading.Event()
        slot = {'event': event, 'result': None, 'error': None}
        with self.lock:
            self.pending[request_id] = {'id': request_id, 'action': action,
                                        'args': args if isinstance(args, dict) else {},
                                        'slot': slot, 'created': time.time()}
        if not event.wait(max(1, min(int(timeout), 90))):
            with self.lock:
                self.pending.pop(request_id, None)
                self.dispatched.discard(request_id)
            raise TimeoutError('La ventana de V-Agent no respondió. Abre la aplicación de escritorio.')
        with self.lock:
            self.pending.pop(request_id, None)
            self.dispatched.discard(request_id)
        if slot['error']:
            raise ValueError(str(slot['error']))
        return slot['result']

    def take(self):
        with self.lock:
            items = []
            for request_id, item in list(self.pending.items()):
                if request_id in self.dispatched:
                    continue
                self.dispatched.add(request_id)
                items.append({'id': request_id, 'action': item['action'], 'args': item['args']})
            return items

    def resolve(self, request_id, result=None, error=None):
        with self.lock:
            item = self.pending.get(request_id)
            if not item:
                return False
            item['slot']['result'] = result
            item['slot']['error'] = error
            item['slot']['event'].set()
            return True

    def close(self):
        with self.lock:
            self.closed = True
            for item in self.pending.values():
                item['slot']['error'] = 'La aplicación se cerró.'
                item['slot']['event'].set()
            self.pending.clear()
            self.dispatched.clear()
