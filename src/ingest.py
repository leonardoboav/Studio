import json
import subprocess
from pathlib import Path
from typing import Literal

import yt_dlp

PROVENANCE_VALUES = Literal["own", "licensed", "sou_host", "third_party"]
EXTRACTABLE = {"own", "licensed", "sou_host"}

RAW_DIR = Path(__file__).parent.parent / "output" / "raw"

_FORMAT_OPTIONS = [
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
    "bestvideo+bestaudio/best",
    "best",
]


def nature_of(provenance: str) -> str:
    """
    Derive content nature from provenance. Locks what the pipeline can do.

    third_party -> signal_only (vira pesquisa para roteiro original, nunca conteúdo
    no vídeo). Isto NÃO é sobre formato (short vs longo): é sobre o mecanismo que
    derrubou o RPM Rambo — fala de terceiro como espinha da peça. Ver CONTEXT.md →
    Refinamento factual.
    """
    return "extractable" if provenance in EXTRACTABLE else "signal_only"


def ingest(url: str, provenance: str, channel_slug: str) -> dict:
    """
    Accepts a YouTube URL or a local file path for extractable sources.

    Returns a dict with:
      file_path    — master MP4, publishing quality
      whisper_path — mono 16kHz WAV, transcription only
      provenance   — own | licensed | sou_host | third_party
      nature       — extractable | signal_only (derived, read-only downstream)
      channel_slug, metadata{...}

    For third_party sources use ingest_reference() instead — this function
    raises ValueError if called with provenance='third_party'.
    """
    if provenance not in ("own", "licensed", "sou_host", "third_party"):
        raise ValueError(
            f"Invalid provenance '{provenance}'. Must be: own, licensed, sou_host, third_party."
        )
    # TRAVA 1 (não afrouxar): third_party nunca entra por aqui. ingest() produz um
    # file_path publicável; deixar third_party passar significaria usar fala de terceiro
    # como espinha de uma peça — exatamente o mecanismo (não o formato) que desmonetizou
    # o RPM Rambo. Vale para short E longo: a duração não blinda (ver CONTEXT.md →
    # Refinamento factual). third_party só via ingest_reference() = signal_only = pesquisa
    # para roteiro original. Reabrir este caminho reintroduz a causa da desmonetização.
    if provenance == "third_party":
        raise ValueError(
            "Use ingest_reference() for third_party sources. "
            "ingest() only handles extractable content (own/licensed/sou_host)."
        )

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    local = Path(url)
    if local.exists() and local.is_file():
        return _ingest_local(local, provenance, channel_slug)
    return _ingest_url(url, provenance, channel_slug)


def ingest_reference(url: str, channel_slug: str) -> dict:
    """
    Ingests a third_party source as SIGNAL ONLY.

    Downloads audio for transcription (research), extracts metadata.
    The resulting dict has NO file_path — no video is produced for publishing.
    The transcript from this source is research material; the roteirista
    extracts theme/hook/structure from it and writes an ORIGINAL script.

    Returns a dict with:
      whisper_path  — audio WAV for transcription (research only)
      nature        — always 'signal_only'
      provenance    — always 'third_party'
      signal        — structured signal extracted from metadata
      channel_slug, metadata{...}
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    info = _extract_info_url(url)
    video_id = info.get("id", "unknown")

    audio_path = _download_audio_only(url, video_id)

    signal = {
        "title": info.get("title", ""),
        "channel": info.get("uploader", ""),
        "description": (info.get("description") or "")[:500],
        "duration_sec": info.get("duration", 0),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "tags": (info.get("tags") or [])[:20],
    }

    result = {
        "whisper_path": str(audio_path),
        "provenance": "third_party",
        "nature": "signal_only",
        "channel_slug": channel_slug,
        "signal": signal,
        "metadata": {
            "id": video_id,
            "title": signal["title"],
            "url": url,
            "channel": signal["channel"],
            "duration_sec": signal["duration_sec"],
            "upload_date": info.get("upload_date", ""),
            "description": signal["description"],
            "thumbnail_url": info.get("thumbnail", ""),
        },
    }

    (RAW_DIR / f"{video_id}_reference.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    return result


def ingest_for_cut(url: str, channel_slug: str) -> dict:
    """
    Baixa um vídeo de terceiro como MASTER para o fluxo de CORTE em momentos (shorts
    9:16 a partir de criador BR). Porta separada e explicitamente nomeada — NÃO afrouxa
    a TRAVA 1 de ingest(): este caminho existe por DECISÃO DE OPERADOR (ver CONTEXT.md →
    "Decisão do operador"), com o risco de reused content declarado.

    Diferente de ingest_reference() (que é signal_only, só áudio p/ pesquisa), aqui
    baixamos o vídeo real porque o produto deste fluxo é cortar o trecho. O resultado
    carrega mode='cut' e a exigência de camada autoral fica registrada nos sidecars
    dos momentos (src/moments.py), não aqui.

    Returns dict compatível com transcribe(): file_path, whisper_path, metadata{...},
    provenance='third_party', mode='cut'.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    info = _extract_info_url(url)
    video_id = info.get("id", "unknown")
    raw_path = _download(url, video_id)
    master, whisper = _normalize(raw_path, video_id, delete_src=True)

    result = {
        "file_path": str(master),
        "whisper_path": str(whisper),
        "provenance": "third_party",
        "nature": "extractable",  # mecanicamente cortável; o risco vive nos sidecars
        "mode": "cut",
        "channel_slug": channel_slug,
        "metadata": {
            "id": video_id,
            "title": info.get("title", video_id),
            "url": url,
            "channel": info.get("uploader", ""),
            "duration_sec": info.get("duration", 0),
            "upload_date": info.get("upload_date", ""),
            "description": (info.get("description") or "")[:500],
            "thumbnail_url": info.get("thumbnail", ""),
        },
    }
    (RAW_DIR / f"{video_id}_cut_source.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    return result


# ── internal helpers ──────────────────────────────────────────────────────────

def _ingest_url(url: str, provenance: str, channel_slug: str) -> dict:
    info = _extract_info_url(url)
    video_id = info.get("id", "unknown")
    raw_path = _download(url, video_id)
    master, whisper = _normalize(raw_path, video_id, delete_src=True)
    return _build_result(
        video_id=video_id,
        master=master,
        whisper=whisper,
        provenance=provenance,
        channel_slug=channel_slug,
        metadata={
            "id": video_id,
            "title": info.get("title", video_id),
            "url": url,
            "channel": info.get("uploader", ""),
            "duration_sec": info.get("duration", 0),
            "upload_date": info.get("upload_date", ""),
            "description": info.get("description", ""),
            "thumbnail_url": info.get("thumbnail", ""),
        },
    )


def _ingest_local(src: Path, provenance: str, channel_slug: str) -> dict:
    video_id = src.stem
    master, whisper = _normalize(src, video_id, delete_src=False)
    return _build_result(
        video_id=video_id,
        master=master,
        whisper=whisper,
        provenance=provenance,
        channel_slug=channel_slug,
        metadata={
            "id": video_id,
            "title": src.stem,
            "url": str(src),
            "channel": "",
            "duration_sec": _get_duration(master),
            "upload_date": "",
            "description": "",
            "thumbnail_url": "",
        },
    )


def _build_result(video_id, master, whisper, provenance, channel_slug, metadata) -> dict:
    result = {
        "file_path": str(master),
        "whisper_path": str(whisper),
        "provenance": provenance,
        "nature": nature_of(provenance),
        "channel_slug": channel_slug,
        "metadata": metadata,
    }
    (RAW_DIR / f"{video_id}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def _extract_info_url(url: str) -> dict:
    opts = {"quiet": True, "skip_download": True, "http_headers": {"User-Agent": "Mozilla/5.0"}}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _download(url: str, video_id: str) -> Path:
    out_template = str(RAW_DIR / f"{video_id}_raw.%(ext)s")
    base_opts = {
        "outtmpl": out_template,
        "concurrent_fragment_downloads": 1,
        "skip_unavailable_fragments": True,
        "http_headers": {"User-Agent": "Mozilla/5.0"},
        "quiet": False,
    }

    for fmt in _FORMAT_OPTIONS:
        try:
            with yt_dlp.YoutubeDL({**base_opts, "format": fmt}) as ydl:
                ydl.download([url])
            break
        except Exception:
            continue
    else:
        for fmt in _FORMAT_OPTIONS:
            try:
                with yt_dlp.YoutubeDL({**base_opts, "format": fmt, "nocheckcertificate": True}) as ydl:
                    ydl.download([url])
                break
            except Exception:
                continue
        else:
            raise RuntimeError(f"Failed to download: {url}")

    candidates = list(RAW_DIR.glob(f"{video_id}_raw.*"))
    if not candidates:
        raise RuntimeError(f"Downloaded file not found for video_id={video_id}")
    return candidates[0]


def _download_audio_only(url: str, video_id: str) -> Path:
    """Download audio only for signal_only references (research, not for publishing)."""
    out_path = RAW_DIR / f"{video_id}_ref.wav"
    if out_path.exists():
        return out_path

    opts = {
        "outtmpl": str(RAW_DIR / f"{video_id}_ref.%(ext)s"),
        "format": "bestaudio/best",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        "postprocessor_args": ["-ac", "1", "-ar", "16000"],
        "http_headers": {"User-Agent": "Mozilla/5.0"},
        "quiet": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception:
        opts["nocheckcertificate"] = True
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    candidates = list(RAW_DIR.glob(f"{video_id}_ref.*"))
    if not candidates:
        raise RuntimeError(f"Audio download failed for reference video_id={video_id}")
    return candidates[0]


def _normalize(src: Path, video_id: str, delete_src: bool = True) -> tuple[Path, Path]:
    """
    Produces two files:
    - master: 1080p H.264 + AAC 192k stereo  →  publishing
    - whisper: mono 16kHz WAV                 →  transcription only
    """
    master = RAW_DIR / f"{video_id}.mp4"
    whisper = RAW_DIR / f"{video_id}_whisper.wav"

    if not master.exists():
        r = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(src),
                "-vf", "scale=-2:1080",
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                str(master),
            ],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"FFmpeg master encode failed:\n{r.stderr}")
        if delete_src:
            src.unlink(missing_ok=True)

    if not whisper.exists():
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(master), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(whisper)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"FFmpeg whisper audio extraction failed:\n{r.stderr}")

    return master, whisper


def _get_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return 0.0
    return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
