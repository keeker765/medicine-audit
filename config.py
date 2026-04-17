"""全局配置"""
import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# LLM 模型
LLM_MODEL = "z-ai/glm-5.1"
OCR_MODEL = "qwen/qwen3.5-flash-02-23"

# 项目路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_BASE_DIR = os.path.join(BASE_DIR, "knowledge_base")
KUZU_DB_DIR = os.path.join(BASE_DIR, "kuzu_data")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
SESSION_DIR = os.path.join(BASE_DIR, "sessions")

# 确保目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SESSION_DIR, exist_ok=True)
