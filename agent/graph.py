"""langgraph StateGraph 定义 — agent_node(流式) + tools_node(并行)"""
import json
import asyncio
import httpx

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START, END

from agent.state import AgentState
from agent.tools import ALL_TOOLS, TOOLS_SCHEMA
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, LLM_MODEL

_headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:8000",
    "X-Title": "Microbiology Report AI",
}

_TOOL_MAP = {t.name: t for t in ALL_TOOLS}

# 全局事件队列 — agent_node 流式推送，streamer 消费
_event_queue: asyncio.Queue | None = None


def set_event_queue(q: asyncio.Queue):
    """设置当前会话的事件队列"""
    global _event_queue
    _event_queue = q


def _to_openai_messages(messages: list) -> list[dict]:
    """将 LangChain messages 转换为 OpenAI 格式"""
    openai_messages = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            openai_messages.append({"role": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            openai_messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            ai_msg = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                ai_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["args"] if isinstance(tc["args"], str) else json.dumps(tc["args"], ensure_ascii=False),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            openai_messages.append(ai_msg)
        elif isinstance(msg, ToolMessage):
            openai_messages.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content,
            })
        elif isinstance(msg, dict):
            openai_messages.append(msg)
    return openai_messages


async def agent_node(state: AgentState) -> dict:
    """流式调用 LLM，逐字推送文本到事件队列"""
    messages = state.get("messages", [])
    openai_messages = _to_openai_messages(messages)

    payload = {
        "model": LLM_MODEL,
        "messages": openai_messages,
        "temperature": 0.3,
        "max_tokens": 4096,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto",
        "stream": True,
    }

    full_content = ""
    tool_calls_map = {}  # index → {id, name, arguments}

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("POST", f"{OPENROUTER_BASE_URL}/chat/completions", headers=_headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})

                # 文本增量 → 推送到事件队列
                if delta.get("content") and _event_queue:
                    full_content += delta["content"]
                    await _event_queue.put({"event": "text_delta", "content": delta["content"]})

                # 工具调用增量 → 累积
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.get("id"):
                            tool_calls_map[idx]["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            tool_calls_map[idx]["name"] = tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            tool_calls_map[idx]["arguments"] += tc["function"]["arguments"]

    # 构建 AIMessage
    ai_kwargs = {"content": full_content}
    if tool_calls_map:
        parsed_tool_calls = []
        for idx in sorted(tool_calls_map.keys()):
            tc = tool_calls_map[idx]
            try:
                args_dict = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args_dict = {}
            parsed_tool_calls.append({
                "id": tc["id"],
                "name": tc["name"],
                "args": args_dict,
            })
        ai_kwargs["tool_calls"] = parsed_tool_calls

    ai_message = AIMessage(**ai_kwargs)
    return {"messages": [ai_message]}


def should_continue(state: AgentState) -> str:
    """条件路由：有 tool_calls → tools_node，否则 → END"""
    messages = state.get("messages", [])
    if not messages:
        return END
    last = messages[-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    return END


async def _execute_tool(tc: dict) -> ToolMessage:
    """执行单个工具调用"""
    tool_name = tc["name"]
    tool_args = tc["args"] if isinstance(tc["args"], dict) else {}
    tool_call_id = tc["id"]

    try:
        tool_fn = _TOOL_MAP.get(tool_name)
        if tool_fn:
            result = await asyncio.to_thread(tool_fn.invoke, tool_args)
        else:
            result = f"未知工具: {tool_name}"
    except Exception as e:
        result = f"工具执行错误: {e}"

    return ToolMessage(content=result, tool_call_id=tool_call_id, name=tool_name)


async def parallel_tool_node(state: AgentState) -> dict:
    """并行执行工具调用（asyncio.gather），并附加引用标记"""
    messages = state.get("messages", [])
    last = messages[-1]
    citation_counter = state.get("citation_counter", 0)

    if not isinstance(last, AIMessage) or not getattr(last, "tool_calls", None):
        return {"messages": []}

    # 并行执行所有 tool_calls
    tasks = [_execute_tool(tc) for tc in last.tool_calls]
    tool_messages = await asyncio.gather(*tasks)

    # 给每个 ToolMessage 添加引用前缀
    for msg in tool_messages:
        citation_counter += 1
        msg.content = f"[引用{citation_counter}]\n\n{msg.content}"

    return {"messages": list(tool_messages), "citation_counter": citation_counter}


def build_graph():
    """构建并编译 langgraph StateGraph"""
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", parallel_tool_node)

    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    graph.add_edge(START, "agent")

    return graph.compile()
