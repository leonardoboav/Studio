# PRD — Agente de Produção de Canais (codinome: "Studio")

> Documento de produto. Objetivo: automatizar a produção de canais de vídeo curto
> (Shorts/Reels/TikTok) de ponta a ponta, de forma **replicável entre canais** e
> **sustentável sob a política de conteúdo do YouTube**.

---

## 1. Contexto e problema

O operador (dono do projeto) construiu manualmente o canal RPM Rambo:
- ~175 vídeos, 13,7 mil inscritos, ~29 mi de visualizações em ~1 ano.
- Audiência movida a Shorts (cortes de entrevistas/podcasts automotivos).
- Processo 100% braçal: download via script Python → edição manual no CapCut →
  thumbnails no Canva (com teste A/B) → descrição via LLM → upload manual.
- Levou 4–5 meses para ser aceito no YouTube Partner Program. Recebeu AdSense por
  ~2 meses. No 3º mês acumulando, o canal foi **desmonetizado por "reused content"**
  e não conseguiu reaplicar.

**Diagnóstico:** o gargalo que matou o canal NÃO foi velocidade de produção — foi o
**modelo de conteúdo** (republicar cortes de terceiros sem valor original suficiente).
A política se aplica ao canal como um todo, não vídeo a vídeo.

**Consequência para este projeto:** automatizar apenas o braçal reproduz o mesmo
fracasso, só que mais rápido e em escala. O agente precisa, por design, resolver as
duas coisas ao mesmo tempo — eliminar o trabalho manual E adicionar a camada de
valor original que torna o conteúdo elegível.

---

## 2. Princípio inegociável (north star)

> **Todo vídeo publicado precisa carregar uma camada de valor original mensurável:
> narração/comentário do criador, edição transformadora, análise ou ângulo próprio.
> Sem essa camada, o vídeo não sai do pipeline.**

Isto é um requisito de produto, não uma recomendação. O módulo de validação
(`gate`) bloqueia qualquer item que não tenha:
1. Roteiro de comentário/narração original associado, OU
2. Transformação editorial significativa documentada (não apenas legenda + reframe).

Fonte do material deve ser: (a) gravada pelo próprio criador, (b) licenciada, ou
(c) usada sob comentário transformador genuíno. O agente **não** tem função de
disfarçar reuso nem de evadir Content ID — isso está explicitamente fora de escopo
(ver §8).

---

## 3. Usuários e modo de uso

- **Usuário primário:** o operador (solo). Perfil técnico (Python, Cursor, Claude Code).
- **Uso:** rodar o pipeline por linha de comando ou job agendado, sobre uma fonte de
  vídeo, gerando N cortes prontos para revisão e publicação.
- **Multi-canal:** o operador quer **abrir canais novos do zero** e replicar o método.
  Cada canal é um "perfil" configurável (ver §6). RPM Rambo seria um perfil; o canal
  de gatos, outro; e assim por diante.

---

## 4. Arquitetura (pipeline em 5 etapas)

```
1. Fonte  →  2. Transcrição  →  3. CÉREBRO (Claude)  →  4. Mãos  →  5. Publicação
   (própria/      (Whisper,        (seleção + roteiro      (corte,      (título,
   licenciada)    timestamps)       original + metadados)   legenda,     thumbnail,
                                                            reframe)     agendamento)
```

- **Etapas 1, 2, 4, 5 = mecânicas.** Commodity. Usar ferramentas prontas / libs.
- **Etapa 3 = o produto.** É onde mora a diferenciação e a sobrevivência do canal.

---

## 5. Requisitos funcionais por módulo

### 5.1 `ingest` (Etapa 1)
- Aceitar fonte local (arquivo gravado pelo criador) ou URL de conteúdo com direito de uso.
- Normalizar para um formato de trabalho (resolução, fps, áudio).
- Registrar a **proveniência** da fonte (campo obrigatório: own / licensed / commentary).
  Itens sem proveniência válida não avançam.

### 5.2 `transcribe` (Etapa 2)
- Transcrição com timestamps por palavra (faster-whisper local).
- Saída estruturada (JSON) com segmentos, falantes (se detectável) e tempos.

### 5.3 `brain` (Etapa 3) — núcleo do agente
Recebe a transcrição + o perfil do canal. Produz, por corte candidato:
- **Seleção de momentos:** identifica trechos com maior potencial, usando os padrões
  de viralização do perfil (ver §6). Atribui um score e justificativa.
- **Ângulo original:** gera o roteiro de narração/comentário que o criador grava por
  cima — incluindo o gancho dos primeiros 3 segundos. Esta é a camada de valor.
- **Metadados:** título no padrão do canal, descrição, hashtags, brief de thumbnail
  (conceito + 2–3 variações para teste A/B).
- **Estrutura de saída:** JSON por corte (timestamps in/out, score, roteiro, metadados).

### 5.4 `hands` (Etapa 4)
- Cortar por timestamp (FFmpeg) OU delegar a uma API de clipping (ver §7 trade-off).
- Reframe vertical 9:16 com tracking de assunto.
- Legenda queimada (estilo do perfil).
- Inserir a narração/comentário gravado pelo criador (faixa de áudio + sync).

### 5.5 `gate` (validação)
- Bloqueia itens sem camada de valor original (princípio §2).
- Checklist automático antes de marcar um corte como "pronto para publicar".

### 5.6 `publish` (Etapa 5)
- Gerar thumbnails a partir dos briefs (variações para A/B).
- Empacotar metadados.
- Agendar/subir (com revisão humana obrigatória antes do publish — não publicar cego).

---

## 6. Perfil de canal (config multi-canal)

Cada canal é um arquivo de configuração (`channels/<slug>.yaml`) com:
- `niche`: nicho (ex.: automotivo, felinos).
- `persona`: voz/ângulo do criador para a narração (tom, vocabulário, opiniões).
- `viral_patterns`: lista de padrões que performam no nicho. Para RPM Rambo, derivados
  dos dados reais: opinião crua de figura conhecida; conflito/treta; "verdade escondida"
  sobre marca; nostalgia. Cada novo canal começa com hipóteses e ajusta com dados.
- `title_style`: padrão de título (ex.: CAIXA ALTA + gancho; nome + opinião + emoji).
- `thumbnail_style`: identidade visual para os briefs.
- `cadence`: frequência de publicação.
- `source_policy`: regra de proveniência aceita para aquele canal.

O objetivo é que abrir um canal novo seja: criar um perfil + apontar a fonte.

---

## 7. Stack técnico

| Camada | Escolha | Observação |
|---|---|---|
| Linguagem | Python 3.11+ | alinhado ao fluxo Cursor/Claude Code |
| Orquestração | Claude Code como agente / script CLI | jobs por etapa |
| Transcrição | faster-whisper (local) | timestamps por palavra, custo zero |
| Cérebro | API Claude (Sonnet para volume; Opus para casos difíceis) | etapa 3 |
| Corte/legenda/reframe | **Decisão pendente** (ver trade-off) | etapa 4 |
| Thumbnail | geração + variações para A/B | etapa 5 |
| Config | YAML por canal | multi-canal |

**Trade-off da Etapa 4 (build vs buy):**
- *Buy* (API de OpusClip/Vizard/Reap): rápido, reframe com tracking resolvido, custo por clipe.
- *Build* (FFmpeg na mão): controle total, sem mensalidade, mas reframe com tracking de
  rosto é o ponto mais difícil de fazer bem.
- *Recomendação inicial:* começar com buy na Etapa 4 para validar o pipeline rápido;
  migrar para build se o volume justificar.

---

## 8. Fora de escopo (explícito)

- Disfarçar conteúdo reutilizado ou evadir o Content ID do YouTube.
- Produção em massa de vídeos quase idênticos / "inauthentic content".
- Publicação automática sem revisão humana.
- Qualquer coisa que recrie o modelo que desmonetizou o RPM Rambo.

---

## 9. Métricas de sucesso

- **Tempo por corte publicável:** reduzir o braçal de horas para minutos de trabalho humano.
- **Taxa de aprovação de monetização** dos canais novos (a métrica que importa).
- **Retenção e CTR** por corte (feedback para `viral_patterns`).
- **Tempo para abrir um canal novo** (meta: perfil + fonte → primeiros cortes no mesmo dia).

---

## 10. Roadmap

**Fase 1 — Pipeline mínimo (1 canal):**
ingest → transcribe → brain (seleção + roteiro) → buy na etapa 4 → revisão manual → publish manual.

**Fase 2 — Camada de valor + gate:**
módulo `gate` ativo; geração de roteiro de narração; thumbnails com A/B.

**Fase 3 — Multi-canal:**
perfis em YAML; abrir canal novo = criar perfil + apontar fonte.

**Fase 4 — Otimização:**
loop de feedback (CTR/retenção → viral_patterns); migrar etapa 4 para build se valer.
