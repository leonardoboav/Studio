import json
from datetime import date
from pathlib import Path

READY_DIR = Path(__file__).parent.parent / "output" / "ready"


def week_dir(week_date: str | None = None) -> Path:
    """Diretório da semana: output/ready/week_<YYYY-MM-DD>/."""
    tag = week_date or date.today().isoformat()
    d = READY_DIR / f"week_{tag}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def package(gated_result: dict, dest: Path | None = None) -> list[dict]:
    """
    Empacota cada peça APROVADA pelo gate num bundle para revisão humana.

    Recebe um resultado que já passou pelo gate (pipeline/orchestrator garantem
    isso a montante — publish não revalida proveniência). Escreve um JSON por peça.
    NÃO publica nem agenda — revisão humana é obrigatória.
    """
    dest = dest or week_dir()

    video_id = gated_result["metadata"]["id"]
    channel_slug = gated_result["channel_slug"]
    provenance = gated_result["provenance"]
    bundles = []

    for cut in gated_result["cuts"]:
        rank = cut["rank"]
        clip_path = cut.get("clip_path")
        if not clip_path:
            print(f"[publish] Pulando corte {rank} — sem arquivo de clipe.")
            continue

        bundle = {
            "channel_slug": channel_slug,
            "source_video_id": video_id,
            "cut_rank": rank,
            "clip_path": clip_path,
            "provenance": provenance,
            "nature": gated_result.get("nature", ""),
            "publish": {
                "title": cut["title"],
                "description": cut["description"],
                "hashtags": cut["hashtags"],
                "thumbnail_brief": cut["thumbnail_brief"],
            },
            "narration_script": cut.get("narration_script", ""),
            "hook": cut["hook"],
            "score": cut.get("score"),
            "viral_pattern": cut.get("viral_pattern", ""),
            "assets_manifest": cut.get("assets_manifest", []),
            "status": "awaiting_review",
        }

        out_path = dest / f"{video_id}_cut{rank:02d}.json"
        out_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
        bundles.append(bundle)

    print(f"[publish] {len(bundles)} peça(s) prontas para revisão em {dest}")
    return bundles


def write_week_manifest(dest: Path, bundles: list[dict], deficit: dict | None = None) -> Path:
    """
    Escreve week_manifest.json com proveniência + licença de cada peça da semana.
    Inclui o relatório de déficit, se a cota não fechou.
    """
    pieces = []
    for b in bundles:
        pieces.append({
            "clip_path": b["clip_path"],
            "title": b["publish"]["title"],
            "provenance": b["provenance"],
            "nature": b.get("nature", ""),
            "licenses": [a.get("license") for a in b.get("assets_manifest", [])],
            "status": b["status"],
        })

    manifest = {
        "week": dest.name,
        "total_pieces": len(pieces),
        "pieces": pieces,
        "deficit": deficit or {},
    }

    man_path = dest / "week_manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[publish] week_manifest.json escrito em {man_path}")
    return man_path
