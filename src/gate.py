"""
Gate — valida valor original antes de qualquer peça sair.

Ciente de PROVENIÊNCIA (own/licensed/sou_host = extractable vs third_party =
signal_only) e de FORMATO (short vs longo). Limiares vêm de channels/<slug>.yaml.

Filosofia: edição decorativa NÃO é transformação. O longo, sem demo, depende
inteiramente da substância autoral do roteiro.

Quem popula os campos que o gate valida (não é o gate que calcula):
  - original_speech_fraction        → roteirista (src/brain.py)
  - longest_thirdparty_block_seconds → diretor-de-arte (src/art_director.py)
  - only_decorative_edits           → montador (src/hands.py)
O gate REJEITA se um campo obrigatório vier ausente — nunca aprova por falta de dado.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml

CHANNELS_DIR = Path(__file__).parent.parent / "channels"

_MISSING = object()  # sentinela: distingue "ausente" de "zero"


@dataclass
class GateResult:
    approved: bool
    reason: str


def load_gate_cfg(channel_slug: str) -> dict:
    profile_path = CHANNELS_DIR / f"{channel_slug}.yaml"
    if not profile_path.exists():
        raise FileNotFoundError(f"Channel profile not found: {profile_path}")
    return yaml.safe_load(profile_path.read_text())


def validate_short(cut: dict, nature: str, cfg: dict) -> GateResult:
    g = cfg["gate"]

    if "start_sec" not in cut or "end_sec" not in cut:
        return GateResult(False, "short sem timestamps (start_sec/end_sec) — campo obrigatório ausente")
    dur = cut["end_sec"] - cut["start_sec"]

    if nature == "signal_only":
        # Short NUNCA pode ser corte de fonte de terceiro (CLAUDE.md, regra 4).
        # Um short signal_only só existe como roteiro 'script' que EU gravo.
        if not (cut.get("narration_script") or "").strip():
            return GateResult(False, "short signal_only sem roteiro próprio gravado — não pode ser corte de terceiro")

    if not (cut.get("hook") or "").strip():
        return GateResult(False, "hook vazio")

    if not (g["short_min_seconds"] <= dur <= g["short_max_seconds"]):
        return GateResult(False, f"duração {dur:.0f}s fora de [{g['short_min_seconds']}, {g['short_max_seconds']}]s")

    return GateResult(True, "ok")


def validate_long(piece: dict, nature: str, cfg: dict) -> GateResult:
    g = cfg["gate"]

    # 1. Opinião/tese própria obrigatória e não-genérica.
    if g.get("require_opinion_field", True):
        op = (piece.get("opiniao") or "").strip()
        if len(op.split()) < 12:
            return GateResult(False, "[MINHA OPINIÃO] ausente ou genérica (< 12 palavras)")

    # 2. Edição decorativa não substitui transformação.
    #    Campo obrigatório — se o montador não preencheu, rejeita (não assume False).
    if g.get("reject_decorative_only", True):
        decorative = piece.get("only_decorative_edits", _MISSING)
        if decorative is _MISSING:
            return GateResult(False, "campo only_decorative_edits ausente — montador não avaliou a peça")
        if decorative:
            return GateResult(False, "peça é fonte de terceiro com edição só decorativa (marca d'água/GIF/CTA)")

    if nature == "signal_only":
        # 3. Substância autoral majoritária — campo obrigatório.
        frac = piece.get("original_speech_fraction", _MISSING)
        if frac is _MISSING:
            return GateResult(False, "campo original_speech_fraction ausente — roteirista não mediu a peça")
        if frac < g["long_min_original_speech_fraction"]:
            return GateResult(
                False,
                f"fala original {frac:.0%} < mínimo {g['long_min_original_speech_fraction']:.0%}; "
                "precisa de mais análise/opinião conduzindo",
            )

        # 4. Nenhum bloco contínuo de terceiro acima do limite — campo obrigatório.
        longest = piece.get("longest_thirdparty_block_seconds", _MISSING)
        if longest is _MISSING:
            return GateResult(False, "campo longest_thirdparty_block_seconds ausente — diretor-de-arte não mediu a timeline")
        if longest > g["long_max_thirdparty_block_seconds"]:
            return GateResult(False, f"bloco de terceiro de {longest}s > {g['long_max_thirdparty_block_seconds']}s sem intervenção")

    return GateResult(True, "ok")


def validate_assets(assets_manifest: list[dict]) -> GateResult:
    """Toda mídia precisa de licença comercial registrada (CLAUDE.md, regra 5)."""
    for a in assets_manifest:
        if not a.get("license"):
            return GateResult(False, f"asset sem licença: {a.get('query') or a.get('url')}")
        if a.get("source") in ("web_generic", "thirdparty_screenshot"):
            return GateResult(False, f"asset de fonte não licenciada: {a.get('source')}")
    return GateResult(True, "ok")


def validate_piece(piece: dict, fmt: str, nature: str, cfg: dict) -> GateResult:
    """
    Dispatcher único. fmt: 'short' | 'longo'. Valida a peça e, se houver
    assets_manifest, valida licenças também. Uma peça só passa se TUDO passar.
    """
    if fmt == "short":
        result = validate_short(piece, nature, cfg)
    elif fmt == "longo":
        result = validate_long(piece, nature, cfg)
    else:
        return GateResult(False, f"formato desconhecido: {fmt}")

    if not result.approved:
        return result

    manifest = piece.get("assets_manifest")
    if manifest:
        asset_result = validate_assets(manifest)
        if not asset_result.approved:
            return asset_result

    return GateResult(True, "ok")
