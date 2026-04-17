"""SSE 流式 Agent — langgraph StateGraph + asyncio.Queue 逐字流式

架构：
1. agent_node 通过全局队列推送 LLM 文本增量
2. run_streaming_agent 在后台运行 graph，前台从队列读取事件
3. 工具事件通过 astream 状态快照检测
4. 所有事件统一格式输出 SSE

输出 SSE 事件：
- {"type":"message","content":"delta text"}
- {"type":"tool_call","citation_index":N,...}
- {"type":"tool_result","citation_index":N,"graph_data":{...},...}
- {"type":"error","content":"..."}
"""
import json
import os
import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.graph import build_graph, set_event_queue
from agent.tools import extract_graph_data, extract_entities_from_tool


def _load_system_prompt() -> str:
    """从 prompt.md 文件加载 system prompt"""
    prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


SYSTEM_PROMPT = _load_system_prompt()

# 最大循环轮数
MAX_ITERATIONS = 15


async def run_streaming_agent(report_data: dict, user_message: str, history: list[dict] = None):
    """流式 langgraph agent 生成器

    通过 asyncio.Queue 桥接 graph 流式输出和 SSE：
    - agent_node 流式推送文本增量到队列
    - 后台 task 运行 graph.astream()，检测工具事件推送到队列
    - 前台从队列消费，yield SSE 事件

    Yields:
        dict: SSE 事件
    """
    # 构建初始 messages
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    if report_data:
        context = _build_report_context(report_data)
        messages.append(HumanMessage(content=context))

    if history:
        for h in history[-6:]:
            messages.append(HumanMessage(content=h.get("question", "")))
            messages.append(HumanMessage(content=h.get("answer", "")))

    messages.append(HumanMessage(content=user_message))

    app = build_graph()
    initial_state = {"messages": messages, "citation_counter": 0}

    # 创建事件队列，注入 graph 模块
    queue = asyncio.Queue()
    set_event_queue(queue)

    # 追踪工具调用
    tool_call_map = {}
    citation_counter = 0

    async def _run_graph():
        """后台运行 graph，检测工具事件推送到队列"""
        nonlocal citation_counter
        try:
            async for node_update in app.astream(initial_state):
                for node_name, node_output in node_update.items():
                    new_messages = node_output.get("messages", [])

                    for msg in new_messages:
                        if isinstance(msg, AIMessage):
                            # 工具调用（文本已通过队列流式推送）
                            if getattr(msg, "tool_calls", None):
                                for tc in msg.tool_calls:
                                    citation_counter += 1
                                    tool_name = tc["name"]
                                    tool_args = tc["args"] if isinstance(tc["args"], dict) else {}
                                    citation_title = _derive_citation_title(tool_name, tool_args)

                                    tool_call_map[tc["id"]] = {
                                        "name": tool_name,
                                        "args": tool_args,
                                        "citation_index": citation_counter,
                                        "title": citation_title,
                                    }

                                    await queue.put({
                                        "event": "tool_call",
                                        "tool_name": tool_name,
                                        "tool_args": json.dumps(tool_args, ensure_ascii=False),
                                        "citation_index": citation_counter,
                                        "citation_title": citation_title,
                                    })

                        elif isinstance(msg, ToolMessage):
                            tool_info = tool_call_map.get(msg.tool_call_id, {})
                            tool_name = tool_info.get("name", msg.name or "")
                            tool_args = tool_info.get("args", {})
                            citation_idx = tool_info.get("citation_index", 0)
                            citation_title = tool_info.get("title", "")

                            # 去掉引用前缀
                            result_text = msg.content or ""
                            if result_text.startswith("[引用"):
                                first_newline = result_text.find("\n\n")
                                if first_newline != -1:
                                    result_text = result_text[first_newline + 2:]

                            # 提取图谱数据
                            graph_data = None
                            entities = extract_entities_from_tool(tool_name, tool_args)
                            try:
                                graph_data = extract_graph_data(tool_name, tool_args, result_text)
                            except Exception:
                                pass

                            await queue.put({
                                "event": "tool_result",
                                "tool_name": tool_name,
                                "citation_index": citation_idx,
                                "citation_title": citation_title,
                                "citation_summary": result_text[:500] if result_text else "",
                                "content": result_text,
                                "graph_data": graph_data,
                                "nodes": entities,
                            })

            # graph 完成
            await queue.put({"event": "done"})
        except Exception as e:
            await queue.put({"event": "error", "content": str(e)})

    # 启动后台 graph 任务
    graph_task = asyncio.create_task(_run_graph())

    try:
        # 前台消费队列，yield SSE 事件
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=180)
            except asyncio.TimeoutError:
                yield {"type": "error", "content": "Agent 超时"}
                break

            evt = item.get("event")

            if evt == "text_delta":
                yield {"type": "message", "content": item["content"]}

            elif evt == "tool_call":
                yield {
                    "type": "tool_call",
                    "tool_name": item["tool_name"],
                    "tool_args": item["tool_args"],
                    "citation_index": item["citation_index"],
                    "citation_title": item["citation_title"],
                    "content": "",
                }

            elif evt == "tool_result":
                yield {
                    "type": "tool_result",
                    "tool_name": item["tool_name"],
                    "citation_index": item["citation_index"],
                    "citation_title": item["citation_title"],
                    "citation_summary": item["citation_summary"],
                    "content": item["content"],
                    "graph_data": item["graph_data"],
                    "nodes": item["nodes"],
                    "edges": [],
                }

            elif evt == "error":
                yield {"type": "error", "content": item["content"]}
                break

            elif evt == "done":
                break
    finally:
        # 确保清理
        if not graph_task.done():
            graph_task.cancel()
            try:
                await graph_task
            except asyncio.CancelledError:
                pass
        set_event_queue(None)


def _derive_citation_title(tool_name: str, tool_args: dict) -> str:
    """派生引用标题"""
    if tool_name == "search_knowledge_base":
        kws = tool_args.get("keywords", [])
        if isinstance(kws, list):
            kw_str = "、".join(kws[:3])
            if len(kws) > 3:
                kw_str += "..."
            return f"搜索: {kw_str}"
        return f"搜索: {kws}"
    elif tool_name == "get_entity_detail":
        names = tool_args.get("names", [])
        if isinstance(names, list):
            ns = "、".join(names[:3])
            if len(names) > 3:
                ns += "..."
            return f"详情: {ns}"
        return f"详情: {names}"
    elif tool_name == "get_related_entities":
        names = tool_args.get("names", [])
        if isinstance(names, list):
            ns = "、".join(names[:3])
            if len(names) > 3:
                ns += "..."
            return f"关联: {ns}"
        return f"关联: {names}"
    elif tool_name == "query_knowledge_graph_cypher":
        q = tool_args.get("natural_language_query", "")
        if len(q) > 20:
            return f"Cypher: {q[:20]}..."
        return f"Cypher: {q}"
    return tool_name


def _build_report_context(report_data: dict) -> str:
    """构建报告上下文文本"""
    p = report_data.get("patient", {})
    bacteria = report_data.get("bacteria_name", "未知")
    specimen = report_data.get("specimen", "未知")
    esbl = report_data.get("esbl", "")
    cre = report_data.get("cre", False)
    susc = report_data.get("susceptibility", [])

    lines = [
        "以下是当前患者的微生物检验报告数据，请基于此进行分析：",
        "",
        f"**检出菌**: {bacteria}",
        f"**标本**: {specimen}",
    ]

    if p.get("gender"):
        lines.append(f"**患者**: {p['gender']}性, {p.get('age', '?')}岁")
    if p.get("department"):
        lines.append(f"**科室**: {p['department']}")

    if esbl == "POS":
        lines.append("**ESBL**: 阳性")
    if cre:
        lines.append("**CRE**: 碳青霉烯类耐药")

    if susc:
        lines.append("")
        lines.append("**药敏结果**:")
        for s in susc:
            sir_map = {"S": "敏感", "I": "中介", "R": "耐药"}
            sir_text = sir_map.get(s.get("sir", ""), s.get("sir", ""))
            mic = f" MIC={s['mic_value']}" if s.get("mic_value") else ""
            lines.append(f"- {s['drug_name']}: {sir_text}{mic}")

    return "\n".join(lines)
