"""Run the evaluation dataset and write evals/results.md and evals/results.json.

Usage:
  uv run python scripts/run_evals.py           # deterministic fake providers (free, offline)
  uv run python scripts/run_evals.py --live    # OpenAI providers from .env (paid API calls)
"""

import argparse
import json
import sys
from pathlib import Path

from app.ai.factory import build_embedding_provider, build_llm_provider
from app.core.config import PROJECT_ROOT, Settings
from app.core.logging import configure_logging
from app.evaluation.harness import CASES_PATH, load_cases, render_markdown, run_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="use OpenAI providers (costs money)")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "evals")
    parser.add_argument("--min-score", type=float, default=None, help="override the threshold")
    parser.add_argument("--no-write", action="store_true", help="print metrics only")
    args = parser.parse_args()

    configure_logging("ERROR")
    overrides = {"retrieval_min_score": args.min_score}
    if args.live:
        settings = Settings(llm_provider="openai", embedding_provider="openai", **overrides)
        suffix = "_live"
    else:
        settings = Settings(
            _env_file=None, llm_provider="fake", embedding_provider="fake", **overrides
        )
        suffix = ""

    summary, results = run_evaluation(
        settings,
        build_llm_provider(settings),
        build_embedding_provider(settings),
        load_cases(args.cases),
    )

    if not args.no_write:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"results{suffix}.md").write_text(
            render_markdown(summary, results), encoding="utf-8"
        )
        (args.out / f"results{suffix}.json").write_text(
            json.dumps(
                {"summary": summary, "cases": [r.model_dump() for r in results]},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    print(json.dumps(summary["metrics"], indent=2))
    print(f"Passed {summary['passed']}/{summary['cases']} cases.")
    for r in results:
        if not r.passed:
            print(f"  FAIL {r.id}: {'; '.join(r.failures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
