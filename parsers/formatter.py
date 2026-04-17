"""报告格式化模块 — 将解析后的报告数据转为 Markdown"""


def format_report_markdown(report: dict) -> str:
    """将结构化报告数据格式化为 Markdown 文档"""
    p = report.get("patient", {})
    bacteria = report.get("bacteria_name", "未检出")
    specimen = report.get("specimen", "")
    esbl = report.get("esbl", "")
    cre = report.get("cre", False)
    susc = report.get("susceptibility", [])

    lines = [
        "# 微生物检验报告",
        "",
        "## 基本信息",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 样本编号 | {p.get('sample_id', '-')} |",
        f"| 样本类型 | {p.get('sample_type', '-')} |",
        f"| 标本 | {specimen} |",
        f"| 患者性别 | {p.get('gender', '-')} |",
        f"| 患者年龄 | {p.get('age', '-')}岁 |",
        f"| 科室 | {p.get('department', '-')} |",
        f"| 床位 | {p.get('bed_no', '-')} |",
        f"| 采集时间 | {p.get('collection_date', '-')} |",
        f"| 报告时间 | {p.get('report_date', '-')} |",
        "",
        "## 细菌鉴定",
        "",
        f"**检出细菌**: {bacteria}",
        "",
        "## 耐药标记",
        "",
    ]

    if esbl:
        lines.append(f"- **ESBL检测**: {'阳性 (+)' if esbl == 'POS' else '阴性 (-)'}")
    if cre:
        lines.append("- **CRE**: 检出 (碳青霉烯类耐药)")
    if not esbl and not cre:
        lines.append("- 无特殊耐药标记")
    lines.append("")

    if susc:
        lines += [
            "## 药敏结果",
            "",
            "| 序号 | 抗菌药物 | MIC值 | 敏感性 |",
            "|------|----------|-------|--------|",
        ]
        for i, s in enumerate(susc, 1):
            sir_text = s.get("sir", "")
            sir_display = {"S": "S (敏感)", "I": "I (中介)", "R": "R (耐药)"}.get(sir_text, sir_text)
            lines.append(f"| {i} | {s.get('drug_name', '-')} | {s.get('mic_value', '-')} | {sir_display} |")
        lines.append("")

        r_count = sum(1 for s in susc if s.get("sir") == "R")
        s_count = sum(1 for s in susc if s.get("sir") == "S")
        i_count = sum(1 for s in susc if s.get("sir") == "I")

        lines += [
            "### 药敏汇总",
            "",
            f"- 共检测 **{len(susc)}** 种抗菌药物",
            f"- 耐药 (R): **{r_count}** 种",
            f"- 敏感 (S): **{s_count}** 种",
            f"- 中介 (I): **{i_count}** 种",
            "",
        ]

        if r_count == len(susc):
            lines.append("> **注意**: 所有检测药物均显示耐药,建议补充检测新型抗菌药物。")
            lines.append("")

    return "\n".join(lines)
