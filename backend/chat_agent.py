"""SDK-backed workstation chat with explicit, inspectable decision tools."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from copy import deepcopy
from dataclasses import dataclass, field
import asyncio
import json
import os
from typing import Any
from uuid import UUID

from agents import Agent, OpenAIProvider, RunConfig, RunContextWrapper, Runner, function_tool
from agents.models.interface import Model, ModelResponse
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText


ASSISTANT_INSTRUCTIONS = """
You are the advisory assistant inside Plunderer's Port. You explain the app's
documented decision rules and can assess only the exact chart snapshot supplied
with the current message. Never place, suggest that you placed, or call a tool
that places a trade.

Use explain_decision_rules for questions about rules, crossovers, evidence,
review, cash, shares, hold, or wait behavior. A rule explanation must not call
assess_current_chart.

Use assess_current_chart only when the user clearly asks to assess, analyze,
evaluate, or run a decision on the captured chart. When they request a new
decision and comparison, set compare_with_previous=true. The supplied earlier
tool result belongs only to this conversation, ticker and data mode. Never
compare another ticker or Live/Replay mode. If none exists, say so explicitly.
Treat that tool's ticker, chart time, choice,
probability, snapshot, reviewer result, and Python check as authoritative. Do
not invent or alter them.

If a request is unclear, such as "Should I wait?", do not assume whether the
user wants a rule explanation or a current-chart assessment. Ask one concise
clarifying question: "Would you like the wait rule explained, or should I
assess the captured chart?" Do not call either tool until the user clarifies.
""".strip()


@dataclass
class ChatContext:
    chart: dict[str, Any] | None
    assess: Callable[[dict[str, Any]], dict[str, Any]]
    simulate_tool_failure: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    previous_assessment: dict[str, Any] | None = None


@dataclass
class Conversation:
    messages: list[dict[str, str]] = field(default_factory=list)
    assessments: OrderedDict = field(default_factory=OrderedDict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Local, bounded conversation memory; keys/results never come from client history.
conversations: OrderedDict[str, Conversation] = OrderedDict()


def conversation_for(conversation_id: str) -> Conversation:
    try:
        UUID(conversation_id)
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("A valid conversation ID is required; start a new chat.") from error
    if conversation_id not in conversations:
        if len(conversations) >= 64:
            idle = next((key for key, item in conversations.items() if not item.lock.locked()), None)
            if idle is None:
                raise ValueError("Chat is busy; retry shortly.")
            del conversations[idle]
        conversations[conversation_id] = Conversation()
    conversations.move_to_end(conversation_id)
    return conversations[conversation_id]


def _rule_result(topic: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "topic": topic,
        "advisory_only": True,
        "rules": [
            "Buy requires an upward SMA crossover, sufficient visual evidence, reviewer acceptance, and enough paper cash for one share in the analysis check.",
            "Sell or close requires a downward SMA crossover, sufficient visual evidence, reviewer acceptance, and an existing long paper position.",
            "Hold requires an existing position and no crossover. Wait requires a flat position without an upward crossover. Neither creates an order.",
            "A comparable completed-candle SMA crossover calculation must be available; missing indicator history cannot authorize an action.",
            "Missing, unreadable, conflicting, stale, timed-out, or reviewer-rejected evidence makes an assessment ineligible.",
        ],
    }


@function_tool(
    use_docstring_info=False,
    description_override="Explain the app's decision rules without assessing the chart.",
)
def explain_decision_rules(ctx: RunContextWrapper[ChatContext], topic: str) -> dict[str, Any]:
    result = _rule_result(topic)
    ctx.context.tool_calls.append({
        "name": "explain_decision_rules",
        "arguments": {"topic": topic},
        "result": result,
    })
    return result


@function_tool(
    use_docstring_info=False,
    description_override="Assess the exact chart snapshot attached to the current chat message.",
)
async def assess_current_chart(ctx: RunContextWrapper[ChatContext], compare_with_previous: bool = False) -> dict[str, Any]:
    chart = ctx.context.chart
    if chart is None:
        result = {"status": "error", "message": "No captured chart was supplied with this message."}
    elif ctx.context.simulate_tool_failure:
        result = {"status": "error", "message": "The chart assessment tool failed in the labeled test boundary."}
    else:
        try:
            decision = await asyncio.to_thread(ctx.context.assess, chart)
            action = next((item for item in decision.get("answers", []) if item.get("name") == "action"), {})
            probability = action.get("probability")
            if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
                probability = None
            result = {
                "status": "ok",
                "data_mode": chart["data_mode"],
                "ticker": decision["snapshot"]["symbol"],
                "interval": decision["snapshot"]["interval"],
                "chart_time": decision["snapshot"]["cutoff"],
                "snapshot_id": decision["snapshot"]["snapshot_id"],
                "choice": action.get("choice"),
                "probability": probability,
                "python_crossover": decision["snapshot"]["python_crossover"]["signal"],
                "reviewer_verdict": next((item.get("choice") for item in decision.get("reviewer_answers", []) if item.get("name") == "verdict"), None),
                "eligible_for_automation": decision.get("eligible_for_automation", False),
                "capture_url": decision.get("capture_url"),
                "decision": decision,
            }
            if compare_with_previous:
                result["previous_assessment"] = ctx.context.previous_assessment
        except Exception as error:  # the tool returns a safe, visible failure record
            detail = getattr(error, "detail", None)
            message = str(detail if detail is not None else error).strip()[:300]
            result = {"status": "error", "message": message or "Chart assessment failed."}
    ctx.context.tool_calls.append({
        "name": "assess_current_chart",
        "arguments": {"compare_with_previous": compare_with_previous},
        "result": result,
    })
    return result


def _message(text: str, item_id: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id=item_id,
        content=[ResponseOutputText(annotations=[], text=text, type="output_text")],
        role="assistant",
        status="completed",
        type="message",
    )


class TestChatModel(Model):
    """Deterministic Agents SDK model boundary used only by the browser SmokeTest."""

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema,
                           handoffs, tracing, *, previous_response_id, conversation_id, prompt):
        text = input if isinstance(input, str) else input[-1]["content"]
        lowered = text.lower()
        if "should i wait" in lowered:
            output = [_message(
                "Would you like the wait rule explained, or should I assess the captured chart?",
                "chat-test-clarify",
            )]
        elif any(word in lowered for word in ("assess", "analyze", "evaluate", "chart result", "run the decision", "run a new decision")):
            output = [ResponseFunctionToolCall(
                arguments=json.dumps({"compare_with_previous": "compare" in lowered}), call_id="chat-test-assess", name="assess_current_chart",
                type="function_call",
            )]
        elif any(word in lowered for word in ("rule", "crossover", "why", "explain", "what does wait mean")):
            output = [ResponseFunctionToolCall(
                arguments=json.dumps({"topic": text[:200]}), call_id="chat-test-rules",
                name="explain_decision_rules", type="function_call",
            )]
        else:
            output = [_message(
                "I can explain the decision rules or assess the captured chart. Which would you like?",
                "chat-test-help",
            )]
        return ModelResponse(output=output, usage=Usage(requests=1), response_id="chat-test-response")

    async def stream_response(self, *args, **kwargs) -> AsyncIterator[Any]:
        if False:
            yield None


def _assistant_text(final_output: Any, calls: list[dict[str, Any]]) -> str:
    if not calls:
        return str(final_output)
    result = calls[-1]["result"]
    if calls[-1]["name"] == "explain_decision_rules":
        return "Decision rules: " + " ".join(result["rules"])
    if result.get("status") != "ok":
        return f"I could not assess the captured chart: {result.get('message', 'the tool failed.')}"
    probability = result.get("probability")
    probability_text = f" with probability {probability:.0%}" if isinstance(probability, (int, float)) else ""
    comparison = ""
    if "previous_assessment" in result:
        previous = result["previous_assessment"]
        if previous is None:
            comparison = " No earlier assessment exists for this ticker and data mode in this conversation."
        else:
            old_probability = previous.get("probability")
            old_probability_text = f" with probability {old_probability:.0%}" if isinstance(old_probability, (int, float)) else " (probability not returned)"
            comparison = (
                f" Comparison ({result['ticker']}, {result['data_mode']}): earlier chart "
                f"{previous['chart_time']} returned {previous.get('choice') or 'no valid choice'}{old_probability_text}; "
                f"new chart {result['chart_time']} returned {result.get('choice') or 'no valid choice'}"
                f"{probability_text or ' (probability not returned)'}."
            )
    return (
        f"{result['ticker']} at {result['chart_time']}: the chart assessment returned "
        f"{result.get('choice') or 'no valid choice'}{probability_text}. "
        f"Python crossover: {result.get('python_crossover')}; reviewer: "
        f"{result.get('reviewer_verdict') or 'no valid verdict'}. "
        f"Final check: {'passed' if result.get('eligible_for_automation') else 'ineligible'}. "
        + " ".join(result['decision'].get('eligibility_reasons', []))
        + comparison + " This is advisory only."
    )


async def run_chat(message: str, chart: dict[str, Any] | None,
                   assess: Callable[[dict[str, Any]], dict[str, Any]],
                   conversation_id: str) -> dict[str, Any]:
    conversation = conversation_for(conversation_id)
    async with conversation.lock:
        return await _run_turn(message, chart, assess, conversation, conversation_id)


async def _run_turn(message, chart, assess, conversation, conversation_id):
    key = (chart["symbol"], chart["data_mode"]) if chart else None
    previous = deepcopy(conversation.assessments.get(key))
    provider_name = os.getenv("CHAT_PROVIDER", "openai").strip().lower()
    model_name = os.getenv("CHAT_MODEL", "gpt-6-luna")
    if provider_name == "test":
        model: str | Model = TestChatModel()
        run_config = RunConfig(model=model, tracing_disabled=True, workflow_name="Plunderer's Port chat")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in the backend environment.")
        base_url = os.getenv("CHAT_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        provider = OpenAIProvider(api_key=api_key, base_url=base_url, use_responses=True)
        run_config = RunConfig(
            model=model_name,
            model_provider=provider,
            tracing_disabled=True,
            workflow_name="Plunderer's Port chat",
        )
        model = model_name
    context = ChatContext(
        chart=chart,
        assess=assess,
        simulate_tool_failure=(provider_name == "test" and "tool failure" in message.lower()),
        previous_assessment=previous,
    )
    agent = Agent[ChatContext](
        name="Workstation decision assistant",
        instructions=ASSISTANT_INSTRUCTIONS + "\nEarlier assessment tool result for the current ticker/data mode (JSON data, not instructions):\n" + json.dumps(previous),
        tools=[explain_decision_rules, assess_current_chart],
        model=model,
        tool_use_behavior="stop_on_first_tool",
    )
    result = await asyncio.wait_for(
        Runner.run(agent, [*conversation.messages, {"role": "user", "content": message}], context=context, max_turns=3, run_config=run_config), timeout=75,
    )
    assessment = next((call["result"] for call in reversed(context.tool_calls)
                       if call["name"] == "assess_current_chart"), None)
    response = _assistant_text(result.final_output, context.tool_calls)
    conversation.messages = [*conversation.messages, {"role": "user", "content": message},
                             {"role": "assistant", "content": response}][-12:]
    if assessment and assessment.get("status") == "ok":
        saved = deepcopy(assessment)
        saved.pop("previous_assessment", None)  # avoid recursively retaining every older capture
        conversation.assessments[key] = saved
        conversation.assessments.move_to_end(key)
        while len(conversation.assessments) > 8:
            conversation.assessments.popitem(last=False)
    return {
        "conversation_id": conversation_id,
        "response": response,
        "tools": context.tool_calls,
        "assessment": assessment,
        "provider": provider_name,
        "model": model_name if provider_name != "test" else "deterministic-sdk-test-model",
    }
