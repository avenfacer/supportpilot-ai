"""Ingest the knowledge base into PostgreSQL/pgvector (idempotent).

Usage: uv run python scripts/ingest_knowledge.py [--dir data/knowledge_base] [--no-prune]
"""

import argparse
import sys
from pathlib import Path

from app.ai.factory import build_embedding_provider
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import build_engine, build_session_factory
from app.repositories.sql import SqlKnowledgeRepository
from app.services.ingestion_service import IngestionService


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=settings.knowledge_base_dir)
    parser.add_argument("--no-prune", action="store_true", help="keep documents missing on disk")
    args = parser.parse_args()

    configure_logging("WARNING")
    engine = build_engine(settings.database_url)
    with build_session_factory(engine)() as session:
        service = IngestionService(
            SqlKnowledgeRepository(session),
            build_embedding_provider(settings),
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        report = service.ingest_directory(args.dir, prune=not args.no_prune)
    engine.dispose()

    print(f"Embedding provider: {settings.embedding_provider}")
    print(f"Created:   {report.created}")
    print(f"Updated:   {report.updated}")
    print(f"Unchanged: {report.unchanged}")
    print(f"Deleted:   {report.deleted}")
    print(f"Chunks written: {report.chunk_count}")
    for error in report.errors:
        print(f"ERROR {error.source_path}: {error.error}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
