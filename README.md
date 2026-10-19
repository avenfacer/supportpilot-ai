# SupportPilot AI

A grounded AI customer-support assistant for **Northstar Shop**, a fictional online store. It answers policy questions with citations from retrieved documents (RAG), looks up orders through a typed tool with server-side authorization, and prepares return and cancellation requests as **pending tickets for human review**. It never executes those requests itself.

> **Demo project.** Northstar Shop, its policies, customers, and orders are synthetic. Identity uses a **demo-only** request header (see [Demo identity](#demo-identity-demo-only)). No real payments, refunds, emails, or customer data are involved.

Built with FastAPI, PostgreSQL + pgvector, SQLAlchemy 2 + Alembic, Pydantic, and a provider-agnostic LLM layer (OpenAI or a deterministic offline fake).

## Highlights

- **Cited RAG answers.** Answers come only from retrieved chunks. Citations are checked against the actual retrieval results, and answers containing numbers that are absent from the cited text are rejected.
- **Abstains instead of guessing.** Low-relevance retrieval, insufficient evidence, or conflicting policy text produces `unsupported` or `handoff`, never a made-up answer.
- **Tool calling with a fixed allowlist.** The model *proposes* one tool call. The application validates it against strict Pydantic schemas (unknown fields such as `customer_id` are rejected), enforces identity and ownership, executes it, and validates the tool output.
- **Authorization outside the model.** Order and ticket access is checked against the trusted request identity. Another customer's order gets the same response as a non-existent one.
- **Human approval is structural.** Tickets are always created as `pending_human_review`, and no code path lets the model change a ticket's status.
- **Safe failure.** Order API timeouts and outages, LLM timeouts, malformed model output, and ticket-store failures each map to a stable, client-safe response.
- **Measured.** 130 automated tests (unit, Postgres integration, evaluation regression) and a 49-case evaluation set with published metrics and limitations.

## Architecture

```mermaid
flowchart TD
    Client[API client] --> Routes["FastAPI routes (/api/v1)"]
    Routes --> Identity["Demo identity dependency"]
    Routes --> ChatService[ChatService]
    ChatService --> Orchestrator[SupportOrchestrator]
    Orchestrator --> Guardrails["Guardrails: injection, human request, sensitive topics"]
    Orchestrator --> Planner["LLM planner: proposes one tool"]
    Planner --> Registry["Tool registry: allowlist + schema validation"]
    Registry --> Knowledge["search_knowledge"]
    Registry --> OrderTool["lookup_order"]
    Registry --> RequestTool["create_support_request"]
    Registry --> HandoffTool["request_human_handoff"]
    Knowledge --> Retrieval["RetrievalService: threshold + quarantine"]
    Retrieval --> PG[("PostgreSQL + pgvector")]
    Knowledge --> Answerer["GroundedAnswerer: JSON answer + citation validation"]
    OrderTool --> OrderService["OrderService: ownership check, retries"]
    RequestTool --> OrderService
    OrderService --> MockAPI["MockOrderClient (synthetic data)"]
    RequestTool --> Tickets["TicketService: pending_human_review only"]
    HandoffTool --> Tickets
    Tickets --> PG
    Answerer --> LLM["LLM provider adapter (OpenAI or fake)"]
    Planner --> LLM
```

| Layer | Location | Responsibility |
| --- | --- | --- |
| Routes | `app/api/` | HTTP concerns only: validation, status codes, dependency wiring |
| Orchestration | `app/ai/orchestrator.py` | Guardrails, tool dispatch, mapping results to responses |
| Grounding | `app/ai/grounded_answer.py` | Prompt assembly, output parsing, citation and number checks |
| Providers | `app/ai/*_provider.py`, `app/ai/fake_*.py` | Vendor SDK code isolated behind interfaces |
| Tools | `app/tools/` | Fixed registry and typed argument schemas |
| Services | `app/services/` | Ingestion, retrieval, orders (authorization), tickets, chat |
| Repositories | `app/repositories/` | SQL (pgvector) and in-memory implementations of the same protocols |
| Prompts | `app/ai/prompts/*_v1.md` | Versioned prompt templates, separate from code |

Chat response statuses are `answered`, `needs_clarification`, `handoff`, `tool_error`, and `unsupported`.

## Quick start (Docker)

Requirements: Docker with Compose.

```bash
docker compose up -d --build
```

This starts PostgreSQL with pgvector, applies migrations, seeds synthetic customers and orders, ingests the knowledge base (all idempotent), and serves the API on <http://localhost:8000>. Interactive API docs are at <http://localhost:8000/docs>.

```bash
curl http://localhost:8000/ready
uv run python scripts/demo_requests.py   # runs the demo scenarios (or use the curl examples below)
```

By default it uses the free, offline **fake** providers. To use OpenAI, set `LLM_PROVIDER=openai`, `EMBEDDING_PROVIDER=openai`, and `OPENAI_API_KEY` in your shell or a `.env` file, then rerun `docker compose up -d --build`. Ingestion re-embeds automatically when the embedding model changes.

## Local development

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and Docker (for PostgreSQL).

```bash
cp .env.example .env                          # adjust if needed
uv sync                                       # install dependencies (incl. dev tools)
docker compose up -d db                       # PostgreSQL + pgvector on localhost:5433
uv run alembic upgrade head                   # create schema
uv run python scripts/seed_demo_data.py       # synthetic customers and orders
uv run python scripts/ingest_knowledge.py     # chunk + embed + store the knowledge base
uv run uvicorn app.main:app --reload          # http://localhost:8000/docs
```

### Configuration

All settings are environment variables (or `.env`), validated at startup by `app/core/config.py`. See [`.env.example`](.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | local Compose DB | PostgreSQL connection (psycopg 3 driver) |
| `LLM_PROVIDER` / `EMBEDDING_PROVIDER` | `fake` | `fake` (offline, deterministic) or `openai` |
| `OPENAI_API_KEY` | empty | Required when an OpenAI provider is selected |
| `OPENAI_CHAT_MODEL` / `OPENAI_EMBEDDING_MODEL` | `gpt-4o-mini` / `text-embedding-3-small` | OpenAI models (embeddings are 1536-d, fixed by the schema) |
| `LLM_TIMEOUT_SECONDS` / `EMBEDDING_TIMEOUT_SECONDS` | `20` | Provider request timeouts |
| `ORDER_API_TIMEOUT_SECONDS` / `ORDER_API_MAX_ATTEMPTS` | `3` / `2` | Order API timeout and retry budget (reads only) |
| `MOCK_ORDER_FAILURE_MODE` | `none` | Simulate `timeout` or `unavailable` for demos and tests |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `120` | Chunking (characters) |
| `RETRIEVAL_TOP_K` / `RETRIEVAL_MIN_SCORE` | `4` / per provider | Retrieval depth and relevance threshold (fake 0.15, OpenAI 0.3) |
| `ENABLE_DEMO_AUTH` | `true` | Trust the demo identity header (disable outside demos) |
| `ENABLE_ADMIN_ENDPOINTS` / `ADMIN_TOKEN` | `false` / empty | Expose ingestion and source listing over HTTP (token required) |

## API usage

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness |
| `GET` | `/ready` | Database and pgvector checks (503 when not ready) |
| `POST` | `/api/v1/chat` | Submit a support message |
| `GET` | `/api/v1/orders/{order_id}` | Order lookup for the signed-in customer |
| `GET` | `/api/v1/tickets/{ticket_id}` | Ticket lookup for its owner |
| `POST` | `/api/v1/knowledge/ingest` | Admin only, disabled by default |
| `GET` | `/api/v1/knowledge/sources` | Admin only, disabled by default |

```bash
# Cited FAQ answer
curl -s localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -d '{"message": "How long does standard shipping take?"}'

# Order lookup as the owner, then as another customer (same response as a missing order)
curl -s localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -H "X-Demo-Customer-Id: CUST-001" -d '{"message": "Where is order ORD-1002?"}'
curl -s localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -H "X-Demo-Customer-Id: CUST-002" -d '{"message": "Where is order ORD-1002?"}'

# Return request: creates a pending_human_review ticket, nothing is executed
curl -s localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -H "X-Demo-Customer-Id: CUST-001" -d '{"message": "I want to return ORD-1001, the bottles leak"}'
curl -s localhost:8000/api/v1/tickets/TKT-XXXXXXXX -H "X-Demo-Customer-Id: CUST-001"

# Unsupported question: abstains and offers a human
curl -s localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -d '{"message": "Do you sell laptops?"}'
```

On Windows PowerShell, use `curl.exe` and escape the inner quotes, or run `uv run python scripts/demo_requests.py`. Full captured responses are in [`docs/demo_transcript.md`](docs/demo_transcript.md).

Errors use a stable, safe shape. Raw prompts, provider messages, submitted input values, and stack traces are never returned:

```json
{"error": {"code": "ai_temporarily_unavailable", "message": "The support assistant is temporarily unavailable...", "request_id": "3f2a..."}}
```

### Demo identity (DEMO-ONLY)

Requests act as a synthetic customer via the `X-Demo-Customer-Id` header (`CUST-001`, `CUST-002`, `CUST-003`). **Anyone can claim any demo customer.** This exists only so reviewers can test authorization. The customer ID is never read from the message body (extra fields are rejected) or from model-generated tool arguments.

In production, `get_optional_customer` in `app/core/security.py` would be replaced by a dependency that verifies a session or an OIDC/JWT access token and derives the customer ID from verified claims. Nothing downstream changes, because services only receive a `CustomerContext`.

Synthetic orders: `CUST-001` owns `ORD-1001` (delivered), `ORD-1002` (shipped), and `ORD-1003` (processing). `CUST-002` owns `ORD-2001` (delivered) and `ORD-2002` (cancelled). `CUST-003` owns `ORD-3001` (out for delivery).

## Testing

```bash
uv run pytest                     # unit + evaluation tests; integration tests skip without a DB
uv run ruff check . && uv run ruff format --check . && uv run mypy

# Integration tests against PostgreSQL + pgvector (uses the supportpilot_test database)
docker compose up -d db
TEST_DATABASE_URL=postgresql+psycopg://supportpilot:supportpilot@localhost:5433/supportpilot_test uv run pytest
# PowerShell: $env:TEST_DATABASE_URL="postgresql+psycopg://supportpilot:supportpilot@localhost:5433/supportpilot_test"; uv run pytest
```

The suite has 130 tests and never calls a paid API. Provider adapters are tested with stub SDK clients, and chat flows use the deterministic fake providers or scripted test doubles.

| Area | Examples |
| --- | --- |
| RAG | Chunk metadata, idempotent re-ingestion, re-embedding on model change, embedding failure leaves no partial data, threshold refusal, citation filtering, number grounding |
| Tools | Unknown tools, malformed JSON, extra fields (`customer_id`, `status`), oversized arguments |
| Authorization | Cross-customer orders and tickets, missing or invalid identity, model-supplied identity ignored |
| Workflow | Tickets always `pending_human_review`, already-cancelled orders, shipped-order cancellation, ticket-store failure |
| Failures | Order API timeout/outage with retry, LLM timeout, malformed model output, unhandled exceptions |
| Injection | User-message overrides, poisoned knowledge-base document quarantined, delimiter escaping |
| Ops | Log redaction (keys, emails, phones), config validation, admin endpoint gating |

## Evaluation

```bash
uv run python scripts/run_evals.py          # offline, deterministic
uv run python scripts/run_evals.py --live   # OpenAI (paid)
```

Current offline results (fake providers, 49 cases): **45/49 pass**. Citation validity, grounded answer rate, unsupported-question abstention, tool success, and authorization are all **100%**. Retrieval Recall@4 is **88.9%**. All failures are paraphrases that the lexical fake embedder cannot match; in most of them the system abstained rather than guessed. The method, metrics, threshold sweep, and limitations are in [`evals/README.md`](evals/README.md), and the full report is in [`evals/results.md`](evals/results.md).

## Design decisions

These resolve the open decisions in the specification.

- **Providers.** OpenAI (`gpt-4o-mini`, `text-embedding-3-small`) behind `LLMProvider` / `EmbeddingProvider`, plus deterministic fakes so the app, tests, and evals run offline at no cost. The LLM interface is task-level (`plan`, `generate_answer`) and returns raw output; parsing and validation stay in application code.
- **Mock order API.** A service module in the same app (`MockOrderClient` behind an `OrderClient` protocol) backed by the synthetic `orders` table, with injectable failure modes. A real integration would implement the same protocol with an HTTP client.
- **Authentication.** A clearly labeled demo header, isolated in one dependency (see above).
- **Order summaries are templated, not generated.** Order answers are built from validated tool output, so the model cannot invent a tracking number or date.
- **Retrieval.** Exact cosine search in pgvector (the corpus is tens of chunks), with chunk size 800, overlap 120, top-k 4, and a per-provider threshold chosen from an evaluation sweep. Hybrid search and reranking were not added because there was no measured need yet. Add an HNSW index once the corpus grows.
- **Workflow.** Explicit Python orchestration (one tool per turn) instead of LangGraph, since the flow is not yet meaningfully stateful. Conversations are stateless; `conversation_id` is echoed back but nothing is stored.
- **Ingestion.** Idempotent via a fingerprint of the content, embedding model, and chunking settings. Documents removed from disk are pruned, and a failed re-ingestion never deletes the existing version.
- **Rate limiting (production plan).** Not implemented in the demo. In production, enforce per-customer and per-IP limits at the API gateway or with Redis (token bucket on `/api/v1/chat`), and cap tokens per conversation.

## Security and privacy notes

- Secrets come only from the environment; `.env` is git-ignored and only `.env.example` is committed.
- Structured JSON logs carry a request ID and redact API keys, bearer tokens, emails, and phone numbers. Message text is not logged; ticket reasons and summaries are redacted and truncated.
- Retrieved text is wrapped in `<untrusted_reference>` tags with delimiters escaped. Chunks that look like injected instructions are quarantined before reaching the model.
- The database role in Compose is the owner role for convenience. In production, the app should use a least-privilege role (DML on app tables only) and migrations should run with a separate role.

## Project structure

```text
app/
  ai/            orchestrator, grounding, prompts, provider adapters, safety heuristics
  api/           health + /api/v1 routes, dependency wiring
  core/          settings, logging/redaction, errors, demo identity
  db/            engine/session, Alembic migrations
  evaluation/    offline evaluation harness
  models/        SQLAlchemy models
  repositories/  SQL (pgvector) and in-memory repositories
  schemas/       Pydantic request/response/domain models
  services/      chunking, ingestion, retrieval, orders, tickets, chat
  tools/         tool registry and typed tool schemas
data/            synthetic knowledge base and demo store data
docs/            case study and demo transcript
evals/           evaluation cases, results, and methodology
scripts/         seed, ingest, evaluation, and demo CLIs
tests/           unit, integration (Postgres), evaluation regression
```

## Limitations and future work

- Published metrics use the fake providers; live OpenAI evaluation results still need to be generated and published (`--live`).
- The offline embedder is lexical, so paraphrases with different vocabulary are missed. A semantic embedding model is expected to close most of this gap.
- Injection detection is heuristic. The real guarantees come from the structural boundaries (allowlist, ownership checks, fixed ticket status), not from the regexes.
- No multi-turn memory, so the assistant asks for the order ID again on each turn.
- Next steps: live evaluation and an OpenAI threshold sweep, an optional hybrid keyword + vector retrieval comparison, a back-office endpoint for agents to approve or reject tickets (human-authenticated), rate limiting, tracing, and a small UI.

See [`docs/case_study.md`](docs/case_study.md) for the portfolio case study.
