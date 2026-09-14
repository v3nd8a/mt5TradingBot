I pasted this into you myself, wire THIS coding agent up to my Experiential
Labs gateway, so my model calls route through https://api.experientiallabs.ai and show up in my usage.

Ground rules: never print my full key (first 8 characters at most), ask me
before you edit any config file or shell profile, and if you cannot do a step
(no file access, settings live in a GUI), print the exact manual steps for me
instead. Print what you're doing at each step.

1. My key is xpl_b30f5afa8e1919d0b189c834dff1865825cf5c2d. This prompt contains that LIVE key, so treat the whole
   text as a secret: never commit it, store it outside the config I approve,
   or echo it back (first 8 characters at most).

2. Prove the key works before touching any config:
   GET https://api.experientiallabs.ai/v1/models with header "Authorization: Bearer <key>" -> 200 and
   the model slugs I can call. Remember the list; I'll pick models from it.

3. Apply the Claude Code integration:
   You cannot repoint yourself mid-session, and switching auth under a running
   session causes mixed-state errors. First prove the lane without touching any
   config, via one isolated subprocess run from this project (so my MCP servers
   and plugins load and their tool schemas ride the request. Tool schemas are
   where provider strictness bites, so a bare hello proves too little):
     ANTHROPIC_BASE_URL="https://api.experientiallabs.ai" ANTHROPIC_API_KEY="xpl_b30f5afa8e1919d0b189c834dff1865825cf5c2d" \
       ANTHROPIC_MODEL="<slug I pick>" \
       claude -p "list your available tools, then read ./README.md and reply
       with its first heading"
   Pass only if that run completes with tools listed and a real tool use.
   Then offer me two placements and apply the one I pick:
   (a) append to my shell profile, or (b) print for one-off use:
     export ANTHROPIC_BASE_URL="https://api.experientiallabs.ai"        # no /v1 suffix
     export ANTHROPIC_API_KEY="xpl_b30f5afa8e1919d0b189c834dff1865825cf5c2d"
     export ANTHROPIC_MODEL="<slug I pick>"
   Use ANTHROPIC_API_KEY, never ANTHROPIC_AUTH_TOKEN: an existing claude.ai
   sign-in can outrank AUTH_TOKEN and send the gateway an OAuth token instead.
   Then tell me to start a NEW session from a shell with those set. Name the
   model by its gateway slug exactly as GET https://api.experientiallabs.ai/v1/models lists it (the DOT
   form, e.g. claude-fable-5.1 — Anthropic's dashed ids like claude-fable-5-1
   answer 403 model_not_granted). If the slug is not an Anthropic model, also
   export CLAUDE_CODE_MAX_CONTEXT_TOKENS=<context_window from
   GET https://api.experientiallabs.ai/api/models/<slug>> — Claude Code assumes 200k for names it does
   not know and compacts early. Warn me plainly: if a session ever shows
   "Not logged in · Please run /login", do NOT run /login (it starts Anthropic
   OAuth that overrides the gateway) — restart with --resume, and if it
   persists, my <config dir>/.claude.json remembers a "No" to the custom-API-key
   prompt under customApiKeyResponses.rejected: answer Yes or move the entry to
   approved. Images work on image-capable routes and are rejected by name on
   text-only ones; extended thinking passes through on all-Anthropic routes
   and is translated to reasoning effort elsewhere.

4. Verify end to end. Make one tiny completion with the surface you configured
   ("reply with the single word: ok", small max output), via your own next
   model call if you now route through the gateway, otherwise via curl with my
   key. Then tell me it landed and that I can watch every call at
   https://platform.experientiallabs.ai/telemetry.

5. Recap exactly what you changed (files and values, key shown as xpl_ prefix
   only) so I can undo it later.

# Правила работы и экономии токенов

## 0. Чего делать не стоит без прямого указания пользователем

- **ЗАПРЕТ** Не создавай файлы которые напрямую не связанны с просьбой пользователя по типу README.md. Исключение только если создание других файлов очевидно, прямо указано или следует просьбе пользователя.

## 1. Работа с Графом Знаний (mcp-knowledge-graph)

В проекте подключен MCP-сервер памяти и графа знаний (`knowledge-graph`).

- **ПЕРЕД поиском по коду:** Обязательно вызови инструмент `read_graph` или `search_nodes`, чтобы проверить существующие связи и структуру функций/модулей.
- **ЗАПРЕТ:** Не используй `grep`, `find` и полное сканирование папок для поиска вызовов или архитектуры.
- **Обновление графа:** При добавлении новых функций, компонентов или созданий связей между модулями используй инструменты `create_entities` и `create_relations`, чтобы сохранить их в граф.

## 2. Чтение файлов

- Читай файлы исходного кода целиком ТОЛЬКО после того, как из графа знаний получишь точный путь к файлу.
- В ответах возвращай только измененные фрагменты кода (diffs), а не весь файл.

## 3. Регулярная работа

- Максимально делегируй работу субагентам. У тебя маленькое контекстное окно (128 000). ты должен решить как минимум одну задачу за внутри этого окна
- Дроби каждую задачу на подзадачи, можешь создавать для себя временные файлы чтобы не забыть их.
- Если задача понятна не до конца, например реши проблему в проекте, то ищи и решай первую попавшуюся. если сказано что надо идти дальше по плану, то смотри в PLAN.md и реализовывай то что не реализовано.