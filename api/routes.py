"""API 路由处理器"""
import json
import uuid
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse, FileResponse

from api.schemas import ChatRequest, EdgeExplainRequest
from parsers.pdf_parser import parse_report, PDF_EXTENSIONS, IMAGE_EXTENSIONS
from parsers.formatter import format_report_markdown
from agent.streamer import run_streaming_agent
from knowledge.graph_store import search_nodes, get_node_neighborhood
from config import SESSION_DIR, FRONTEND_DIR

router = APIRouter()


# ─── Session 持久化 ───

def _session_path(session_id: str) -> str:
    return os.path.join(SESSION_DIR, f"{session_id}.json")


def _save_session(session_id: str, data: dict):
    path = _session_path(session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_session(session_id: str) -> dict | None:
    path = _session_path(session_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_session(session_id: str) -> dict:
    s = _load_session(session_id)
    if s is None:
        raise HTTPException(404, "会话不存在")
    return s


def _list_sessions() -> list[dict]:
    results = []
    if not os.path.isdir(SESSION_DIR):
        return results
    for fname in os.listdir(SESSION_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(SESSION_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            report = s.get("report_data", {})
            results.append({
                "session_id": s.get("session_id", fname[:-5]),
                "bacteria": report.get("bacteria_name", ""),
                "specimen": report.get("specimen", ""),
                "department": report.get("patient", {}).get("department", ""),
                "created_at": s.get("created_at", ""),
            })
        except Exception:
            continue
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results


# ─── 页面路由 ───

@router.get("/chat", response_class=HTMLResponse)
async def chat_page():
    chat_html = Path(FRONTEND_DIR) / "chat.html"
    if chat_html.exists():
        return HTMLResponse(content=chat_html.read_text(encoding="utf-8"))
    raise HTTPException(404, "chat.html not found")


@router.get("/graph", response_class=HTMLResponse)
async def graph_page():
    graph_html = Path(FRONTEND_DIR) / "graph.html"
    if graph_html.exists():
        return HTMLResponse(content=graph_html.read_text(encoding="utf-8"))
    raise HTTPException(404, "graph.html not found")


# ─── 上传 ───

@router.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""

    if ext not in PDF_EXTENSIONS and ext not in IMAGE_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式: {ext}，请上传 PDF 或图片文件")

    session_id = uuid.uuid4().hex[:8]
    filepath = f"uploads/{session_id}_{file.filename}"

    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

    # 解析报告
    report = parse_report(filepath)

    # 生成 Markdown
    report_markdown = format_report_markdown(report)

    # 创建会话
    session_data = {
        "session_id": session_id,
        "report_data": report,
        "report_markdown": report_markdown,
        "filepath": filepath,
        "created_at": datetime.now().isoformat(),
        "analysis_log": [],
    }
    _save_session(session_id, session_data)

    return {
        "session_id": session_id,
        "report": report,
        "report_markdown": report_markdown,
    }


# ─── 聊天（SSE 流式） ───

@router.post("/api/chat")
async def chat(request: ChatRequest):
    session = _load_session(request.session_id)
    report_data = session.get("report_data") if session else None
    history = session.get("analysis_log", []) if session else []

    async def event_generator():
        collected = []
        collected_entities = []
        try:
            async for event in run_streaming_agent(report_data, request.message, history):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "message":
                    collected.append(event.get("content", ""))
                if event.get("type") == "tool_result":
                    for n in event.get("nodes", []):
                        if n not in collected_entities:
                            collected_entities.append(n)
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

        # 记录到会话
        if request.session_id and collected:
            s = _load_session(request.session_id)
            if s:
                s["analysis_log"].append({
                    "question": request.message,
                    "answer": "".join(collected),
                    "entities": collected_entities,
                    "timestamp": datetime.now().isoformat(),
                })
                _save_session(request.session_id, s)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ─── 会话管理 ───

@router.get("/api/sessions")
async def list_sessions():
    return {"sessions": _list_sessions()}


@router.get("/api/report/{session_id}")
async def get_report(session_id: str):
    session = _get_session(session_id)
    return {
        "report": session["report_data"],
        "report_markdown": session["report_markdown"],
        "analysis_log": session.get("analysis_log", []),
    }


# ─── 导出 ───

@router.get("/api/export/{session_id}")
async def export_report(session_id: str):
    session = _get_session(session_id)
    report = session["report_data"]
    markdown = session["report_markdown"]
    log = session.get("analysis_log", [])

    lines = [
        f"# 微生物报告分析导出",
        f"\n导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n---\n",
        markdown,
    ]

    if log:
        lines.append("\n## 分析记录\n")
        for entry in log:
            lines.append(f"### Q: {entry['question']}")
            lines.append(entry["answer"])
            lines.append("")

    content = "\n".join(lines)
    return PlainTextResponse(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=microbio_report_{session_id}.md"},
    )


# ─── 查看原始文件 ───

@router.get("/api/file/{session_id}")
async def get_original_file(session_id: str):
    session = _get_session(session_id)
    filepath = session.get("filepath", "")
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(404, "原始文件不存在")
    return FileResponse(
        filepath,
        media_type="application/octet-stream",
        filename=os.path.basename(filepath),
    )


# ─── 知识图谱 API ───

@router.get("/api/graph/search")
async def graph_search(q: str, limit: int = 20):
    results = search_nodes(q, limit)
    return {"results": results}


@router.get("/api/graph/node/{node_name:path}")
async def graph_node(node_name: str):
    hood = get_node_neighborhood(node_name)
    if not hood["node"]:
        raise HTTPException(404, f"未找到节点: {node_name}")
    return hood


@router.get("/api/graph/node")
async def graph_node_query(node_name: str):
    hood = get_node_neighborhood(node_name)
    if not hood["node"]:
        raise HTTPException(404, f"未找到节点: {node_name}")
    return hood


@router.get("/api/graph/expand/{node_name:path}")
async def graph_expand(node_name: str):
    hood = get_node_neighborhood(node_name)
    return hood


@router.get("/api/graph/expand")
async def graph_expand_query(node_name: str):
    hood = get_node_neighborhood(node_name)
    return hood


@router.get("/api/graph/all")
async def graph_all():
    """返回全图数据（所有节点和边）"""
    from knowledge.graph_store import get_all_graph_data
    return get_all_graph_data()


@router.post("/api/graph/explain")
async def graph_explain_edge(req: EdgeExplainRequest):
    from agent.llm import chat_completion

    prompt = (
        f"在微生物学知识图谱中，存在一条从「{req.source}」到「{req.target}」的关系，"
        f"关系类型为「{req.relation}」。"
        f"请用通俗易懂的中文，为临床医生简要解释这条关系的临床意义（2-3句话）。"
        f"不要使用 Markdown 格式。"
    )

    messages = [
        {"role": "system", "content": "你是一个临床微生物学专家，请用简洁专业的语言回答。"},
        {"role": "user", "content": prompt},
    ]

    try:
        result = chat_completion(messages, tools=None, model=None)
        content = result["choices"][0]["message"]["content"]
        return {"explanation": content}
    except Exception as e:
        return {"explanation": f"[解释失败: {str(e)}]"}
