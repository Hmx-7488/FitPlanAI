"""食材识别服务 — 基于 Vision Model 的多模态食材识别"""

import json
import base64
import logging
import uuid
import re
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from app.core.config import get_settings
from app.models.user import User, IngredientRecognition, Recipe
from app.schemas.vision import (
    IngredientItem, RecognizeResponse, ConfirmRequest, ConfirmResponse,
    RecipeRequest, RecipeItem, RecipeImage, RecipeResponse, SubstituteItem,
)
from app.rag.retriever import retrieve_knowledge
from app.services.image_utils import image_extension
from app.services.recipe_image_service import prepare_recipe_image_jobs

settings = get_settings()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_vision_llm(max_tokens: int = 1000):
    """获取 Vision Model（支持图片输入）。

    返回配置好的 ChatOpenAI 实例，使用 DashScope 兼容 API。
    调用方应根据任务复杂度调整 max_tokens。
    """
    model = settings.VISION_MODEL or settings.LLM_MODEL
    return ChatOpenAI(
        model=model,
        openai_api_key=settings.LLM_API_KEY,
        openai_api_base=settings.LLM_BASE_URL,
        temperature=0.3,
        request_timeout=120,
        max_retries=2,
        max_tokens=max_tokens,
    )


# 向后兼容别名，供尚未迁移的调用方使用
_get_vision_llm = get_vision_llm


def encode_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """将图片字节编码为 base64 data URL，用于 Vision Model 请求。"""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


# 向后兼容别名
_encode_image = encode_image


def _extract_json_array(raw: str) -> list:
    """从 LLM 响应文本中提取 JSON 数组，处理 markdown 代码块包裹。"""
    text = raw.strip()
    json_start = text.find("[")
    json_end = text.rfind("]") + 1
    if json_start >= 0 and json_end > json_start:
        text = text[json_start:json_end]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")
    return data


async def recognize_food_items(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    mode: str = "dish",
    max_tokens: int = 600,
) -> list[dict]:
    """识别图片中的食物/菜品。

    供 meal.py 的 analyze_meal 和 recognize_meal 共用，统一 prompt 和解析逻辑。

    Args:
        image_bytes: 图片原始字节
        mime_type: MIME 类型
        mode: 识别模式 — "dish" 返回菜品级信息（含热量），"ingredient" 返回食材级信息
        max_tokens: LLM 最大输出 token 数

    Returns:
        list[dict]: 识别结果列表。dish 模式返回 dish_name/estimated_portion_g/calories_kcal/
        protein_g/carbs_g/fat_g/confidence；ingredient 模式返回 name/display_name/
        estimated_weight_g/confidence。
    """
    if mode == "dish":
        prompt = (
            "请识别图片中的食物/菜品。对于每个菜品，输出 JSON 数组：\n"
            '[{"dish_name":"番茄炒蛋","estimated_portion_g":220,'
            '"calories_kcal":260,"protein_g":14,"carbs_g":12,"fat_g":18,"confidence":0.82}]\n\n'
            "要求：estimated_portion_g 为估算份量克数，calories_kcal 为估算热量，"
            "protein_g/carbs_g/fat_g 为蛋白质/碳水/脂肪克数，confidence 为置信度 0-1。"
            "只输出 JSON 数组。"
        )
    else:
        prompt = (
            "请识别图片中的食物/食材。对于每个食材，输出 JSON 数组：\n"
            '[{"name":"egg","display_name":"鸡蛋","estimated_weight_g":100,"confidence":0.9},'
            '{"name":"tomato","display_name":"番茄","estimated_weight_g":150,"confidence":0.85}]\n\n'
            "要求：\n"
            "- name: 食材英文名（小写）\n"
            "- display_name: 食材中文名\n"
            "- estimated_weight_g: 估算重量（克）\n"
            "- confidence: 置信度 0-1\n"
            "只输出 JSON 数组，不要其他文字。如果没有识别到食材，返回空数组 []。"
        )

    llm = get_vision_llm(max_tokens=max_tokens)
    image_data = encode_image(image_bytes, mime_type=mime_type)

    message = HumanMessage(content=[
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_data, "detail": "low"}},
    ])

    response = llm.invoke([message])
    raw = response.content.strip()
    items = _extract_json_array(raw)

    # 校验并清理结果
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned.append(item)
    return cleaned


async def recognize_ingredients(
    db: AsyncSession,
    user_id: int,
    image_bytes: bytes,
    filename: str = "photo.jpg",
    mime_type: str = "image/jpeg",
) -> RecognizeResponse:
    """识别图片中的食材"""
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    # 保存图片
    ext = image_extension(mime_type, filename)
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    saved_path.write_bytes(image_bytes)

    # 调用公共接口识别食材
    try:
        ingredients_data = await recognize_food_items(
            image_bytes, mime_type=mime_type, mode="ingredient", max_tokens=800,
        )
    except Exception:
        logger.exception(
            "Vision ingredient recognition failed; returning empty result. "
            "user_id=%s mime_type=%s bytes=%s filename=%s",
            user_id,
            mime_type,
            len(image_bytes),
            filename,
        )
        ingredients_data = []

    ingredients = [
        IngredientItem(
            name=item.get("name", "unknown"),
            display_name=item.get("display_name", "未知食材"),
            estimated_weight_g=item.get("estimated_weight_g", 100),
            confidence=item.get("confidence", 0.5),
            need_confirm=True,
        )
        for item in ingredients_data if isinstance(item, dict)
    ]

    # 生成追问
    if ingredients:
        names = "、".join(f"{i.display_name} 约{i.estimated_weight_g:.0f}g" for i in ingredients)
        question = f"识别到：{names}。请确认或修改重量，然后生成菜谱。"
    else:
        question = "未能识别出食材，请重新拍摄或手动输入。"

    # 保存记录
    rec = IngredientRecognition(
        user_id=user_id,
        image_path=str(saved_path),
        ingredients_json=json.dumps([i.model_dump() for i in ingredients], ensure_ascii=False),
        status="pending",
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)

    return RecognizeResponse(
        recognition_id=rec.id, ingredients=ingredients, question_to_user=question,
    )


async def confirm_ingredients(db: AsyncSession, request: ConfirmRequest) -> ConfirmResponse:
    """用户确认/修改食材重量"""
    rec = await db.get(IngredientRecognition, request.recognition_id)
    if not rec:
        raise ValueError("识别记录不存在")

    rec.confirmed_json = json.dumps(
        [i.model_dump() for i in request.confirmed_ingredients], ensure_ascii=False
    )
    rec.status = "confirmed"
    await db.commit()

    return ConfirmResponse(
        recognition_id=rec.id,
        status="confirmed",
        confirmed_ingredients=request.confirmed_ingredients,
    )


async def generate_recipes(db: AsyncSession, request: RecipeRequest) -> RecipeResponse:
    """基于确认的食材生成轻食菜谱"""
    user = await db.get(User, request.user_id)
    if not user:
        raise ValueError("用户不存在")
    rec = await db.get(IngredientRecognition, request.recognition_id)
    if not rec:
        raise ValueError("识别记录不存在")

    forbidden = json.loads(user.forbidden_foods) if user.forbidden_foods else []
    allergies = json.loads(user.allergies) if user.allergies else []
    diet_pref = user.diet_preference or "balanced"

    ingredient_desc = "\n".join(
        f"- {i.display_name}: {i.estimated_weight_g:.0f}g"
        for i in request.confirmed_ingredients
    )
    exclude_text = "、".join(forbidden + allergies) if (forbidden or allergies) else "无"

    # RAG 检索
    names = " ".join(i.display_name for i in request.confirmed_ingredients)
    recipe_knowledge = "\n".join(retrieve_knowledge(f"食谱 做法 {names}", k=2))
    nutrition_knowledge = "\n".join(retrieve_knowledge(f"食材热量 {names}", k=2))

    llm = get_vision_llm(max_tokens=1800)
    prompt = f"""你是轻食厨师。根据以下食材生成 2-3 个轻食方案。

可用食材：
{ingredient_desc}
饮食偏好：{diet_pref}
忌口/过敏：{exclude_text}

参考：{recipe_knowledge[:400]}
{nutrition_knowledge[:300]}

只输出严格 JSON 数组，不要 Markdown 或额外说明。每个方案结构：
{{
  "name": "菜名",
  "ingredients": ["鸡胸肉 150g", "生菜 100g"],
  "calories_est": 350,
  "protein_est": 35,
  "carbs_est": 30,
  "fat_est": 10,
  "steps": ["步骤1", "步骤2", "步骤3"],
  "substitute_ingredients": [
    {{"missing": "鸡胸肉", "alternatives": ["去皮鸡腿肉 170g", "北豆腐 250g"]}}
  ],
  "shopping_list": ["生菜 100g", "全麦面包 2片"]
}}

要求：
1. 优先使用用户已有食材；购物清单只列方案需要但用户未提供的食材。
2. 每个主要食材提供 1-2 个营养接近的替代项，替代项不得包含忌口或过敏食材。
3. 做法必须是 3-5 个可执行步骤。
4. 营养数值必须是数字，食材必须带大致用量。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    raw_recipe_content = response.content
    recipes = _parse_recipes(raw_recipe_content, request.confirmed_ingredients)
    if not recipes:
        raise ValueError("菜谱模型返回格式无效，请重试")
    recipe_content = _format_recipe_content(recipes)

    recipe = Recipe(
        user_id=request.user_id,
        recognition_id=request.recognition_id,
        recipe_content=recipe_content,
        nutrition_json=json.dumps({
            "total_calories": sum(r.calories_est for r in recipes),
            "total_protein": sum(r.protein_est for r in recipes),
        }, ensure_ascii=False),
    )
    db.add(recipe)
    await db.commit()
    await db.refresh(recipe)

    await prepare_recipe_image_jobs(db, recipe.id, recipes)

    return RecipeResponse(
        recipe_id=recipe.id,
        user_id=request.user_id,
        recognition_id=request.recognition_id,
        food_image_url=f"/uploads/{Path(rec.image_path).name}" if rec.image_path else "",
        recipes=recipes,
        total_calories=sum(r.calories_est for r in recipes),
        total_protein=sum(r.protein_est for r in recipes),
        recipe_content=recipe_content,
        created_at=recipe.created_at,
    )


def _parse_recipes(content: str, ingredients: list[IngredientItem]) -> list[RecipeItem]:
    """Parse current JSON responses and historical Markdown recipe records."""
    json_start = content.find("[")
    json_end = content.rfind("]") + 1
    if json_start >= 0 and json_end > json_start:
        try:
            data = json.loads(content[json_start:json_end])
            if isinstance(data, list):
                recipes = [
                    _build_structured_recipe(item, ingredients)
                    for item in data[:3]
                    if isinstance(item, dict)
                ]
                if recipes:
                    return recipes
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    heading_pattern = re.compile(
        r"(?ms)^#{1,4}\s*\*\*(?:\d+[.、]\s*)?(.+?)\*\*\s*(.*?)(?=^#{1,4}\s*\*\*|\Z)"
    )
    recipes = [
        _build_recipe(name.strip(), body.strip().splitlines(), ingredients)
        for name, body in heading_pattern.findall(content)
    ]
    return recipes[:3]


def _build_structured_recipe(data: dict, available: list[IngredientItem]) -> RecipeItem:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("Recipe name is required")

    ingredient_lines = data.get("ingredients", [])
    if not isinstance(ingredient_lines, list):
        ingredient_lines = []
    ingredient_lines = [str(item).strip() for item in ingredient_lines if str(item).strip()]

    steps = data.get("steps", [])
    if isinstance(steps, list):
        steps_text = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))
    else:
        steps_text = str(steps).strip()

    substitutes = []
    raw_substitutes = data.get("substitute_ingredients", [])
    if isinstance(raw_substitutes, list):
        for item in raw_substitutes[:8]:
            if not isinstance(item, dict):
                continue
            missing = str(item.get("missing", "")).strip()
            alternatives = item.get("alternatives", [])
            if missing and isinstance(alternatives, list):
                substitutes.append(SubstituteItem(
                    missing=missing,
                    alternatives=[str(alt).strip() for alt in alternatives[:3] if str(alt).strip()],
                ))

    shopping = data.get("shopping_list", [])
    if not isinstance(shopping, list):
        shopping = []

    available_names = {item.display_name for item in available}
    used_names = [
        item.display_name
        for item in available
        if any(item.display_name in line for line in ingredient_lines)
    ]
    image_ingredients = "、".join((used_names or ingredient_lines)[:4])

    return RecipeItem(
        name=name,
        ingredients=ingredient_lines,
        calories_est=max(0, int(float(data.get("calories_est", 0) or 0))) or 300,
        protein_est=max(0, float(data.get("protein_est", 0) or 0)) or 20.0,
        carbs_est=max(0, float(data.get("carbs_est", 0) or 0)),
        fat_est=max(0, float(data.get("fat_est", 0) or 0)),
        steps=steps_text,
        image=RecipeImage(
            alt=f"{name}成品图",
            generation_prompt=(
                f"菜品名称：{name}。主要食材及用量：{image_ingredients}。"
                f"烹饪与摆盘应与以下做法一致：{steps_text[:240]}。"
                "单人份健康轻食成品，所有主要食材清晰可见，颜色自然，"
                "白色或浅色餐盘，真实食物摄影，自然日光，45度视角，背景简洁"
            ),
        ),
        missing_ingredients=[
            item
            for item in shopping
            if not any(name in str(item) for name in available_names)
        ],
        substitute_ingredients=substitutes,
        shopping_list=[str(item).strip() for item in shopping if str(item).strip()],
    )


def _format_recipe_content(recipes: list[RecipeItem]) -> str:
    sections = []
    for index, recipe in enumerate(recipes, 1):
        ingredients = "\n".join(f"- {item}" for item in recipe.ingredients)
        substitutes = "\n".join(
            f"- {item.missing}：{' / '.join(item.alternatives)}"
            for item in recipe.substitute_ingredients
        ) or "- 无"
        shopping = "、".join(recipe.shopping_list) or "无需额外采购"
        sections.append(
            f"### **{index}. {recipe.name}**\n"
            f"**食材**\n{ingredients}\n\n"
            f"**营养估算**：{recipe.calories_est} kcal | 蛋白质 {recipe.protein_est:g}g | "
            f"碳水 {recipe.carbs_est:g}g | 脂肪 {recipe.fat_est:g}g\n\n"
            f"**做法**\n{recipe.steps}\n\n"
            f"**替代食材**\n{substitutes}\n\n"
            f"**购物清单**：{shopping}"
        )
    return "\n\n---\n\n".join(sections)


def _build_recipe(name: str, lines: list[str], ingredients: list[IngredientItem]) -> RecipeItem:
    """构建单个菜谱项（含图片信息、替代食材和购物清单）"""
    full_text = "\n".join(lines)

    def labeled_number(label: str) -> float:
        match = re.search(rf"{label}[^0-9]*([\d.]+)", full_text, re.IGNORECASE)
        return float(match.group(1)) if match else 0

    calories = int(labeled_number(r"(?:热量|calories?)"))
    protein = labeled_number(r"蛋白质?")
    carbs = labeled_number(r"碳水")
    fat = labeled_number(r"脂肪")

    used = [ing.display_name for ing in ingredients if ing.display_name in full_text]
    if not used:
        ingredient_match = re.search(
            r"(?ms)\*\*食材\*\*[：:]?\s*(.*?)(?=\n\s*\*\*|\Z)",
            full_text,
        )
        if ingredient_match:
            used = [
                re.sub(r"^[-*\d.\s]+", "", line).strip()
                for line in ingredient_match.group(1).splitlines()
                if re.sub(r"^[-*\d.\s]+", "", line).strip()
            ]
        else:
            used = [i.display_name for i in ingredients[:3]]

    steps_match = re.search(
        r"(?ms)\*\*(?:做法|步骤)\*\*[：:]?\s*(.*?)(?=\n\s*\*\*|\Z)",
        full_text,
    )
    steps = steps_match.group(1).strip() if steps_match else ""
    if not steps:
        steps = full_text[:100]

    # 生成图片生成提示词
    ingredients_text = "、".join(used[:4])
    generation_prompt = (
        f"菜品名称：{name}。主要食材：{ingredients_text}。"
        f"烹饪与摆盘应符合以下做法：{steps[:240]}。"
        "单人份健康轻食成品，所有主要食材清晰可见，颜色自然，"
        "白色或浅色餐盘，真实食物摄影，自然日光，45度视角，背景简洁"
    )

    image = RecipeImage(
        url="",
        alt=f"{name}成品图",
        generation_prompt=generation_prompt,
        status="queued",
    )

    # 食材缺口分析：识别菜谱中提到但用户没有的食材
    available_names = {ing.display_name for ing in ingredients}
    missing = []
    substitutes = []
    shopping = []
    # 常见食材的替代建议映射
    common_missing_map = {
        "西兰花": ["菠菜", "生菜", "黄瓜"],
        "鸡胸肉": ["鸡腿肉", "瘦牛肉", "豆腐"],
        "糙米": ["白米", "红薯", "燕麦"],
        "三文鱼": ["鲈鱼", "鳕鱼", "虾仁"],
        "牛油果": ["橄榄油", "坚果"],
    }
    for common_ingredient, alternatives in common_missing_map.items():
        if common_ingredient in full_text and common_ingredient not in available_names:
            missing.append(common_ingredient)
            substitutes.append(SubstituteItem(
                missing=common_ingredient,
                alternatives=alternatives[:2],
            ))
            shopping.append(common_ingredient)

    return RecipeItem(
        name=name, ingredients=used,
        calories_est=calories or 300, protein_est=protein or 20.0,
        carbs_est=carbs or 30.0, fat_est=fat or 10.0,
        steps=steps, image=image,
        missing_ingredients=missing,
        substitute_ingredients=substitutes,
        shopping_list=shopping,
    )
