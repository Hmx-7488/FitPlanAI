"""补剂推荐服务。

按用户目标 + 伤病关键词匹配 supplements_map.json（确定性匹配），
再用 RAG 知识文档生成个性化推荐文案。
"""
import json
import logging
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from app.core.config import get_settings
from app.core.restrictions import canonical_source_restrictions
from app.rag.retriever import retrieve_knowledge

logger = logging.getLogger(__name__)
settings = get_settings()

DATA_FILE = Path(__file__).parent.parent.parent / "data" / "supplements" / "supplements_map.json"

_supplements_cache: list[dict] | None = None


def _condition_conflicts(supplement: dict, conditions: list[str]) -> bool:
    """保守过滤用户已声明且与补剂禁忌直接匹配的情况。"""
    normalized_conditions = [str(value).strip().lower() for value in conditions if str(value).strip()]
    medical_keywords = (
        "肾", "肝", "心律", "高钙", "结石", "癫痫", "甲状腺",
        "孕", "抗凝", "乳糖", "als",
    )
    equivalent_groups = (
        ("贝壳", "海鲜", "甲壳"),
        ("乳糖", "乳制品", "牛奶"),
    )
    for contraindication in supplement.get("contraindications", []):
        normalized = str(contraindication).strip().lower()
        if normalized and any(
            condition in normalized or normalized in condition
            for condition in normalized_conditions
        ):
            return True
        if normalized and any(
            keyword in normalized and any(keyword in condition for condition in normalized_conditions)
            for keyword in medical_keywords
        ):
            return True
        if normalized and any(
            any(alias in normalized for alias in group)
            and any(any(alias in condition for alias in group) for condition in normalized_conditions)
            for group in equivalent_groups
        ):
            return True
    return False


def _source_conflicts(
    supplement: dict,
    restrictions: list[str],
    diet_preference: str,
) -> bool:
    """按补剂来源标签过滤食物限制和素食偏好。"""
    fallback_sources = {
        "乳清蛋白粉": ["milk"],
        "酪蛋白": ["milk"],
        "鱼油（Omega-3）": ["fish"],
        "氨基葡萄糖": ["shellfish"],
        "胶原蛋白肽": ["animal"],
    }
    source_tags = set(supplement.get("source_tags") or fallback_sources.get(supplement.get("name"), []))
    if diet_preference == "vegetarian" and source_tags.intersection({"fish", "shellfish", "animal"}):
        return True

    return bool(source_tags.intersection(canonical_source_restrictions(restrictions)))


def _fallback_recommendations(candidates: list[dict], goal_type: str) -> list[dict]:
    """使用数据表中的规范字段生成确定性降级结果。"""
    return [
        {
            "name": supplement["name"],
            "name_en": supplement.get("name_en", ""),
            "reason": f"可作为{goal_type}目标下的可选补充，优先保证日常饮食和训练安排。",
            "dosage": supplement["dosage"],
            "timing": supplement["timing"],
            "contraindications": supplement.get("contraindications", []),
        }
        for supplement in candidates[:5]
    ]


def _validate_llm_recommendations(raw_items: object, candidates: list[dict]) -> list[dict]:
    """只接收候选补剂名称；剂量、时机和禁忌始终以本地数据为准。"""
    if not isinstance(raw_items, list):
        return []

    by_name = {supplement["name"]: supplement for supplement in candidates}
    validated = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        reason = item.get("reason")
        if name not in by_name or name in seen or not isinstance(reason, str) or not reason.strip():
            continue
        canonical = by_name[name]
        validated.append({
            "name": canonical["name"],
            "name_en": canonical.get("name_en", ""),
            "reason": reason.strip()[:300],
            "dosage": canonical["dosage"],
            "timing": canonical["timing"],
            "contraindications": canonical.get("contraindications", []),
        })
        seen.add(name)
        if len(validated) == 5:
            break
    return validated


def _load_supplements() -> list[dict]:
    """加载补剂映射（启动时缓存到内存）。"""
    global _supplements_cache
    if _supplements_cache is not None:
        return _supplements_cache
    if not DATA_FILE.exists():
        logger.warning("Supplements map not found: %s", DATA_FILE)
        _supplements_cache = []
        return _supplements_cache
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, list):
            raise ValueError("supplements map root must be a list")
        _supplements_cache = loaded
    except (OSError, json.JSONDecodeError, ValueError):
        logger.exception("Failed to load supplements map; using empty candidates")
        _supplements_cache = []
        return _supplements_cache
    logger.info("Loaded %d supplements from %s", len(_supplements_cache), DATA_FILE.name)
    return _supplements_cache


def _match_supplements(
    goal_type: str,
    injuries: list[str],
    diet_tags: list[str] | None = None,
) -> list[dict]:
    """按用户目标 + 伤病关键词确定性匹配补剂候选列表。"""
    all_supps = _load_supplements()
    injuries_lower = [i.lower() for i in injuries] if injuries else []
    injury_text = " ".join(injuries_lower)

    matched = []
    for supp in all_supps:
        # 目标类型匹配
        if goal_type not in supp.get("goal_type", []):
            continue

        triggers = [t.lower() for t in supp.get("triggers", [])]
        score = 0

        # 伤病关键词匹配
        for trigger in triggers:
            if any(trigger in inj for inj in injuries_lower) or trigger in injury_text:
                score += 10
                break

        # 通用目标匹配（muscle_gain / fat_loss 本身就是 trigger）
        if goal_type in triggers:
            score += 5

        # 其他通用 trigger
        general_triggers = ["recovery", "deficiency", "balanced_nutrition"]
        for gt in general_triggers:
            if gt in triggers:
                score += 2

        if score > 0:
            matched.append({**supp, "match_score": score})

    # 按匹配分数和排序优先级排序
    matched.sort(key=lambda x: (-x["match_score"], x.get("sort_order", 99)))

    # 去掉 match_score，返回干净的补剂信息
    for m in matched:
        del m["match_score"]

    return matched[:8]  # 最多返回 8 个


async def generate_supplement_recommendations(
    goal_type: str,
    injuries: list[str],
    diet_preference: str = "balanced",
    allergies: list[str] | None = None,
    forbidden_foods: list[str] | None = None,
) -> list[dict]:
    """生成补剂推荐。

    1. 确定性匹配候选列表
    2. RAG 检索补剂知识
    3. LLM 生成个性化推荐文案
    """
    health_conditions = [
        *injuries,
        *(allergies or []),
        *(forbidden_foods or []),
    ]
    try:
        candidates = [
            supplement
            for supplement in _match_supplements(goal_type, injuries)
            if not _condition_conflicts(supplement, health_conditions)
            and not _source_conflicts(supplement, health_conditions, diet_preference)
        ]
    except Exception:
        logger.exception("Failed to prepare supplement candidates; using empty recommendations")
        return []
    if not candidates:
        return []

    # RAG 检索补剂知识
    supplement_names = " ".join(s["name"] for s in candidates)
    try:
        knowledge = retrieve_knowledge(f"补剂 {supplement_names} {goal_type}", k=3)
    except Exception:
        logger.exception("Supplement knowledge retrieval failed; continuing without RAG context")
        knowledge = []
    knowledge_text = "\n".join(knowledge) if knowledge else ""

    # LLM 生成推荐文案
    injuries_text = "、".join(injuries) if injuries else "无"
    allergies_text = "、".join([*(allergies or []), *(forbidden_foods or [])]) or "无"
    candidates_text = "\n".join(
        f"- {s['name']}（{s['name_en']}）：触发条件={s['triggers']}，"
        f"剂量={s['dosage']}，时机={s['timing']}，禁忌={s['contraindications']}"
        for s in candidates
    )

    try:
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_BASE_URL,
            temperature=0.5,
            request_timeout=60,
            max_retries=2,
            max_tokens=1000,
        )
    except Exception:
        logger.exception("Supplement recommendation client initialization failed")
        return _fallback_recommendations(candidates, goal_type)

    prompt = f"""你是运动营养师。根据用户信息从候选补剂列表中推荐 3-5 个最合适的补剂，并为每个补剂写一段个性化推荐理由。

用户信息：
- 目标：{goal_type}
- 伤病：{injuries_text}
- 过敏/禁忌食物：{allergies_text}
- 饮食偏好：{diet_preference}

候选补剂列表：
{candidates_text}

参考知识：
{knowledge_text[:600]}

只输出严格 JSON 数组（无 markdown、无额外文字）：
[
  {{
    "name": "补剂名",
    "name_en": "英文名",
    "reason": "针对该用户的个性化推荐理由（1-2 句话）",
    "dosage": "推荐剂量",
    "timing": "服用时机",
    "contraindications": ["禁忌1"]
  }}
]

规则：
1. 只从候选列表中选择补剂
2. reason 必须结合用户的具体目标和伤病情况
3. 如果用户有禁忌，不要推荐对应补剂
4. 优先推荐证据更强的补剂
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        json_start = raw.find("[")
        json_end = raw.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            raw = raw[json_start:json_end]
        recommendations = _validate_llm_recommendations(json.loads(raw), candidates)
        if recommendations:
            return recommendations
    except Exception:
        logger.exception("Supplement recommendation LLM call failed")

    # 降级：返回候选列表的原始信息
    return _fallback_recommendations(candidates, goal_type)
