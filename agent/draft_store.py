"""Durable per-conversation tool drafts, including cancelled generations."""
import json
from pathlib import Path
import re
import secrets


def _target(record):
    path = (record.get("args") or {}).get("path") or record.get("file_path") or ""
    if not path:
        return ""
    name = Path(str(path).replace("\\", "/")).name
    return re.sub(r"^[0-9a-f]{32}-", "", name, flags=re.I).lower()


def _discard_disk_target(workspace, target):
    if workspace is None or not target:
        return
    try:
        folder = workspace.path("drafts")
        snapshots = list(folder.glob("*.json")) if folder.is_dir() else []
    except (OSError, ValueError):
        return
    for snap_path in snapshots:
        if not re.fullmatch(r"[0-9a-f]{32}", snap_path.stem):
            continue
        try:
            snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if snapshot.get("name") in RECOVERABLE and _target(snapshot) == target:
            for copy in folder.glob(snap_path.stem + "-*"):
                try:
                    copy.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                snap_path.unlink(missing_ok=True)
            except OSError:
                pass


# Only an unfinished file write can be recovered (draft_recovery.pending_draft); "mcp__draft" is a
# call still being streamed whose tool is not known yet.
RECOVERABLE = {"pc__fs_write", "mcp__draft"}


def prune_finished(workspace):
    """Remove snapshots that can never be recovered: finished calls and non-write tools.

    Earlier versions saved every tool call (a read, a listing...) and a full copy of every written
    file, so a chat folder filled with dozens of files without the user doing anything.
    """
    if workspace is None:
        return
    try:
        folder = workspace.path("drafts")
        snapshots = list(folder.glob("*.json")) if folder.is_dir() else []
    except (OSError, ValueError):
        return
    for path in snapshots:
        if not re.fullmatch(r"[0-9a-f]{32}", path.stem):
            continue
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        finished = snapshot.get("status") == "completed" and snapshot.get("ok") is not False
        if finished or snapshot.get("name") not in RECOVERABLE:
            for copy in folder.glob(path.stem + "-*"):
                copy.unlink(missing_ok=True)
            path.unlink(missing_ok=True)


class DraftStore:
    def __init__(self, workspace, write_text):
        self.workspace = workspace
        self.write_text = write_text
        self.records = {}
        prune_finished(workspace)

    def observe(self, event):
        trace = event.get("id")
        if not trace or event.get("type") not in ("tool_draft", "tool", "tool_state", "tool_result"):
            return
        record = self.records.setdefault(trace, {
            "id": secrets.token_hex(16), "name": "", "status": "drafting",
            "parts": [], "args": {}, "dirty_chars": 0, "dirty": False,
        })
        record["name"] = event.get("name") or record["name"]
        record["status"] = event.get("status") or record["status"]
        delta = event.get("delta")
        if event["type"] == "tool_draft" and isinstance(delta, str):
            record["parts"].append(delta)
            record["dirty_chars"] += len(delta)
        if isinstance(event.get("args"), dict):
            record["args"] = event["args"]
        if event['type'] == 'tool_result':
            for key in ('result', 'ok', 'executed', 'elapsed_ms'):
                if key in event:
                    record[key] = event[key]
        record["dirty"] = True
        if event["type"] == "tool_result" and event.get("denied"):
            # The user said no: content they refused (and earlier failed attempts at the same
            # file in this turn) must not stay on disk as a "draft".
            target = _target(record)
            for key, other in list(self.records.items()):
                if key == trace or (other["name"] == record["name"] and other["status"] != "completed"
                                    and target and _target(other) == target):
                    self._discard(other)
                    self.records.pop(key, None)
            return
        if record["name"] and record["name"] not in RECOVERABLE:
            # Nothing to recover from a read, a listing or a command: keep no file for it.
            if event["type"] == "tool_result":
                self.records.pop(trace, None)
            return
        if event["type"] == "tool_result" and event.get("ok") is not False and record["status"] == "completed":
            # The file is written: its draft and earlier unfinished attempts at the same file are spent.
            target = _target(record)
            for key, other in list(self.records.items()):
                if key == trace or (other["name"] == record["name"] and target and _target(other) == target):
                    self._discard(other)
                    self.records.pop(key, None)
            _discard_disk_target(self.workspace, target)
            return
        event["draft_id"] = record["id"]
        if event["type"] == "tool_result" or record["dirty_chars"] >= 65536:
            self._save(record)
        if record.get("file_path"):
            event["recovery_path"] = record["file_path"]
        if record.get("storage_error"):
            event["draft_warning"] = record["storage_error"]

    def _discard(self, record):
        if self.workspace is None:
            return
        for relative in (record.get("file_path"), "drafts/" + record["id"] + ".json"):
            if not relative:
                continue
            try:
                self.workspace.path(relative).unlink(missing_ok=True)
            except (OSError, ValueError):
                pass

    def _save(self, record):
        if self.workspace is None or not record["dirty"]:
            return
        try:
            self._write_snapshot(record)
            record.pop("storage_error", None)
        except (OSError, ValueError) as error:
            record["storage_error"] = "No se pudo respaldar el borrador en disco: " + str(error)

    def _write_snapshot(self, record):
        snapshot = {key: record[key] for key in ("id", "name", "status", "args")}
        snapshot["raw"] = "".join(record["parts"])
        for key in ('result', 'ok', 'executed', 'elapsed_ms'):
            if key in record:
                snapshot[key] = record[key]
        if record["name"] == "mcp__draft":
            from tool_markup import complete_draft_call
            decoded = complete_draft_call(snapshot["raw"], {"pc__fs_write": {
                "type": "object", "properties": {"path": {}, "content": {}}, "required": ["path", "content"]}})
            if decoded:
                record["name"] = snapshot["name"] = decoded[0]
                record["args"] = snapshot["args"] = decoded[1]
        if record["name"] == "pc__fs_write":
            args = record["args"]
            if not isinstance(args.get("content"), str):
                try:
                    obj = json.loads(snapshot["raw"], strict=False)
                    candidate = obj.get("arguments", obj) if isinstance(obj, dict) else {}
                    args = candidate if isinstance(candidate, dict) else {}
                except ValueError:
                    args = {}
            if isinstance(args.get("content"), str):
                filename = Path(str(args.get("path") or "archivo.txt").replace("\\", "/")).name
                filename = re.sub(r"[^\w. -]", "_", filename)[:100] or "archivo.txt"
                relative = "drafts/" + record["id"] + "-" + filename
                self.write_text(self.workspace.path(relative), args["content"])
                record["file_path"] = snapshot["file_path"] = relative
        if record['name'] == 'pc__fs_write' and not snapshot.get('file_path'):
            from draft_recovery import extract_file
            file = extract_file(snapshot)
            if file and file[1]:
                filename = re.sub(r'[^\w. -]', '_', Path(str(file[0]).replace('\\', '/')).name)[:100] or 'archivo.txt'
                relative = 'drafts/' + record['id'] + '-' + filename
                self.write_text(self.workspace.path(relative), file[1])
                record['file_path'] = snapshot['file_path'] = relative
                snapshot['partial'] = not file[2]
        target = self.workspace.path("drafts/" + record["id"] + ".json")
        self.write_text(target, json.dumps(snapshot, ensure_ascii=False))
        record["dirty_chars"] = 0
        record["dirty"] = False

    def flush(self):
        for record in self.records.values():
            if record["status"] in ("drafting", "validating", "running"):
                record["status"] = "interrupted"
                record["dirty"] = True
            self._save(record)


def read_draft(workspace, draft_id):
    if not isinstance(draft_id, str) or not re.fullmatch(r"[0-9a-f]{32}", draft_id):
        raise ValueError("Identificador de borrador no válido.")
    path = workspace.path("drafts/" + draft_id + ".json")
    return json.loads(path.read_text(encoding="utf-8"))
