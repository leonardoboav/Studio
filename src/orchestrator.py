"""
Orchestrator (opcional, via Python) — alternativa ao Claude Code como orquestrador.

No fluxo principal QUEM orquestra é o Claude Code (lendo CLAUDE.md e delegando aos
sub-agentes). Este módulo existe para rodar a cadência por script/cron:

    python -m src.orchestrator plan-week --channel ia

ESCOPO (deliberadamente estreito): plan_week só MONTA a agenda e a ORDEM de cota.
Ele NÃO reimplementa segurança de proveniência. As travas já estão a montante e são
a única fonte da verdade:
  - ingest() levanta erro em third_party (Bloco 2);
  - gate.validate_short barra short signal_only sem roteiro próprio (Bloco 3).
Duplicar essas checagens aqui criaria duas fontes da verdade que divergem com o tempo.
Então plan_week confia nelas: só conta, ordena e — se faltar — reporta e PARA.
"""
import argparse
import json
from pathlib import Path

import yaml

CHANNELS_DIR = Path(__file__).parent.parent / "channels"


def plan_week(channel_slug: str, inputs: dict) -> dict:
    """
    Monta a agenda da semana e a ordem de preenchimento de cota.

    `inputs` descreve o material que EU já tenho disponível (não baixa nada aqui):
      {
        "own_long":     ["longo.mp4"]          # gravação própria longa (extractable)
        "own_takes":    ["take1.mp4", ...]     # takes meus avulsos (extractable)
        "script_themes":["tema validado", ...] # temas p/ roteiro 'script' que EU gravo
      }

    NÃO recebe nem aceita material signal_only para virar short — por design.
    Retorna um plano: agenda ordenada + relatório de déficit (se a cota não fechar).
    """
    cfg = _load_cfg(channel_slug)
    cadence = cfg.get("cadence", {})
    shorts_needed = cadence.get("shorts_per_week", 5)
    longs_needed = cadence.get("longs_per_week", 1)

    own_long = list(inputs.get("own_long", []))
    own_takes = list(inputs.get("own_takes", []))
    script_themes = list(inputs.get("script_themes", []))

    agenda = []

    # ── Longo da semana ──────────────────────────────────────────────────────
    longs_planned = 0
    for src in own_long[:longs_needed]:
        agenda.append({"format": "longo", "strategy": "own_recording", "source": src})
        longs_planned += 1

    # ── Shorts, NA ORDEM de preferência do CLAUDE.md ─────────────────────────
    # 1) fatiar o longo próprio  2) takes avulsos  3) roteiros 'script'
    shorts_planned = 0

    for src in own_long[:longs_needed]:
        if shorts_planned >= shorts_needed:
            break
        agenda.append({"format": "short", "strategy": "slice_own_long", "source": src})
        shorts_planned += 1

    for src in own_takes:
        if shorts_planned >= shorts_needed:
            break
        agenda.append({"format": "short", "strategy": "own_take", "source": src})
        shorts_planned += 1

    for theme in script_themes:
        if shorts_planned >= shorts_needed:
            break
        agenda.append({"format": "short", "strategy": "script", "theme": theme})
        shorts_planned += 1

    # ── Déficit: só reporta e para. NUNCA completa com signal_only. ──────────
    deficit = {}
    short_gap = max(0, shorts_needed - shorts_planned)
    long_gap = max(0, longs_needed - longs_planned)
    if short_gap or long_gap:
        deficit = {
            "shorts_faltando": short_gap,
            "longos_faltando": long_gap,
            "mensagem": (
                f"faltam {short_gap} short(s) e {long_gap} longo(s) — "
                "grave mais takes ou aprove mais roteiros. "
                "NÃO vou completar a cota com corte de terceiro (signal_only)."
            ),
        }

    return {
        "channel": channel_slug,
        "target": {"shorts": shorts_needed, "longs": longs_needed},
        "planned": {"shorts": shorts_planned, "longs": longs_planned},
        "agenda": agenda,
        "deficit": deficit,
    }


def _load_cfg(channel_slug: str) -> dict:
    path = CHANNELS_DIR / f"{channel_slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Channel profile not found: {path}")
    return yaml.safe_load(path.read_text())


def _main() -> None:
    parser = argparse.ArgumentParser(description="Studio — planejador de cadência semanal")
    sub = parser.add_subparsers(dest="command", required=True)
    pw = sub.add_parser("plan-week", help="Monta a agenda da semana")
    pw.add_argument("--channel", required=True)
    pw.add_argument("--inputs-json", default="{}", help="JSON com own_long/own_takes/script_themes")
    args = parser.parse_args()

    if args.command == "plan-week":
        plan = plan_week(args.channel, json.loads(args.inputs_json))
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        if plan["deficit"]:
            print("\n⚠️  " + plan["deficit"]["mensagem"])


if __name__ == "__main__":
    _main()
