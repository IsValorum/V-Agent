"""Host-side file confinement. Arbitrary host commands require explicit full-PC access."""
import hmac
import os
import re
import shutil
import stat
import threading
from pathlib import Path

from runtime_paths import DATA_ROOT
SANDBOX = DATA_ROOT / 'workspaces'
WORKSPACE_FOLDER = 'conversations'
LEGACY_WORKSPACE_FOLDER = 'conversaciones'
WORKSPACE_SUBFOLDERS = {'borradores': 'drafts', 'salidas': 'outputs', 'contexto': 'context'}
_MIGRATED = set()
_MIGRATION_LOCK = threading.Lock()

PC_PRIVATE_ARGS = frozenset(("_pc_access_key", "_pc_workspace"))


def _merge_tree(source, destination):
    """Move a legacy tree without overwriting current user files."""
    source, destination = Path(source), Path(destination)
    if not source.exists():
        return
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        return
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir() and target.is_dir() and not item.is_symlink():
            _merge_tree(item, target)
            continue
        if target.exists():
            stem, suffix = target.stem, target.suffix
            index = 2
            while True:
                candidate = target.with_name(f'{stem}.legacy-{index}{suffix}')
                if not candidate.exists():
                    target = candidate
                    break
                index += 1
        item.rename(target)
    source.rmdir()


def migrate_workspace_layout(root):
    """Rename legacy Spanish workspace folders once, preserving every file."""
    root = Path(root).resolve()
    with _MIGRATION_LOCK:
        if root in _MIGRATED:
            return
        current = root / WORKSPACE_FOLDER
        legacy = root / LEGACY_WORKSPACE_FOLDER
        if legacy.exists():
            _merge_tree(legacy, current)
        if current.exists():
            for conversation in current.iterdir():
                if not conversation.is_dir() or conversation.is_symlink():
                    continue
                for old, new in WORKSPACE_SUBFOLDERS.items():
                    source, destination = conversation / old, conversation / new
                    if source.exists():
                        _merge_tree(source, destination)
        _MIGRATED.add(root)


def conversation_id(value):
    if (not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", value)
            or getattr(os.path, "isreserved", lambda _: False)(value)):
        raise ValueError("Identificador de conversación no válido. Abre el chat y vuelve a intentar.")
    return value


def workspace_signature(secret, chat_id):
    return hmac.digest(secret.encode("utf-8"), ("workspace:" + conversation_id(chat_id)).encode("ascii"), "sha256").hex()


class AccessDenied(PermissionError):
    pass

class AccessPolicy:
    def __init__(self, root=SANDBOX):
        self.root = Path(os.path.abspath(root))
        self.mode = 'sandbox'
        self.lock = threading.Lock()
        self._check_links(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root == Path(SANDBOX).resolve():
            migrate_workspace_layout(self.root)

    @staticmethod
    def _check_links(path):
        for component in (*reversed(path.parents), path):
            try:
                info = component.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise AccessDenied('Sandbox: no se permiten enlaces ni junctions.')

    @property
    def workspaces(self):
        return self.root / WORKSPACE_FOLDER

    def for_conversation(self, chat_id):
        return AccessPolicy(self.workspaces / conversation_id(chat_id))

    def snapshot(self):
        with self.lock:
            return {'mode': self.mode, 'root': str(self.root),
                    'shell_available': self.mode == 'full_pc', 'kind': 'file-sandbox',
                    'workspaces': str(self.workspaces)}

    def set_mode(self, mode):
        if mode not in ('sandbox', 'full_pc'):
            raise ValueError('Acceso no válido.')
        with self.lock:
            self.mode = mode
        return self.snapshot()

    def path(self, value, full_access=False, campo='path'):
        if not isinstance(value, str) or not value.strip() or '\x00' in value:
            # Nombre del campo en el mensaje: fs_copy usa desde/destino y un "path debe contener
            # una ruta" deja al modelo relanzando la misma llamada vacia.
            raise ValueError('%s debe contener una ruta.' % campo)
        value = os.path.expanduser(value)
        # Old conversations may still reference the Spanish workspace subfolders.
        first, separator, rest = value.replace('\\', '/').partition('/')
        if separator and first in WORKSPACE_SUBFOLDERS:
            value = WORKSPACE_SUBFOLDERS[first] + '/' + rest
        if full_access:
            return Path(os.path.abspath(value if os.path.isabs(value) else self.root / value))
        if value[:1] in ('/', '\\') and value[:2] not in ('//', '\\\\') and value.strip('/\\'):
            # "/flowtrack.html" is a Linux habit, not a Windows location: inside the isolated folder it
            # can only mean "here". Rejecting it ended long file writes for nothing (seen 2026-11-10).
            # Drive, network and parent (..) paths remain rejected below.
            value = value.lstrip('/\\')
        drive, tail = os.path.splitdrive(value)
        if value.startswith(('\\\\', '//', '\\', '/')) or drive and not os.path.isabs(value):
            # Decir donde SI se puede escribir: sin eso el modelo reintenta la misma ruta
            # o, peor, narra el escrito como si hubiera ocurrido.
            example = Path(value.replace('\\', '/')).name or 'archivo.txt'
            raise AccessDenied(f'Sandbox: "{value}" es una ruta absoluta. Usa una ruta relativa a la '
                               f'carpeta de trabajo, por ejemplo "{example}" (eso escribe en {self.root}).')
        raw = Path(value)
        for part in raw.parts:
            if part == raw.anchor or part in ('.', '..'):
                continue
            if ':' in part or getattr(os.path, 'isreserved', lambda p: False)(part):
                raise AccessDenied(f'Sandbox: "{value}" lleva letra de unidad o un nombre reservado. '
                                   f'Escribe dentro de {self.root} con una ruta relativa.')
        candidate = Path(os.path.abspath(raw if raw.is_absolute() else self.root / raw))
        root = os.path.normcase(str(self.root))
        try:
            inside = os.path.commonpath([root, os.path.normcase(str(candidate))]) == root
        except ValueError:
            inside = False
        if not inside:
            raise AccessDenied(f'Sandbox: "{value}" queda fuera de la carpeta de trabajo ({self.root}). '
                               f'Activa "Toda la PC" en la interfaz para escribir fuera de ella.')
        self._check_links(candidate)
        return candidate

    def check_tool(self, name, args, full_access=False):
        if name == 'fs_copy':
            # Dos rutas en la misma llamada: ambas pasan por el mismo confine, si no el modelo
            # podria leer fuera de la carpeta de trabajo "copiando" hacia dentro.
            self.path(args.get('desde'), full_access, 'desde')
            self.path(args.get('destino'), full_access, 'destino')
        elif name in ('fs_list', 'fs_read', 'fs_write', 'fs_edit', 'web_render', 'fs_search'):
            self.path(args.get('path') or '.', full_access)
        elif name == 'fs_manage':
            self.path(args.get('path'), full_access)
            if args.get('destination'):self.path(args.get('destination'), full_access)
        # shell_run is permitted here only because the worker itself enforces
        # the verified OS-isolated runner when no full-access key is present.
