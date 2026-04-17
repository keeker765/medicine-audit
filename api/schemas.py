"""Pydantic 请求/响应模型"""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class EdgeExplainRequest(BaseModel):
    source: str
    target: str
    relation: str
