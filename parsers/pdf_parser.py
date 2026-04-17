"""统一报告解析器 — 支持 PDF (PyMuPDF) + 图片 (OCR)"""
import re
import base64
from pathlib import Path

import fitz  # PyMuPDF

# 支持的文件类型
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}

# 中文药名映射
DRUG_NAME_MAP = {
    "阿米卡星": "Amikacin",
    "阿莫西林/克拉维酸": "Amoxicillin-Clavulanate",
    "阿莫西林-克拉维酸": "Amoxicillin-Clavulanate",
    "氨苄西林": "Ampicillin",
    "氨苄西林/舒巴坦": "Ampicillin-Sulbactam",
    "氨苄西林-舒巴坦": "Ampicillin-Sulbactam",
    "氨曲南": "Aztreonam",
    "复方新诺明": "TMP-SMX",
    "甲氧苄啶/磺胺甲噁唑": "TMP-SMX",
    "甲氧苄啶-磺胺甲噁唑": "TMP-SMX",
    "哌拉西林/他唑巴坦": "Piperacillin-Tazobactam",
    "哌拉西林-他唑巴坦": "Piperacillin-Tazobactam",
    "庆大霉素": "Gentamicin",
    "妥布霉素": "Tobramycin",
    "环丙沙星": "Ciprofloxacin",
    "左氧氟沙星": "Levofloxacin",
    "头孢吡肟": "Cefepime",
    "头孢呋辛": "Cefuroxime",
    "头孢呋辛（口服）": "Cefuroxime (oral)",
    "头孢呋辛(口服)": "Cefuroxime (oral)",
    "头孢呋新钠": "Cefuroxime sodium",
    "头孢呋辛钠": "Cefuroxime sodium",
    "头孢唑啉": "Cefazolin",
    "头孢哌酮/舒巴坦": "Cefoperazone-Sulbactam",
    "头孢哌酮-舒巴坦": "Cefoperazone-Sulbactam",
    "头孢曲松": "Ceftriaxone",
    "头孢噻肟": "Cefotaxime",
    "头孢他啶": "Ceftazidime",
    "头孢 他啶": "Ceftazidime",
    "头孢西丁": "Cefoxitin",
    "头孢替坦": "Cefotetan",
    "头孢洛扎/他唑巴坦": "Ceftolozane-Tazobactam",
    "头孢洛扎-他唑巴坦": "Ceftolozane-Tazobactam",
    "头孢他啶/阿维巴坦": "Ceftazidime-Avibactam",
    "头孢他啶-阿维巴坦": "Ceftazidime-Avibactam",
    "厄他培南": "Ertapenem",
    "美罗培南": "Meropenem",
    "亚胺培南": "Imipenem",
    "亚胺培南/瑞来巴坦": "Imipenem-Relebactam",
    "亚胺培南-瑞来巴坦": "Imipenem-Relebactam",
    "美罗培南/法硼巴坦": "Meropenem-Vaborbactam",
    "四环素": "Tetracycline",
    "替加环素": "Tigecycline",
    "多黏菌素B": "Polymyxin B",
    "多粘菌素B": "Polymyxin B",
    "多黏菌素E": "Colistin",
    "多粘菌素E": "Colistin",
    "粘菌素": "Colistin",
    "呋喃妥因": "Nitrofurantoin",
    "磷霉素": "Fosfomycin",
    "万古霉素": "Vancomycin",
    "利奈唑胺": "Linezolid",
    "达托霉素": "Daptomycin",
}

SIR_MAP = {"敏感": "S", "中介": "I", "耐药": "R", "S": "S", "I": "I", "R": "R", "SDD": "S"}

# 已知细菌名列表
KNOWN_BACTERIA = [
    "肺炎克雷伯菌", "大肠埃希菌", "铜绿假单胞菌", "鲍曼不动杆菌",
    "金黄色葡萄球菌", "表皮葡萄球菌", "溶血葡萄球菌",
    "阴沟肠杆菌", "产气肠杆菌", "奇异变形杆菌", "普通变形杆菌",
    "粘质沙雷菌", "黏质沙雷菌", "弗劳地枸橼酸杆菌", "嗜麦芽窄食单胞菌",
    "洋葱伯克霍尔德菌", "粪肠球菌", "屎肠球菌",
    "弗氏柠檬酸杆菌复合群", "摩根摩根菌",
]


def parse_report(filepath: str) -> dict:
    """统一解析入口：自动判断文件类型，返回结构化报告"""
    ext = Path(filepath).suffix.lower()
    if ext in PDF_EXTENSIONS:
        text = _extract_pdf_text(filepath)
    elif ext in IMAGE_EXTENSIONS:
        text = _extract_image_text(filepath)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")

    return _parse_text_to_report(text)


def _extract_pdf_text(filepath: str) -> str:
    """PyMuPDF 提取 PDF 文本"""
    doc = fitz.open(filepath)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()
    return full_text


def _extract_image_text(filepath: str) -> str:
    """调用 OCR 模型提取图片文本"""
    from agent.llm import ocr_image

    with open(filepath, "rb") as f:
        img_data = base64.b64encode(f.read()).decode("utf-8")

    ext = Path(filepath).suffix.lower()
    mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".bmp": "bmp", ".tiff": "tiff", ".webp": "webp"}
    mime = f"image/{mime_map.get(ext, 'jpeg')}"

    prompt = """请提取这份微生物检验报告中的所有信息，按以下格式输出：

患者信息：
- 姓名：
- 性别：
- 年龄：
- 科室：
- 床位：
- 住院号：
- 样本种类：
- 采集时间：

培养结果：
- 检出菌：
- ESBL检测结果：

药敏试验结果：
（每行格式：药名 MIC值 敏感性）

请完整提取所有药敏结果，不要遗漏任何药物。"""

    return ocr_image(img_data, prompt, mime)


def _parse_text_to_report(text: str) -> dict:
    """将文本解析为结构化报告（Claude 前端契约格式）"""
    patient = _extract_patient_info(text)
    bacteria_name = _extract_bacteria(text)
    specimen = _extract_specimen(text, patient)
    esbl = _detect_esbl(text)
    susceptibility = _extract_susceptibility(text)

    # CRE 检测
    cre = "CRE" in text
    for s in susceptibility:
        if s["drug_name"] in ("厄他培南", "美罗培南", "亚胺培南") and s["sir"] == "R":
            cre = True
            break

    return {
        "patient": patient,
        "bacteria_name": bacteria_name,
        "bacteria_name_en": "",
        "specimen": specimen,
        "esbl": esbl,
        "cre": cre,
        "susceptibility": susceptibility,
    }


def _extract_patient_info(text: str) -> dict:
    info = {
        "name": "", "age": "", "gender": "", "department": "",
        "sample_id": "", "sample_type": "", "bed_no": "",
        "collection_date": "", "report_date": "",
    }

    # 性别/年龄
    m = re.search(r"性别/年龄[：:]\s*([男女])/(\d+)岁", text)
    if m:
        info["gender"] = m.group(1)
        info["age"] = m.group(2)
    else:
        gm = re.search(r"性\s*别[：:]\s*([男女])", text)
        if gm:
            info["gender"] = gm.group(1)
        am = re.search(r"年\s*龄[：:]\s*(\d+)", text)
        if am:
            info["age"] = am.group(1)

    # PDF 特殊格式：标签在值的下方
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    label_map = {
        "姓  名:": "name", "姓名:": "name", "姓名：": "name",
        "床  位:": "bed_no", "床位:": "bed_no",
        "科    室:": "department", "科室:": "department",
        "病  区:": "department", "病区:": "department",
        "住院号:": "sample_id", "住 院 号:": "sample_id",
        "条码号:": "sample_id",
        "样本种类:": "sample_type",
    }
    all_labels = {l.replace(" ", "").replace("：", ":") for l in label_map}
    all_labels.update({"信息提示:", "备注:", "申请医生:", "来源:", "来源：", "样本编号:"})

    for i, line in enumerate(lines):
        clean = line.replace(" ", "").replace("：", ":")
        for label, key in label_map.items():
            if clean == label.replace(" ", "") and i > 0:
                val = lines[i - 1].strip()
                val_clean = val.replace(" ", "").replace("：", ":")
                if val and val_clean not in all_labels and ":" not in val_clean and not info[key]:
                    info[key] = val
                break

    # 正则提取补充
    if not info["name"]:
        m = re.search(r"姓\s*名[：:\s]+(\S+?)(?:\s+来源|\s+住院|\s*$)", text)
        if m and m.group(1).strip() not in ("来源：", "来源:"):
            info["name"] = m.group(1).strip()

    if not info["department"]:
        m = re.search(r"科\s*室[：:\s]*(\S+)", text)
        if m:
            info["department"] = m.group(1).strip()

    if not info["bed_no"]:
        m = re.search(r"床\s*位[：:\s]*(\S+)", text)
        if m:
            info["bed_no"] = m.group(1).strip()

    if not info["sample_type"]:
        m = re.search(r"样本种类[：:\s]*(\S+)", text)
        if m:
            info["sample_type"] = m.group(1).strip()

    m = re.search(r"采集时间[：:\s]*(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*\d{0,2}:?\d{0,2}:?\d{0,2})", text)
    if m:
        info["collection_date"] = m.group(1).strip()

    m = re.search(r"报告时间[：:\s]*(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*\d{0,2}:?\d{0,2})", text)
    if m:
        info["report_date"] = m.group(1).strip()

    return info


def _extract_bacteria(text: str) -> str:
    for name in KNOWN_BACTERIA:
        if name in text:
            return name
    m = re.search(r"(?:培养结果|鉴定结果|细菌鉴定|检出菌)[：:]\s*(.+?)(?:\n|$)", text)
    if m:
        return m.group(1).strip()
    return ""


def _extract_specimen(text: str, patient: dict) -> str:
    if patient.get("sample_type"):
        return patient["sample_type"]
    keywords = ["胸(腹)水", "胸（腹）水", "血液", "尿液", "痰", "脑脊液", "伤口", "分泌物", "引流液", "胆汁"]
    for kw in keywords:
        if kw in text:
            return kw
    m = re.search(r"(?:标本类型|标\s*本|样本)[：:]\s*(.+?)(?:\n|$)", text)
    if m:
        return m.group(1).strip()
    return ""


def _detect_esbl(text: str) -> str:
    """返回 "POS" / "NEG" / "" """
    patterns = [
        r"ESBL.*?(阳性|阴性|\+|\-|POS|NEG)",
        r"(阳性|阴性|\+|\-|POS|NEG)\s*\n\s*ESBL",
        r"(POS|NEG)\s*\n\s*ESBL",
        r"超广谱.*?内酰胺酶[：:]*\s*(阳性|阴性|\+|\-)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().upper()
            if val in ("阳性", "+", "POS"):
                return "POS"
            if val in ("阴性", "-", "NEG"):
                return "NEG"
            return val

    # 行扫描补充
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if "ESBL" in line.upper():
            for j in range(max(0, i - 3), min(len(lines), i + 4)):
                if j == i:
                    continue
                if lines[j].upper() in ("POS", "NEG", "阳性", "阴性"):
                    return "POS" if lines[j].upper() in ("POS", "阳性") else "NEG"
            break

    return ""


def _extract_susceptibility(text: str) -> list[dict]:
    """提取药敏结果 → [{drug_name, mic_value, sir}]"""
    results = []
    seen = set()

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for drug_cn, drug_en in DRUG_NAME_MAP.items():
        for i, line in enumerate(lines):
            if line != drug_cn and line.replace(" ", "") != drug_cn.replace(" ", ""):
                continue

            sensitivity = None
            mic = None

            # 搜索前面几行
            for j in range(max(0, i - 3), i):
                if lines[j] in ("耐药", "敏感", "中介"):
                    sensitivity = SIR_MAP[lines[j]]
                elif re.match(r"^[><=≥≤]*\d+[\.\d]*$", lines[j]):
                    mic = lines[j]

            # 搜索后面几行
            if not sensitivity:
                for j in range(i + 1, min(len(lines), i + 4)):
                    if lines[j] in ("耐药", "敏感", "中介"):
                        sensitivity = SIR_MAP[lines[j]]
                    elif re.match(r"^[><=≥≤]*\d+[\.\d]*$", lines[j]) and not mic:
                        mic = lines[j]

            if sensitivity:
                clean_name = drug_cn.replace(" ", "")
                if clean_name not in seen:
                    seen.add(clean_name)
                    results.append({
                        "drug_name": clean_name,
                        "mic_value": mic or "",
                        "sir": sensitivity,
                    })
            break

    return results
