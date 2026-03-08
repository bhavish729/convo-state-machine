from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from tara.config import LLMProvider, settings


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
    """
    provider = provider or settings.llm_provider
    temperature = temperature if temperature is not None else settings.llm_temperature
    max_tokens = max_tokens or settings.llm_max_tokens

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

    if tools:
        llm = llm.bind_tools(tools)

    return llm
