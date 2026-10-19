from app.ai.embedding_provider import EmbeddingProvider
from app.ai.fake_embedding import FakeEmbeddingProvider
from app.ai.fake_llm import FakeLLMProvider
from app.ai.llm_provider import LLMProvider
from app.core.config import Settings
from app.models import EMBEDDING_DIMENSIONS


def _api_key(settings: Settings) -> str:
    if settings.openai_api_key is None:
        raise ValueError("OPENAI_API_KEY is not configured")
    return settings.openai_api_key.get_secret_value()


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        from app.ai.openai_provider import OpenAILLMProvider

        return OpenAILLMProvider(
            api_key=_api_key(settings),
            model=settings.openai_chat_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return FakeLLMProvider()


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        from app.ai.openai_provider import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(
            api_key=_api_key(settings),
            model=settings.openai_embedding_model,
            dimensions=EMBEDDING_DIMENSIONS,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    return FakeEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)
