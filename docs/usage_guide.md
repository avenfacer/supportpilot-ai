# How to use SupportPilot AI

A short guide for running this demo, then using the same pattern on the next freelance project. Technical detail is in the [README](../README.md).

Northstar Shop, the customers, and the orders in this repo are **synthetic**. The identity header is for the demo only. There are no real payments, refunds, or emails.

## What this system does

One message comes in. The model only **proposes one tool**. The application validates it, checks identity, runs the tool, then validates the result.

| Customer request | What happens |
| --- | --- |
| Policy / FAQ question | The answer comes only from document chunks that were found, plus citations. Weak evidence → refuse to answer. |
| Order status | Data from the order API, after an ownership check. The answer is assembled from that data. The model does not write it. |
| Return or cancellation | A `pending_human_review` ticket. Nothing is executed. |
| Out of scope, asks for a human, or a sensitive topic | Handoff or abstain. |

Response statuses: `answered`, `needs_clarification`, `handoff`, `tool_error`, `unsupported`.

## Running it

Docker (fastest):

```bash
docker compose up -d --build
curl http://localhost:8000/ready
uv run python scripts/demo_requests.py
```

API docs are at <http://localhost:8000/docs>. The default uses the **fake** provider (offline, free). For OpenAI, set `LLM_PROVIDER=openai`, `EMBEDDING_PROVIDER=openai`, and `OPENAI_API_KEY` in `.env`, then restart Compose.

Without the full Compose stack (database only):

```bash
cp .env.example .env
uv sync
docker compose up -d db
uv run alembic upgrade head
uv run python scripts/seed_demo_data.py
uv run python scripts/ingest_knowledge.py
uv run uvicorn app.main:app --reload
```

On PowerShell use `curl.exe`, or just run `scripts/demo_requests.py`. A sample response is recorded in [demo_transcript.md](demo_transcript.md).

## Using the API

Demo identity is the `X-Demo-Customer-Id` header (`CUST-001`, `CUST-002`, `CUST-003`). Anyone can claim to be a demo customer. The ID is never read from the message body.

| Customer | Orders |
| --- | --- |
| `CUST-001` | `ORD-1001` delivered, `ORD-1002` shipped, `ORD-1003` processing |
| `CUST-002` | `ORD-2001` delivered, `ORD-2002` cancelled |
| `CUST-003` | `ORD-3001` out for delivery |

```bash
# FAQ with citations
curl.exe -s localhost:8000/api/v1/chat -H "Content-Type: application/json" -d "{\"message\": \"How long does standard shipping take?\"}"

# Own order
curl.exe -s localhost:8000/api/v1/chat -H "Content-Type: application/json" -H "X-Demo-Customer-Id: CUST-001" -d "{\"message\": \"Where is order ORD-1002?\"}"

# Someone else's order: same response as an order that does not exist
curl.exe -s localhost:8000/api/v1/chat -H "Content-Type: application/json" -H "X-Demo-Customer-Id: CUST-002" -d "{\"message\": \"Where is order ORD-1002?\"}"

# Return: a pending ticket, nothing executed
curl.exe -s localhost:8000/api/v1/chat -H "Content-Type: application/json" -H "X-Demo-Customer-Id: CUST-001" -d "{\"message\": \"I want to return ORD-1001, the bottles leak\"}"
```

Check a ticket: `GET /api/v1/tickets/{ticket_id}` with the same customer header. Admin endpoints (`/api/v1/knowledge/*`) stay off until `ENABLE_ADMIN_ENDPOINTS=true` and `ADMIN_TOKEN` is set.

Before demoing to someone else:

```bash
uv run pytest
uv run python scripts/run_evals.py
```

Tests do not call a paid API. Live evals (`--live`) only when there is an OpenAI key and a budget.

## Limits you should not loosen

These are what make the system safe, not the prompt:

- The model never touches the database or an API. Only tools on the allowlist (`app/tools/`).
- Identity comes from a request that has already been verified, not from the model's arguments.
- Someone else's order looks the same as an order that does not exist.
- Tickets are always `pending_human_review`. There is no method that changes status.
- A policy answer with no valid citation, or with a number that is not in the cited text, is replaced with an abstain.
- Errors returned to the client contain no prompt, stack trace, or input contents.

## Reusing it for a freelance client

Copy this repo as a template. Change the **business content**. Leave the **safety shape** as it is.

One engagement, the same order of work:

1. **Set the scope.** Three things only: answer from documents, read data through a tool, and turn consequential actions (refund, cancel, change an account) into a ticket. Refuse anything outside that in the proposal.
2. **Replace the knowledge.** Delete the Northstar markdown in `data/knowledge_base/` and put in the client's policies (shipping, returns, warranty, escalation). One topic per file. Then `uv run python scripts/ingest_knowledge.py`. Re-ingesting is safe to repeat; changing the embedding model re-embeds everything.
3. **Replace the order data.** For a demo, edit `data/demo/store.json` and run `scripts/seed_demo_data.py`. For production, write a new HTTP client that follows the `OrderClient` protocol. The order service and the ownership check do not need to be rewritten.
4. **Replace identity.** The demo uses `X-Demo-Customer-Id` and `ENABLE_DEMO_AUTH=true`. For a real client, change the dependency in `app/core/security.py` so it reads a session or a JWT, then turn demo auth off. Services below it only accept a `CustomerContext`.
5. **Rewrite the evals from the client's cases.** In `evals/cases.jsonl`, rebuild at least these categories: direct FAQ, paraphrase, similar policies, out-of-scope question, successful order, someone else's order, order API failure, return/cancel (pending ticket), ask for a human, prompt injection. Check the outcome and leakage, not the exact sentence.
6. **Measure offline first, then live.** `uv run pytest` and `uv run python scripts/run_evals.py` must pass at no cost. Only then `--live` with the client's model. If many paraphrases fail, raise embedding quality. Do not lower the threshold until off-topic answers start passing. Record the numbers and the limits (see [evals/README.md](../evals/README.md)).
7. **Hand over something someone else can run.** A README for how to run it, a demo transcript, metrics, and a list of what was left out on purpose (multi-turn memory, rate limiting, UI, a back office for approving tickets).

What usually moves with the client, and what stays:

| Changed per client | Stays |
| --- | --- |
| Knowledge-base files, shop name, order data | Tool allowlist, strict schema, ownership check |
| Order API adapter and login | Ticket status cannot be changed by the model |
| Eval cases and the retrieval threshold | Citation and number validation |
| LLM provider via env | Fake provider for tests |

Do not add a tool that executes a refund, cancels an order, or changes ticket status. If the client asks for that action, add a human approval queue, not a new tool for the model.
