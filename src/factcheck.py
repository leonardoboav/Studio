"""
Gate de VERACIDADE — ortogonal ao gate de originalidade.

Originalidade pergunta "isso é meu?"; veracidade pergunta "isso é verdade?".
São independentes. Roda EM SÉRIE após a régua de originalidade e ANTES do
diretor-de-arte. NÃO toca nas 6 travas nem no gate de originalidade.

PRINCÍPIO (não violar): o agente NÃO decide sozinho se um fato é verdadeiro. Um LLM
que "confirma" fatos plausíveis gera falsa segurança — mesmo risco do classificador de
cláusulas inclinado ao otimista. Este módulo faz o BRAÇAL (extrai claims, busca fonte,
casa) e entrega um RELATÓRIO; o veredito final de publicar é do humano.

Falha fecha, omissão NÃO aprova (espelha o sentinela _MISSING do gate de originalidade):
- claim sem busca concluída = nao_encontrado (nunca confirmado);
- "confirmado" sem url_fonte real é rebaixado para nao_encontrado;
- se a web search não estiver disponível no ambiente, FALHA EXPLÍCITO (raise),
  nunca retorna "confirmado" vazio.
"""
import json
import os
import re
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "output" / "raw"

_MAX_CLAIMS = 12          # bound de custo/tempo; claims além disso ficam pendentes
_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}

# Termos genéricos que começam frase em PT — não são nomes próprios.
_PT_STOPWORDS = {
    "o", "a", "os", "as", "na", "no", "nas", "nos", "vou", "isso", "aqui", "para",
    "se", "mas", "e", "quem", "imagina", "use", "não", "estou", "concentrar",
    "funciona", "jailbreak", "três", "dois", "primeiro", "segundo", "terceiro",
    "regulação", "acesso", "qualquer", "esse", "essa", "agora", "na", "de", "do",
}


class WebSearchUnavailable(RuntimeError):
    """Web search não disponível no ambiente — falha explícita (não aprova por omissão)."""


# ── pipeline público ────────────────────────────────────────────────────────────

def run_factcheck(piece: dict, video_id: str) -> dict:
    """
    Recebe o roteiro aprovado pela régua + o clause_breakdown existente.
    Faz o braçal: extrai claims factuais, sinaliza nomes/números (Whisper erra),
    busca fonte para cada claim e classifica. Salva o relatório em
    output/raw/<id>_factcheck.json. NÃO decide publicar.
    """
    import anthropic

    breakdown = piece.get("clause_breakdown", [])
    roteiro = piece.get("roteiro", "")

    # 2. Reusa o breakdown — seleciona label "fact" (não reclassifica). Filtra a
    #    fragmentos verificáveis (com número, nome próprio, ou substanciais).
    fact_clauses = [
        c["clause"] for c in breakdown
        if c.get("label") == "fact" and _is_verifiable(c["clause"])
    ]
    truncated = len(fact_clauses) > _MAX_CLAIMS
    claims_to_check = fact_clauses[:_MAX_CLAIMS]

    # Nomes próprios e números do roteiro inteiro → "verificar_transcrição"
    # (Whisper small erra "Fable 5", "Mythos 5", datas, códigos).
    transcription_flags = _extract_transcription_flags(roteiro)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    claims = []
    for clause in claims_to_check:
        try:
            claims.append(_verify_claim(client, clause))
        except WebSearchUnavailable:
            raise  # falha explícita — não aprova por omissão
        except Exception as e:
            # Busca não concluída = nao_encontrado (NUNCA confirmado).
            claims.append({
                "claim": clause, "status": "nao_encontrado",
                "url_fonte": "", "trecho_fonte": "", "fonte_tipo": "",
                "erro": str(e)[:120],
            })

    # Claims que não couberam no bound ficam pendentes (não confirmados).
    for clause in fact_clauses[_MAX_CLAIMS:]:
        claims.append({
            "claim": clause, "status": "nao_encontrado",
            "url_fonte": "", "trecho_fonte": "", "fonte_tipo": "",
            "erro": "nao verificado (acima do limite de claims)",
        })

    summary = {
        "total": len(claims),
        "confirmado": sum(c["status"] == "confirmado" for c in claims),
        "nao_encontrado": sum(c["status"] == "nao_encontrado" for c in claims),
        "contradito": sum(c["status"] == "contradito" for c in claims),
        "transcription_flags": len(transcription_flags),
        "claims_truncados": truncated,
    }

    out = {
        "video_id": video_id,
        "claims": claims,
        "transcription_flags": transcription_flags,
        "summary": summary,
    }
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{video_id}_factcheck.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False)
    )
    return out


def veracity_gate(fc: dict) -> dict:
    """
    Gate de veracidade. NÃO aprova por omissão.

    - QUALQUER "contradito" → reprovado (bloqueia o diretor-de-arte).
    - QUALQUER "nao_encontrado" ou flag de transcrição pendente →
      requer_confirmacao_humana (não avança sem input explícito).
    - Só "aprovado" se TODOS os fatos = confirmado e sem flags pendentes.
    """
    claims = fc.get("claims", [])
    contraditos = [c for c in claims if c["status"] == "contradito"]
    nao_encontrados = [c for c in claims if c["status"] == "nao_encontrado"]
    flags = fc.get("transcription_flags", [])

    if contraditos:
        return {
            "status": "reprovado",
            "reason": f"{len(contraditos)} claim(s) contradito(s) por fonte — não passa para o diretor-de-arte",
            "contraditos": contraditos,
        }
    if nao_encontrados or flags:
        return {
            "status": "requer_confirmacao_humana",
            "reason": f"{len(nao_encontrados)} fato(s) sem fonte + {len(flags)} termo(s) a conferir na transcrição",
            "nao_encontrado": nao_encontrados,
            "transcription_flags": flags,
        }
    return {"status": "aprovado", "reason": "todos os fatos confirmados por fonte"}


# ── verificação de um claim (braçal: busca + casa) ──────────────────────────────

_PROMPT = """Você é um verificador de fatos. Verifique a AFIRMAÇÃO buscando fontes na web.

AFIRMAÇÃO: "{claim}"

Regras:
- Busque fontes reais. PRIORIZE fonte primária: site/blog oficial da entidade citada
  (ex.: anthropic.com), documento de governo, veículo de imprensa estabelecido.
  DESPRIORIZE fórum, agregador, outro vídeo de YouTube, rede social.

- Identifique o NÚCLEO da afirmação (o fato central que ela assere) e classifique:
  - "confirmado": uma fonte crível confirma o NÚCLEO. Se a fonte confirma o núcleo
    mas diverge num detalhe secundário, número aproximado ou enquadramento, AINDA é
    "confirmado" — registre a divergência no campo "ressalva".
  - "contradito": use SOMENTE quando uma fonte crível NEGA EXPLICITAMENTE o núcleo
    (afirma o oposto do fato central). Divergência de nuance, detalhe, data aproximada
    ou enquadramento NÃO é contradito.
  - "nao_encontrado": nenhuma fonte crível encontrada.

- NA DÚVIDA entre "confirmado com ressalva" e "contradito", escolha CONFIRMADO com
  ressalva. "contradito" reprova a peça inteira e bloqueia o pipeline — reserve-o para
  falsidade real do núcleo, não para imprecisão de detalhe.
- NUNCA marque "confirmado" sem uma url_fonte real e crível.
- trecho_fonte e ressalva: paráfrase MUITO curta (< 15 palavras cada). NÃO cole
  parágrafos da fonte.

Responda APENAS com JSON, sem markdown:
{{"status":"confirmado|contradito|nao_encontrado","url_fonte":"","trecho_fonte":"","ressalva":"","fonte_tipo":"primaria|secundaria|fraca"}}"""


def _verify_claim(client, claim: str) -> dict:
    import anthropic

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            tools=[_WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": _PROMPT.format(claim=claim)}],
        )
    except (anthropic.BadRequestError, anthropic.PermissionDeniedError) as e:
        if _is_tool_unavailable(e):
            raise WebSearchUnavailable(
                "Web search (web_search_20250305) indisponível nesta conta/ambiente. "
                "Habilite a ferramenta no Console da Anthropic. O factcheck NÃO aprova "
                "por omissão — por isso falha explícito em vez de fingir confirmação."
            ) from e
        raise

    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text")
    data = _parse_json(text)

    status = data.get("status", "nao_encontrado")
    url = (data.get("url_fonte") or "").strip()
    # Omissão não aprova: "confirmado" sem url real vira nao_encontrado (espelha _MISSING).
    if status == "confirmado" and not url:
        status = "nao_encontrado"
    if status not in ("confirmado", "contradito", "nao_encontrado"):
        status = "nao_encontrado"

    trecho = " ".join((data.get("trecho_fonte") or "").split()[:15])  # < 15 palavras
    ressalva = " ".join((data.get("ressalva") or "").split()[:15])
    return {
        "claim": claim, "status": status, "url_fonte": url,
        "trecho_fonte": trecho, "ressalva": ressalva,
        "fonte_tipo": data.get("fonte_tipo", ""),
    }


def _is_tool_unavailable(err) -> bool:
    msg = str(err).lower()
    return ("web_search" in msg or "web search" in msg) and (
        "not" in msg or "enable" in msg or "support" in msg or "invalid" in msg
        or "permission" in msg or "allow" in msg
    )


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return {}


# ── extração (braçal determinístico) ────────────────────────────────────────────

def _is_verifiable(clause: str) -> bool:
    """Claim verificável: tem número, nome próprio, ou é substancial (>= 6 palavras)."""
    if len(clause.split()) >= 6:
        return True
    if re.search(r"\d", clause):
        return True
    return bool(_proper_nouns(clause))


def _extract_transcription_flags(roteiro: str) -> list[dict]:
    """
    Nomes próprios e números do roteiro inteiro — Whisper small erra esses.
    Marca para conferência humana contra a transcrição. NÃO é aprovação.

    Dedup: componentes de um nome multi-palavra (ex.: 'Fable', '5' dentro de
    'Fable 5') não viram flags separadas.
    """
    nouns = _proper_nouns(roteiro)
    # tokens já cobertos por um nome multi-palavra (ex.: "Fable 5" cobre "Fable" e "5")
    covered = set()
    for n in nouns:
        if " " in n:
            for tok in n.split():
                covered.add(tok.lower())

    flags = []
    seen = set()
    for noun in nouns:
        key = noun.lower()
        if key in seen or (" " not in noun and key in covered):
            continue
        seen.add(key)
        flags.append({"term": noun, "type": "nome_proprio", "note": "verificar_transcrição"})
    for num in re.findall(r"\b\d+(?:[.,]\d+)?%?\b", roteiro):
        if num.lower() in seen or num.lower() in covered:
            continue
        seen.add(num.lower())
        flags.append({"term": num, "type": "numero", "note": "verificar_transcrição"})
    return flags


def _proper_nouns(text: str) -> list[str]:
    """
    Nomes próprios = palavras capitalizadas (ou Capital+número, ex.: 'Fable 5') que
    NÃO são início de frase nem stopword PT. Heurística simples e conservadora.
    """
    nouns = []
    # padrão "Fable 5", "Mythos 5", "GPT 4" etc.
    for m in re.finditer(r"\b([A-ZÀ-Ý][a-zà-ÿ]+)\s+(\d+)\b", text):
        nouns.append(f"{m.group(1)} {m.group(2)}")
    # capitalizadas isoladas, ignorando início de frase
    sentences = re.split(r"[.!?\n]+", text)
    for sent in sentences:
        words = sent.strip().split()
        for i, w in enumerate(words):
            token = w.strip(",;:'\"()")
            if i == 0:
                continue  # início de frase é sempre capitalizado
            if re.match(r"^[A-ZÀ-Ý][a-zà-ÿ]{2,}$", token) and token.lower() not in _PT_STOPWORDS:
                nouns.append(token)
    return nouns


# ── CLI de teste ────────────────────────────────────────────────────────────────

def _print_report(fc: dict, gate: dict) -> None:
    s = fc["summary"]
    print("\n" + "=" * 78)
    print(f"RELATÓRIO DE VERACIDADE — {fc['video_id']}")
    print("=" * 78)
    print(f"Claims: {s['total']}  |  confirmado={s['confirmado']}  "
          f"nao_encontrado={s['nao_encontrado']}  contradito={s['contradito']}  "
          f"| flags transcrição={s['transcription_flags']}")
    print("\nCLAIMS:")
    for c in fc["claims"]:
        mark = {"confirmado": "✓", "contradito": "✗", "nao_encontrado": "?"}.get(c["status"], "?")
        print(f"  [{mark} {c['status']}] {c['claim'][:60]}")
        if c["url_fonte"]:
            print(f"        fonte ({c.get('fonte_tipo','')}): {c['url_fonte']}")
        if c["trecho_fonte"]:
            print(f"        trecho: \"{c['trecho_fonte']}\"")
        if c.get("ressalva"):
            print(f"        ressalva: {c['ressalva']}")
        if c.get("erro"):
            print(f"        nota: {c['erro']}")
    if fc["transcription_flags"]:
        termos = ", ".join(f["term"] for f in fc["transcription_flags"])
        print(f"\nVERIFICAR NA TRANSCRIÇÃO (Whisper erra): {termos}")
    print("\n" + "-" * 78)
    icon = {"aprovado": "✅", "reprovado": "⛔", "requer_confirmacao_humana": "⚠️"}.get(gate["status"], "")
    print(f"GATE DE VERACIDADE: {icon} {gate['status'].upper()}")
    print(f"  {gate['reason']}")
    if gate["status"] != "aprovado":
        print("  → NÃO avança para o diretor-de-arte sem sua decisão.")


def _main() -> None:
    import sys
    from pipeline import _load_dotenv
    _load_dotenv()

    cuts_path = sys.argv[1] if len(sys.argv) > 1 else "output/raw/_signal_test_cuts.json"
    video_id = sys.argv[2] if len(sys.argv) > 2 else Path(cuts_path).stem

    cuts = json.loads(Path(cuts_path).read_text())
    piece = cuts[0] if isinstance(cuts, list) else cuts

    print(f"Rodando factcheck em {cuts_path} (peça rank {piece.get('rank','?')})...")
    fc = run_factcheck(piece, video_id)
    gate = veracity_gate(fc)
    _print_report(fc, gate)


if __name__ == "__main__":
    _main()
