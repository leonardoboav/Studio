"""
Testes do contrato de seleção de momentos (src/moments_contract.py).

Duas camadas:
  1. ADVERSARIAL (sintético, sem API): provam que o validador pega cada classe de
     violação que o LLM pode cometer e aprova a seleção limpa.
  2. REGRESSÃO sobre a saída REAL cacheada (output/clips/..._moments.json + a
     transcrição): a única seleção de momentos que o agente já produziu. Documenta
     que o validador captura o defeito real que escapou (momento de 62s rejeitado
     tarde no ffmpeg) e que os momentos que VIRARAM mp4 cumprem o contrato.

A camada de JULGAMENTO (escolheu os trechos editorialmente certos?) é eval com LLM,
fora daqui — ver tests/eval_moments.py.

    .venv/bin/pytest tests/test_moments_contract.py -v
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.moments_contract import (  # noqa: E402
    validate_moment_selection,
    errors,
    is_shippable,
    ERROR,
    WARNING,
)

# Transcrição-fixture mínima: 3 segmentos com fronteiras nítidas em 0/40, 40/95, 95/130.
SEGMENTS = [
    {"start": 0.0, "end": 40.0, "text": "a"},
    {"start": 40.0, "end": 95.0, "text": "b"},
    {"start": 95.0, "end": 130.0, "text": "c"},
]
TOTAL = 130.0


def cut(**over):
    c = {"rank": 1, "assunto": "assunto único", "assunto_slug": "assunto",
         "start_sec": 0.0, "end_sec": 40.0}
    c.update(over)
    return c


def fields(violations):
    return {x.field for x in violations}


# ── 1. ADVERSARIAL ────────────────────────────────────────────────────────────
class TestContratoSintetico:
    def test_selecao_limpa_passa(self):
        cuts = [cut(rank=1, start_sec=0.0, end_sec=40.0),
                cut(rank=2, start_sec=40.0, end_sec=95.0)]
        v = validate_moment_selection(cuts, SEGMENTS, TOTAL)
        assert v == []
        assert is_shippable(v)

    def test_momento_longo_demais_ERROR(self):
        # 0–95 = 95s > 60s. Esta é a falha que hoje só o ffmpeg pega (tarde).
        v = validate_moment_selection([cut(end_sec=95.0)], SEGMENTS, TOTAL)
        assert "duracao" in fields(errors(v))
        assert not is_shippable(v)

    def test_momento_curto_demais_ERROR(self):
        # precisa de fronteiras em 0 e 20 p/ isolar duração; uso tol implícito alto.
        v = validate_moment_selection(
            [cut(end_sec=20.0)], [{"start": 0.0, "end": 20.0}], 130.0)
        assert "duracao" in fields(errors(v))

    def test_fora_da_janela_ERROR(self):
        v = validate_moment_selection([cut(start_sec=120.0, end_sec=160.0)], SEGMENTS, TOTAL)
        assert "janela" in fields(errors(v))

    def test_campo_obrigatorio_ausente_ERROR(self):
        c = cut(); del c["end_sec"]
        v = validate_moment_selection([c], SEGMENTS, TOTAL)
        assert "end_sec" in fields(errors(v))

    def test_assunto_vazio_ERROR(self):
        v = validate_moment_selection([cut(assunto="  ")], SEGMENTS, TOTAL)
        assert "assunto" in fields(errors(v))

    def test_end_antes_de_start_ERROR(self):
        v = validate_moment_selection([cut(start_sec=40.0, end_sec=10.0)], SEGMENTS, TOTAL)
        assert "ordem" in fields(errors(v))

    def test_corte_no_meio_da_fala_WARNING(self):
        # start 12s não cai em fronteira (0/40/95); duração ok (12→52 = 40s).
        v = validate_moment_selection([cut(start_sec=12.0, end_sec=52.0)], SEGMENTS, TOTAL)
        assert "fronteira_inicio" in fields(v)
        assert all(x.severity == WARNING for x in v)  # deriva é aviso, não bloqueio
        assert is_shippable(v)

    def test_momentos_sobrepostos_WARNING(self):
        cuts = [cut(rank=1, start_sec=0.0, end_sec=40.0),
                cut(rank=2, start_sec=35.0, end_sec=95.0)]  # 35 < 40 → overlap
        v = validate_moment_selection(cuts, SEGMENTS, TOTAL)
        assert "sobreposicao" in fields(v)

    def test_poucos_momentos_WARNING(self):
        v = validate_moment_selection([cut()], SEGMENTS, TOTAL)
        assert "count" in fields(v)

    def test_acumula_varias_violacoes(self):
        # um único momento 95s + fora de fronteira: dois problemas no mesmo cut.
        v = validate_moment_selection([cut(start_sec=3.0, end_sec=98.0)], SEGMENTS, TOTAL)
        assert {"duracao", "fronteira_inicio"} <= fields(v)


# ── 2. REGRESSÃO sobre a saída real do agente ─────────────────────────────────
GOLDEN_CUTS = ROOT / "output" / "clips" / "5qD5Do_HriQ_ia_moments.json"
GOLDEN_TRANSCRIPT = ROOT / "output" / "raw" / "5qD5Do_HriQ_transcript.json"

requires_golden = pytest.mark.skipif(
    not (GOLDEN_CUTS.exists() and GOLDEN_TRANSCRIPT.exists()),
    reason="saída cacheada do agente ausente (output/clips + output/raw)",
)


@pytest.fixture(scope="module")
def golden():
    cuts = json.loads(GOLDEN_CUTS.read_text())
    tr = json.loads(GOLDEN_TRANSCRIPT.read_text())
    return cuts, tr["segments"], float(tr["duration_sec"])


@requires_golden
class TestRegressaoSaidaReal:
    def test_validador_pega_o_momento_de_62s(self, golden):
        # Defeito REAL: o LLM escolheu um momento de 62s; o pipeline só rejeitou no
        # ffmpeg, deixando sidecar órfão. O validador tem que pegar ANTES do corte.
        cuts, segs, total = golden
        v = validate_moment_selection(cuts, segs, total)
        dur_errs = [x for x in errors(v) if x.field == "duracao"]
        assert dur_errs, "validador deveria flagar o momento >60s que escapou pro ffmpeg"

    def test_momentos_que_viraram_mp4_cumprem_duracao(self, golden):
        # Os 3 momentos com mp4 (ranks 1,2,4) estão dentro de 30–60s.
        cuts, segs, total = golden
        shipped = [c for c in cuts if (c["end_sec"] - c["start_sec"]) <= 60]
        v = validate_moment_selection(shipped, segs, total)
        assert not [x for x in errors(v) if x.field == "duracao"]

    def test_relatorio_de_fronteira_nao_vazio(self, golden):
        # Documenta a deriva: timestamps arredondados p/ inteiro não batem na fala.
        cuts, segs, total = golden
        v = validate_moment_selection(cuts, segs, total)
        assert any(x.field.startswith("fronteira") for x in v)
