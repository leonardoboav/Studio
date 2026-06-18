"""
Brain — motor do sub-agente 'roteirista'. Chama a API Claude.

Dois modos, decididos por `nature`:
  - extractable: seleciona trechos reais (timestamps) da MINHA fala.
  - signal_only: gera ROTEIRO ORIGINAL com [MINHA OPINIÃO]. Proibido traduzir/
    parafrasear a fonte; recebe só o sinal estruturado + transcrição como pesquisa.

original_speech_fraction (signal_only): o LLM CLASSIFICA cada cláusula (julgamento),
mas o Python CONTA as palavras e divide (aritmética determinística). A fração nunca
vem do número que o LLM chutar — é computada do clause_breakdown pela régua exata do
roteirista.md (posição+razão = original; fato; neutro excluído do denominador).
"""
import json
import os
import re
import time
from pathlib import Path

import yaml

# anthropic é importado tardiamente dentro das funções que chamam a API, para que a
# régua determinística (compute_original_fraction) seja importável sem a lib instalada.

CLIPS_DIR = Path(__file__).parent.parent / "output" / "clips"
CHANNELS_DIR = Path(__file__).parent.parent / "channels"

_MAX_RETRIES = 3

# ── Régua de classificação (espelha .claude/agents/roteirista.md) ───────────────
_RUBRIC = """
Régua DUPLA para classificar cada cláusula do roteiro:

- "original" — toma posição E carrega justificativa/especificidade própria (os DOIS).
  Ex.: "isso é problema de design, não de tecnologia" (distinção própria);
       "o mercado vai ignorar por dois anos porque falta caso de uso" (previsão + razão).
- "fact" — descreve sem posicionamento, OU posição sem razão (hype vazio), OU claim
  factual sem fonte. Ex.: "o modelo foi lançado dia 11 e custa X" (fato puro);
       "isso vai mudar tudo" (posição sem razão → NÃO conta como original);
       "é a mais rápida do mercado" (claim sem benchmark → fato).
- "neutral" — transição ("vou te mostrar", "então"), CTA ("deixa o like"), pergunta
  retórica sem resposta no mesmo trecho. EXCLUÍDO do denominador.

Frase mista (fato + posição na mesma sentença): QUEBRE em cláusulas separadas e
classifique cada uma. "custa X, e isso é caro demais pro que entrega" vira duas:
"custa X" (fact) e "isso é caro demais pro que entrega" (original).

O clause_breakdown DEVE cobrir o roteiro inteiro, cláusula por cláusula, em ordem.
""".strip()

# ── Modo extractable (cortes de fala própria) ───────────────────────────────────
_SYSTEM_EXTRACTABLE = """
Você é o núcleo criativo de um agente de produção de Shorts para YouTube.
Analisa a transcrição da MINHA gravação e seleciona cortes reais com potencial.

Regras: gancho nos 3 primeiros segundos; duração 15–60s; prefira os padrões do perfil.
Responda SOMENTE com JSON válido, sem markdown.
""".strip()

_USER_EXTRACTABLE = """
## Perfil do canal
{profile_json}

## Transcrição (minha fala — extractable)
{transcript_text}

## Tarefa
Identifique entre 3 e 7 cortes. Para cada um:
{{
  "cuts": [
    {{
      "rank": 1, "score": 0.0-1.0, "score_reason": "...",
      "start_sec": 0.0, "end_sec": 0.0,
      "hook": "gancho dos 3 primeiros segundos",
      "narration_script": "o que eu falo no corte (minha fala já existente)",
      "title": "...", "description": "...", "hashtags": ["#x"],
      "thumbnail_brief": {{"concept": "...", "variations": ["A", "B"]}},
      "viral_pattern": "padrão do perfil acionado"
    }}
  ]
}}
"""

# ── Modo signal_only (roteiro original a partir de tema) ─────────────────────────
_SYSTEM_SIGNAL = f"""
Você é o ROTEIRISTA do canal. Transforma um TEMA (extraído como sinal de uma
referência de terceiro) num roteiro ORIGINAL em PT-BR, com voz e ângulo próprios.

PROIBIDO: traduzir ou parafrasear a fonte. A transcrição da referência é só pesquisa
interna — você escreve SEU vídeo sobre o tema, não refaz o vídeo que viralizou.

Respeite o tom do perfil (cético, direto, anti-hype).
Se o tema não permitir contribuição original real, retorne {{"cuts": [], "skip_reason": "..."}}.
Se envolver IP protegido (personagem/marca/obra), retorne {{"cuts": [], "ip_flag": "..."}}.

{_RUBRIC}

Responda SOMENTE com JSON válido, sem markdown.
""".strip()

_USER_SIGNAL = """
## Perfil do canal
{profile_json}

## Sinal da referência (tema/gancho/estrutura — NÃO copiar texto)
{signal_json}

## Transcrição da referência (PESQUISA interna — proibido copiar/traduzir)
{transcript_text}

## Tarefa
Escreva 1 a 3 peças ORIGINAIS sobre o tema. Para cada uma:
{{
  "cuts": [
    {{
      "rank": 1,
      "formato_sugerido": "longo",
      "hook": "gancho original dos 3 primeiros segundos",
      "opiniao": "[MINHA OPINIÃO] tese própria não-genérica, >= 12 palavras, com PORQUÊ",
      "teste": "ponto de vista prático (no longo de IA não há demo)",
      "roteiro": "texto completo PT-BR: hook -> contexto -> minha tese -> desenvolvimento -> veredito -> CTA",
      "clause_breakdown": [
        {{"clause": "texto exato da cláusula", "label": "original|fact|neutral", "reason": "por que esse rótulo"}}
      ],
      "title": "...", "description": "...", "hashtags": ["#x"],
      "thumbnail_brief": {{"concept": "...", "variations": ["A", "B"]}}
    }}
  ]
}}
Lembre: o clause_breakdown cobre o roteiro inteiro, em ordem. NÃO calcule fração — o
sistema calcula a partir dos rótulos.
"""


# ── Modo cut (seleção de MOMENTOS 30–60s de criador BR) ─────────────────────────
_SYSTEM_MOMENTS = """
Você seleciona MOMENTOS de um vídeo de terceiro para virar shorts verticais (9:16).
Um MOMENTO é um trecho de 30 a 60 segundos que se sustenta SOZINHO: tem um assunto
único e sentido completo (começo-meio-fim de uma ideia), não corta no meio de uma
frase nem depende de contexto que ficou de fora.

Critérios de um bom momento:
- assunto único e nítido (dá pra resumir em uma frase);
- gancho logo no início (a primeira fala já prende);
- fecha o raciocínio dentro da janela (não deixa pergunta sem resposta no trecho);
- 30–60s. Se a ideia boa tem 22s, NÃO estique com enchimento — descarte.

Use SOMENTE os timestamps que aparecem na transcrição. start_sec e end_sec devem cair
em fronteiras de fala (começo/fim de segmentos), nunca no meio de uma palavra.

Responda SOMENTE com JSON válido, sem markdown.
""".strip()

_USER_MOMENTS = """
## Perfil do canal (tom/nicho — para escolher o que é relevante)
{profile_json}

## Transcrição com timestamps (vídeo de terceiro)
{transcript_text}

## Tarefa
Selecione de 2 a 6 MOMENTOS. Para cada um:
{{
  "cuts": [
    {{
      "rank": 1,
      "assunto": "frase do que o trecho realmente diz",
      "assunto_slug": "kebab-case-curto-do-assunto",
      "por_que_tem_sentido": "por que fecha sozinho: o gancho e o fechamento do raciocínio",
      "start_sec": 0.0,
      "end_sec": 0.0,
      "score": 0.0,
      "score_reason": "por que este trecho tem potencial"
    }}
  ]
}}
Lembre: 30–60s, fronteira de fala, assunto único. Qualidade > quantidade.
"""


def select_moments(transcribe_result: dict) -> dict:
    """
    Modo 'cut': lê a transcrição com timestamps e propõe MOMENTOS de 30–60s com assunto
    fechado, para o fluxo de shorts a partir de criador BR (src/moments.py). Reaproveita
    retry/parse da API. Cache por video_id+channel+modo cut.
    """
    channel_slug = transcribe_result["channel_slug"]
    video_id = transcribe_result["metadata"]["id"]

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CLIPS_DIR / f"{video_id}_{channel_slug}_moments.json"
    if cache_path.exists():
        cuts = json.loads(cache_path.read_text())
        return {**transcribe_result, "cuts": cuts}

    import anthropic

    profile = _load_profile(channel_slug)
    transcript_text = _flatten_transcript(transcribe_result.get("transcript", {"segments": []}))
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    cuts = _call_with_retry(
        client, _SYSTEM_MOMENTS,
        _USER_MOMENTS.format(
            profile_json=json.dumps(profile, ensure_ascii=False, indent=2),
            transcript_text=transcript_text,
        ),
    )
    cache_path.write_text(json.dumps(cuts, indent=2, ensure_ascii=False))
    return {**transcribe_result, "cuts": cuts}


def run_brain(transcribe_result: dict) -> dict:
    """
    Dispatch por nature. Cache key inclui channel_slug e modo.
    """
    channel_slug = transcribe_result["channel_slug"]
    video_id = transcribe_result["metadata"]["id"]
    nature = transcribe_result.get("nature", "extractable")

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CLIPS_DIR / f"{video_id}_{channel_slug}_{nature}_cuts.json"
    if cache_path.exists():
        cuts = json.loads(cache_path.read_text())
        return {**transcribe_result, "cuts": cuts}

    import anthropic

    profile = _load_profile(channel_slug)
    transcript_text = _flatten_transcript(transcribe_result.get("transcript", {"segments": []}))
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if nature == "signal_only":
        signal = transcribe_result.get("signal", {})
        cuts = _call_with_retry(
            client, _SYSTEM_SIGNAL,
            _USER_SIGNAL.format(
                profile_json=json.dumps(profile, ensure_ascii=False, indent=2),
                signal_json=json.dumps(signal, ensure_ascii=False, indent=2),
                transcript_text=transcript_text,
            ),
        )
        cuts = [_finalize_signal_piece(p) for p in cuts]
    else:
        cuts = _call_with_retry(
            client, _SYSTEM_EXTRACTABLE,
            _USER_EXTRACTABLE.format(
                profile_json=json.dumps(profile, ensure_ascii=False, indent=2),
                transcript_text=transcript_text,
            ),
        )

    cache_path.write_text(json.dumps(cuts, indent=2, ensure_ascii=False))
    return {**transcribe_result, "cuts": cuts}


# ── Cálculo determinístico da fração (a régua) ──────────────────────────────────

def compute_original_fraction(clause_breakdown: list[dict]) -> float:
    """
    original_speech_fraction = palavras(original) / palavras(original + fact).
    Neutros excluídos do denominador. Exato, reproduzível, auditável.
    Retorna 0.0 se não houver nenhuma cláusula que conte (denominador zero).
    """
    original_words = sum(_word_count(c["clause"]) for c in clause_breakdown if c.get("label") == "original")
    fact_words = sum(_word_count(c["clause"]) for c in clause_breakdown if c.get("label") == "fact")
    denom = original_words + fact_words
    if denom == 0:
        return 0.0
    return round(original_words / denom, 3)


def _finalize_signal_piece(piece: dict) -> dict:
    """
    Carimba a fração calculada pela régua (não a que o LLM porventura mandou) e
    espelha o roteiro em narration_script para o montador. opiniao já vem do LLM.
    """
    breakdown = piece.get("clause_breakdown", [])
    piece["original_speech_fraction"] = compute_original_fraction(breakdown)
    if "roteiro" in piece and "narration_script" not in piece:
        piece["narration_script"] = piece["roteiro"]
    return piece


def _word_count(text: str) -> int:
    return len((text or "").split())


# ── Chamada à API com parse defensivo + retry ───────────────────────────────────

def _call_with_retry(client, system: str, user: str) -> list:
    import anthropic

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            # Sem prefill de assistant: este modelo não suporta. O JSON é garantido
            # pela instrução no system + parse defensivo (_parse_cuts via regex).
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                system=system,
                messages=[
                    {"role": "user", "content": user},
                ],
            )
            if message.stop_reason == "max_tokens":
                raise RuntimeError("Brain truncado (max_tokens). Entrada longa demais.")
            return _parse_cuts(message.content[0].text)

        except (json.JSONDecodeError, KeyError) as e:
            if attempt == _MAX_RETRIES:
                raise RuntimeError(f"Brain devolveu JSON inválido após {_MAX_RETRIES} tentativas: {e}")
            print(f"[brain] Tentativa {attempt} — erro de JSON, repetindo...")
            time.sleep(2**attempt)

        except anthropic.RateLimitError:
            if attempt == _MAX_RETRIES:
                raise
            wait = 2**attempt
            print(f"[brain] Rate limit, aguardando {wait}s...")
            time.sleep(wait)


def _parse_cuts(raw: str) -> list:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("Nenhum objeto JSON na resposta do brain", cleaned, 0)
    return json.loads(match.group())["cuts"]


def _load_profile(channel_slug: str) -> dict:
    profile_path = CHANNELS_DIR / f"{channel_slug}.yaml"
    if not profile_path.exists():
        raise FileNotFoundError(f"Channel profile not found: {profile_path}")
    return yaml.safe_load(profile_path.read_text())


def _flatten_transcript(transcript: dict) -> str:
    lines = []
    for seg in transcript.get("segments", []):
        lines.append(f"[{_fmt_time(seg['start'])} → {_fmt_time(seg['end'])}] {seg['text']}")
    return "\n".join(lines)


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"
