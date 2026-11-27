"""Per-model MTP capabilities and persisted engine arguments."""
from functools import lru_cache
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from model_import import _atomic_json


_DRAFT_HINTS = ("mtp", "dspark", "dflash", "draft", "assistant")
_STRATA_DSPARK_TYPES = frozenset(("F32", "F16", "BF16", "Q8_0"))


@lru_cache(maxsize=128)
def _header(path, size, modified):
    from gguf_catalog import inspect
    info = inspect(path)
    meta = info['metadata']
    arch = meta.get("general.architecture")
    embd = meta.get(str(arch) + ".embedding_length")
    return {
        "path": path,
        "head": info['head'],
        "arch": arch,
        "embedding": embd,
        "pre": meta.get("tokenizer.ggml.pre"),
        "markov_rank": meta.get(str(arch) + ".dspark.markov_rank"),
        "types": list((info.get("types") or {}).keys()),
        "signature": (arch, embd, meta.get(str(arch) + ".expert_count")),
    }


def _dspark_unsupported_types(candidate):
    return [t for t in (candidate.get("types") or []) if t not in _STRATA_DSPARK_TYPES]


def _compatible(candidate, main):
    """True when `candidate` is a valid Strata MTP head, Q8_0/F16/BF16 DSpark drafter, or Gemma 4 assistant for `main`."""
    if candidate["head"] and candidate["signature"] == main["signature"]:
        return True
    if candidate.get("arch") == "dflash" and candidate.get("markov_rank"):
        if candidate.get("embedding") is None or candidate.get("embedding") != main.get("embedding"):
            return False
        c_pre, m_pre = candidate.get("pre"), main.get("pre")
        if c_pre and m_pre and c_pre != m_pre:
            return False
        if _dspark_unsupported_types(candidate):
            return False
        return True
    if main.get("arch") == "gemma4" and candidate.get("arch") == "gemma4" and candidate.get("path") != main.get("path"):
        return True
    return False


def header(path):
    path = Path(path).resolve()
    stat = path.stat()
    return _header(str(path), stat.st_size, stat.st_mtime_ns)


def argument(args, flag, default=None):
    return args[args.index(flag) + 1] if flag in args[:-1] else default


def describe(config_path):
    try:
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"integrated": False, "source": "", "tokens": 0, "files": [], "available": False}
    args = cfg.get("args") or []
    weight = Path(argument(args, "--model", ""))
    if not weight.is_absolute():
        weight = Path(cfg.get("cwd") or Path(config_path).parent) / weight
    try:
        main = header(weight)
    except (OSError, ValueError, EOFError, KeyError):
        return {"integrated": False, "source": "", "tokens": 0, "files": [], "available": False}
    external = argument(args, "--draft-model", "")
    source = external or ("integrated" if main["head"] else "")
    weight_resolved = str(weight.resolve()).lower()
    candidates = [
        p for p in weight.parent.glob("*.gguf")
        if str(p.resolve()).lower() != weight_resolved and any(h in p.name.lower() for h in _DRAFT_HINTS)
    ]
    if external:
        candidates.append(Path(external))
    files = []
    seen = set()
    for path in candidates:
        path = path.resolve()
        if str(path).lower() in seen:
            continue
        seen.add(str(path).lower())
        try:
            candidate = header(path)
        except (OSError, ValueError, EOFError, KeyError):
            continue
        if _compatible(candidate, main):
            files.append({"path": str(path), "name": path.name})
    tokens = 0 if "--no-draft" in args or not source else min(3, max(0, int(argument(args, "--window", 8)) - 1))
    return {"integrated": main["head"], "source": source, "tokens": tokens, "files": files, "available": True}


def save(config_path, source, tokens):
    if type(tokens) is not int or not 0 <= tokens <= 3:
        raise ValueError("Draft tokens debe estar entre 0 y 3.")
    if not isinstance(source, str):
        raise ValueError("Selecciona una fuente MTP.")
    path = Path(config_path)
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    info = describe(path)
    if not info["available"]:
        raise ValueError("No se pudo comprobar el modelo.")
    if source == "integrated":
        if not info["integrated"]:
            raise ValueError("Este modelo no incluye MTP integrado.")
    elif source:
        candidate = Path(source).resolve()
        args = cfg["args"]
        main = Path(argument(args, "--model", ""))
        if not main.is_absolute():
            main = Path(cfg.get("cwd") or path.parent) / main
        if candidate.suffix.lower() != ".gguf" or not candidate.is_file():
            raise ValueError("Selecciona un archivo GGUF MTP existente.")
        metadata = header(candidate)
        if not _compatible(metadata, header(main)):
            if metadata.get("arch") == "dflash":
                bad_types = _dspark_unsupported_types(metadata)
                if metadata.get("markov_rank") and bad_types:
                    raise ValueError(
                        f"Strata requiere la versión Q8_0 (o F16/BF16) del borrador DSpark (por ejemplo dspark-Inkling-2-Mini-Q8_0.gguf); "
                        f"este archivo está cuantizado en {', '.join(bad_types)}."
                    )
                raise ValueError("Este borrador DSpark/DFlash no es compatible con Strata para este modelo.")
            raise ValueError("El archivo no contiene una cabeza MTP con las dimensiones de este modelo.")
        source = str(candidate)
    if not source and tokens:
        raise ValueError("Selecciona primero una fuente MTP.")
    before = json.loads(json.dumps(cfg))
    args = cfg["args"]
    for flag in ("--draft-model", "--window", "--no-draft"):
        while flag in args:
            index = args.index(flag)
            del args[index:index + (1 if flag == "--no-draft" else 2)]
    if source and source != "integrated":
        args.extend(["--draft-model", source])
    args.extend(["--window", str(tokens + 1)])
    if not tokens or not source:
        args.append("--no-draft")
    if cfg != before:
        _atomic_json(path, cfg)
    return describe(path), before, cfg != before
