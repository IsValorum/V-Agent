"""Politica de VRAM dinamica para el Strata Agent (tarjetas pequenas, 6 GB aqui).

Que hace y por que:

* El motor reparte la VRAM libre entre tres cosas: la cache de expertos, el KV y el
  buffer de paso (staging). Lo que se deja apartado para otros programas es
  `--vram-reserve-mib` (suelo duro 256 MiB: `src/poly/engine.cpp:1364`).
* Medido en este PC (RTX 4050 6 GB, Qwen3.6-35B-A3B APEX, `POST /v1/vram` en caliente):
      reserva 256 -> 1567 expertos en cache (1889 MiB) | 512 -> 1354 (1633) | 768 -> 1140 (1376)
  o sea ~1,205 MiB por experto: cada 256 MiB de reserva cuestan ~212 expertos (-13,6%).
* Con contexto largo pasa lo contrario que con uno corto: la KV crece en piezas de 4096
  filas (46,6 MiB con q8_0, 11.968 B/token medidos: `q8_0 KV cache: 544 bytes a row` x 22)
  y con 128K y reserva 256 el motor da `cudaGraphInstantiate: out of memory`; con 512
  desaparece (`docs/Q8_KV.md:110-119`). La tabla sigue ese ancla.
* `--stage-mib 1024` fija el buffer de paso para siempre y apaga `--stage-read-mib`
  (`src/poly/engine.hpp:66-74`: con el default de 128 vale 2048). Sin la flag, el staging
  vale 128 MiB y solo se presta del cache mientras se lee un prompt, que es lo que midio
  +268 expertos residentes (`docs/BACKENDS.md:2026-2029`). Por eso la politica lo quita.

Nada de esto toca los ficheros del modelo ni las demas opciones del config.
"""
from __future__ import annotations

import json
import urllib.request

# MiB de VRAM que el motor deja libres, por contexto maximo. Suelo 256 (el del motor),
# techo 768 (mas cache no se paga con contextos cortos y el escritorio necesita aire).
RESERVE_TABLE = ((32768, 256), (65536, 384), (98304, 448), (131072, 512), (262144, 768))
FLOOR_MIB, CEIL_MIB = 256, 768
KV_BYTES_PER_TOKEN = {"q8_0": 11968, "fp16": 22528, "int8": 11264, "int8k": 11552}
KV_CHUNK_ROWS = 4096                     # cover() crece de 4096 en 4096 filas + 1024 por delante

DROP_ARGS = ("--stage-mib", "--stage-read-mib")     # se deja el default del motor (128 + 2048)


def kv_mib(tokens: int, kv: str = "q8_0") -> float:
    """Lo que vale ese contexto en la KV cache (aproximado, el formato por defecto q8_0)."""
    return tokens * KV_BYTES_PER_TOKEN.get(kv, KV_BYTES_PER_TOKEN["fp16"]) / (2 ** 20)


def reserve_for(tokens: int, kv: str = "q8_0") -> int:
    """Reserva en MiB para un contexto maximo dado, interpolando la tabla y redondeando a 64.

    Con q8_0 la KV de todo el contexto pesa menos que la tabla; se anade un minimo que
    crece con el contexto para que la pieza de 4096 filas y los grafos de CUDA puedan
    aparecer sin pelearse con el cache de expertos.
    """
    if tokens <= 0:
        return FLOOR_MIB
    prev_t, prev_r = RESERVE_TABLE[0]
    out = prev_r
    if tokens <= prev_t:
        out = prev_r
    else:
        for t, r in RESERVE_TABLE[1:]:
            if tokens <= t:
                out = prev_r + (r - prev_r) * (tokens - prev_t) / (t - prev_t)
                break
            prev_t, prev_r = t, r
        else:
            out = RESERVE_TABLE[-1][1]
    need = max(0, kv_mib(tokens, kv) - kv_mib(32768, kv)) / 4.0      # cabezal para piezas + grafos
    out = max(out, FLOOR_MIB + need)
    out = int(round(out / 64.0) * 64)
    return max(FLOOR_MIB, min(CEIL_MIB, out))


def plan(max_context: int, kv: str = "q8_0", current_reserve: int | None = None) -> dict:
    """Los argumentos que la politica quiere para ese contexto, y por que.

    `current_reserve`: la reserva que ya tenia el config. Se respeta si era MAS alta que
    la del plan (un modelo de 65 GB que pidio 1024 MiB de margen no se lo quita quien
    cambia el contexto); si era mas baja, manda el plan.
    """
    reserve = reserve_for(max_context, kv)
    kept = ""
    if current_reserve and current_reserve > reserve:
        reserve, kept = int(current_reserve), " (se conserva la del config, pedia mas margen)"
    else:
        reserve = max(reserve, FLOOR_MIB)
    return {
        "max_context": max_context,
        "kv": kv,
        "vram_reserve_mib": reserve,
        "kv_total_mib": round(kv_mib(max_context, kv), 1),
        "drop": list(DROP_ARGS),
        "note": ("el staging vuelve al default del motor (128 MiB fijos + 2048 MiB prestados "
                 "mientras se lee), y la reserva deja %d MiB libres para el escritorio%s" % (reserve, kept)),
    }


def apply_to_args(args: list, p: dict) -> list:
    """Reescribe la lista de argumentos del motor con el plan; no toca lo demas."""
    out = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in DROP_ARGS or a == "--vram-reserve-mib" or a == "--max-context":
            skip = True                                   # su valor va detras
            continue
        out.append(a)
    out += ["--max-context", str(p["max_context"]), "--vram-reserve-mib", str(p["vram_reserve_mib"])]
    return out


def apply_to_config(path: str, p: dict) -> dict:
    """Aplica el plan a un `strata-*.json` y devuelve {antes, despues} para poder revertir."""
    with open(path, encoding="utf-8") as h:
        cfg = json.load(h)
    before = list(cfg.get("args") or [])
    cfg["args"] = apply_to_args(before, p)
    with open(path, "w", encoding="utf-8") as h:
        json.dump(cfg, h, indent=1)
        h.write("\n")
    return {"config": path, "before": before, "after": cfg["args"]}


def restore_config(info: dict) -> None:
    with open(info["config"], encoding="utf-8") as h:
        cfg = json.load(h)
    cfg["args"] = info["before"]
    with open(info["config"], "w", encoding="utf-8") as h:
        json.dump(cfg, h, indent=1)
        h.write("\n")


def resize(port: int, reserve_mib: int | None, timeout: float = 60.0) -> dict:
    """`POST /v1/vram` en el motor: recolma la cache de expertos sin reiniciar nada.

    None vuelve a la reserva con la que arranco. Devuelve las cifras del motor
    (expert_slots, expert_cache_mib, vram_free_mib). Nada si el motor esta escribiendo.
    """
    url = f"http://127.0.0.1:{port}/v1/vram"
    body = b"{}" if reserve_mib is None else json.dumps({"reserve_mib": int(reserve_mib)}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def current(port: int, timeout: float = 8.0) -> dict:
    """Lo que el motor dice tener ahora: reserva aplicada, expertos y VRAM libre.

    `/v1/status` solo trae el bloque `vram` cuando el motor ya contestó a un VRAM; por eso
    se prueba primero el status y, si no viene, `/metrics`, que siempre lleva `engine.vram`.
    """
    out = {}
    for path in ("/v1/status", "/metrics"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
                st = json.load(r)
        except Exception:
            continue
        eng = st.get("engine") or {}
        v = st.get("vram") or eng.get("vram") or {}
        out["loaded"] = st.get("loaded", out.get("loaded"))
        ctx = (st.get("context") or {}).get("native") or eng.get("max_context")
        if ctx:
            out["context"] = ctx
        for k in ("reserve_mib", "expert_slots", "expert_slots_full", "expert_cache_mib", "vram_free_mib"):
            if v.get(k) is not None and out.get(k) is None:
                out[k] = v[k]
        if out.get("reserve_mib") is not None and out.get("context"):
            break
    return out



def estimate_tokens(messages) -> int:
    """Tokens de un historial, sin tokenizador: 3,6 caracteres por token y 60 de plantilla por turno.

    Sirve para decidir la reserva; para el numero fino esta lo que mide el motor (context_usage).
    """
    n = 0
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            n += len(c) / 3.6
        elif isinstance(c, list):
            n += sum(len(x.get("text", "")) / 3.6 for x in c if isinstance(x, dict))
        n += 60
    return int(n)


def auto_reserve(messages, max_context: int, used_tokens: int = 0, kv: str = "q8_0",
                 step_mib: int = 128) -> int:
    """Reserva para ESTE turno: lo que pide el contexto que se va a ocupar, no el techo.

    Con 5K tokens de conversacion la reserva baja al suelo (256 MiB) y la cache coge
    ~213 expertos mas (+13,6% medidos); cuando la charla crece se sube antes de que la
    KV y los grafos tengan que pelearse con el cache, que es lo que daba el
    `cudaGraphInstantiate: out of memory` con 128K y reserva 256 (`docs/Q8_KV.md:110-119`).
    `step_mib` es la histéresis: solo se cambia cuando la diferencia vale la pena, porque
    recolmar la cache cuesta 11 ms soltar y ~262 ms recuperar.
    """
    need = max(used_tokens, estimate_tokens(messages)) + 2048      # el turno nuevo + aire
    want = reserve_for(min(max(4096, need), max_context), kv)
    return int(want // step_mib * step_mib) if want >= FLOOR_MIB + step_mib else FLOOR_MIB


def tune(port: int, messages, max_context: int, used_tokens: int = 0, kv: str = "q8_0",
         step_mib: int = 128) -> dict:
    """Aplica `auto_reserve` si merece la pena; devuelve que hizo (y que no)."""
    now = current(port)
    want = auto_reserve(messages, max_context, used_tokens, kv)
    have = now.get("reserve_mib")
    if have is None:
        # El motor solo cuenta su reserva despues de un VRAM: la primera vuelta la fija y
        # a partir de ahi ya hay con que comparar.
        try:
            out = resize(port, want)
        except Exception as e:
            return {"applied": False, "wanted": want, "why": str(e)[:120]}
        return {"applied": True, "from": None, "to": out.get("reserve_mib", want),
                "expert_slots": out.get("expert_slots"), "expert_slots_full": out.get("expert_slots_full")}
    if abs(want - have) < step_mib:
        return {"applied": False, "reserve_mib": have, "wanted": want, "why": "dentro de la histeresis"}
    try:
        out = resize(port, want)
    except Exception as e:
        return {"applied": False, "reserve_mib": have, "wanted": want, "why": str(e)[:120]}
    return {"applied": True, "from": have, "to": out.get("reserve_mib"),
            "expert_slots": out.get("expert_slots"), "expert_slots_full": out.get("expert_slots_full")}


# ---------------------------------------------------------------- de linea de comandos
#   python agent/vram_policy.py show                 que hay ahora y que haria la politica
#   python agent/vram_policy.py apply [techo]        aplica a TODOS los strata-*.json
#   python agent/vram_policy.py apply [techo] solo   aplica solo al config del modelo cargado
#   python agent/vram_policy.py revert               vuelve a los args guardados en el backup
# apply escribe agent/vram-policy-backup.json con los args de antes; sin ese fichero no toca nada.
if __name__ == "__main__":
    import glob
    import os
    import sys

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repository root
    BACKUP = os.path.join(ROOT, "agent", "vram-policy-backup.json")
    what = (sys.argv[1] if len(sys.argv) > 1 else "show").lower()
    caps = sorted({int(a[a.index("--max-context") + 1]) for f in glob.glob(ROOT + "/strata-*.json")
                   for a in [json.load(open(f, encoding="utf-8")).get("args") or []] if "--max-context" in a})
    if what == "show":
        print("techos declarados en los configs:", caps)
        for t in (16384, 32768, 65536, 98304, 131072):
            print("  %7d tokens -> reserva %3d MiB, KV %6.0f MiB" % (t, reserve_for(t), kv_mib(t)))
        for f in sorted(glob.glob(ROOT + "/strata-*.json"))[:3]:
            a = json.load(open(f, encoding="utf-8")).get("args") or []
            print("  %s: %s" % (f.rsplit("\\", 1)[-1], " ".join(x for x in a if x.startswith("--"))[:150]))
        print("(la politica quita --stage-mib/--stage-read-mib y fija --vram-reserve-mib por techo)")
    elif what in ("apply", "revert"):
        files = sorted(glob.glob(ROOT + "/strata-*.json"))
        if what == "revert":
            saved = json.load(open(BACKUP, encoding="utf-8"))
            for path, args in saved.items():
                cfg = json.load(open(path, encoding="utf-8"))
                cfg["args"] = args
                json.dump(cfg, open(path, "w", encoding="utf-8"), indent=1)
            print("restoredos %d configs desde el backup" % len(saved))
        else:
            top = int(sys.argv[2]) if len(sys.argv) > 2 else 16384
            only = "solo" in sys.argv[3:]
            if only:
                files = files[:1]
            before = {f: (json.load(open(f, encoding="utf-8")).get("args") or []) for f in files}
            json.dump(before, open(BACKUP, "w", encoding="utf-8"), indent=1)
            for f in files:
                a = before[f]
                kv = a[a.index("--kv") + 1] if "--kv" in a else "q8_0"
                cap = int(a[a.index("--max-context") + 1]) if "--max-context" in a else top
                apply_to_config(f, plan(cap, kv))
            print("aplicado a %d configs (techo propio de cada uno; backup en %s); "
                  "hay que recargar cada modelo para que suelte el stage fijo"
                  % (len(files), BACKUP))
    else:
        print("uso: vram_policy.py [show | apply [techo] [solo] | revert]")


