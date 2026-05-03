# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

P-JARI SC is a Django app that assists judges of the JARI (Junta Administrativa de Recursos de Infrações) in Santa Catarina with traffic-violation appeals. The core value is a multi-phase "Assessor JARI" engine that ingests scanned process PDFs, runs admissibility/prescription/decadence calculations, drafts theses analysis, and produces a final legal opinion (parecer técnico).

The legal logic lives in `logica-pjari_v2.md` (current spec) and `logica_jari.md` (older reference). Treat these — plus `Jornada_Pjari.md` — as the source of truth for *what* the engine should compute. Never invent dates, norms, or conclusions; the system is "criatividade proibida, inferência proibida".

## Common commands

Use the local venv (`source venv/bin/activate`) before running any Python command.

```bash
# Dev server (Django)
python manage.py runserver

# Celery worker (dev: uses watchmedo to auto-reload on .py changes)
bash start_worker.sh

# Celery beat (scheduler — currently runs the daily engine self-test cron)
bash start_beat.sh

# Tailwind build (output → chat/static/css/tailwind.css, gitignored)
npm run build:css

# Migrations
python manage.py migrate
python manage.py makemigrations chat

# Tests — Django runner (no pytest config in repo)
python manage.py test                                # full suite
python manage.py test chat.tests.test_fases -v 2     # single module
python manage.py test chat.tests_jari_math -v 2      # date-math regression suite

# Daily health check / WhatsApp metrics cron
python manage.py run_daily_cron [--force_e2e]
```

In production (Railway / Docker), `start.sh` runs Gunicorn ASGI with the Uvicorn worker (SSE needs non-blocking IO). The worker uses two queues — `fast` (phases 1–4) and `heavy` (phase 5 `gerar_parecer`) — split across `start_worker_fast.sh` / `start_worker_heavy.sh`. `release.sh` is the Railway Release Command and runs migrations + ensures the superuser/Site/SocialApp once before any replica boots.

## Architecture

### The phase engine (`chat/engine/`)

`JariEngine` (in `chat/engine/__init__.py`) is a thin dispatcher over `phase_N.py` modules — never put phase logic in the dispatcher. `chat/jari_engine.py` is a backward-compat stub re-exporting from `chat/engine/`; do **not** add new code there.

Phases are tracked on `Parecer.status_fase` (see the mapping comment in [chat/models.py:25-34](chat/models.py#L25)). Half-step states (`10`, `31`, `41`) mean "aguardando confirmação do julgador" — the user must click OK before the engine advances. The constants are exported from `chat.engine` (e.g. `FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE = 31`).

Important separation:
- **Deterministic math lives in [chat/jari_math.py](chat/jari_math.py)** (tempestividade, prescrição punitiva 5y, prescrição intercorrente 3y, decadência with COVID-19 256-day window). LLMs never compute dates — they only extract them.
- **Phase 31/41 stores both the engine flag and the `julgador_*` override** on `Parecer`. From phase 4 onward, **always read the `julgador_*` field** as the source of truth — the IA-computed `is_*`/`has_*` flags are only the initial suggestion.
- **`tipo_penalidade`, `tem_flagrante`, `data_conhecimento_infracao`, `data_totalizacao_pontos`** drive Filter 2/3 branches in `JariMath.check_decadencia` / `check_prescription_punitiva`. When changing those rules, update `tests_jari_math.py` and `tests/test_fases.py`.

### LLM integrations (`chat/integrations/`)

Four providers, each with a single responsibility:
- **`gemini.py`** — extraction (Fase 1 autopreenchimento), DIR matching, and final `parecer_final` synthesis. Uploads PDFs to Gemini Files API, polls until `ACTIVE`. Field-size limits in `_LIMITES` are tuned to fit the prompt window.
- **`vertex.py`** — RAG against the "Inventário Normativo" data store (Discovery Engine). Results are cached in Redis for 24h via `_rag_cache_key`. This is the "GPS" — never bypass it for legal references.
- **`perplexity.py`** — open-web jurisprudence search, used as supplementary evidence after Vertex.
- **`anthropic.py`** — phase 6 audit/blindagem scoring and feedback loop.

Prompts for phases 3–5 are in `chat/prompts/phase_N.py`. Keep prompts there; never inline them in `engine/` or `tasks.py`.

### Async pipeline (`chat/tasks.py` + Celery)

The user-visible flow is synchronous-looking but each phase is a Celery task because Gemini PDF polling can take 60–90s and would trip Gunicorn's worker timeout. Routing:

- **`fast` queue** (concurrency 16): `processar_fase1_task`, `processar_fase2_task`, `processar_fase3_admissibilidade_task`, `processar_fase3_precompute_task`, `processar_fase4_task`, `processar_fase4_analise_task`. `time_limit=360–480s`, `max_retries=3`.
- **`heavy` queue** (concurrency 8): `gerar_parecer_task` only — phase 5 final synthesis. `time_limit=600s`, `max_tasks_per_child=20` to recycle workers and free Gemini SDK memory.
- **Beat**: `rodar_testes_engine_task` runs every 6h to detect regressions in the math/engine.

Transient Gemini errors (504, `DEADLINE_EXCEEDED`, timeout) are detected by `_is_gemini_transient` and retried with 30s/60s/90s backoff. Soft-time-limit exceptions degrade gracefully to manual-flow prompts — preserve that pattern when adding new phases.

After every task, `task_postrun` closes idle Postgres connections (`config/celery.py`); the workers connect to a managed Postgres on Railway and would otherwise exhaust the client pool.

The frontend reads task progress via SSE at `/chat/stream/<task_id>/` (see `views/chat.py`); plain JSON polling is also available at `/chat/task-status/<task_id>/`.

### Auth duality (Allauth + Clerk)

The project runs **both** `django-allauth` (email/password + Google) and a **Clerk** middleware (`chat.middleware_clerk.ClerkAuthenticationMiddleware`) that authenticates JWTs from a Clerk frontend. They coexist — Clerk creates/links Django users via `chat/webhooks_clerk.py`, and `chat.middleware.RequireTermsAcceptanceMiddleware` runs *after* Clerk to gate access on `legal.AceiteDocumentoLegal`.

Order matters in `MIDDLEWARE`: Clerk must run before `RequireTermsAcceptance` (see comments in `config/settings.py`).

### Models worth knowing

`Parecer` (chat/models.py) is the central record — every phase reads/writes its fields. Other apps point at it: `ParecerFinal` holds the post-edit TinyMCE HTML (use `Parecer.conteudo_final` to read the canonical version, never lookup directly). `AuditEvent` / `AiRequestLog` provide the trail for the "Estatísticas Gerais" dashboard. `BancoTese` is the citations bank (community + private). `legal.DocumentoLegal` + `AceiteDocumentoLegal` back the Terms-of-Use gate.

### Storage

`USE_GCS` defaults to `not DEBUG`. In production, uploads (`Parecer.*_pdf_path`) hit a GCS bucket (`pjari-midias`) via `django-storages`; signed URLs expire in 24h. Static files always go through WhiteNoise — there's a custom `TolerantWhiteNoiseStorage` in `config/custom_storage.py` to swallow missing-manifest errors. `collectstatic` runs at Docker build time, not at startup.

### Observability

- **Sentry** is configured in `config/settings.py` with custom `_sentry_before_send` that drops 404/403, plus tags every Celery task with `parecer_id`/`pa`/`sgpe` (see `_sentry_task_context` in `tasks.py`). Performance traces sample at 20% in prod.
- **`django-silk`** is opt-in via `SILK_ENABLED=True` env var; never auto-enabled in DEBUG. Mounted at `/silk/`, requires `is_staff`.
- **Health**: `/health/` checks DB + Redis and is exempt from `SECURE_SSL_REDIRECT` for Railway healthchecks.
