# Evaluation

The evaluation runs every case in [`cases.jsonl`](cases.jsonl) through the real chat pipeline:
the guardrails, tool registry, retrieval, grounding checks, order service, and ticket service. Repositories are in-memory, so no database is needed and the results are reproducible.

```bash
uv run python scripts/run_evals.py                  # fake providers: free, offline, deterministic
uv run python scripts/run_evals.py --min-score 0.2  # override the retrieval threshold
uv run python scripts/run_evals.py --live           # OpenAI providers from .env (paid API calls)
```

Outputs go to `results.md` and `results.json` (or `results_live.*` for `--live`). The test `tests/evaluation/test_eval_dataset.py` reruns the offline evaluation in CI. It fails on any safety regression and on any drop below the current quality baseline.

## Dataset

There are 49 synthetic cases in 11 categories:

| Category | Cases | What it checks |
| --- | --- | --- |
| faq | 7 | Direct policy questions are answered with citations from the expected document |
| paraphrase | 6 | The same questions, reworded with different vocabulary |
| confusable | 5 | Similar policies that are easy to mix up (refund for a cancellation vs. a return, and so on) |
| unsupported | 5 | Questions outside the knowledge base must not be answered |
| order_success | 4 | Order status comes from the mock order API, including "no tracking yet" |
| order_unauthorized | 4 | Another customer's order, or no identity: nothing leaks |
| tool_failure | 3 | Order API timeout/outage produces `tool_error` and no fabricated details |
| return_cancel | 4 | Requests create only `pending_human_review` tickets, with policy citations |
| handoff | 2 | Explicit human request and a sensitive issue (fraud) |
| prompt_injection | 5 | Override attempts, delimiter escape, and social engineering |
| ambiguous | 4 | Missing details lead to a clarifying question |

Each case records the expected status (one or more acceptable values), expected source documents, the expected tool, whether a ticket should be created, and strings the answer must or must not contain. Checks target outcomes and safety properties, not exact wording.

## Metrics

| Metric | Definition |
| --- | --- |
| outcome_pass_rate | Share of cases where every check passed |
| retrieval_recall_at_k | Knowledge cases where an expected document is in the top-k candidates (before the threshold) |
| answerable_answered_rate | FAQ, paraphrase, and confusable cases that were answered rather than abstained |
| citation_validity | Share of cited chunk IDs that were in that turn's retrieval results |
| grounded_answer_rate | Answered knowledge responses that have citations and contain no numbers missing from the cited text |
| unsupported_abstention_rate | Unsupported questions that were declined or escalated, with no citations |
| tool_success_rate | Order-lookup cases that returned the correct mock-API data |
| authorization_pass_rate | Authorization and injection cases where no forbidden string leaked |
| latency | In-process timings per stage (plan, retrieval, generation, tool, ticket) and in total |
| tokens / cost | Provider-reported token usage, priced with an illustrative gpt-4o-mini rate (live mode only) |

## Current results (fake providers)

See [`results.md`](results.md) for the full report. Summary at `min_score=0.15`: **45/49 cases pass**. Citation validity, grounded answer rate, unsupported abstention, tool success, and authorization are all 100%. Retrieval Recall@4 is 88.9%.

All 4 failures are paraphrases. The fake embedder hashes words, so it only matches shared vocabulary ("sending something back" does not match "return"). In three of the four, the pipeline abstained instead of guessing. In `para-money-back` it answered with a grounded but unhelpful sentence from the returns/cancellations documents instead of the refund timeline. This is the main quality gap that a semantic embedding model is expected to close.

### Threshold sweep (fake embedder)

| min_score | Passed | Answerable answered | Unsupported abstention |
| --- | --- | --- | --- |
| 0.10 | 45/49 | 0.833 | 1.0 |
| 0.15 | 45/49 | 0.833 | 1.0 |
| 0.20 | 44/49 | 0.778 | 1.0 |
| 0.25 | 43/49 | 0.722 | 1.0 |
| 0.30 | 43/49 | 0.667 | 1.0 |

Unrelated questions score at most about 0.05 against the corpus. 0.15 is the highest threshold that keeps the best answer rate, so it leaves the most margin against noise. The threshold was chosen on this same small dataset, so treat it as tuned rather than validated.

## Limitations

- The default results use the deterministic fake providers. The planner is rule-based and the answerer is extractive (it copies source sentences), so groundedness is 100% almost by construction. These results show that the safety boundaries hold: authorization, the tool allowlist, citation validation, abstention, and ticket status. They do not measure the language quality of a real LLM.
- Live OpenAI results have not been published yet. Run `--live` with an API key and commit `results_live.md`. The OpenAI threshold default (0.3) is a starting point and needs its own sweep.
- 49 cases is a small, hand-written dataset. It covers each behavior but cannot support claims of statistical accuracy.
- Prompt-injection checks are regex heuristics plus structural defenses. New phrasings will get past the heuristics; the structural defenses (ownership checks, allowlist, no status-changing tool) are what bound the impact.
- Latency is measured in-process with in-memory storage and no network, so it is not representative of production.
