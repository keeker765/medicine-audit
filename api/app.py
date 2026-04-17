"""FastAPI 应用"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import FRONTEND_DIR
from api.routes import router
from knowledge.graph_store import init_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="微生物报告智能解读系统", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    logger.info("初始化知识图谱...")
    init_graph()
    logger.info("知识图谱就绪")


app.include_router(router)

# 挂载前端静态文件（放在最后，作为 fallback）
frontend_path = Path(FRONTEND_DIR)
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
