from fastapi import APIRouter
from app.api.api_v1 import auth, knowledge_base, chat, api_keys, evaluation, traces

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(knowledge_base.router, prefix="/knowledge-base", tags=["knowledge-base"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_router.include_router(evaluation.router, prefix="/evaluation", tags=["evaluation"])
api_router.include_router(traces.router, prefix="/traces", tags=["traces"])
