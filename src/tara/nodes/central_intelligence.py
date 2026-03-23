from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tara.llm.provider import get_llm
from tara.state.schema import RoutingDecision, SentimentLevel

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
#  Streaming LLM — extract response_to_borrower early
# ═══════════════════════════════════════════════════

def _extract_response_from_partial_json(accumulated: str) -> str | None:
    """Try to extract `response_to_borrower` from a partially streamed JSON string.

    Returns the response text if the field is complete, or None if not yet available.
    Handles both complete and partial JSON by looking for the pattern:
      "response_to_borrower": "...complete value..."
    followed by a comma or closing brace.
    """
    # Look for the key followed by a complete string value
    pattern = r'"response_to_borrower"\s*:\s*"((?:[^"\\]|\\.)*)"\s*[,}]'
    m = re.search(pattern, accumulated, re.DOTALL)
    if m:
        # Unescape JSON string escapes
        raw = m.group(1)
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw
    return None


async def stream_ci_response(
    state: dict,
    prompt_builder: Callable[[dict], str],
    on_response_text: Callable[[str], None] | None = None,
) -> dict:
    """Stream the LLM call and extract response_to_borrower as early as possible.

    This is a drop-in replacement for _central_intelligence_impl that uses
    llm.astream() instead of llm.ainvoke(). When the response_to_borrower
    field is complete in the streaming output, ``on_response_text`` is called
    immediately (before the full JSON is done). This allows TTS to start
    while the LLM is still generating routing/extracted_info fields.

    Falls back to ainvoke if streaming isn't supported by the provider.
    """
    system_prompt = prompt_builder(state)
    llm = get_llm()

    conversation = list(state.get("messages", []))

    if not conversation:
        bootstrap = HumanMessage(content="[Call connected. Begin the conversation.]")
        conversation = [bootstrap]
        extra_messages = [bootstrap]
    elif conversation[-1].type != "human":
        cue = HumanMessage(content="[Continue based on the updated context above.]")
        conversation = conversation + [cue]
        extra_messages = [cue]
    else:
        extra_messages = []

    llm_messages = [SystemMessage(content=system_prompt)] + conversation

    # Try streaming — fall back to ainvoke if not supported
    accumulated = ""
    response_text_sent = False

    try:
        async for chunk in llm.astream(llm_messages):
            token = ""
            if isinstance(chunk.content, str):
                token = chunk.content
            elif isinstance(chunk.content, list):
                for block in chunk.content:
                    if isinstance(block, dict):
                        token += block.get("text", "")
                    elif isinstance(block, str):
                        token += block
            accumulated += token

            # Check if response_to_borrower is complete
            if not response_text_sent and on_response_text:
                extracted = _extract_response_from_partial_json(accumulated)
                if extracted:
                    logger.info(f"[CI-STREAM] Early response extracted ({len(accumulated)} chars so far)")
                    on_response_text(extracted)
                    response_text_sent = True

    except (NotImplementedError, AttributeError):
        # Provider doesn't support streaming — fall back to ainvoke
        logger.info("[CI-STREAM] Streaming not supported, falling back to ainvoke")
        response = await llm.ainvoke(llm_messages)
        accumulated = _extract_text_content(response)

    # Parse the complete JSON
    routing = _parse_routing_decision_from_text(accumulated)

    logger.info(
        f"[CI] Turn {state.get('turn_count', 0)+1}: next_node='{routing['next_node']}', "
        f"reasoning='{routing.get('reasoning', '')[:80]}'"
    )

    # Retry once if JSON parse failed
    if (
        routing["next_node"] == "escalate"
        and "Failed to parse" in routing["reasoning"]
    ):
        logger.warning("[CI-STREAM] JSON parse failed, retrying with ainvoke...")
        retry_msg = HumanMessage(
            content="Your previous response was not valid JSON. "
            "Return ONLY the JSON object with keys: next_node, reasoning, "
            "response_to_borrower, extracted_info. No markdown, no extra text."
        )
        response = await llm.ainvoke(
            llm_messages + [AIMessage(content=accumulated), retry_msg]
        )
        routing = _parse_routing_decision(response)
        logger.info(f"[CI-STREAM] Retry result: next_node='{routing['next_node']}'")

    # If we never sent response text early, send it now
    if not response_text_sent and on_response_text and routing["response_to_borrower"]:
        on_response_text(routing["response_to_borrower"])

    # Build state update (same logic as _central_intelligence_impl)
    return _build_ci_state_update(state, routing, extra_messages)


def make_central_intelligence(prompt_builder: Callable[[dict], str]):
    """Factory: create a CI node wired to a specific prompt builder.

    Each agent (pre_due, bucket_x, npa) provides its own prompt builder
    so the same CI logic drives different conversation strategies.
    """

    async def central_intelligence(state: dict) -> dict:
        return await _central_intelligence_impl(state, prompt_builder)

    return central_intelligence


async def _central_intelligence_impl(
    state: dict, prompt_builder: Callable[[dict], str]
) -> dict:
    """
    The brain of Tara. Evaluates full conversation context and
    decides which action node should execute next.

    Sets routing_decision for the conditional edge to inspect.
    """
    system_prompt = prompt_builder(state)
    llm = get_llm()  # No tools — prompt handles routing directly

    conversation = list(state.get("messages", []))

    # Gemini requires the last message to be from the user.
    # Handle two cases:
    # 1. Empty conversation (first turn) — inject a bootstrap message
    # 2. Conversation ends with AI (after action node loops back) — add continuation cue
    if not conversation:
        bootstrap = HumanMessage(content="[Call connected. Begin the conversation.]")
        conversation = [bootstrap]
        extra_messages = [bootstrap]  # Include in state so it's in history
    elif conversation[-1].type != "human":
        cue = HumanMessage(content="[Continue based on the updated context above.]")
        conversation = conversation + [cue]
        extra_messages = [cue]
    else:
        extra_messages = []

    llm_messages = [SystemMessage(content=system_prompt)] + conversation

    response = await llm.ainvoke(llm_messages)
    routing = _parse_routing_decision(response)

    logger.info(
        f"[CI] Turn {state.get('turn_count', 0)+1}: next_node='{routing['next_node']}', "
        f"reasoning='{routing.get('reasoning', '')[:80]}'"
    )

    # Retry once if JSON parse failed (avoids unnecessary escalation)
    if (
        routing["next_node"] == "escalate"
        and "Failed to parse" in routing["reasoning"]
    ):
        logger.warning("[CI] JSON parse failed, retrying LLM call...")
        retry_msg = HumanMessage(
            content="Your previous response was not valid JSON. "
            "Return ONLY the JSON object with keys: next_node, reasoning, "
            "response_to_borrower, extracted_info. No markdown, no extra text."
        )
        response = await llm.ainvoke(llm_messages + [response, retry_msg])
        routing = _parse_routing_decision(response)
        logger.info(f"[CI] Retry result: next_node='{routing['next_node']}'")

    return _build_ci_state_update(state, routing, extra_messages)


# Backward-compatible default: uses NPA prompt (original behavior)
async def central_intelligence(state: dict) -> dict:
    """Default CI node using the NPA prompt (backward compatibility)."""
    from tara.llm.prompts import build_central_intelligence_prompt

    return await _central_intelligence_impl(state, build_central_intelligence_prompt)


def _build_ci_state_update(
    state: dict, routing: RoutingDecision, extra_messages: list
) -> dict:
    """Build the state update dict from a parsed routing decision.

    Shared by both _central_intelligence_impl and stream_ci_response.
    """
    _SENTIMENT_MAP = {
        "very_negative": SentimentLevel.VERY_NEGATIVE,
        "negative": SentimentLevel.NEGATIVE,
        "neutral": SentimentLevel.NEUTRAL,
        "positive": SentimentLevel.POSITIVE,
        "cooperative": SentimentLevel.COOPERATIVE,
    }
    sentiment_raw = routing.get("extracted_info", {}).get("detected_sentiment", "")
    detected = _SENTIMENT_MAP.get(sentiment_raw)

    result: dict = {
        "messages": extra_messages + [AIMessage(content=routing["response_to_borrower"])],
        "routing_decision": routing,
        "turn_count": state.get("turn_count", 0) + 1,
    }

    if detected:
        result["current_sentiment"] = detected
        result["sentiment_history"] = [sentiment_raw]

    # --- Tactical memory ---
    extracted = routing.get("extracted_info", {})
    tactical_update: dict = {}

    consequence = extracted.get("consequence_used")
    if consequence:
        tactical_update["consequences_used"] = [consequence]

    tactic = extracted.get("tactic_used")
    if tactic:
        tactical_update["tactics_used"] = [tactic]

    occupation = extracted.get("occupation")
    if occupation:
        tactical_update["borrower_occupation"] = occupation

    if tactical_update:
        result["tactical_memory"] = tactical_update

    # --- Call progress ---
    progress_update: dict = {}

    partial_amount = extracted.get("partial_amount")
    if partial_amount:
        try:
            amount = float(partial_amount)
            debt = state.get("borrower_profile", {}).get("debt_amount", 0)
            progress_update["partial_amount_committed"] = amount
            progress_update["remaining_amount"] = max(0, debt - amount)
        except (ValueError, TypeError):
            pass

    payment_mode = extracted.get("payment_mode")
    if payment_mode:
        progress_update["payment_mode_confirmed"] = payment_mode

    identity_challenge = extracted.get("identity_challenge")
    if identity_challenge:
        progress_update["identity_challenged"] = True
        progress_update["identity_challenge_turn"] = state.get("turn_count", 0)
        progress_update["claimed_identity"] = extracted.get("claimed_identity", "unknown")

    if progress_update:
        result["call_progress"] = progress_update

    return result


def _extract_text_content(response: AIMessage) -> str:
    """
    Extract text from an AI message, handling both string content
    and Gemini's list-of-blocks format: [{'type': 'text', 'text': '...'}].
    """
    if isinstance(response.content, str):
        return response.content
    if isinstance(response.content, list):
        parts = []
        for block in response.content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(response.content)


def _parse_routing_decision_from_text(content: str) -> RoutingDecision:
    """Parse routing decision from raw text (used by streaming path)."""
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if json_match:
        raw = json_match.group(1)
    else:
        raw = content

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "next_node": "escalate",
            "reasoning": "Failed to parse LLM routing decision",
            "response_to_borrower": content,
            "extracted_info": {},
        }

    response_text = data.get("response_to_borrower")
    if not response_text:
        for key in data:
            if "response" in key.lower() and key not in ("next_node", "reasoning", "extracted_info"):
                response_text = data[key]
                break
    if not response_text:
        response_text = content

    return RoutingDecision(
        next_node=data.get("next_node", "escalate"),
        reasoning=data.get("reasoning", ""),
        response_to_borrower=response_text,
        extracted_info=data.get("extracted_info", {}),
    )


def _parse_routing_decision(response: AIMessage) -> RoutingDecision:
    """
    Extract structured routing decision from LLM response.
    The LLM is instructed to return pure JSON.
    Falls back to escalation if parsing fails.
    """
    content = _extract_text_content(response)

    # Try to extract JSON from markdown code block
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if json_match:
        raw = json_match.group(1)
    else:
        raw = content

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "next_node": "escalate",
            "reasoning": "Failed to parse LLM routing decision",
            "response_to_borrower": content,
            "extracted_info": {},
        }

    # Fuzzy-match the response key — LLM sometimes typos it as
    # "response_to_browser", "response_to_user", "borrower_response", etc.
    response_text = data.get("response_to_borrower")
    if not response_text:
        for key in data:
            if "response" in key.lower() and key not in ("next_node", "reasoning", "extracted_info"):
                response_text = data[key]
                break
    if not response_text:
        response_text = content  # Last resort

    return RoutingDecision(
        next_node=data.get("next_node", "escalate"),
        reasoning=data.get("reasoning", ""),
        response_to_borrower=response_text,
        extracted_info=data.get("extracted_info", {}),
    )
