# Evaluation results

- LLM provider: `fake (fake-rules-v1)`
- Embedding provider: `fake`
- Retrieval: top_k=4, min_score=0.15
- Cases: 49, passed: 45

## Metrics

| Metric | Value |
| --- | --- |
| outcome_pass_rate | 0.918 |
| retrieval_recall_at_k | 0.889 |
| answerable_answered_rate | 0.833 |
| citation_validity | 1.0 |
| grounded_answer_rate | 1.0 |
| unsupported_abstention_rate | 1.0 |
| tool_success_rate | 1.0 |
| authorization_pass_rate | 1.0 |

## Pass rate by category

| Category | Passed |
| --- | --- |
| ambiguous | 4/4 |
| confusable | 5/5 |
| faq | 7/7 |
| handoff | 2/2 |
| order_success | 4/4 |
| order_unauthorized | 4/4 |
| paraphrase | 2/6 |
| prompt_injection | 5/5 |
| return_cancel | 4/4 |
| tool_failure | 3/3 |
| unsupported | 5/5 |

## Latency (ms, in-process, excludes network)

| Measure | Value |
| --- | --- |
| p50_total | 17.7 |
| p95_total | 22.03 |
| mean_generation | 0.65 |
| mean_plan | 3.1 |
| mean_retrieval | 16.5 |
| mean_ticket | 0.13 |
| mean_tool | 0.1 |

Tokens: prompt=0, completion=0. Estimated cost (USD): None

## Failed cases

| Case | Category | Status | Failures |
| --- | --- | --- | --- |
| para-send-back-deadline | paraphrase | unsupported | status unsupported not in answered; missing '30 days' |
| para-canada | paraphrase | unsupported | status unsupported not in answered; missing 'Canada' |
| para-money-back | paraphrase | answered | missing '5-7 business days'; cited ['cancellations', 'returns'] instead of ['refunds'] |
| para-cards | paraphrase | unsupported | status unsupported not in answered; missing 'Visa' |
