import json
from pathlib import Path

from faster_whisper import WhisperModel

TRANSCRIPTS_DIR = Path(__file__).parent.parent / "output" / "raw"

_MODEL: WhisperModel | None = None


def transcribe(ingest_result: dict, model_size: str = "large-v3") -> dict:
    """
    Transcribe with word-level timestamps using the dedicated whisper audio file
    (mono 16kHz WAV), not the master video — so publishing quality is never degraded.
    """
    video_id = ingest_result["metadata"]["id"]

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    cache_path = TRANSCRIPTS_DIR / f"{video_id}_transcript.json"
    if cache_path.exists():
        transcript = json.loads(cache_path.read_text())
        return {**ingest_result, "transcript": transcript}

    audio_path = ingest_result.get("whisper_path") or ingest_result["file_path"]

    model = _get_model(model_size)
    segments_raw, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        language="pt",
        vad_filter=True,
    )

    segments = []
    for seg in segments_raw:
        words = [
            {"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)}
            for w in (seg.words or [])
        ]
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": words,
        })

    transcript = {
        "language": info.language,
        "duration_sec": round(info.duration, 2),
        "segments": segments,
    }

    cache_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
    return {**ingest_result, "transcript": transcript}


def _get_model(model_size: str) -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = WhisperModel(model_size, device="auto", compute_type="auto")
    return _MODEL
