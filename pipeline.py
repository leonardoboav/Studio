#!/usr/bin/env python3
"""
Studio — pipeline CLI (run manual rápido do caminho EXTRACTABLE).

Uso:
    python pipeline.py --file /caminho/gravacao.mp4 --provenance own --channel ia
    python pipeline.py --url <youtube_url> --provenance licensed --channel ia
    python pipeline.py --dry-run            # prova que o gate REPROVA e não escreve em ready/

Para fontes third_party (signal_only) o caminho é outro: ingest_reference +
roteirista (sub-agente), não este CLI. ingest() levanta erro em third_party.

GATE: nenhuma peça chega a output/ready/ sem passar por gate.validate_piece —
a MESMA função do módulo gate (fonte única). Se reprovar, para e imprime o motivo.
"""
import argparse
import os
import sys
from pathlib import Path

from src.gate import load_gate_cfg, validate_piece   # fonte única do gate
from src.hands import cut_clips
from src.publish import package, week_dir, write_week_manifest


def _load_dotenv() -> None:
    """
    Carrega .env (na raiz do projeto) para os.environ, sem dependência externa.
    Não sobrescreve variáveis já definidas no ambiente. A chave fica só no disco
    (o .env está no .gitignore) — nunca no código nem no histórico.
    """
    env_path = Path(__file__).parent / ".env"
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


def gate_and_publish(result: dict, fmt: str) -> list[dict]:
    """
    Estágio compartilhado: roda gate.validate_piece em cada peça, corta SÓ as
    aprovadas e empacota. Se nenhuma passar, NÃO escreve nada em ready/.

    Esta é a única porta para output/ready/. Não há caminho que pule o gate.
    """
    cfg = load_gate_cfg(result["channel_slug"])
    nature = result["nature"]

    approved, rejected = [], []
    for piece in result["cuts"]:
        verdict = validate_piece(piece, fmt, nature, cfg)
        (approved if verdict.approved else rejected).append((piece, verdict))

    for piece, verdict in rejected:
        print(f"[gate] REPROVADO (peça {piece.get('rank', '?')}): {verdict.reason}")

    if not approved:
        print("\n✗ Nenhuma peça passou no gate. NADA escrito em output/ready/.")
        return []

    print(f"[gate] {len(approved)} de {len(result['cuts'])} peça(s) aprovada(s).")

    # Só as aprovadas seguem para o corte e o empacotamento.
    result["cuts"] = [piece for piece, _ in approved]
    result = cut_clips(result)

    dest = week_dir()
    bundles = package(result, dest)
    write_week_manifest(dest, bundles)
    return bundles


def run(source: str, provenance: str, channel: str, fmt: str = "short",
        whisper_model: str = "large-v3") -> None:
    # Imports tardios: ingest/transcribe/brain puxam yt_dlp, whisper, anthropic.
    from src.ingest import ingest
    from src.transcribe import transcribe
    from src.brain import run_brain

    print(f"\n[pipeline] Iniciando — channel={channel}  provenance={provenance}  fmt={fmt}")

    print("\n[1/5] Ingest...")
    result = ingest(url=source, provenance=provenance, channel_slug=channel)

    print(f"\n[2/5] Transcribe (whisper={whisper_model})...")
    result = transcribe(result, model_size=whisper_model)

    print("\n[3/5] Brain (Claude — seleção + roteiros)...")
    result = run_brain(result)

    print("\n[4/5] Gate + corte + empacotamento...")
    bundles = gate_and_publish(result, fmt)

    if not bundles:
        sys.exit(1)

    print(f"\n✓ Pronto. {len(bundles)} peça(s) para revisão. Grave sua narração e publique manualmente.\n")


def dry_run() -> None:
    """
    Teste de ponta a ponta DE MENTIRA: alimenta o gate real com peças que DEVEM
    reprovar e mostra que o pipeline para sem escrever em ready/.
    Não baixa, não transcreve, não chama API, não roda FFmpeg.
    """
    print("=== DRY-RUN: provando que o gate REPROVA ===\n")

    # Caso A: longo signal_only com fala original abaixo do mínimo (0.25 < 0.40).
    caso_a = {
        "channel_slug": "ia",
        "nature": "signal_only",
        "provenance": "third_party",
        "metadata": {"id": "dryrun_A"},
        "cuts": [{
            "rank": 1,
            "opiniao": "acho que essa ferramenta tem um trade-off interessante de custo e latência aqui",
            "only_decorative_edits": False,
            "original_speech_fraction": 0.25,            # < 0.40 → deve reprovar
            "longest_thirdparty_block_seconds": 10,
            "hook": "olha isso",
        }],
    }

    # Caso B: longo signal_only com campo do gate AUSENTE (montador não avaliou).
    caso_b = {
        "channel_slug": "ia",
        "nature": "signal_only",
        "provenance": "third_party",
        "metadata": {"id": "dryrun_B"},
        "cuts": [{
            "rank": 1,
            "opiniao": "minha leitura é que o ganho real está na orquestração, não no modelo em si",
            # only_decorative_edits AUSENTE de propósito → _MISSING → deve reprovar
            "original_speech_fraction": 0.80,
            "longest_thirdparty_block_seconds": 10,
            "hook": "preste atenção nisto",
        }],
    }

    ready_before = sorted(p.name for p in (week_dir().parent).rglob("*.json"))

    out = []
    for nome, caso in [("A — fração original 0.25 < 0.40", caso_a),
                       ("B — campo only_decorative_edits ausente", caso_b)]:
        print(f"\n--- Caso {nome} ---")
        bundles = gate_and_publish(caso, fmt="longo")
        out.extend(bundles)

    ready_after = sorted(p.name for p in (week_dir().parent).rglob("*.json"))
    novos = [f for f in ready_after if f not in ready_before and f != "week_manifest.json"]

    print("\n=== RESULTADO ===")
    print(f"Peças aprovadas: {len(out)} (esperado: 0)")
    print(f"Novos bundles em ready/: {novos or 'nenhum'} (esperado: nenhum)")
    if out or novos:
        print("✗ FALHA: algo passou que não deveria.")
        sys.exit(1)
    print("✓ OK: o gate reprovou ambos e nada foi escrito em output/ready/.")


def dry_run_approve() -> None:
    """
    Teste de APROVAÇÃO: uma peça válida (todos os campos do gate preenchidos,
    original_speech_fraction >= 0.40, licença ok) passa ponta a ponta pelo MESMO
    gate_and_publish e gera bundle + week_manifest.json. Usa um vídeo de teste real
    para o FFmpeg cortar (sem download, sem API, sem Whisper).
    """
    import json
    import subprocess
    from pathlib import Path

    print("=== DRY-RUN APPROVE: provando que o gate APROVA o bom ===\n")

    raw_dir = Path(__file__).parent / "output" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    test_video = raw_dir / "dryrun_ok.mp4"

    if not test_video.exists():
        print("[setup] Gerando vídeo de teste (20s) com FFmpeg...")
        subprocess.run(
            ["ffmpeg", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=20:size=1280x720:rate=30",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
             "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", "-shortest",
             str(test_video)],
            capture_output=True, text=True, check=True,
        )

    result = {
        "channel_slug": "ia",
        "nature": "signal_only",
        "provenance": "third_party",
        "file_path": str(test_video),
        "metadata": {"id": "dryrun_ok", "duration_sec": 20},
        "transcript": {"segments": [{"start": 0.0, "end": 15.0, "text": "narração própria"}]},
        "cuts": [{
            "rank": 1,
            "start_sec": 0.0,
            "end_sec": 15.0,
            "hook": "a verdade que ninguém testou sobre essa ferramenta",
            "narration_script": "roteiro original que eu mesmo gravo por cima, com minha análise",
            "opiniao": "minha leitura é que o ganho real está na orquestração e não no modelo, porque o gargalo é contexto",
            "only_decorative_edits": False,
            "original_speech_fraction": 0.62,
            "longest_thirdparty_block_seconds": 12,
            "title": "Testei e a real é outra",
            "description": "minha análise sem hype",
            "hashtags": ["#ia", "#tech"],
            "thumbnail_brief": {"concept": "rosto + palavra-âncora", "variations": ["A", "B"]},
            "viral_pattern": "contra_hype",
            "assets_manifest": [
                {"url": "https://pexels.com/x", "source": "pexels",
                 "license": "pexels_free_commercial", "query": "data center"},
                {"url": "https://pixabay.com/m", "source": "pixabay_music",
                 "license": "pixabay_content_license", "query": "ambient tech"},
            ],
        }],
    }

    bundles = gate_and_publish(result, fmt="longo")

    dest = week_dir()
    print("\n=== RESULTADO ===")
    print(f"Peças aprovadas: {len(bundles)} (esperado: 1)")
    print(f"\nArquivos em {dest}:")
    for p in sorted(dest.iterdir()):
        print(f"  {p.name}")

    manifest_path = dest / "week_manifest.json"
    print("\n=== week_manifest.json ===")
    print(manifest_path.read_text())

    if len(bundles) != 1 or not manifest_path.exists():
        print("✗ FALHA: peça válida não gerou bundle/manifest.")
        sys.exit(1)
    print("✓ OK: peça válida aprovada, bundle + week_manifest.json escritos.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Studio — pipeline (caminho extractable)")
    parser.add_argument("--dry-run", action="store_true", help="Prova que o gate reprova e não escreve em ready/")
    parser.add_argument("--dry-run-approve", action="store_true", dest="dry_run_approve",
                        help="Prova que o gate aprova peça válida e gera bundle + week_manifest")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--url", help="URL do YouTube (licensed/sou_host)")
    g.add_argument("--file", help="Arquivo local (own)")
    parser.add_argument("--provenance", choices=["own", "licensed", "sou_host"],
                        help="Proveniência extractable (third_party usa ingest_reference, não este CLI)")
    parser.add_argument("--channel", help="Slug do canal (channels/<slug>.yaml)")
    parser.add_argument("--format", default="short", choices=["short", "longo"], dest="fmt")
    parser.add_argument("--whisper-model", default="large-v3", dest="whisper_model",
                        help="Modelo do Whisper (use 'small' para 1º teste rápido; 'large-v3' p/ produção)")
    args = parser.parse_args()

    _load_dotenv()  # carrega .env antes de qualquer chamada que use a API

    if args.dry_run:
        dry_run()
        return

    if args.dry_run_approve:
        dry_run_approve()
        return

    source = args.url or args.file
    if not source or not args.provenance or not args.channel:
        parser.error("forneça --url/--file, --provenance e --channel (ou use --dry-run)")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("ANTHROPIC_API_KEY ausente — coloque no arquivo .env (ver .env.example)")
    run(source=source, provenance=args.provenance, channel=args.channel,
        fmt=args.fmt, whisper_model=args.whisper_model)


if __name__ == "__main__":
    main()
