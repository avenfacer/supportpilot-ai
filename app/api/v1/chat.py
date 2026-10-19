from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_chat_service
from app.core.security import CustomerContext, get_optional_customer
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={503: {"description": "The AI provider is temporarily unavailable."}},
)
def chat(
    request: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
    customer: Annotated[CustomerContext | None, Depends(get_optional_customer)],
) -> ChatResponse:
    """Submit a customer-support message and receive a structured, machine-readable outcome."""
    return service.handle(request, customer).response
