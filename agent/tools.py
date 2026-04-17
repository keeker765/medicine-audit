"""工具函数 — 逐步探索知识图谱 + Cypher skill 兜底

所有探索工具支持 list 输入，内部批量执行，返回合并结果。
同时兼容模型发送单数字符串参数（keyword/name）和列表参数（keywords/names）。
"""
import json
import os

from langchain_core.tools import tool

from agent.llm import chat_completion
from knowledge.graph_store import (
    execute_cypher,
    get_schema_text,
    search_nodes,
    get_node_neighborhood,
)
from knowledge.graph_viz import get_graph_data

# Cypher 生成使用更快的模型
CYPHER_MODEL = "google/gemini-3.1-flash-lite-preview"


def _normalize_to_list(value) -> list[str]:
    """将输入标准化为 list[str]，兼容模型发送的 string 或 list"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return [str(value)]


# ─── 工具 1: 关键词搜索（支持多个关键词） ───

@tool
def search_knowledge_base(keywords: list[str] = None, keyword: str = None, entity_type: str = None) -> str:
    """按关键词搜索知识图谱中的实体（药物、菌种、治疗方案等）。

    支持传入多个关键词同时搜索，合并去重后返回。
    可选按 entity_type 过滤（Drug/Organism/DrugClass/ResistanceMechanism/InfectionSite）。
    """
    # 兼容：模型可能发送 keyword（单数）或 keywords（复数）
    kws = _normalize_to_list(keywords) if keywords else _normalize_to_list(keyword)
    if not kws:
        return "请提供搜索关键词"

    all_results = []
    seen_names = set()
    for kw in kws:
        results = search_nodes(kw, limit=10)
        for r in results:
            if entity_type and r.get("type") != entity_type:
                continue
            if r["name"] not in seen_names:
                seen_names.add(r["name"])
                all_results.append(r)

    if not all_results:
        kw_str = "、".join(kws)
        return f"未找到与 '{kw_str}' 相关的实体。"

    lines = []
    for r in all_results:
        en = f" ({r['english']})" if r.get("english") else ""
        lines.append(f"- [{r['type']}] {r['name']}{en}")
    return "\n".join(lines)


# ─── 工具 2: 实体详情（支持多个实体） ───

@tool
def get_entity_detail(names: list[str] = None, name: str = None) -> str:
    """获取实体的完整属性和所有关联关系。

    支持传入多个实体名称同时查询，返回每个实体的详细信息和 1-hop 邻域关系。
    """
    name_list = _normalize_to_list(names) if names else _normalize_to_list(name)
    if not name_list:
        return "请提供实体名称"

    parts = []
    for n in name_list:
        data = get_node_neighborhood(n)
        if not data["node"]:
            parts.append(f"未找到实体: {n}\n")
            continue
        parts.append(_format_neighborhood(data))

    return "\n\n---\n\n".join(parts)


# ─── 工具 3: 关联实体（支持多个实体） ───

@tool
def get_related_entities(names: list[str] = None, name: str = None, relation: str = None) -> str:
    """获取与指定实体通过特定关系类型相连的其他实体。

    支持传入多个实体名称同时查询。
    可选 relation 过滤关系类型
    （BELONGS_TO_CLASS/INTRINSIC_RESISTANT/HAS_TREATMENT/RECOMMENDED_FOR/COMMON_IN/AMPC_RISK）。
    """
    name_list = _normalize_to_list(names) if names else _normalize_to_list(name)
    if not name_list:
        return "请提供实体名称"

    parts = []
    for n in name_list:
        data = get_node_neighborhood(n)
        if not data["node"]:
            parts.append(f"未找到实体: {n}\n")
            continue
        parts.append(_format_filtered_neighborhood(data, relation))

    return "\n\n---\n\n".join(parts)


# ─── 工具 4: Cypher skill（兜底） ───

def _load_cypher_prompt() -> str:
    """从 cypher_prompt.md 加载 Cypher 生成 prompt"""
    prompt_path = os.path.join(os.path.dirname(__file__), "cypher_prompt.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()

_CYPHER_SYSTEM_PROMPT = _load_cypher_prompt()


@tool
def query_knowledge_graph_cypher(natural_language_query: str) -> str:
    """使用 Cypher 直接查询知识图谱。

    仅在复杂查询且其他工具无法满足时使用。
    输入自然语言查询，系统会自动生成 Cypher 并执行。
    """
    schema_text = get_schema_text()

    # AI 生成 Cypher
    cypher_resp = chat_completion([
        {"role": "system", "content": _CYPHER_SYSTEM_PROMPT.format(schema=schema_text)},
        {"role": "user", "content": natural_language_query},
    ], model=CYPHER_MODEL)
    cypher = cypher_resp["choices"][0]["message"]["content"].strip()

    # 清理 markdown 代码块包裹
    if cypher.startswith("```"):
        cypher = "\n".join(cypher.split("\n")[1:])
        if cypher.endswith("```"):
            cypher = cypher[:-3]
        cypher = cypher.strip()

    # 执行 Cypher
    try:
        raw_results = execute_cypher(cypher)
    except Exception as e:
        return f"查询执行失败: {e}\n\n生成的 Cypher: {cypher}"

    return _format_results(raw_results) if raw_results else "未找到相关知识"


# ─── 工具列表（供 langgraph 使用） ───

ALL_TOOLS = [
    search_knowledge_base,
    get_entity_detail,
    get_related_entities,
    query_knowledge_graph_cypher,
]


# ─── OpenAI function calling 格式的工具 schema（供流式 LLM 用） ───

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "按关键词搜索知识图谱中的实体（药物、菌种、治疗方案等）。支持传入多个关键词同时搜索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "搜索关键词列表，如 ['美罗培南', '头孢他啶', 'ESBL']。也可传单个字符串。",
                    },
                    "entity_type": {
                        "type": "string",
                        "description": "可选，过滤实体类型：Drug/Organism/DrugClass/ResistanceMechanism/InfectionSite",
                    },
                },
                "required": ["keywords"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_detail",
            "description": "获取实体的完整属性和所有关联关系。支持传入多个实体名称同时查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "实体名称列表，如 ['美罗培南', '肺炎克雷伯菌']。也可传单个字符串。",
                    },
                },
                "required": ["names"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_related_entities",
            "description": "获取与指定实体通过特定关系类型相连的其他实体。支持传入多个实体名称同时查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "实体名称列表，如 ['肺炎克雷伯菌', '大肠埃希菌']。也可传单个字符串。",
                    },
                    "relation": {
                        "type": "string",
                        "description": "可选，关系类型过滤：BELONGS_TO_CLASS/INTRINSIC_RESISTANT/HAS_TREATMENT/RECOMMENDED_FOR/COMMON_IN/AMPC_RISK",
                    },
                },
                "required": ["names"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_graph_cypher",
            "description": "使用 Cypher 直接查询知识图谱。仅在复杂查询且其他工具无法满足时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "natural_language_query": {
                        "type": "string",
                        "description": "自然语言查询，如'碳青霉烯耐药株的推荐治疗方案'",
                    },
                },
                "required": ["natural_language_query"],
            },
        }
    },
]


# ─── 辅助函数 ───

def extract_graph_data(tool_name: str, tool_args: dict, tool_result: str) -> dict | None:
    """从工具结果中提取图谱可视化数据"""
    if tool_name == "search_knowledge_base":
        return None

    if tool_name in ("get_entity_detail", "get_related_entities"):
        name_list = _get_names_from_args(tool_args)
        for n in name_list:
            data = get_graph_data(n)
            if data and data.get("nodes"):
                return data
        return None

    if tool_name == "query_knowledge_graph_cypher":
        entities = _extract_entities_from_result(tool_result)
        if entities:
            return get_graph_data(entities[0]["name"])
        return None

    return None


def extract_entities_from_tool(tool_name: str, tool_args: dict) -> list[dict]:
    """从工具调用参数中提取涉及的实体"""
    if tool_name == "search_knowledge_base":
        kws = _get_keywords_from_args(tool_args)
        return [{"id": kw, "name": kw, "type": ""} for kw in kws]

    if tool_name in ("get_entity_detail", "get_related_entities"):
        name_list = _get_names_from_args(tool_args)
        return [{"id": n, "name": n, "type": ""} for n in name_list]

    return []


def _get_names_from_args(tool_args: dict) -> list[str]:
    """从工具参数中提取实体名称列表，兼容 name/names"""
    names = tool_args.get("names")
    name = tool_args.get("name")
    return _normalize_to_list(names) if names else _normalize_to_list(name)


def _get_keywords_from_args(tool_args: dict) -> list[str]:
    """从工具参数中提取关键词列表，兼容 keyword/keywords"""
    keywords = tool_args.get("keywords")
    keyword = tool_args.get("keyword")
    return _normalize_to_list(keywords) if keywords else _normalize_to_list(keyword)


def _extract_entities_from_result(result_text: str) -> list[dict]:
    """从格式化的结果文本中粗略提取实体名称"""
    import re
    entities = []
    for m in re.finditer(r"\*\*[^:]+:\s*([^*]+)\*\*", result_text):
        name = m.group(1).strip()
        if name:
            entities.append({"id": name, "name": name, "type": ""})
    return entities[:10]


def _format_neighborhood(data: dict) -> str:
    """格式化节点邻域信息（包含节点属性 + 关联关系）"""
    node = data["node"]
    edges = data.get("edges", [])

    lines = [f"**{node['type']}: {node['name']}**"]

    # 显示节点自身属性
    for key, val in node.items():
        if key in _SKIP_FIELDS or key in ("name", "type") or val is None or val == "":
            continue
        label = _FIELD_LABELS.get(key, key)
        lines.append(f"- {label}: {val}")

    # 显示关联关系
    if edges:
        relation_groups = {}
        for e in edges:
            rel = e["relation"]
            if rel not in relation_groups:
                relation_groups[rel] = []
            target_name = e["target"]
            relation_groups[rel].append(target_name)

        rel_labels = {
            "BELONGS_TO_CLASS": "所属药物分类",
            "INTRINSIC_RESISTANT": "天然耐药",
            "HAS_TREATMENT": "治疗方案",
            "RECOMMENDED_FOR": "推荐用于",
            "COMMON_IN": "常见感染部位",
            "AMPC_RISK": "AmpC 风险",
        }

        for rel, targets in relation_groups.items():
            label = rel_labels.get(rel, rel)
            lines.append(f"- {label}: {', '.join(targets)}")

    return "\n".join(lines)


def _format_filtered_neighborhood(data: dict, relation: str = None) -> str:
    """格式化过滤后的邻域关系"""
    node = data["node"]
    edges = data.get("edges", [])

    if relation:
        edges = [e for e in edges if e["relation"] == relation]

    if not edges:
        rel_info = f" (关系: {relation})" if relation else ""
        return f"{node['name']}{rel_info} — 无关联实体"

    lines = [f"**{node['name']} 的关联实体**:"]
    for e in edges:
        lines.append(f"- [{e['relation']}] → {e['target']}")
    return "\n".join(lines)


def _format_results(results: list) -> str:
    """将 Cypher 查询结果格式化为可读 Markdown 文本"""
    if not results:
        return "未找到相关知识"

    parts = []
    for i, row in enumerate(results):
        if not isinstance(row, dict):
            parts.append(f"{i + 1}. {row}")
            continue

        node_type = row.get("_label", "")
        type_label = _TYPE_LABELS.get(node_type, "实体")

        name = row.get("name") or row.get("plan_id") or ""
        if name:
            parts.append(f"**{type_label}: {name}**")
        else:
            parts.append(f"**{type_label} #{i + 1}**")

        for key, val in row.items():
            if key in _SKIP_FIELDS or val is None or val == "":
                continue
            label = _FIELD_LABELS.get(key, key)
            parts.append(f"- {label}: {val}")

        parts.append("")

    return "\n".join(parts)


_TYPE_LABELS = {
    "Drug": "药物",
    "Organism": "微生物",
    "DrugClass": "药物分类",
    "ResistanceMechanism": "耐药机制",
    "TreatmentPlan": "治疗方案",
    "InfectionSite": "感染部位",
}

_FIELD_LABELS = {
    "name": "名称", "english": "英文名", "drug_class": "药物分类",
    "mechanism": "作用机制", "spectrum_text": "抗菌谱", "dosing_info": "剂量",
    "adverse_effects": "不良反应", "key_notes": "注意事项",
    "admin_tier": "管理分级", "clsi_tier": "CLSI分级",
    "breakpoint_s": "S折点", "breakpoint_i": "I折点", "breakpoint_r": "R折点",
    "breakpoint_sdd": "SDD折点", "route": "给药途径",
    "characteristics": "特征", "common_infections": "常见感染",
    "category": "类别", "description": "描述",
    "clinical_rule": "临床规则", "recommended_text": "推荐药物",
    "alternative_text": "替代药物", "avoid_text": "避免药物",
    "plan_id": "方案ID", "organism_name": "目标菌种",
    "resistance_context": "耐药背景", "first_line": "一线方案",
    "alternative": "替代方案", "combination": "联合方案",
    "last_resort": "最后手段", "oral_stepdown": "口服降阶梯",
    "notes": "备注", "empiric_therapy": "经验治疗",
    "duration": "疗程", "common_pathogens": "常见病原体",
}

_SKIP_FIELDS = {"_id", "_label", "_src", "_dst"}
