---
description: Carrega o último arquivo de sessão salvo deste projeto (Agente Youtube) para restaurar o contexto ao abrir uma nova conversa
allowed-tools: Bash(ls:*), Read
---

Você está retomando o trabalho no projeto **Studio (Agente Youtube)** numa conversa nova.
Restaure o contexto da última sessão salva.

## Passos

1. Liste as sessões deste projeto, mais recente primeiro:
   `ls -t ~/.claude/session-data/*-agente-youtube-*-session.tmp 2>/dev/null`
2. Se não houver nenhuma, diga que não há sessão salva e siga lendo `CLAUDE.md` +
   `CONTEXT.md` + o índice de memória (`MEMORY.md`) normalmente. PARE aqui.
3. Se houver, leia o arquivo mais recente (o primeiro da lista) por completo.
4. Se o usuário passou um argumento (`$ARGUMENTS`), use-o para escolher um arquivo
   específico em vez do mais recente (casa por short-id ou data).

## O que devolver ao usuário

Um briefing curto, não o arquivo inteiro:
- **Onde paramos** — o "Próximo passo exato" da sessão salva, em destaque.
- **O que já funciona** — 2–4 bullets do "O que FUNCIONOU".
- **Não repetir** — os itens do "O que NÃO funcionou" (para não refazer erros).
- **Bloqueios** ainda abertos, se houver.
- Cite o caminho do arquivo de sessão lido.

Depois pergunte se o usuário quer seguir pelo "Próximo passo exato" ou fazer outra coisa.
