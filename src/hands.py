"""
Hands — motor do sub-agente 'montador' (FFmpeg).

Dois caminhos:
  - cut_clips(): SHORT extractable — corta o trecho do master, reframe 9:16.
  - build_long(): LONGO — monta o esqueleto a partir do timeline.json (diretor de
    arte) + narração: assets nos timestamps, narração como trilha principal, música
    royalty-free com duck, legenda queimada, CTA no beat marcado.

Ponto de chegada é ESQUELETO (rascunho .mp4 + EDL), não render final.
Áudio de publicação (AAC 192k), nunca o WAV 16k do Whisper.
Só usa assets presentes no assets_manifest (licenciados); beat sem asset licenciado
vira slate preto marcado como pendente — NUNCA substituído por mídia não licenciada.
"""
import json
import subprocess
from pathlib import Path

CLIPS_DIR = Path(__file__).parent.parent / "output" / "clips"

_MIN_CLIP_DURATION = 5.0
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
_LONG_W, _LONG_H, _FPS = 1920, 1080, 30


# ── SHORT (extractable) — inalterado ────────────────────────────────────────────

def cut_clips(gate_result: dict) -> dict:
    """Corta cada short aprovado do master. Timestamps validados/snapeados; áudio 192k."""
    src = gate_result["file_path"]
    video_id = gate_result["metadata"]["id"]
    total_duration = gate_result["metadata"].get("duration_sec", 0)
    transcript = gate_result.get("transcript", {})

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    for cut in gate_result["cuts"]:
        rank = cut["rank"]
        start, end = _validated_timestamps(cut, transcript, total_duration)
        if start is None:
            print(f"[hands] Pulando short {rank} — timestamps inválidos.")
            cut["clip_path"] = None
            continue

        out_path = CLIPS_DIR / f"{video_id}_cut{rank:02d}.mp4"
        # Cache só vale se o arquivo existir E não estiver vazio (run anterior pode
        # ter deixado um .mp4 de 0 byte ao falhar — não tratar isso como pronto).
        if out_path.exists() and out_path.stat().st_size > 0:
            cut["clip_path"] = str(out_path)
            continue

        cmd = [
            "ffmpeg", "-y", "-ss", str(start), "-i", src, "-t", str(round(end - start, 3)),
            # Crop 9:16 limitado ao tamanho real (min) — funciona em fonte landscape
            # OU já vertical, sem estourar a largura/altura disponível.
            "-vf", "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920,setsar=1",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", str(out_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        cut["clip_path"] = None if r.returncode != 0 else str(out_path)
        if r.returncode != 0:
            print(f"[hands] Erro FFmpeg no short {rank}:\n{r.stderr}")

    return gate_result


# ── LONGO — monta o esqueleto a partir do timeline + narração ───────────────────

def build_long(piece: dict, work_dir: Path | None = None) -> dict:
    """
    Monta o esqueleto do vídeo longo.

    piece (campos esperados):
      video_id           — id da peça
      narration_path     — áudio da narração (trilha principal, 192k). OBRIGATÓRIO.
      timeline           — lista de beats OU timeline_path (json do diretor de arte)
      assets_manifest    — lista OU assets_manifest_path (licenças)
      music_path         — (opc) música royalty-free, entra com duck sob a narração
      cta                — (opc) {"start","end","text"} — CTA de like no beat marcado
      subtitle_path      — (opc) .srt para queimar

    Retorna piece + draft_path, edl_path, pending_beats, only_decorative_edits=False.
    """
    video_id = piece["video_id"]
    work_dir = work_dir or (CLIPS_DIR / f"{video_id}_long")
    work_dir.mkdir(parents=True, exist_ok=True)

    narration_path = piece.get("narration_path")
    if not narration_path or not Path(narration_path).exists():
        raise FileNotFoundError("build_long requer narration_path existente (trilha principal).")

    timeline = _load_list(piece.get("timeline"), piece.get("timeline_path"))
    manifest = _load_list(piece.get("assets_manifest"), piece.get("assets_manifest_path"))
    narration_dur = _duration(narration_path)

    # Queries licenciadas presentes no manifesto (cross-check de licença).
    licensed_queries = {m.get("query") for m in manifest if m.get("license")}

    # 1) Validar cada beat e montar segmentos (asset licenciado OU slate pendente).
    segments, edl_beats, pending = [], [], []
    for i, beat in enumerate(_valid_beats(timeline, narration_dur)):
        used = _beat_is_licensed(beat, licensed_queries)
        seg_path = work_dir / f"seg_{i:02d}.mp4"
        dur = round(beat["end"] - beat["start"], 3)

        if used:
            _make_asset_segment(beat["asset_path"], dur, seg_path)
        else:
            pending.append({"index": i, "start": beat["start"], "end": beat["end"],
                            "query": beat.get("query"), "reason": "asset ausente do manifesto ou do disco"})
            _make_slate_segment(dur, seg_path, label="ASSET PENDENTE")

        segments.append(seg_path)
        edl_beats.append({
            "index": i, "start": beat["start"], "end": beat["end"],
            "asset_path": beat.get("asset_path") if used else None,
            "source": beat.get("source") if used else None,
            "license": beat.get("license") if used else None,
            "query": beat.get("query"), "status": "used" if used else "pending",
        })

    if not segments:
        raise RuntimeError("Timeline sem beats válidos — nada a montar.")

    # 2) Trilha visual: concatena os segmentos uniformes.
    visual = work_dir / "visual.mp4"
    _concat(segments, visual, work_dir)

    # 3) Áudio: narração principal + música com duck (sidechain).
    mixed = work_dir / "mix.m4a"
    _mix_audio(narration_path, piece.get("music_path"), mixed)

    # 4) Combina visual + áudio, queima legenda e CTA (best-effort, com fallback).
    draft = work_dir / f"{video_id}_draft.mp4"
    applied = _combine(visual, mixed, draft, piece.get("subtitle_path"), piece.get("cta"))

    # 5) EDL — documento autoritativo para o acabamento manual.
    edl = {
        "video_id": video_id,
        "draft_path": str(draft),
        "resolution": f"{_LONG_W}x{_LONG_H}",
        "narration_path": narration_path,
        "music_path": piece.get("music_path"),
        "audio": "AAC 192k (narração principal + música com duck)",
        "subtitle_path": piece.get("subtitle_path"),
        "subtitle_burned": applied["subtitle"],
        "cta": piece.get("cta"),
        "cta_burned": applied["cta"],
        "burn_note": applied.get("reason", ""),
        "beats": edl_beats,
        "pending_beats": pending,
        "note": "ESQUELETO para acabamento manual — não é render final.",
    }
    edl_path = work_dir / f"{video_id}_edl.json"
    edl_path.write_text(json.dumps(edl, indent=2, ensure_ascii=False))

    piece["draft_path"] = str(draft)
    piece["edl_path"] = str(edl_path)
    piece["pending_beats"] = pending
    # Montagem real (cortes, assets nos timestamps, mix) — não é edição só decorativa.
    piece["only_decorative_edits"] = False
    print(f"[hands] Longo montado: {draft.name} ({len(edl_beats)} beats, {len(pending)} pendente(s))")
    return piece


# ── helpers de validação ────────────────────────────────────────────────────────

def _valid_beats(timeline: list, narration_dur: float) -> list:
    """Ordena por start e mantém só beats com janela válida dentro da narração."""
    out = []
    for beat in sorted(timeline, key=lambda b: b.get("start", 0)):
        start = float(beat.get("start", 0))
        end = float(beat.get("end", 0))
        if start < 0 or end <= start:
            continue
        if narration_dur > 0:
            end = min(end, narration_dur)
            if end <= start:
                continue
        out.append({**beat, "start": round(start, 3), "end": round(end, 3)})
    return out


def _beat_is_licensed(beat: dict, licensed_queries: set) -> bool:
    """Usável só se: tem asset no disco, carrega license, e a query está no manifesto."""
    path = beat.get("asset_path")
    if not path or not Path(path).exists():
        return False
    if not beat.get("license"):
        return False
    return beat.get("query") in licensed_queries


# ── helpers de FFmpeg ───────────────────────────────────────────────────────────

def _make_asset_segment(asset_path: str, dur: float, out_path: Path) -> None:
    ext = Path(asset_path).suffix.lower()
    vf = (f"scale={_LONG_W}:{_LONG_H}:force_original_aspect_ratio=decrease,"
          f"pad={_LONG_W}:{_LONG_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")
    if ext in _IMAGE_EXT:
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", asset_path, "-t", str(dur),
               "-r", str(_FPS), "-vf", vf, "-an", "-c:v", "libx264", "-crf", "20",
               "-preset", "fast", "-pix_fmt", "yuv420p", str(out_path)]
    elif ext in _VIDEO_EXT:
        cmd = ["ffmpeg", "-y", "-i", asset_path, "-t", str(dur), "-r", str(_FPS),
               "-vf", vf, "-an", "-c:v", "libx264", "-crf", "20", "-preset", "fast",
               "-pix_fmt", "yuv420p", str(out_path)]
    else:
        _make_slate_segment(dur, out_path, label="FORMATO DESCONHECIDO")
        return
    _run(cmd, f"segmento de asset {asset_path}")


def _make_slate_segment(dur: float, out_path: Path, label: str) -> None:
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           f"color=c=black:s={_LONG_W}x{_LONG_H}:r={_FPS}:d={dur}",
           "-an", "-c:v", "libx264", "-crf", "20", "-preset", "fast",
           "-pix_fmt", "yuv420p", str(out_path)]
    _run(cmd, f"slate ({label})")


def _concat(segments: list, out_path: Path, work_dir: Path) -> None:
    list_file = work_dir / "concat.txt"
    list_file.write_text("".join(f"file '{s.resolve()}'\n" for s in segments))
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-c", "copy", str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # Fallback: re-encoda se o copy falhar (params divergentes).
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
               "-c:v", "libx264", "-crf", "20", "-preset", "fast", str(out_path)]
        _run(cmd, "concat (re-encode)")


def _mix_audio(narration: str, music: str | None, out_path: Path) -> None:
    if music and Path(music).exists():
        # Música comprimida pela narração (sidechain) → duck real sob a fala.
        flt = ("[1:a][0:a]sidechaincompress=threshold=0.05:ratio=8:release=300[duck];"
               "[0:a][duck]amix=inputs=2:duration=first:dropout_transition=0[a]")
        cmd = ["ffmpeg", "-y", "-i", narration, "-stream_loop", "-1", "-i", music,
               "-filter_complex", flt, "-map", "[a]",
               "-c:a", "aac", "-b:a", "192k", str(out_path)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return
        print(f"[hands] duck falhou, usando só narração:\n{r.stderr[:300]}")
    cmd = ["ffmpeg", "-y", "-i", narration, "-c:a", "aac", "-b:a", "192k", str(out_path)]
    _run(cmd, "áudio (só narração)")


def _combine(visual: Path, audio: Path, draft: Path, subtitle: str | None, cta: dict | None) -> dict:
    """Combina visual+áudio aplicando legenda e CTA. Fallback gracioso se falhar."""
    applied = {"subtitle": False, "cta": False, "reason": ""}
    vf_parts = []

    has_subs = _has_filter("subtitles")
    has_draw = _has_filter("drawtext")
    font = _font_file()

    want_subtitle = bool(subtitle and Path(subtitle).exists())
    want_cta = bool(cta and cta.get("text"))

    if want_subtitle and has_subs:
        vf_parts.append(f"subtitles='{Path(subtitle).resolve()}'")
        applied["subtitle"] = True
    if want_cta and has_draw and font:
        txt = cta["text"].replace("'", "").replace(":", " ")
        vf_parts.append(
            f"drawtext=fontfile='{font}':text='{txt}':fontcolor=white:fontsize=54:"
            f"box=1:boxcolor=black@0.6:boxborderw=20:x=(w-tw)/2:y=h-160:"
            f"enable='between(t,{cta.get('start',0)},{cta.get('end',0)})'"
        )
        applied["cta"] = True

    # Motivo auto-documentado quando algo pedido não pôde ser queimado.
    missing = []
    if want_subtitle and not has_subs:
        missing.append("legenda (ffmpeg sem filtro 'subtitles'/libass)")
    if want_cta and (not has_draw or not font):
        missing.append("CTA (ffmpeg sem 'drawtext'/fonte)")
    if missing:
        applied["reason"] = ("não queimado, mantido no EDL para acabamento manual: "
                             + "; ".join(missing))
        print(f"[hands] {applied['reason']}")

    base = ["ffmpeg", "-y", "-i", str(visual), "-i", str(audio)]
    if vf_parts:
        cmd = base + ["-vf", ",".join(vf_parts), "-map", "0:v", "-map", "1:a",
                      "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                      "-c:a", "aac", "-b:a", "192k", "-shortest", str(draft)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return applied
        applied = {"subtitle": False, "cta": False,
                   "reason": "queima falhou em runtime; mantido no EDL para acabamento manual"}
        print(f"[hands] {applied['reason']}:\n{r.stderr[:200]}")

    cmd = base + ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "20",
                  "-preset", "fast", "-c:a", "aac", "-b:a", "192k", "-shortest", str(draft)]
    _run(cmd, "combine (sem queima)")
    return applied


def _has_filter(name: str) -> bool:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in r.stdout.splitlines() if line.strip())


# ── utilitários ─────────────────────────────────────────────────────────────────

def _validated_timestamps(cut, transcript, total_duration):
    raw_start = float(cut.get("start_sec", 0))
    raw_end = float(cut.get("end_sec", 0))
    segments = transcript.get("segments", [])
    if segments:
        raw_start = _snap(raw_start, segments, "start")
        raw_end = _snap(raw_end, segments, "end")
    start = max(0.0, raw_start)
    end = min(total_duration, raw_end) if total_duration > 0 else raw_end
    if end <= start or (end - start) < _MIN_CLIP_DURATION:
        return None, None
    return round(start, 3), round(end, 3)


def _snap(seconds, segments, side):
    best, best_dist = seconds, float("inf")
    for seg in segments:
        boundary = seg["start"] if side == "start" else seg["end"]
        d = abs(boundary - seconds)
        if d < best_dist:
            best_dist, best = d, boundary
    return best


def _load_list(inline, path):
    if inline is not None:
        return inline
    if path and Path(path).exists():
        return json.loads(Path(path).read_text())
    return []


def _duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return 0.0
    return float(json.loads(r.stdout).get("format", {}).get("duration", 0))


def _font_file() -> str | None:
    for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc",
              "/Library/Fonts/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return p
    return None


def _run(cmd: list, what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou em {what}:\n{r.stderr[:500]}")
