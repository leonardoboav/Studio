"""
Moments — fluxo de SHORTS a partir de criador BR (decisão de operador, ver CONTEXT.md).

Pipeline:
  ingest_for_cut (baixa master third_party)
    -> transcribe (pt)
    -> brain.select_moments (acha trechos 30-60s com assunto fechado)
    -> corta em 9:16 + organiza em output/moments/<figura>/<data>__<fonte>/
    -> escreve sidecars (_figura.json, _fonte.json, NN__assunto.json)

IMPORTANTE: o momento extraído é MATÉRIA-PRIMA. Sozinho (corte + legenda) é reused
content pela política do YouTube. Todo sidecar carimba precisa_camada_autoral=true:
o short publicável exige comentário/ângulo do operador por cima. Ver README de
output/moments/ e CONTEXT.md -> "Decisão do operador".
"""
import json
import os
import re
import subprocess
import unicodedata
from datetime import date
from pathlib import Path

from src.ingest import ingest_for_cut
from src.transcribe import transcribe
from src.brain import select_moments

MOMENTS_DIR = Path(__file__).parent.parent / "output" / "moments"

_MIN_DUR, _MAX_DUR = 30.0, 60.0


def slugify(text: str, max_words: int = 6) -> str:
    """minúsculas, ASCII (acentos viram letra base), separador '-', curto."""
    norm = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    norm = re.sub(r"[^a-zA-Z0-9\s-]", "", norm).lower().strip()
    words = re.split(r"[\s-]+", norm)
    words = [w for w in words if w][:max_words]
    return "-".join(words) or "sem-titulo"


def extract_moments(url: str, channel_slug: str = "ia", model_size: str = "small") -> dict:
    """Roda o fluxo completo e devolve o resumo (caminhos + momentos)."""
    ingested = ingest_for_cut(url, channel_slug)
    # Criador BR -> força pt (não auto-detect): a transcrição guia o corte.
    transcribed = transcribe(ingested, model_size=model_size, language="pt")
    selected = select_moments(transcribed)

    figura = ingested["metadata"].get("channel") or "desconhecido"
    figura_slug = slugify(figura, max_words=4)
    fonte_slug = slugify(ingested["metadata"].get("title", "fonte"), max_words=6)
    extraido_em = date.today().isoformat()

    fonte_dir = MOMENTS_DIR / figura_slug / f"{extraido_em}__{fonte_slug}"
    fonte_dir.mkdir(parents=True, exist_ok=True)

    src_video = ingested["file_path"]
    total_dur = float(ingested["metadata"].get("duration_sec", 0) or 0)

    written = []
    for i, m in enumerate(selected["cuts"], start=1):
        start = float(m.get("start_sec", 0))
        end = float(m.get("end_sec", 0))
        dur = round(end - start, 3)
        nn = f"{i:02d}"
        assunto_slug = slugify(m.get("assunto_slug") or m.get("assunto", f"momento-{nn}"))
        base = f"{nn}__{assunto_slug}"
        mp4_path = fonte_dir / f"{base}.mp4"

        status, note = _cut_vertical(src_video, start, end, dur, total_dur, mp4_path)

        sidecar = {
            "assunto": m.get("assunto", ""),
            "por_que_tem_sentido": m.get("por_que_tem_sentido", ""),
            "figura": figura,
            "fonte_url": ingested["metadata"].get("url", url),
            "start": round(start, 3),
            "end": round(end, 3),
            "duracao": dur,
            "proveniencia": "third_party",
            "nota_licenca": "corte de terceiro — uso sob decisão de operador (ver CONTEXT.md)",
            "trecho_transcrito": _transcript_slice(transcribed.get("transcript", {}), start, end),
            "precisa_camada_autoral": True,
            "status_corte": status,
            "obs": note,
        }
        (fonte_dir / f"{base}.json").write_text(json.dumps(sidecar, indent=2, ensure_ascii=False))
        written.append({"file": f"{base}.mp4", "assunto": sidecar["assunto"],
                        "duracao": dur, "status": status, "obs": note})

    _write_fonte_json(fonte_dir, ingested, figura, figura_slug, extraido_em, written)
    _update_figura_json(MOMENTS_DIR / figura_slug, figura, ingested["metadata"].get("channel", ""))

    return {
        "figura": figura,
        "pasta": str(fonte_dir),
        "momentos": written,
        "total": len(written),
    }


# ── corte 9:16 ──────────────────────────────────────────────────────────────────

def _cut_vertical(src, start, end, dur, total_dur, out_path: Path) -> tuple[str, str]:
    """Corta o trecho em 9:16 1080x1920, crf 18, áudio AAC 192k. Valida a janela."""
    if dur < _MIN_DUR:
        return "rejeitado", f"momento de {dur:.1f}s < {_MIN_DUR:.0f}s mínimo"
    if dur > _MAX_DUR:
        return "rejeitado", f"momento de {dur:.1f}s > {_MAX_DUR:.0f}s máximo"
    if start < 0 or (total_dur and end > total_dur + 1):
        return "rejeitado", f"janela fora do vídeo (0–{total_dur:.0f}s)"

    if out_path.exists() and out_path.stat().st_size > 0:
        return "ok", "cache"

    cmd = [
        "ffmpeg", "-y", "-ss", str(start), "-i", src, "-t", str(dur),
        "-vf", "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920,setsar=1",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not (out_path.exists() and out_path.stat().st_size > 0):
        return "erro", f"ffmpeg falhou: {r.stderr[-300:]}"
    return "ok", ""


def _transcript_slice(transcript: dict, start: float, end: float) -> str:
    parts = [s["text"] for s in transcript.get("segments", [])
             if s["start"] >= start - 0.5 and s["end"] <= end + 0.5]
    return " ".join(parts).strip()


# ── sidecars ─────────────────────────────────────────────────────────────────────

def _write_fonte_json(fonte_dir, ingested, figura, figura_slug, extraido_em, written):
    data = {
        "figura": figura,
        "figura_slug": figura_slug,
        "canal": ingested["metadata"].get("channel", ""),
        "fonte_url": ingested["metadata"].get("url", ""),
        "titulo": ingested["metadata"].get("title", ""),
        "duracao_total": ingested["metadata"].get("duration_sec", 0),
        "proveniencia": "third_party",
        "extraido_em": extraido_em,
        "momentos": [w["file"] for w in written],
    }
    (fonte_dir / "_fonte.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _update_figura_json(figura_dir: Path, figura: str, canal: str):
    figura_dir.mkdir(parents=True, exist_ok=True)
    path = figura_dir / "_figura.json"
    data = json.loads(path.read_text()) if path.exists() else {"figura": figura, "canal": canal, "fontes": []}
    fontes = sorted({p.name for p in figura_dir.iterdir() if p.is_dir()})
    data["figura"] = figura
    data["canal"] = canal or data.get("canal", "")
    data["fontes"] = fontes
    data["total_fontes"] = len(fontes)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _load_dotenv() -> None:
    """Carrega .env da raiz em os.environ, sem sobrescrever o que já existe."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    import sys

    _load_dotenv()
    if len(sys.argv) < 2:
        print("uso: python -m src.moments <url> [channel_slug=ia] [whisper_model=small]")
        sys.exit(1)
    _url = sys.argv[1]
    _channel = sys.argv[2] if len(sys.argv) > 2 else "ia"
    _model = sys.argv[3] if len(sys.argv) > 3 else "small"

    out = extract_moments(_url, _channel, _model)
    print(json.dumps(out, indent=2, ensure_ascii=False))
