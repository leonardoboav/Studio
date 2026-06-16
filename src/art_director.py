"""
Diretor de arte — beat do roteiro -> query visual -> asset licenciado -> timeline.

Esqueleto determinístico. A escolha fina de query por beat é tarefa do sub-agente
'diretor-de-arte' (que chama estas funções). Aqui ficam as ferramentas mecânicas.

Saída: timeline.json + assets_manifest.json + longest_thirdparty_block_seconds
(este último é o campo que o gate de longo valida — calculado aqui, em quem mede
a timeline).
"""
import json
from pathlib import Path

from . import media_banks


def build_timeline(script: dict, narration_segments: list[dict], cfg: dict, work_dir: Path) -> dict:
    """
    Para cada beat (segmento de narração com timestamp), define uma query visual,
    busca um asset licenciado e monta timeline.json + assets_manifest.json.

    narration_segments: [{"start": float, "end": float, "text": str}, ...]

    Retorna:
      {
        "timeline_path": ...,
        "assets_manifest_path": ...,
        "longest_thirdparty_block_seconds": float,  # campo p/ o gate
      }
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    timeline = []
    manifest = []

    for seg in narration_segments:
        query = _query_for_beat(seg["text"])           # sub-agente refina a query
        asset = media_banks.search_licensed(query, cfg)  # só fontes licenciadas (ou None)

        if asset is None:
            # Sem asset licenciado -> marca pra revisão, NÃO inventa fonte.
            timeline.append({
                "start": seg["start"], "end": seg["end"], "asset_path": None,
                "query": query, "note": "sem asset licenciado encontrado",
            })
            continue

        timeline.append({
            "start": seg["start"], "end": seg["end"],
            "asset_path": asset["path"], "query": query,
            "source": asset["source"], "license": asset["license"],
        })
        manifest.append({
            "url": asset["url"], "source": asset["source"],
            "license": asset["license"], "query": query,
        })

    longest_block = _longest_thirdparty_block(timeline)

    tl_path = work_dir / "timeline.json"
    man_path = work_dir / "assets_manifest.json"
    tl_path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False))
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    return {
        "timeline_path": str(tl_path),
        "assets_manifest_path": str(man_path),
        "longest_thirdparty_block_seconds": longest_block,
    }


def _longest_thirdparty_block(timeline: list[dict]) -> float:
    """
    Mede o maior segmento contínuo SEM asset próprio licenciado cobrindo a narração.

    Beats sem asset_path (None) são tela "crua" — se o conteúdo de fundo for de
    terceiro, esse é o bloco exposto. O gate de longo rejeita blocos > limite do yaml.
    Beats contíguos sem asset são somados num único bloco.
    """
    longest = 0.0
    running = 0.0
    for beat in timeline:
        if beat.get("asset_path") is None:
            running += (beat["end"] - beat["start"])
            longest = max(longest, running)
        else:
            running = 0.0
    return round(longest, 2)


def _query_for_beat(text: str) -> str:
    """Placeholder. O sub-agente diretor-de-arte gera a query visual de cada beat."""
    return text[:60]
