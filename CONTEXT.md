# CONTEXT — Agente de Produção de Canais

> Contexto de fundo para qualquer agente/desenvolvedor trabalhando neste projeto.
> Leia antes do PRD. O PRD diz *o que* construir; este doc diz *por quê* e *o que não repetir*.

---

## Por que este projeto existe

O operador construiu e operou o canal RPM Rambo (automotivo, Shorts) manualmente,
chegou a ~29 mi de views e conseguiu monetização. Após ~2 meses de AdSense, o canal
foi desmonetizado por **reused content** e não conseguiu reaplicar. Os vídeos ainda
alcançam pessoas (distribuição de Shorts independe de monetização), mas o canal foi
abandonado porque, sem retorno, manter o processo braçal não se sustentava.

A intenção agora **não** é ressuscitar o RPM Rambo, e sim **construir um método
replicável** para abrir canais novos com resultado melhor e mais rápido — eliminando
o trabalho manual que esgotou o operador na primeira vez.

## A lição central (não repetir)

O canal não caiu por ser lento de produzir. Caiu pelo **modelo de conteúdo**:
cortes de podcasts/entrevistas de terceiros (ACF, Sérgio Habib, Flow, etc.) sem
camada de valor original suficiente. A política de reused content / "inauthentic
content" do YouTube avalia o canal como um todo.

> Automatizar o braçal sem corrigir o modelo = chegar ao mesmo muro mais rápido,
> agora em N canais. Por isso o "valor original" é requisito de produto, não enfeite.

Cortes **não** são proibidos pelo YouTube. O que é exigido é comentário original
significativo, modificação substancial ou valor de entretenimento/educação. O risco
adicional do reuso cru também inclui Content ID e strikes — licenciada ou genuinamente transformada.

### Refinamento factual (o que realmente caiu, e por quê)

Registro factual para corrigir uma leitura comum e perigosa do histórico:

- **Não foram os Shorts que caíram.** Tanto a desmonetização por reused content quanto
  o strike de copyright vieram dos **vídeos longos**. Os Shorts do RPM Rambo **nunca
  foram flagrados**.
- **A causa não foi o formato "longo".** Foram os vídeos longos utilizando **mecanismo** dos shorts: fala de terceiro como
  **espinha** do vídeo (cortes de podcast/entrevista) + edição **apenas decorativa** por
  cima. Mas nas diretrizes e documentação do YouTube permite esse modelo de mecanismos nos shorts, não nos vídeos longos. Você deve saber diferenciar o modelo a ser escolhido
- **Corolário inequívoco:** como a causa é o mecanismo e **não a duração**, o **mesmo
  mecanismo aplicado a um short continua sendo reused content**. A duração **não blinda**.
  O fato de os Shorts do RPM Rambo não terem caído **não prova** que corte de terceiro
  em short é seguro — prova apenas que o **maior ofensor (os longos) existia e foi
  flagrado primeiro**. Tirar o ofensor maior não torna o menor inofensivo.

> Por isso "valor original" e "fala própria como espinha" são exigências de **mecanismo**,
> válidas para short E longo. Nenhuma peça — independente da duração — pode ter fala de
> terceiro como espinha com edição só decorativa por cima.

## O que funcionava (manter) e o que faltava (corrigir)

**Funcionava:**
- Audiência via Shorts. O ativo de tração eram os Shorts, não os vídeos longos.
- Títulos com gancho emocional (opinião, treta, "verdade escondida").
- Teste A/B de thumbnail.
- Disciplina de publicação.

**Faltava:**
- Camada de valor original (o criador como voz/ângulo, não só o clipe de terceiro).
- O ativo era a figura terceira (ACF), não o criador. No canal novo, **o ativo tem
  que ser o criador**: narração, comentário, ângulo próprio. O agente escala isso —
  não substitui.

## Padrões de viralização observados (dados reais do RPM Rambo)

Os maiores Shorts giraram em torno de:
1. **Opinião crua de figura conhecida** (os maiores hits passavam por uma figura forte).
2. **Conflito / treta** ("bateram de frente", "discutir", "cobrou", "se desentendem").
3. **"Verdade escondida" / desmascarar marca** ("X mentiu", "escondem isso de você").
4. **Nostalgia automotiva** (modelos clássicos, ídolos).

Esses padrões viram a base inicial de `viral_patterns` no perfil do canal automotivo.
Para nichos novos (ex.: felinos), começar com hipóteses e ajustar pelos dados.

## Perfil técnico do operador (premissas de implementação)

- Trabalha em Python, Cursor e Claude Code.
- Padrão de iniciar projetos com `PRD.md` + `CONTEXT.md` antes de codar.
- Já tinha script Python para download de vídeos; editava no CapCut; thumbnails no
  Canva; descrições via LLM. O agente substitui essas etapas manuais.
- Solo. Sem time. Otimizar para baixo overhead operacional e poucas mensalidades.

## Restrições e limites

- Revisão humana obrigatória antes de publicar.
- Sem evasão de Content ID, sem produção em massa de vídeos quase idênticos.
- Fonte sempre com proveniência registrada (própria / licenciada / comentário transformador).

## Glossário

- **Cérebro (brain):** módulo da Etapa 3 (Claude) que seleciona cortes, escreve o
  ângulo original e gera metadados. É o produto.
- **Mãos (hands):** Etapa 4 — corte, legenda, reframe. Mecânico.
- **Gate:** validação que bloqueia itens sem valor original.
- **Perfil de canal:** config (YAML) que define nicho, persona, padrões e estilo de um canal.
- **Camada de valor original:** narração/comentário/edição transformadora que torna o
  vídeo elegível para monetização. Requisito inegociável.
