from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tara.llm.prompts import build_central_intelligence_prompt
from tara.llm.provider import get_llm
from tara.state.schema import RoutingDecision
from tara.tools.analysis import assess_sentiment, detect_objection_type
from tara.tools.borrower import get_borrower_profile, get_negotiation_history
from tara.tools.payment import calculate_payment_options

ALL_TOOLS = [
    get_borrower_profile,
    get_negotiation_history,
    calculate_payment_options,
    detect_objection_type,
    assess_sentiment,
]


def central_intelligence(state: dict) -> dict:
    """
    The brain of Tara. Evaluates full conversation context and
    decides which action node should execute next.

    Sets routing_decision for the conditional edge to inspect.
    """
    system_prompt = build_central_intelligence_prompt(state)
    llm = get_llm(tools=ALL_TOOLS)

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

    response = llm.invoke(llm_messages)
    routing = _parse_routing_decision(response)

    return {
        "messages": extra_messages + [AIMessage(content=routing["response_to_borrower"])],
        "routing_decision": routing,
        "turn_count": state.get("turn_count", 0) + 1,
    }


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
