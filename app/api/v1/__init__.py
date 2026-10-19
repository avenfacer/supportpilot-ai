from fastapi import APIRouter

from app.api.v1.chat import router as chat_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.orders import router as orders_router
from app.api.v1.tickets import router as tickets_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(chat_router)
api_router.include_router(orders_router)
api_router.include_router(tickets_router)
api_router.include_router(knowledge_router)
