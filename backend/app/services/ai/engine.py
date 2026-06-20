"""
AI Engine — LiteLLM unified adapter layer.
Supports OpenAI, Deepseek, Ollama, and any OpenAI-compatible endpoint.
"""
from dataclasses import dataclass
from typing import Optional
import litellm
import structlog

from app.core.config import settings

logger = structlog.get_logger()


@dataclass
class AIResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    finish_reason: str


@dataclass
class ModelConfig:
    model_id: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 4096


class AIEngine:
    """
    Unified LLM adapter. All AI calls go through here.
    Decision: LiteLLM because it provides a consistent interface
    for 100+ models including Deepseek, local Ollama, and OpenAI.
    """

    def __init__(self, model_config: Optional[ModelConfig] = None):
        self.model_config = model_config or self._default_config()

    def _default_config(self) -> ModelConfig:
        return ModelConfig(
            model_id=settings.DEFAULT_AI_MODEL,
            api_base=settings.DEFAULT_AI_API_BASE,
            api_key=settings.DEFAULT_AI_API_KEY,
        )

    async def complete(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AIResponse:
        cfg = self.model_config
        kwargs = {
            "model": cfg.model_id,
            "messages": messages,
            "temperature": temperature or cfg.temperature,
            "max_tokens": max_tokens or cfg.max_tokens,
        }

        if cfg.api_base:
            kwargs["api_base"] = cfg.api_base
        if cfg.api_key:
            kwargs["api_key"] = cfg.api_key

        logger.info("ai_engine.calling", model=cfg.model_id, messages_count=len(messages))

        response = await litellm.acompletion(**kwargs)
        choice = response.choices[0]

        result = AIResponse(
            content=choice.message.content or "",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            model=response.model,
            finish_reason=choice.finish_reason,
        )

        logger.info(
            "ai_engine.completed",
            model=cfg.model_id,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        return result

    async def complete_with_system(
        self,
        system_prompt: str,
        user_content: str,
        **kwargs,
    ) -> AIResponse:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        return await self.complete(messages, **kwargs)


def build_engine_from_db_model(db_model) -> AIEngine:
    """Build AIEngine from database AIModel record."""
    from app.core.security import decrypt

    config = ModelConfig(
        model_id=db_model.model_id,
        api_base=db_model.api_base,
        api_key=decrypt(db_model.api_key_encrypted) if db_model.api_key_encrypted else None,
        temperature=db_model.config.get("temperature", 0.3),
        max_tokens=db_model.config.get("max_tokens", 4096),
    )
    return AIEngine(config)
