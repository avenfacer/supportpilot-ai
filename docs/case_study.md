# Case study: SupportPilot AI

**One line:** a grounded customer-support agent with cited RAG, secure order-lookup tools, and human-approved return and cancellation workflows, built with FastAPI, PostgreSQL/pgvector, and automated evaluation.

## Problem

Support chatbots fail in predictable ways. They invent policy details, guess order statuses, reveal data across accounts, and "complete" refunds they have no authority over. The goal was an assistant for a fictional store (Northstar Shop) that is useful for routine questions and **safe by construction** for everything else. When it cannot ground an answer or lacks permission, it says so and hands off to a human.

## Approach

1. **Treat the LLM as an untrusted planner.** For each message the model proposes exactly one tool from a fixed registry. The application validates the proposal with strict schemas (unknown fields rejected), resolves identity from the request context, enforces ownership, executes the tool, and validates its output. Arbitrary function names, SQL, URLs, and model-chosen customer IDs never execute.
2. **Ground every policy claim.** Knowledge answers are generated only from retrieved chunks, with the model's output constrained to a JSON contract. Citations the retriever did not return are dropped. An answer with no valid citations, or with numbers that do not appear in the cited text, is replaced by an abstention.
3. **Keep consequential actions human.** Returns and cancellations become tickets in `pending_human_review`. The ticket service has no status-transition method, so no prompt can approve anything.
4. **Fail loudly and safely.** Order API outages and timeouts (retried once, since reads are idempotent), LLM timeouts, malformed model output, and storage failures each map to a distinct, client-safe outcome. The assistant never claims a ticket exists unless it was persisted.

## Architecture

FastAPI routes handle HTTP only. A `ChatService` wraps the `SupportOrchestrator`, which runs deterministic guardrails (injection patterns, explicit human requests, sensitive topics such as fraud or safety) before asking the model to plan. Tools call services (retrieval, orders, tickets), and services call repositories. Repositories have both a PostgreSQL/pgvector implementation and an in-memory one behind the same protocol. Vendor SDK code lives in a single adapter module. See the diagram in the [README](../README.md#architecture).

Notable choices:

- **Templated order answers.** Order status replies are rendered from validated tool data rather than generated, which removes a whole class of hallucination (made-up tracking numbers and dates).
- **Indistinguishable denials.** Another customer's order gets the same response as a non-existent order, so the API does not leak which orders exist.
- **Ingestion fingerprinting.** Re-ingestion is idempotent, and the fingerprint includes the embedding model and chunking settings, so switching providers re-embeds documents instead of mixing vector spaces.
- **Offline by default.** Deterministic fake providers (hashed bag-of-words embeddings, a rule-based planner, an extractive answerer) let the app, the 130-test suite, and the evaluation run with no API key and no cost. OpenAI is configured with environment variables.

## Testing and evaluation

- **Tests:** unit tests with in-memory repositories and scripted LLM doubles; integration tests that run migrations, pgvector search, and the full API against PostgreSQL; and an evaluation regression test that fails on any safety regression.
- **Evaluation set:** 49 hand-written cases covering FAQ, paraphrase, confusable policies, unsupported questions, order success, authorization failure, tool failure, return/cancel requests, handoff, prompt injection, and ambiguity. Checks target outcomes, citation validity, and leakage, not exact wording.

| Metric (offline, fake providers) | Result |
| --- | --- |
| Cases passed | 45 / 49 |
| Retrieval Recall@4 | 88.9% |
| Citation validity | 100% |
| Unsupported-question abstention | 100% |
| Authorization pass rate | 100% |
| Tool success rate | 100% |

All four failures are paraphrases that a lexical embedder cannot match. In three of them the system abstained rather than answering wrongly, which is the intended failure mode. The retrieval threshold was chosen with a sweep (0.10-0.30) and documented as tuned on the same dataset.

## Lessons learned

- **The strongest guardrails are structural, not textual.** Regex injection detection catches the obvious attempts. The guarantees come from the allowlist, server-side ownership checks, and the lack of any status-changing tool. The eval includes a social-engineering case that the heuristics deliberately miss and the ownership check stops.
- **Validate the model's output like any other untrusted input.** Parsing into a schema, intersecting citations with retrieval results, and checking numbers against sources are cheap and catch real failure modes.
- **Make abstention a first-class outcome.** Explicit statuses (`answered`, `needs_clarification`, `handoff`, `tool_error`, `unsupported`) keep behavior testable and let a client render the right next step.
- **Deterministic fakes pay for themselves.** They make tests fast and free, and they exercise the same validation paths as the real provider. They do not replace a live evaluation, which is the next step.

## Limitations and next steps

Live OpenAI evaluation results are not yet published. Identity is a demo header. There is no multi-turn memory or rate limiting (a production plan is documented). Next steps: a live evaluation with a provider-specific threshold sweep, a hybrid retrieval comparison, a human-authenticated back office for ticket decisions, tracing, and a lightweight UI.
