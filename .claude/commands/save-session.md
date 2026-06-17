---
description: Salva o estado da sessão atual em ~/.claude/session-data/ para retomar o contexto numa próxima conversa, sem repetir erros nem perder decisões
argument-hint: "[short-id opcional]"
allowed-tools: Bash(date:*), Bash(mkdir:*), Bash(ls:*), Write
---

Você vai salvar o estado desta sessão de trabalho no projeto **Studio (Agente Youtube)**
para que uma próxima conversa retome o contexto sem perder nada.

## Onde salvar

- Diretório canônico: `~/.claude/session-data/` (crie com `mkdir -p` se não existir).
- Nome do arquivo: `YYYY-MM-DD-agente-youtube-<short-id>-session.tmp`
  - Use a data de hoje (rode `date +%F`).
  - `<short-id>`: use o argumento `$ARGUMENTS` se fornecido; senão gere um slug curto
    (letras/dígitos/hífen, 8+ chars) que resuma o foco da sessão.
  - O prefixo `agente-youtube` é obrigatório — é o que separa as sessões deste projeto
    das de outros projetos no diretório global.

## O que escrever (TODAS as seções são obrigatórias)

Preencha com conteúdo HONESTO e específico, lido do que realmente aconteceu nesta
conversa. Se uma seção não tiver conteúdo, escreva "Nada nesta sessão" — nunca omita a
seção.

1. **O que estamos construindo** — 1–3 parágrafos com o objetivo e o contexto do sistema.
2. **O que FUNCIONOU** — itens confirmados com evidência específica (teste passou, comando
   rodou, API retornou, arquivo gerado). Cite o comando/saída quando houver.
3. **O que NÃO funcionou** — cada abordagem que falhou + o motivo exato da falha.
   > Esta é a seção MAIS crítica: sem ela, a próxima sessão repete cegamente os mesmos
   > erros. Seja específico (ex.: "modelo claude-sonnet-4-6 rejeita prefill de assistant").
4. **O que ainda NÃO foi tentado** — abordagens promissoras ainda não exploradas.
5. **Estado atual dos arquivos** — tabela: arquivo | status (Completo / Em progresso /
   Quebrado / Não iniciado) | nota curta.
6. **Decisões tomadas** — escolhas de arquitetura e o PORQUÊ de cada uma.
7. **Bloqueios e perguntas em aberto** — pendências que precisam de atenção na próxima sessão.
8. **Próximo passo exato** — a ÚNICA ação mais crítica para retomar (concreta, acionável).

## Regras

- Respeite as travas e a lição do projeto (ver `CLAUDE.md`/`CONTEXT.md`): não registre
  nada que sugira afrouxar as travas de proveniência.
- Nunca escreva chaves de API, segredos ou o conteúdo do `.env` no arquivo de sessão.
- Ao terminar, imprima o caminho completo do arquivo salvo e um resumo de 3 linhas.
