"""Agent 状态定义"""
from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    report_data: Optional[dict]
    report_markdown: Optional[str]
    citation_counter: int          # 引用编号计数器（tool_node 递增）
