from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import RepositoriesDep, SettingsDep, get_ingestion_service
from app.core.security import require_admin
from app.schemas.knowledge import IngestionReport, SourceDocument
from app.services.ingestion_service import IngestionService

# Admin-only: disabled unless ENABLE_ADMIN_ENDPOINTS=true, and requires X-Admin-Token.
router = APIRouter(
    prefix="/knowledge", tags=["knowledge (admin)"], dependencies=[Depends(require_admin)]
)


@router.post("/ingest", response_model=IngestionReport)
def ingest(
    settings: SettingsDep,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> IngestionReport:
    return service.ingest_directory(settings.knowledge_base_dir)


@router.get("/sources", response_model=list[SourceDocument])
def list_sources(repos: RepositoriesDep) -> list[SourceDocument]:
    return repos.knowledge.list_documents()
