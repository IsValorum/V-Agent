"""Read GGUF weights before reporting a manual load as ready. No inference/prompt."""
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

GIB = 1024 ** 3

def memory_available():
    import psutil
    memory = psutil.virtual_memory()
    return memory.available, memory.total

def weight_files(config_path):
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    args = config.get('args') or []
    root = Path(config.get('cwd') or config_path.parent)
    files = []
    identities = set()
    for flag in ('--model', '--draft-model'):
        if flag not in args[:-1]:
            continue
        path = (root / args[args.index(flag) + 1]).resolve()
        if path.suffix.lower() != '.gguf':
            continue
        match = re.fullmatch(r'(.+)-(\d{5})-of-(\d{5})\.gguf', path.name, re.I)
        parts = [path]
        if match:
            count = int(match[3])
            if not 1 <= count <= 1000:
                raise ValueError('Número de partes del modelo no válido.')
            parts = [path.with_name(f'{match[1]}-{index:05d}-of-{count:05d}{path.suffix}') for index in range(1, count + 1)]
        for part in parts:
            stat = part.stat()
            if not part.is_file() or stat.st_size <= 0:
                raise ValueError('No se puede leer el archivo de pesos: ' + str(part))
            identity = (stat.st_dev, stat.st_ino) if stat.st_ino else os.path.normcase(str(part))
            if identity not in identities:
                identities.add(identity)
                files.append((part, stat.st_size, stat.st_mtime_ns))
    return files


class LoadCancelled(RuntimeError):
    pass


class ModelPreparation:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.state = {'active': False, 'stage': 'idle', 'model': None}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def update(self, **changes):
        with self.lock:
            self.state.update(changes)
            self.state['revision'] = self.state.get('revision', 0) + 1

    def begin(self, model):
        with self.lock:
            self.cancelled.clear()
            self.state = {'request_id': secrets.token_urlsafe(18), 'revision': 0, 'active': True, 'stage': 'checking', 'model': model,
                          'done_bytes': 0, 'total_bytes': 0, 'percent': None,
                          'started_at': time.time(), 'mode': None, 'message': 'Comprobando pesos…'}

    def request_cancel(self, request_id):
        with self.lock:
            if not self.state.get('active') or request_id != self.state.get('request_id'):
                raise ValueError('Esa carga ya no está activa. Actualiza su estado.')
            self.cancelled.set()
            self.state.update(stage='cancelling', cancel_requested=True, message='Cancelando la carga…',
                              revision=self.state.get('revision', 0) + 1)
            return dict(self.state)

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise LoadCancelled('Carga cancelada.')

    def finish_cancelled(self):
        self.update(active=False, stage='cancelled', message='Carga cancelada.', finished_at=time.time())

    def read_weights(self, config_path):
        self.check_cancelled()
        files = weight_files(config_path)
        total = sum(size for _, size, _ in files)
        available, physical = memory_available()
        reserve = max(3 * GIB, int(physical * .1))
        self.update(total_bytes=total, available_bytes=available, reserve_bytes=reserve)
        if not files or total > max(0, available - reserve):
            self.update(mode='on_demand', stage='starting', message='RAM insuficiente para precargar todos los pesos; lectura bajo demanda.')
            return
        self.update(stage='reading', mode='preloaded', percent=0, message='Leyendo pesos antes de cargar…')
        # Buffered reads warm the same OS file cache used by the engine's mapped
        # weights. A fixed buffer avoids allocating another model-sized copy.
        buffer = bytearray(16 * 1024 * 1024)
        done = 0
        for path, size, modified in files:
            with path.open('rb', buffering=0) as stream:
                remaining = size
                while remaining:
                    self.check_cancelled()
                    free, _ = memory_available()
                    if free < max(GIB, reserve // 2):
                        self.update(mode='on_demand', stage='starting', message='Memoria libre limitada; el resto de pesos se leerá bajo demanda.')
                        return
                    count = stream.readinto(memoryview(buffer)[:min(len(buffer), remaining)])
                    if not count:
                        raise OSError('El archivo de pesos cambió durante la lectura: ' + str(path))
                    done += count
                    remaining -= count
                    self.update(done_bytes=done, percent=round(done * 100 / total, 1))
                current = path.stat()
                if current.st_size != size or current.st_mtime_ns != modified:
                    raise OSError('El archivo de pesos cambió durante la lectura: ' + str(path))
        self.check_cancelled()
        self.update(stage='starting', percent=100, message='Pesos leídos. Preparando el motor…')

    def finish(self):
        with self.lock:
            self.check_cancelled()
            mode = self.state.get('mode')
            self.state.update(active=False, stage='ready', finished_at=time.time(),
                              revision=self.state.get('revision', 0) + 1,
                              message='Modelo preparado.' if mode == 'preloaded' else 'Modelo cargado; parte de los pesos se leerá bajo demanda.')

    def settle(self, config_path, server_pid, timeout=120):
        """Let the native engine finish its background mapped-page reader too.

        Watch only the verified engine child, never other applications' disk IO.
        No requests or token generation are used to warm the model.
        """
        if self.snapshot().get('mode') != 'preloaded' or not server_pid:
            return
        import psutil
        config_path = Path(config_path)
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
        executable = config.get('exe')
        if not executable:
            return
        executable = os.path.normcase(str((Path(config.get('cwd') or config_path.parent) / executable).resolve()))
        processes = []
        for process in psutil.Process(server_pid).children(recursive=True):
            try:
                if os.path.normcase(str(Path(process.exe()).resolve())) == executable:
                    processes.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        if not processes:
            self.update(mode='on_demand', message='No se pudo comprobar la preparación de la memoria del motor.')
            return
        self.update(stage='settling', message='Terminando la preparación en RAM…')
        def counters():
            return [(p.io_counters().read_bytes, p.memory_info().rss) for p in processes]
        previous = counters()
        quiet = time.monotonic()
        deadline = quiet + timeout
        while time.monotonic() < deadline:
            if self.cancelled.wait(.25):
                self.check_cancelled()
            current = counters()
            if any(now[0] - old[0] > 65536 or abs(now[1] - old[1]) > 4 * 1024 ** 2 for old, now in zip(previous, current)):
                quiet = time.monotonic()
            elif time.monotonic() - quiet >= 1.25:
                return
            previous = current
        self.update(mode='on_demand', message='El motor sigue preparando pesos en segundo plano; lectura bajo demanda.')

    def fail(self, error):
        self.update(active=False, stage='error', message=str(error), finished_at=time.time())

    def clear(self):
        with self.lock:
            self.state = {'active': False, 'stage': 'idle', 'model': None}
