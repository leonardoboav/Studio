"""
Suite adversarial do gate (src/gate.py).

Filosofia: o gate é a ÚLTIMA linha de defesa contra o mecanismo que desmonetizou o
RPM Rambo (fala de terceiro como espinha + edição só decorativa — ver CONTEXT.md).
Estes testes provam que ele REJEITA todo caso proibido e que NÃO aprova por falta de
dado. Cada teste mapeia para uma regra inegociável do CLAUDE.md.

São testes puros: sem rede, sem API, sem mídia. Rodam com a config real de channels/ia.yaml.

    .venv/bin/pytest tests/test_gate.py -v
"""
import sys
from pathlib import Path

import pytest

# Permite `import src.gate` rodando da raiz do projeto.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.gate import (  # noqa: E402
    load_gate_cfg,
    validate_short,
    validate_long,
    validate_assets,
    validate_piece,
)


@pytest.fixture(scope="module")
def cfg():
    """Config real do canal de IA — os limiares vêm daqui, não hardcoded no teste."""
    return load_gate_cfg("ia")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers: peças "boas" mínimas que DEVEM passar. Cada teste de rejeição parte de
# uma dessas e quebra exatamente um campo, isolando a causa da reprovação.
# ──────────────────────────────────────────────────────────────────────────────
def good_short(**over):
    cut = {
        "start_sec": 0,
        "end_sec": 30,          # 30s ∈ [15, 60]
        "hook": "olha o que isso faz na prática",
        "narration_script": "roteiro meu que eu gravo",
    }
    cut.update(over)
    return cut


def good_long(**over):
    piece = {
        "opiniao": "na minha visão o hype de agentes ignora o custo real de manutenção em produção",
        "only_decorative_edits": False,
        "original_speech_fraction": 0.65,
        "longest_thirdparty_block_seconds": 20,
    }
    piece.update(over)
    return piece


# ──────────────────────────────────────────────────────────────────────────────
# REGRA 4 — Nenhum short pode ser corte de fonte signal_only.
# ──────────────────────────────────────────────────────────────────────────────
class TestShortSignalOnly:
    def test_signal_only_sem_roteiro_proprio_REJEITA(self, cfg):
        # Corte de terceiro virando short = o reused content que derrubou o RPM Rambo.
        cut = good_short(narration_script="")
        r = validate_short(cut, "signal_only", cfg)
        assert not r.approved
        assert "terceiro" in r.reason or "roteiro próprio" in r.reason

    def test_signal_only_so_espaco_no_roteiro_REJEITA(self, cfg):
        cut = good_short(narration_script="   ")
        assert not validate_short(cut, "signal_only", cfg).approved

    def test_signal_only_COM_roteiro_proprio_passa(self, cfg):
        # Short script que EU gravo é a única forma legítima de signal_only virar short.
        cut = good_short(narration_script="meu roteiro original gravado por mim")
        assert validate_short(cut, "signal_only", cfg).approved


# ──────────────────────────────────────────────────────────────────────────────
# Short — campos obrigatórios e janela de duração (channels/ia.yaml).
# ──────────────────────────────────────────────────────────────────────────────
class TestShortBasico:
    def test_sem_timestamps_REJEITA(self, cfg):
        cut = good_short()
        del cut["end_sec"]
        r = validate_short(cut, "extractable", cfg)
        assert not r.approved
        assert "timestamp" in r.reason

    def test_hook_vazio_REJEITA(self, cfg):
        assert not validate_short(good_short(hook=""), "extractable", cfg).approved

    def test_curto_demais_REJEITA(self, cfg):
        # 10s < short_min_seconds (15)
        assert not validate_short(good_short(start_sec=0, end_sec=10), "extractable", cfg).approved

    def test_longo_demais_REJEITA(self, cfg):
        # 90s > short_max_seconds (60)
        assert not validate_short(good_short(start_sec=0, end_sec=90), "extractable", cfg).approved

    def test_nos_limites_passa(self, cfg):
        lo = cfg["gate"]["short_min_seconds"]
        hi = cfg["gate"]["short_max_seconds"]
        assert validate_short(good_short(start_sec=0, end_sec=lo), "extractable", cfg).approved
        assert validate_short(good_short(start_sec=0, end_sec=hi), "extractable", cfg).approved

    def test_extractable_valido_passa(self, cfg):
        assert validate_short(good_short(), "extractable", cfg).approved


# ──────────────────────────────────────────────────────────────────────────────
# REGRA 2/3 — Longo: opinião própria e edição decorativa não é transformação.
# ──────────────────────────────────────────────────────────────────────────────
class TestLongOpiniaoEDecorativo:
    def test_opiniao_ausente_REJEITA(self, cfg):
        assert not validate_long(good_long(opiniao=""), "signal_only", cfg).approved

    def test_opiniao_generica_curta_REJEITA(self, cfg):
        # < 12 palavras = genérica.
        assert not validate_long(good_long(opiniao="acho legal e interessante"), "signal_only", cfg).approved

    def test_so_edicao_decorativa_REJEITA(self, cfg):
        r = validate_long(good_long(only_decorative_edits=True), "signal_only", cfg)
        assert not r.approved
        assert "decorativa" in r.reason

    def test_campo_decorativo_AUSENTE_REJEITA(self, cfg):
        # Ausente != False: montador não avaliou → rejeita, nunca assume seguro.
        piece = good_long()
        del piece["only_decorative_edits"]
        r = validate_long(piece, "signal_only", cfg)
        assert not r.approved
        assert "only_decorative_edits" in r.reason


# ──────────────────────────────────────────────────────────────────────────────
# REGRA 2 — Longo signal_only: substância autoral majoritária e sem bloco gigante.
# ──────────────────────────────────────────────────────────────────────────────
class TestLongSignalOnly:
    def test_fracao_original_baixa_REJEITA(self, cfg):
        # 0.30 < long_min_original_speech_fraction (0.40).
        assert not validate_long(good_long(original_speech_fraction=0.30), "signal_only", cfg).approved

    def test_fracao_AUSENTE_REJEITA(self, cfg):
        piece = good_long()
        del piece["original_speech_fraction"]
        r = validate_long(piece, "signal_only", cfg)
        assert not r.approved
        assert "original_speech_fraction" in r.reason

    def test_bloco_terceiro_grande_REJEITA(self, cfg):
        # 60s > long_max_thirdparty_block_seconds (45).
        assert not validate_long(good_long(longest_thirdparty_block_seconds=60), "signal_only", cfg).approved

    def test_bloco_terceiro_AUSENTE_REJEITA(self, cfg):
        piece = good_long()
        del piece["longest_thirdparty_block_seconds"]
        r = validate_long(piece, "signal_only", cfg)
        assert not r.approved
        assert "longest_thirdparty_block_seconds" in r.reason

    def test_signal_only_no_limiar_passa(self, cfg):
        frac = cfg["gate"]["long_min_original_speech_fraction"]
        blk = cfg["gate"]["long_max_thirdparty_block_seconds"]
        piece = good_long(original_speech_fraction=frac, longest_thirdparty_block_seconds=blk)
        assert validate_long(piece, "signal_only", cfg).approved


# ──────────────────────────────────────────────────────────────────────────────
# REGRA 5 — Toda mídia precisa de licença comercial registrada.
# ──────────────────────────────────────────────────────────────────────────────
class TestAssets:
    def test_asset_sem_licenca_REJEITA(self, cfg):
        manifest = [{"query": "cidade noite", "source": "pexels", "license": ""}]
        assert not validate_assets(manifest).approved

    def test_asset_fonte_web_generica_REJEITA(self, cfg):
        manifest = [{"query": "qualquer img", "source": "web_generic", "license": "CC0"}]
        assert not validate_assets(manifest).approved

    def test_asset_screenshot_terceiro_REJEITA(self, cfg):
        manifest = [{"url": "x", "source": "thirdparty_screenshot", "license": "CC0"}]
        assert not validate_assets(manifest).approved

    def test_assets_licenciados_passam(self, cfg):
        manifest = [
            {"query": "data center", "source": "pexels", "license": "Pexels License"},
            {"query": "code", "source": "unsplash", "license": "Unsplash License"},
        ]
        assert validate_assets(manifest).approved


# ──────────────────────────────────────────────────────────────────────────────
# Dispatcher — validate_piece combina peça + assets; só passa se TUDO passar.
# ──────────────────────────────────────────────────────────────────────────────
class TestDispatcher:
    def test_formato_desconhecido_REJEITA(self, cfg):
        assert not validate_piece(good_short(), "carrossel", "extractable", cfg).approved

    def test_long_valido_mas_asset_sem_licenca_REJEITA(self, cfg):
        piece = good_long(assets_manifest=[{"query": "x", "source": "pexels", "license": ""}])
        assert not validate_piece(piece, "longo", "signal_only", cfg).approved

    def test_long_valido_com_assets_licenciados_passa(self, cfg):
        piece = good_long(assets_manifest=[{"query": "x", "source": "pexels", "license": "Pexels License"}])
        assert validate_piece(piece, "longo", "signal_only", cfg).approved

    def test_short_extractable_sem_assets_passa(self, cfg):
        assert validate_piece(good_short(), "short", "extractable", cfg).approved
