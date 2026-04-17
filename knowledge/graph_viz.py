"""知识图谱可视化数据生成

为前端 SVG 渲染生成 {center, nodes, edges} 格式数据。
"""
from knowledge.graph_store import get_node_neighborhood, _get_conn, _rows

# 前端节点类型映射（KuzuDB 节点表名 → 前端显示类型）
TYPE_MAP = {
    "Drug": "Drug",
    "Organism": "Bacterium",
    "DrugClass": "DrugClass",
    "ResistanceMechanism": "ResistanceMechanism",
    "TreatmentPlan": "TreatmentPlan",
    "InfectionSite": "InfectionSite",
}


def get_graph_data(entity_name: str) -> dict | None:
    """获取实体 1-hop 邻域的可视化数据

    返回格式:
    {
        "center": "meropenem",
        "nodes": [{"id": "meropenem", "type": "Drug", "name": "美罗培南"}, ...],
        "edges": [{"source": "meropenem", "target": "carbapenems", "relation": "BELONGS_TO_CLASS"}, ...]
    }
    """
    hood = get_node_neighborhood(entity_name)
    if not hood["node"]:
        return None

    center_name = hood["node"]["name"]
    nodes = []
    edges = []

    # 中心节点（带完整属性）
    center_type = TYPE_MAP.get(hood["node"]["type"], hood["node"]["type"])
    center_node = {
        "id": center_name,
        "type": center_type,
        "name": center_name,
    }
    # 附加节点属性（Drug 的 mechanism/dosing 等，TreatmentPlan 的 first_line 等）
    for k, v in hood["node"].items():
        if k not in ("name", "type") and v:
            center_node[k] = v
    nodes.append(center_node)

    # 邻居节点（带属性）
    for nb in hood["neighbors"]:
        nb_type = TYPE_MAP.get(nb["type"], nb["type"])
        nb_node = {
            "id": nb["name"],
            "type": nb_type,
            "name": nb["name"],
        }
        for k, v in nb.items():
            if k not in ("name", "type") and v:
                nb_node[k] = v
        nodes.append(nb_node)

    # 边
    for edge in hood["edges"]:
        edges.append({
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge["relation"],
        })

    return {"center": center_name, "nodes": nodes, "edges": edges}
