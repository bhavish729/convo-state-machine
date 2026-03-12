from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from tara.config import LLMProvider, settings

# ── LLM instance cache ──
# LangChain chat models are stateless (no conversation memory) and reuse
# HTTP connection pools internally.  Caching avoids re-importing the SDK
# module and re-instantiating the client on every turn (~50-150 ms saved).
_llm_cache: dict[tuple, BaseChatModel] = {}


def get_llm(
    *,
    provider: LLMProvider | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[BaseTool] | None = None,
) -> BaseChatModel:
    """
    Factory that returns a configured LangChain chat model.

    Provider-agnostic — the rest of the codebase only sees BaseChatModel.
    If tools are provided, they are bound via .bind_tools().

    Instances are cached by (provider, model, temperature, max_tokens) so
    repeated calls with the same parameters return the same object.
    Tool-bound models are never cached (bind_tools returns a new wrapper).
    """
    provider = provider or settings.llm_provider
    temperature = temperature if temperature is not None else settings.llm_temperature
    max_tokens = max_tokens or settings.llm_max_tokens

    # Resolve the model name for the cache key
    if provider == LLMProvider.OPENAI:
        model_name = settings.openai_model
    elif provider == LLMProvider.ANTHROPIC:
        model_name = settings.anthropic_model
    elif provider == LLMProvider.GEMINI:
        model_name = settings.google_model
    else:
        model_name = str(provider)

    cache_key = (provider, model_name, temperature, max_tokens)

    # Return cached instance if available (never cache tool-bound models)
    if not tools and cache_key in _llm_cache:
        return _llm_cache[cache_key]

    if provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif provider == LLMProvider.GEMINI:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=settings.google_model,
            google_api_key=settings.google_api_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    # Cache the base model (without tools)
    if not tools:
        _llm_cache[cache_key] = llm

    if tools:
        llm = llm.bind_tools(tools)

    return llm
