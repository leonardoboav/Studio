"""
Contrato de seleção de momentos — valida o que o brain.select_moments PROMETE.

select_moments() pede ao LLM trechos 30–60s, com assunto único, timestamps em
fronteira de fala e dentro do vídeo (ver _SYSTEM_MOMENTS/_USER_MOMENTS em src/brain.py).
Nada garante que a resposta cumpra isso: hoje a única checagem é o ffmpeg em
src/moments.py, que rejeita TARDE (depois de transcrever e cachear) e só pega duração
e janela — deixa passar corte no meio de frase e sobreposição.

Este módulo é a régua determinística (sem API) que transforma "o agente escolheu os
momentos certos?" numa lista auditável de violações. Serve para:
  - testar a saída já cacheada (regressão sobre a seleção do LLM);
  - ser plugado ANTES do corte em moments.py, rejeitando momento ruim cedo.

Não julga gosto editorial (isso é eval com LLM); valida o CONTRATO estrutural.
"""
from dataclasses import dataclass

# Limites do contrato (espelham brain._SYSTEM_MOMENTS e moments._MIN_DUR/_MAX_DUR).
MIN_DUR = 30.0
MAX_DUR = 60.0
# Quão longe um timestamp pode cair de uma fronteira de segmento antes de virar risco
# de cortar no meio da fala. Folga p/ arredondamento, mas aperta o "começo/fim de frase".
BOUNDARY_TOL = 1.5
# A tarefa pede de 2 a 6 momentos.
MIN_CUTS, MAX_CUTS = 2, 6

ERROR = "error"      # quebra o contrato — o momento NÃO deve ser cortado.
WARNING = "warning"  # cheira a problema (deriva/sobreposição) — revisar.


@dataclass(frozen=True)
class Violation:
    rank: object   # rank do momento, ou None p/ violação do conjunto.
    field: str
    severity: str
    message: str


def _nearest(value: float, pool) -> float:
    return min(pool, key=lambda p: abs(p - value)) if pool else float("inf")


def validate_moment_selection(
    cuts: list[dict],
    segments: list[dict],
    total_dur: float,
    *,
    min_dur: float = MIN_DUR,
    max_dur: float = MAX_DUR,
    boundary_tol: float = BOUNDARY_TOL,
) -> list[Violation]:
    """
    Confere cada momento contra o contrato e devolve TODAS as violações (não para na
    primeira — quem chama decide se barra em ERROR ou também em WARNING).

    `segments`: lista de {"start","end",...} da transcrição (as fronteiras de fala reais).
    `total_dur`: duração do vídeo-fonte em segundos.
    """
    v: list[Violation] = []
    starts = [s["start"] for s in segments]
    ends = [s["end"] for s in segments]

    n = len(cuts)
    if n < MIN_CUTS or n > MAX_CUTS:
        v.append(Violation(None, "count", WARNING,
                           f"{n} momentos fora do esperado [{MIN_CUTS}, {MAX_CUTS}]"))

    spans = []
    for c in cuts:
        rank = c.get("rank", "?")

        # Campos obrigatórios para o corte/sidecar acontecerem.
        for fld in ("start_sec", "end_sec"):
            if c.get(fld) is None:
                v.append(Violation(rank, fld, ERROR, f"campo obrigatório ausente: {fld}"))
        if c.get("start_sec") is None or c.get("end_sec") is None:
            continue
        if not (c.get("assunto") or "").strip():
            v.append(Violation(rank, "assunto", ERROR, "assunto vazio — momento sem rótulo"))

        s, e = float(c["start_sec"]), float(c["end_sec"])
        dur = e - s

        if e <= s:
            v.append(Violation(rank, "ordem", ERROR, f"end ({e}) <= start ({s})"))
            continue

        # 1. Duração 30–60s (a falha que hoje só o ffmpeg pega, tarde).
        if dur < min_dur:
            v.append(Violation(rank, "duracao", ERROR, f"{dur:.1f}s < {min_dur:.0f}s mínimo"))
        elif dur > max_dur:
            v.append(Violation(rank, "duracao", ERROR, f"{dur:.1f}s > {max_dur:.0f}s máximo"))

        # 2. Dentro do vídeo.
        if s < 0 or (total_dur and e > total_dur + 1):
            v.append(Violation(rank, "janela", ERROR,
                               f"[{s:.0f},{e:.0f}] fora de [0,{total_dur:.0f}]s"))

        # 3. Timestamps em fronteira de fala (senão corta no meio da frase).
        if segments:
            ds, de = abs(s - _nearest(s, starts)), abs(e - _nearest(e, ends))
            if ds > boundary_tol:
                v.append(Violation(rank, "fronteira_inicio", WARNING,
                                   f"start {s:.1f}s a {ds:.1f}s da fronteira de fala mais próxima"))
            if de > boundary_tol:
                v.append(Violation(rank, "fronteira_fim", WARNING,
                                   f"end {e:.1f}s a {de:.1f}s da fronteira de fala mais próxima"))

        spans.append((s, e, rank))

    # 4. Momentos não podem se sobrepor (reusariam a mesma footage).
    spans.sort()
    for (s1, e1, r1), (s2, e2, r2) in zip(spans, spans[1:]):
        if e1 > s2:
            v.append(Violation(r2, "sobreposicao", WARNING,
                               f"momento {r2} começa em {s2:.0f}s antes de {r1} terminar ({e1:.0f}s)"))

    return v


def errors(violations: list[Violation]) -> list[Violation]:
    return [x for x in violations if x.severity == ERROR]


def is_shippable(violations: list[Violation]) -> bool:
    """Sem nenhum ERROR, o conjunto pode ir para o corte (warnings só sinalizam)."""
    return not errors(violations)


def format_report(violations: list[Violation]) -> str:
    if not violations:
        return "contrato OK — nenhum problema"
    lines = []
    for x in sorted(violations, key=lambda x: (x.severity != ERROR, str(x.rank))):
        tag = "✗" if x.severity == ERROR else "⚠"
        lines.append(f"  {tag} [rank {x.rank}] {x.field}: {x.message}")
    return "\n".join(lines)
