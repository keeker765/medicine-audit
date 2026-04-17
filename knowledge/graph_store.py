"""KuzuDB 知识图谱存储 — 精简版

保留：Schema DDL + YAML 数据导入 + 名称规范化 + 通用 Cypher 执行
删除：所有硬编码查询函数（由 AI 生成 Cypher 替代）
新增：execute_cypher / get_schema_text / search_nodes / get_node_neighborhood
"""
import json
import logging
import os
import re
import shutil
from typing import Optional

import yaml
import kuzu

from config import KUZU_DB_DIR, KNOWLEDGE_BASE_DIR

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 模块级状态
# ═══════════════════════════════════════════════════════════════════

_db: Optional[kuzu.Database] = None
_conn: Optional[kuzu.Connection] = None
_MARKER = KUZU_DB_DIR + ".imported"


def _get_conn() -> kuzu.Connection:
    global _db, _conn
    if _conn is None:
        _db = kuzu.Database(KUZU_DB_DIR)
        _conn = kuzu.Connection(_db)
    return _conn


def _load_yaml(filename: str) -> dict:
    path = os.path.join(KNOWLEDGE_BASE_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ═══════════════════════════════════════════════════════════════════
# 名称规范化
# ═══════════════════════════════════════════════════════════════════

DRUG_ALIASES = {
    "哌拉西林-他唑巴坦": "哌拉西林/他唑巴坦",
    "阿莫西林-克拉维酸": "阿莫西林/克拉维酸",
    "氨苄西林-舒巴坦": "氨苄西林/舒巴坦",
    "甲氧苄啶-磺胺甲噁唑": "甲氧苄啶/磺胺甲噁唑",
    "头孢他啶-阿维巴坦": "头孢他啶/阿维巴坦",
    "头孢洛扎-他唑巴坦": "头孢洛扎/他唑巴坦",
    "头孢哌酮-舒巴坦": "头孢哌酮/舒巴坦",
    "亚胺培南-瑞来巴坦": "亚胺培南/瑞来巴坦",
    "美罗培南-韦博巴坦": "美罗培南/法硼巴坦",
    "美罗培南/韦博巴坦": "美罗培南/法硼巴坦",
    "多黏菌素E（黏菌素）": "多黏菌素E",
    "多黏菌素E(黏菌素)": "多黏菌素E",
    "黏菌素": "多黏菌素E",
    "头孢呋辛酯": "头孢呋辛",
    "复方磺胺甲噁唑": "甲氧苄啶/磺胺甲噁唑",
}

ORGANISM_ALIASES = {
    "弗劳地柠檬酸杆菌复合群": "弗氏柠檬酸杆菌复合群",
    "产气克雷伯菌": "产气肠杆菌",
    "黏质沙雷菌": "粘质沙雷菌",
}


def _norm_drug(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[（(][^）)]*[）)]$', '', name).strip()
    if re.search(r'[\u4e00-\u9fff]', name):
        name = name.replace('-', '/')
    return DRUG_ALIASES.get(name, name)


def _norm_org(name: str) -> str:
    name = name.strip()
    name = re.sub(r'\s*\(.*?\)\s*$', '', name).strip()
    name = re.sub(r'\s*（.*?）\s*$', '', name).strip()
    return ORGANISM_ALIASES.get(name, name)


def _parse_intrinsic_drugs(drug_raw: str) -> list[str]:
    if "黏菌素/多黏菌素" in drug_raw:
        return ["多黏菌素B", "多黏菌素E"]
    base = re.sub(r'[（(][^）)]*[）)]', '', drug_raw).strip()
    if "/" in base:
        return [_norm_drug(p.strip()) for p in base.split("/") if p.strip()]
    return [_norm_drug(base)]


# ═══════════════════════════════════════════════════════════════════
# Schema DDL
# ═══════════════════════════════════════════════════════════════════

_SCHEMA = [
    """CREATE NODE TABLE IF NOT EXISTS Drug (
        name STRING, english STRING, drug_class STRING,
        mechanism STRING, spectrum_text STRING, dosing_info STRING,
        adverse_effects STRING, key_notes STRING,
        admin_tier STRING, clsi_tier STRING,
        breakpoint_s STRING, breakpoint_i STRING,
        breakpoint_r STRING, breakpoint_sdd STRING,
        route STRING,
        PRIMARY KEY (name)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Organism (
        name STRING, english STRING,
        characteristics STRING, common_infections STRING,
        PRIMARY KEY (name)
    )""",
    "CREATE NODE TABLE IF NOT EXISTS DrugClass (name STRING, PRIMARY KEY (name))",
    """CREATE NODE TABLE IF NOT EXISTS ResistanceMechanism (
        name STRING, category STRING, description STRING,
        clinical_rule STRING, recommended_text STRING,
        alternative_text STRING, avoid_text STRING,
        PRIMARY KEY (name)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS TreatmentPlan (
        plan_id STRING, organism_name STRING, resistance_context STRING,
        first_line STRING, alternative STRING, combination STRING,
        last_resort STRING, oral_stepdown STRING, notes STRING,
        PRIMARY KEY (plan_id)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS InfectionSite (
        name STRING, empiric_therapy STRING,
        duration STRING, common_pathogens STRING,
        PRIMARY KEY (name)
    )""",
    "CREATE REL TABLE IF NOT EXISTS BELONGS_TO_CLASS (FROM Drug TO DrugClass)",
    "CREATE REL TABLE IF NOT EXISTS INTRINSIC_RESISTANT (FROM Organism TO Drug, action STRING)",
    "CREATE REL TABLE IF NOT EXISTS HAS_TREATMENT (FROM Organism TO TreatmentPlan)",
    "CREATE REL TABLE IF NOT EXISTS RECOMMENDED_FOR (FROM Drug TO ResistanceMechanism, line STRING)",
    "CREATE REL TABLE IF NOT EXISTS COMMON_IN (FROM Organism TO InfectionSite)",
    "CREATE REL TABLE IF NOT EXISTS AMPC_RISK (FROM Organism TO ResistanceMechanism, risk_level STRING)",
]

_SCHEMA_DESCRIPTION = """
知识图谱包含以下节点类型和关系：

## 节点类型
- Drug(name, english, drug_class, mechanism, spectrum_text, dosing_info, adverse_effects, key_notes, admin_tier, clsi_tier, breakpoint_s/i/r/sdd, route)
- Organism(name, english, characteristics, common_infections)
- DrugClass(name)
- ResistanceMechanism(name, category, description, clinical_rule, recommended_text, alternative_text, avoid_text)
- TreatmentPlan(plan_id, organism_name, resistance_context, first_line, alternative, combination, last_resort, oral_stepdown, notes)
- InfectionSite(name, empiric_therapy, duration, common_pathogens)

## 关系类型
- (Drug)-[:BELONGS_TO_CLASS]->(DrugClass)
- (Organism)-[:INTRINSIC_RESISTANT {action}]->(Drug)
- (Organism)-[:HAS_TREATMENT]->(TreatmentPlan)
- (Drug)-[:RECOMMENDED_FOR {line}]->(ResistanceMechanism)
- (Organism)-[:COMMON_IN]->(InfectionSite)
- (Organism)-[:AMPC_RISK {risk_level}]->(ResistanceMechanism)

注意：药物 name 用中文名（如"美罗培南"），菌种 name 用中文名（如"肺炎克雷伯菌"）。

## 关键字段示例值（查询时务必使用这些实际值）
TreatmentPlan.resistance_context 的实际值：
  "敏感株（非产ESBL）", "产ESBL株", "碳青霉烯耐药株(CRKP) > enzyme_type_unknown",
  "碳青霉烯耐药株(CRKP) > KPC_producing", "碳青霉烯耐药株(CRKP) > NDM_producing",
  "特殊人群", "敏感株"
查询 CRE/碳青霉烯耐药 时用 CONTAINS '碳青霉烯' 而非 'CRE'。
查询 ESBL 时用 CONTAINS 'ESBL'。
ResistanceMechanism.name 的实际值："ESBL", "KPC", "NDM", "AmpC"。
Organism.name 示例："肺炎克雷伯菌", "大肠埃希菌", "铜绿假单胞菌", "鲍曼不动杆菌"。
"""


# ═══════════════════════════════════════════════════════════════════
# 数据导入
# ═══════════════════════════════════════════════════════════════════

def _import_all(conn: kuzu.Connection):
    drugs_yaml = _load_yaml("drugs.yaml")
    reporting_yaml = _load_yaml("reporting.yaml")
    treatment_yaml = _load_yaml("treatment.yaml")
    resistance_yaml = _load_yaml("resistance.yaml")
    reference_yaml = _load_yaml("reference.yaml")

    drug_set = _import_drugs(conn, drugs_yaml, reporting_yaml)
    org_set = _import_organisms(conn, reference_yaml, treatment_yaml)
    cls_set = _import_drug_classes(conn, drugs_yaml, reporting_yaml)
    _import_resistance_mechanisms(conn, resistance_yaml)
    _import_treatment_plans(conn, treatment_yaml)
    _import_infection_sites(conn, treatment_yaml)

    _import_drug_class_rels(conn, drug_set, cls_set)
    _import_intrinsic_resistance_rels(conn, resistance_yaml, org_set, drug_set)
    _import_treatment_rels(conn, org_set)
    _import_resistance_drug_rels(conn, resistance_yaml, drug_set)
    _import_infection_site_rels(conn, treatment_yaml, org_set)
    _import_ampc_rels(conn, resistance_yaml, org_set)


def _rows(result) -> list:
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    return rows


def _safe_create_rel(conn, cypher: str, params: dict) -> bool:
    try:
        conn.execute(cypher, params)
        return True
    except Exception:
        return False


# --- 节点导入 ---

def _import_organisms(conn, reference_yaml, treatment_yaml) -> set[str]:
    organisms = {}
    for entry in reference_yaml.get("organisms_covered", []):
        m = re.match(r'^(.+?)\s*\((.+?)\)\s*$', entry)
        if m:
            cn = _norm_org(m.group(1))
            organisms[cn] = {"english": m.group(2), "characteristics": "", "common_infections": ""}

    for org_name, org_data in treatment_yaml.get("treatment_guidelines", {}).items():
        cn = _norm_org(org_name)
        if cn not in organisms:
            organisms[cn] = {"english": "", "characteristics": "", "common_infections": ""}
        organisms[cn]["english"] = org_data.get("english", organisms[cn]["english"])
        organisms[cn]["characteristics"] = org_data.get("characteristic", "")
        ci = org_data.get("common_infections", [])
        organisms[cn]["common_infections"] = json.dumps(ci, ensure_ascii=False) if ci else ""

    for name, info in organisms.items():
        conn.execute(
            "CREATE (o:Organism {name:$n, english:$e, characteristics:$c, common_infections:$ci})",
            {"n": name, "e": info["english"], "c": info["characteristics"], "ci": info["common_infections"]},
        )
    logger.info("Imported %d organisms", len(organisms))
    return set(organisms.keys())


def _import_drug_classes(conn, drugs_yaml, reporting_yaml) -> set[str]:
    classes = set()
    for d in drugs_yaml.get("drug_details", []):
        if d.get("class"):
            classes.add(d["class"])
    for tier_data in drugs_yaml.get("administrative_tiers", {}).get("tiers", {}).values():
        for d in tier_data.get("drugs", []):
            if d.get("class"):
                classes.add(d["class"])
    for class_name in reporting_yaml.get("mic_breakpoints", {}).get("breakpoints_by_class", {}).keys():
        classes.add(class_name)

    for cls in classes:
        conn.execute("CREATE (c:DrugClass {name:$n})", {"n": cls})
    logger.info("Imported %d drug classes", len(classes))
    return classes


def _import_drugs(conn, drugs_yaml, reporting_yaml) -> set[str]:
    drugs: dict[str, dict] = {}
    _empty = {
        "english": "", "drug_class": "", "mechanism": "", "spectrum_text": "",
        "dosing_info": "", "adverse_effects": "", "key_notes": "",
        "admin_tier": "", "clsi_tier": "",
        "breakpoint_s": "", "breakpoint_i": "", "breakpoint_r": "", "breakpoint_sdd": "",
        "route": "",
    }

    for d in drugs_yaml.get("drug_details", []):
        name = _norm_drug(d["name"])
        spectrum = d.get("spectrum", {})
        sp_parts = []
        for k, v in spectrum.items():
            if isinstance(v, list):
                sp_parts.append(f"{k}: {', '.join(str(x) for x in v)}")
        dosing = d.get("dosing", {})
        ds_parts = []
        for k, v in dosing.items():
            if isinstance(v, dict):
                for sk, sv in v.items():
                    ds_parts.append(f"{k}.{sk}: {sv}")
            else:
                ds_parts.append(f"{k}: {v}")

        drugs[name] = {
            "english": d.get("english", ""),
            "drug_class": d.get("class", ""),
            "mechanism": d.get("mechanism", ""),
            "spectrum_text": "; ".join(sp_parts),
            "dosing_info": "; ".join(ds_parts),
            "adverse_effects": "; ".join(d.get("adverse_effects", [])),
            "key_notes": d.get("key_notes", ""),
            "admin_tier": "", "clsi_tier": "",
            "breakpoint_s": "", "breakpoint_i": "", "breakpoint_r": "", "breakpoint_sdd": "",
            "route": "",
        }

    for tier_name, tier_data in drugs_yaml.get("administrative_tiers", {}).get("tiers", {}).items():
        for d in tier_data.get("drugs", []):
            name = _norm_drug(d["name"])
            if name not in drugs:
                drugs[name] = {
                    **_empty,
                    "english": d.get("english", ""),
                    "drug_class": d.get("class", ""),
                    "spectrum_text": d.get("spectrum", ""),
                    "key_notes": d.get("notes", ""),
                    "admin_tier": tier_name,
                    "route": d.get("route", ""),
                }
            else:
                drugs[name]["admin_tier"] = tier_name
                if not drugs[name]["route"]:
                    drugs[name]["route"] = d.get("route", "")

    bpc = reporting_yaml.get("mic_breakpoints", {}).get("breakpoints_by_class", {})
    for class_name, class_data in bpc.items():
        drug_list = class_data if isinstance(class_data, list) else class_data.get("drugs", [])
        for bp in drug_list:
            if not isinstance(bp, dict) or "drug" not in bp:
                continue
            name = _norm_drug(bp["drug"])
            if "systemic" in bp:
                s, i, r = bp["systemic"].get("S", ""), bp["systemic"].get("I", ""), bp["systemic"].get("R", "")
            else:
                s, i, r = str(bp.get("S", "")), str(bp.get("I", "")), str(bp.get("R", ""))
            sdd = str(bp.get("SDD", ""))
            tier_val = str(bp.get("tier", ""))

            if name not in drugs:
                drugs[name] = {
                    **_empty,
                    "english": bp.get("english", ""),
                    "drug_class": class_name,
                    "key_notes": bp.get("note", ""),
                    "clsi_tier": tier_val,
                    "breakpoint_s": s, "breakpoint_i": i, "breakpoint_r": r, "breakpoint_sdd": sdd,
                }
            else:
                rec = drugs[name]
                if not rec["clsi_tier"]:
                    rec["clsi_tier"] = tier_val
                if not rec["breakpoint_s"]:
                    rec["breakpoint_s"] = s
                    rec["breakpoint_i"] = i
                    rec["breakpoint_r"] = r
                    rec["breakpoint_sdd"] = sdd
                if not rec["english"] and bp.get("english"):
                    rec["english"] = bp["english"]
                if not rec["drug_class"]:
                    rec["drug_class"] = class_name

    tier_num_map = {
        "tier1_group_A": "1", "tier2_group_B": "2",
        "tier3_group_C": "3", "tier4_group_D": "4", "urinary_only": "U",
    }
    for tier_key, tier_data in reporting_yaml.get("cascade_reporting", {}).get("tiers", {}).items():
        tier_num = tier_num_map.get(tier_key, "")
        for drug_entry in tier_data.get("drugs", []):
            names = drug_entry.split("或") if "或" in drug_entry else [drug_entry]
            for raw in names:
                name = _norm_drug(raw)
                if name in drugs:
                    if not drugs[name]["clsi_tier"]:
                        drugs[name]["clsi_tier"] = tier_num
                else:
                    drugs[name] = {**_empty, "clsi_tier": tier_num}

    for name, info in drugs.items():
        conn.execute(
            """CREATE (d:Drug {
                name:$name, english:$english, drug_class:$dc,
                mechanism:$mech, spectrum_text:$sp, dosing_info:$dos,
                adverse_effects:$ae, key_notes:$kn,
                admin_tier:$at, clsi_tier:$ct,
                breakpoint_s:$bs, breakpoint_i:$bi, breakpoint_r:$br, breakpoint_sdd:$bsdd,
                route:$rt
            })""",
            {
                "name": name, "english": info["english"], "dc": info["drug_class"],
                "mech": info["mechanism"], "sp": info["spectrum_text"],
                "dos": info["dosing_info"], "ae": info["adverse_effects"],
                "kn": info["key_notes"], "at": info["admin_tier"],
                "ct": info["clsi_tier"],
                "bs": info["breakpoint_s"], "bi": info["breakpoint_i"],
                "br": info["breakpoint_r"], "bsdd": info["breakpoint_sdd"],
                "rt": info["route"],
            },
        )
    logger.info("Imported %d drugs", len(drugs))
    return set(drugs.keys())


def _import_resistance_mechanisms(conn, resistance_yaml):
    rules = resistance_yaml.get("resistance_rules", {})
    mechs = {}

    esbl = rules.get("ESBL", {})
    mechs["ESBL"] = {
        "category": "β-内酰胺酶", "description": esbl.get("description", ""),
        "clinical_rule": esbl.get("rule", ""),
        "recommended_text": json.dumps(esbl.get("recommended", []), ensure_ascii=False),
        "alternative_text": json.dumps(esbl.get("alternative", []), ensure_ascii=False),
        "avoid_text": json.dumps(esbl.get("avoid", []), ensure_ascii=False),
    }

    cre = rules.get("CRE", {})
    mechs["CRE"] = {
        "category": "碳青霉烯酶", "description": cre.get("description", ""),
        "clinical_rule": cre.get("rule", ""),
        "recommended_text": "", "alternative_text": "", "avoid_text": "",
    }

    kpc = cre.get("KPC_type", {})
    mechs["KPC"] = {
        "category": "碳青霉烯酶", "description": kpc.get("description", ""),
        "clinical_rule": "",
        "recommended_text": json.dumps(kpc.get("first_line", []), ensure_ascii=False),
        "alternative_text": json.dumps(kpc.get("alternative", []), ensure_ascii=False),
        "avoid_text": "",
    }

    ndm = cre.get("NDM_type", {})
    mechs["NDM"] = {
        "category": "金属β-内酰胺酶", "description": ndm.get("description", ""),
        "clinical_rule": ndm.get("notes", ""),
        "recommended_text": json.dumps(ndm.get("first_line", []), ensure_ascii=False),
        "alternative_text": json.dumps(ndm.get("alternative", []), ensure_ascii=False),
        "avoid_text": "",
    }

    ampc = rules.get("AmpC", {})
    mechs["AmpC"] = {
        "category": "AmpC β-内酰胺酶",
        "description": "染色体编码AmpC β-内酰胺酶，可诱导去阻遏高表达",
        "clinical_rule": "",
        "recommended_text": json.dumps(ampc.get("recommended", []), ensure_ascii=False),
        "alternative_text": "",
        "avoid_text": json.dumps(ampc.get("avoid", []), ensure_ascii=False),
    }

    for name, info in mechs.items():
        conn.execute(
            "CREATE (r:ResistanceMechanism {name:$n, category:$cat, description:$descr, clinical_rule:$rule, recommended_text:$rec, alternative_text:$alt, avoid_text:$avo})",
            {"n": name, "cat": info["category"], "descr": info["description"],
             "rule": info["clinical_rule"], "rec": info["recommended_text"],
             "alt": info["alternative_text"], "avo": info["avoid_text"]},
        )
    logger.info("Imported %d resistance mechanisms", len(mechs))


def _is_treatment_plan(data) -> bool:
    if not isinstance(data, dict):
        return False
    plan_keys = {
        "first_line", "alternative", "oral_stepdown", "empiric",
        "UTI_uncomplicated", "UTI_complicated", "systemic", "UTI",
        "combination_severe", "last_resort", "notes",
    }
    return bool(plan_keys & set(data.keys()))


def _val_to_str(val) -> str:
    if isinstance(val, list):
        return "; ".join(str(x) for x in val)
    if isinstance(val, dict):
        parts = []
        for k, v in val.items():
            if isinstance(v, list):
                parts.append(f"{k}: {'; '.join(str(x) for x in v)}")
            else:
                parts.append(f"{k}: {v}")
        return "; ".join(parts)
    return str(val) if val else ""


def _insert_one_plan(conn, organism: str, context: str, data: dict):
    plan_id = f"{organism}_{context}"
    first_line = _val_to_str(data.get("first_line", data.get("empiric", "")))
    extras = []
    for key in ("UTI_uncomplicated", "UTI_complicated", "systemic", "UTI"):
        if key in data:
            extras.append(f"[{key}] {_val_to_str(data[key])}")
    if extras:
        first_line = first_line + ("; " if first_line else "") + "; ".join(extras)

    conn.execute(
        """CREATE (t:TreatmentPlan {
            plan_id:$pid, organism_name:$org, resistance_context:$ctx,
            first_line:$fl, alternative:$alt, combination:$combo,
            last_resort:$lr, oral_stepdown:$os, notes:$notes
        })""",
        {
            "pid": plan_id, "org": organism, "ctx": context,
            "fl": first_line,
            "alt": _val_to_str(data.get("alternative", "")),
            "combo": _val_to_str(data.get("combination_severe", "")),
            "lr": _val_to_str(data.get("last_resort", "")),
            "os": _val_to_str(data.get("oral_stepdown", "")),
            "notes": _val_to_str(data.get("notes", "")),
        },
    )


def _import_treatment_plans(conn, treatment_yaml):
    count = 0
    for org_name, org_data in treatment_yaml.get("treatment_guidelines", {}).items():
        cn = _norm_org(org_name)
        for res_ctx, plan_data in org_data.get("treatment_by_resistance", {}).items():
            if _is_treatment_plan(plan_data):
                _insert_one_plan(conn, cn, res_ctx, plan_data)
                count += 1
            elif isinstance(plan_data, dict):
                for sub_key, sub_data in plan_data.items():
                    if isinstance(sub_data, dict) and _is_treatment_plan(sub_data):
                        _insert_one_plan(conn, cn, f"{res_ctx} > {sub_key}", sub_data)
                        count += 1

        special = org_data.get("special_populations", {})
        if special:
            notes = "; ".join(f"{k}: {v}" for k, v in special.items())
            conn.execute(
                """CREATE (t:TreatmentPlan {
                    plan_id:$pid, organism_name:$org, resistance_context:$ctx,
                    first_line:$fl, alternative:$a, combination:$c,
                    last_resort:$l, oral_stepdown:$o, notes:$n
                })""",
                {"pid": f"{cn}_特殊人群", "org": cn, "ctx": "特殊人群",
                 "fl": "", "a": "", "c": "", "l": "", "o": "", "n": notes},
            )
            count += 1
    logger.info("Imported %d treatment plans", count)


def _import_infection_sites(conn, treatment_yaml):
    empiric = treatment_yaml.get("empiric_therapy", {})
    for site_name, site_data in empiric.items():
        pathogens = site_data.get("common_pathogens", [])
        conn.execute(
            """CREATE (i:InfectionSite {
                name:$n, empiric_therapy:$th, duration:$dur, common_pathogens:$cp
            })""",
            {
                "n": site_name,
                "th": site_data.get("initial_empiric", ""),
                "dur": site_data.get("duration", ""),
                "cp": json.dumps(pathogens, ensure_ascii=False),
            },
        )
    logger.info("Imported %d infection sites", len(empiric))


# --- 关系导入 ---

def _import_drug_class_rels(conn, drug_set: set, cls_set: set):
    count = 0
    result = conn.execute("MATCH (d:Drug) WHERE d.drug_class <> '' RETURN d.name, d.drug_class")
    while result.has_next():
        row = result.get_next()
        dname, dcls = row[0], row[1]
        if dcls in cls_set:
            if _safe_create_rel(conn,
                    "MATCH (d:Drug {name:$d}), (c:DrugClass {name:$c}) CREATE (d)-[:BELONGS_TO_CLASS]->(c)",
                    {"d": dname, "c": dcls}):
                count += 1
    logger.info("Created %d BELONGS_TO_CLASS rels", count)


def _import_intrinsic_resistance_rels(conn, resistance_yaml, org_set: set, drug_set: set):
    count = 0
    for entry in resistance_yaml.get("resistance_rules", {}).get("intrinsic_resistance", []):
        drug_names = _parse_intrinsic_drugs(entry.get("drug", ""))
        action = entry.get("action", "")
        for org_raw in entry.get("organisms", []):
            org = _norm_org(org_raw)
            if org not in org_set:
                continue
            for dname in drug_names:
                if dname not in drug_set:
                    continue
                if _safe_create_rel(conn,
                        "MATCH (o:Organism {name:$o}), (d:Drug {name:$d}) CREATE (o)-[:INTRINSIC_RESISTANT {action:$a}]->(d)",
                        {"o": org, "d": dname, "a": action}):
                    count += 1
    logger.info("Created %d INTRINSIC_RESISTANT rels", count)


def _import_treatment_rels(conn, org_set: set):
    count = 0
    result = conn.execute("MATCH (t:TreatmentPlan) RETURN t.plan_id, t.organism_name")
    while result.has_next():
        row = result.get_next()
        pid, org = row[0], row[1]
        if org in org_set:
            if _safe_create_rel(conn,
                    "MATCH (o:Organism {name:$o}), (t:TreatmentPlan {plan_id:$p}) CREATE (o)-[:HAS_TREATMENT]->(t)",
                    {"o": org, "p": pid}):
                count += 1
    logger.info("Created %d HAS_TREATMENT rels", count)


def _import_resistance_drug_rels(conn, resistance_yaml, drug_set: set):
    count = 0
    rules = resistance_yaml.get("resistance_rules", {})

    def _add_rels(drug_list: list, mech_name: str, line_type: str):
        nonlocal count
        for drug_raw in drug_list:
            cleaned = re.sub(r'[（(][^）)]*[）)]', '', drug_raw).strip()
            dname = _norm_drug(cleaned)
            if "/" in dname and "多黏菌素" in dname:
                for sub in ["多黏菌素B", "多黏菌素E"]:
                    if sub in drug_set:
                        if _safe_create_rel(conn,
                                "MATCH (d:Drug {name:$d}), (r:ResistanceMechanism {name:$m}) CREATE (d)-[:RECOMMENDED_FOR {line:$l}]->(r)",
                                {"d": sub, "m": mech_name, "l": line_type}):
                            count += 1
            elif dname in drug_set:
                if _safe_create_rel(conn,
                        "MATCH (d:Drug {name:$d}), (r:ResistanceMechanism {name:$m}) CREATE (d)-[:RECOMMENDED_FOR {line:$l}]->(r)",
                        {"d": dname, "m": mech_name, "l": line_type}):
                    count += 1

    esbl = rules.get("ESBL", {})
    _add_rels(esbl.get("recommended", []), "ESBL", "recommended")
    _add_rels(esbl.get("alternative", []), "ESBL", "alternative")
    _add_rels(esbl.get("avoid", []), "ESBL", "avoid")

    kpc = rules.get("CRE", {}).get("KPC_type", {})
    _add_rels(kpc.get("first_line", []), "KPC", "first_line")
    _add_rels(kpc.get("alternative", []), "KPC", "alternative")
    _add_rels(kpc.get("last_resort", []), "KPC", "last_resort")

    ndm = rules.get("CRE", {}).get("NDM_type", {})
    _add_rels(ndm.get("first_line", []), "NDM", "first_line")
    _add_rels(ndm.get("alternative", []), "NDM", "alternative")

    ampc = rules.get("AmpC", {})
    _add_rels(ampc.get("recommended", []), "AmpC", "recommended")
    _add_rels(ampc.get("avoid", []), "AmpC", "avoid")

    logger.info("Created %d RECOMMENDED_FOR rels", count)


def _import_infection_site_rels(conn, treatment_yaml, org_set: set):
    count = 0
    for site_name, site_data in treatment_yaml.get("empiric_therapy", {}).items():
        for pathogen in site_data.get("common_pathogens", []):
            org = _norm_org(pathogen)
            if org in org_set:
                if _safe_create_rel(conn,
                        "MATCH (o:Organism {name:$o}), (i:InfectionSite {name:$s}) CREATE (o)-[:COMMON_IN]->(i)",
                        {"o": org, "s": site_name}):
                    count += 1
    logger.info("Created %d COMMON_IN rels", count)


def _import_ampc_rels(conn, resistance_yaml, org_set: set):
    count = 0
    risk_strat = resistance_yaml.get("resistance_rules", {}).get("AmpC", {}).get("risk_stratification", {})
    for risk_key in ("moderate_to_high", "lower_risk"):
        risk_data = risk_strat.get(risk_key, {})
        level = "high" if "high" in risk_key else "low"
        for org_raw in risk_data.get("organisms", []):
            org = _norm_org(org_raw)
            if org in org_set:
                if _safe_create_rel(conn,
                        "MATCH (o:Organism {name:$o}), (r:ResistanceMechanism {name:$m}) CREATE (o)-[:AMPC_RISK {risk_level:$rl}]->(r)",
                        {"o": org, "m": "AmpC", "rl": level}):
                    count += 1
    logger.info("Created %d AMPC_RISK rels", count)


# ═══════════════════════════════════════════════════════════════════
# 通用查询接口（AI 驱动 Cypher 使用）
# ═══════════════════════════════════════════════════════════════════

def execute_cypher(query: str) -> list[dict]:
    """执行 Cypher 查询，返回结果列表"""
    conn = _get_conn()
    result = conn.execute(query)
    rows = []
    while result.has_next():
        row = result.get_next()
        if len(row) == 1 and isinstance(row[0], dict):
            rows.append(row[0])
        else:
            rows.append(row)
    return rows


def get_schema_text() -> str:
    """返回 schema 描述文本，供 AI 生成 Cypher 时参考"""
    return _SCHEMA_DESCRIPTION


def search_nodes(keyword: str, limit: int = 20) -> list[dict]:
    """按关键词搜索所有节点类型"""
    conn = _get_conn()
    results = []
    node_types = [
        ("Drug", "name", "english"),
        ("Organism", "name", "english"),
        ("DrugClass", "name", None),
        ("ResistanceMechanism", "name", None),
        ("InfectionSite", "name", None),
    ]
    for label, name_field, en_field in node_types:
        rows = _rows(conn.execute(
            f"MATCH (n:{label}) WHERE n.{name_field} CONTAINS $q "
            f"RETURN n.{name_field} as name, '{label}' as type"
            + (f", n.{en_field} as english" if en_field else ", '' as english"),
            {"q": keyword},
        ))
        for r in rows:
            results.append({"id": r[0], "name": r[0], "type": r[1], "english": r[2]})
    return results[:limit]


def get_node_neighborhood(node_name: str, node_type: str = None) -> dict:
    """获取节点 1-hop 邻域，返回 {node, neighbors, edges}"""
    conn = _get_conn()
    node = None
    neighbors = []
    edges = []

    # 查找中心节点（支持 name 和 plan_id）
    if node_type:
        rows = _rows(conn.execute(
            f"MATCH (n:{node_type}) WHERE n.name = $name OR n.plan_id = $name RETURN n",
            {"name": node_name},
        ))
    else:
        rows = _rows(conn.execute(
            "MATCH (n) WHERE n.name = $name OR n.plan_id = $name RETURN n",
            {"name": node_name},
        ))

    if not rows:
        return {"node": None, "neighbors": [], "edges": []}

    node_data = rows[0][0]
    node = {"name": node_data.get("name") or node_data.get("plan_id", ""), "type": _detect_node_type(node_data)}
    # 保留所有属性供格式化使用
    for k, v in node_data.items():
        if k not in ("_id", "_label", "_src", "_dst") and v is not None and v != "":
            node[k] = v

    # 按关系类型分别查出边（KuzuDB 需要显式指定关系类型名）
    _REL_TYPES = [
        ("BELONGS_TO_CLASS", "b", False),
        ("INTRINSIC_RESISTANT", "b", False),
        ("HAS_TREATMENT", "b", False),
        ("RECOMMENDED_FOR", "b", False),
        ("COMMON_IN", "b", False),
        ("AMPC_RISK", "b", False),
    ]
    for rel_name, _, _ in _REL_TYPES:
        try:
            out_rows = _rows(conn.execute(
                f"MATCH (a)-[r:{rel_name}]->(b) WHERE a.name = $name RETURN r, b",
                {"name": node_name},
            ))
        except Exception:
            continue
        for rel_obj, target in out_rows:
            t_name = target.get("name") or target.get("plan_id") or ""
            if not t_name:
                continue
            t_type = _detect_node_type(target)
            rel_props = {k: v for k, v in (rel_obj.items() if isinstance(rel_obj, dict) else [])
                         if k not in ("_label", "_src", "_dst", "_id")}
            neighbors.append({"name": t_name, "type": t_type})
            edges.append({"source": node_name, "target": t_name, "relation": rel_name, "properties": rel_props})

    # 查入边（反向）
    for rel_name, _, _ in _REL_TYPES:
        try:
            in_rows = _rows(conn.execute(
                f"MATCH (a)-[r:{rel_name}]->(b) WHERE b.name = $name RETURN r, a",
                {"name": node_name},
            ))
        except Exception:
            continue
        for rel_obj, source in in_rows:
            s_name = source.get("name") or source.get("plan_id") or ""
            if not s_name:
                continue
            s_type = _detect_node_type(source)
            rel_props = {k: v for k, v in (rel_obj.items() if isinstance(rel_obj, dict) else [])
                         if k not in ("_label", "_src", "_dst", "_id")}
            neighbors.append({"name": s_name, "type": s_type})
            edges.append({"source": s_name, "target": node_name, "relation": rel_name, "properties": rel_props})

    # 去重
    seen = set()
    unique_neighbors = []
    for n in neighbors:
        if n["name"] not in seen:
            seen.add(n["name"])
            unique_neighbors.append(n)

    return {"node": node, "neighbors": unique_neighbors, "edges": edges}


def _detect_node_type(node_data: dict) -> str:
    # 优先用 _label（KuzuDB 自带）
    label = node_data.get("_label", "")
    if label in ("Drug", "Organism", "DrugClass", "ResistanceMechanism", "TreatmentPlan", "InfectionSite"):
        return label
    # fallback: 按特征属性检测（只检查有值的属性）
    if node_data.get("organism_name") or node_data.get("plan_id"):
        return "TreatmentPlan"
    if node_data.get("drug_class") or node_data.get("mechanism"):
        return "Drug"
    if node_data.get("characteristics") or node_data.get("common_infections"):
        return "Organism"
    if node_data.get("category") and node_data.get("clinical_rule"):
        return "ResistanceMechanism"
    if node_data.get("empiric_therapy"):
        return "InfectionSite"
    if len(node_data) <= 3 and "name" in node_data:
        return "DrugClass"
    return "Unknown"


def get_all_graph_data() -> dict:
    """返回全图数据 {nodes: [...], edges: [...]}，用于前端一次性加载"""
    conn = _get_conn()
    nodes = []
    edges = []

    node_types = [
        ("Drug", "name"), ("Organism", "name"), ("DrugClass", "name"),
        ("ResistanceMechanism", "name"), ("TreatmentPlan", "plan_id"),
        ("InfectionSite", "name"),
    ]
    for label, _name_field in node_types:
        try:
            rows = _rows(conn.execute(f"MATCH (n:{label}) RETURN n"))
        except Exception:
            continue
        for (node_data,) in rows:
            n_name = node_data.get("name") or node_data.get("plan_id", "")
            if not n_name:
                continue
            n_type = _detect_node_type(node_data)
            node_item = {"name": n_name, "type": n_type}
            # 保留所有有值的属性
            for k, v in node_data.items():
                if k not in ("_id", "_label", "_src", "_dst") and v is not None and v != "":
                    node_item[k] = v
            nodes.append(node_item)

    # (关系名, 源节点名称属性, 目标节点名称属性)
    rel_types = [
        ("BELONGS_TO_CLASS", "a.name", "b.name"),
        ("INTRINSIC_RESISTANT", "a.name", "b.name"),
        ("HAS_TREATMENT", "a.name", "b.plan_id"),
        ("RECOMMENDED_FOR", "a.name", "b.name"),
        ("COMMON_IN", "a.name", "b.name"),
        ("AMPC_RISK", "a.name", "b.name"),
    ]
    seen_edges = set()
    for rel_name, src_prop, tgt_prop in rel_types:
        try:
            rows = _rows(conn.execute(
                f"MATCH (a)-[r:{rel_name}]->(b) RETURN {src_prop} AS src, {tgt_prop} AS tgt"
            ))
        except Exception:
            continue
        for src, tgt in rows:
            if not src or not tgt:
                continue
            edge_key = (src, tgt, rel_name)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append({"source": src, "target": tgt, "relation": rel_name})

    return {"nodes": nodes, "edges": edges}


# ═══════════════════════════════════════════════════════════════════
# 初始化
# ═══════════════════════════════════════════════════════════════════

def rebuild_graph():
    """删除旧数据，重新导入全部 YAML → KuzuDB"""
    global _db, _conn
    _db, _conn = None, None

    if os.path.isdir(KUZU_DB_DIR):
        shutil.rmtree(KUZU_DB_DIR)
    elif os.path.exists(KUZU_DB_DIR):
        os.remove(KUZU_DB_DIR)

    db = kuzu.Database(KUZU_DB_DIR)
    conn = kuzu.Connection(db)

    for ddl in _SCHEMA:
        conn.execute(ddl)

    _import_all(conn)

    with open(_MARKER, "w", encoding="utf-8") as f:
        f.write("ok")

    _db, _conn = db, conn

    n = _rows(conn.execute("MATCH (n) RETURN count(n)"))[0][0]
    e = _rows(conn.execute("MATCH ()-[r]->() RETURN count(r)"))[0][0]
    logger.info("Graph rebuilt: %d nodes, %d edges", n, e)
    return n, e


def init_graph(force_rebuild: bool = False):
    """启动时调用：如果已导入则跳过"""
    if os.path.exists(_MARKER) and not force_rebuild:
        logger.info("Graph already imported, skipping rebuild")
        _get_conn()
        return
    rebuild_graph()
