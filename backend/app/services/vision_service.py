"""食材识别服务 — 基于 Vision Model 的多模态食材识别"""

import json
import base64
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
    RecipeRequest, RecipeItem, RecipeImage, RecipeResponse,
)
from app.rag.retriever import retrieve_knowledge

settings = get_settings()

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _get_vision_llm(max_tokens: int = 1000):
    """获取 Vision Model（支持图片输入）"""
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


def _encode_image(image_bytes: bytes) -> str:
    """将图片编码为 base64 data URL"""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


async def recognize_ingredients(
    db: AsyncSession, user_id: int, image_bytes: bytes, filename: str = "photo.jpg",
) -> RecognizeResponse:
    """识别图片中的食材"""
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    # 保存图片
    ext = Path(filename).suffix or ".jpg"
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    saved_path.write_bytes(image_bytes)

    # 调用 Vision Model
    llm = _get_vision_llm(max_tokens=800)
    image_data = _encode_image(image_bytes)

    prompt = (
        "请识别图片中的食材。对于每个食材，输出 JSON 数组：\n"
        '[{"name":"chicken_breast","display_name":"鸡胸肉",'
        '"estimated_weight_g":150,"confidence":0.92}]\n\n'
        "要求：name 英文小写下划线，display_name 中文，"
        "estimated_weight_g 估算克数，confidence 置信度 0-1。"
        "只输出 JSON 数组。没有食材返回 []"
    )

    message = HumanMessage(content=[
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_data, "detail": "low"}},
    ])

    response = llm.invoke([message])
    raw = response.content.strip()

    # 解析 JSON
    try:
        if "```" in raw:
            json_start = raw.find("[")
            json_end = raw.rfind("]") + 1
            raw = raw[json_start:json_end]
        ingredients_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
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

    llm = _get_vision_llm(max_tokens=1200)
    prompt = f"""你是轻食厨师。根据以下食材生成 2-3 个轻食方案。

可用食材：
{ingredient_desc}
饮食偏好：{diet_pref}
忌口/过敏：{exclude_text}

参考：{recipe_knowledge[:400]}
{nutrition_knowledge[:300]}

每个方案：
**菜名**
- 食材：用量
- 热量：约 XXX kcal | 蛋白质：XXg
- 做法：3-5 步
最后附烹饪小贴士。简洁实用。"""

    response = llm.invoke([HumanMessage(content=prompt)])
    recipe_content = response.content
    recipes = _parse_recipes(recipe_content, request.confirmed_ingredients)

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

    return RecipeResponse(
        recipe_id=recipe.id,
        user_id=request.user_id,
        recognition_id=request.recognition_id,
        recipes=recipes,
        total_calories=sum(r.calories_est for r in recipes),
        total_protein=sum(r.protein_est for r in recipes),
        recipe_content=recipe_content,
        created_at=recipe.created_at,
    )


def _parse_recipes(content: str, ingredients: list[IngredientItem]) -> list[RecipeItem]:
    """从 LLM 输出中解析菜谱"""
    recipes = []
    sections = content.split("**")
    current_name = ""
    current_lines = []

    for section in sections:
        section = section.strip()
        if not section:
            continue
        if "\n" not in section[:30] and len(section) < 30:
            if current_name and current_lines:
                recipes.append(_build_recipe(current_name, current_lines, ingredients))
            current_name = section.replace("*", "").strip()
            current_lines = []
        else:
            current_lines.extend(section.split("\n"))

    if current_name and current_lines:
        recipes.append(_build_recipe(current_name, current_lines, ingredients))
    return recipes[:3]


def _build_recipe(name: str, lines: list[str], ingredients: list[IngredientItem]) -> RecipeItem:
    """构建单个菜谱项（含图片信息、替代食材和购物清单）"""
    full_text = "\n".join(lines)

    calories = 0
    for line in lines:
        if "kcal" in line.lower() or "热量" in line:
            nums = re.findall(r"(\d+)", line)
            if nums:
                calories = int(nums[0])
                break

    protein = 0.0
    for line in lines:
        if "蛋白" in line:
            nums = re.findall(r"([\d.]+)", line)
            if nums:
                protein = float(nums[0])
                break

    carbs = 0.0
    for line in lines:
        if "碳水" in line:
            nums = re.findall(r"([\d.]+)", line)
            if nums:
                carbs = float(nums[0])
                break

    fat = 0.0
    for line in lines:
        if "脂肪" in line:
            nums = re.findall(r"([\d.]+)", line)
            if nums:
                fat = float(nums[0])
                break

    used = [ing.display_name for ing in ingredients if ing.display_name in full_text]
    if not used:
        used = [i.display_name for i in ingredients[:3]]

    steps = ""
    for line in lines:
        if "做法" in line or "步骤" in line:
            steps = line.split("：", 1)[-1].strip() if "：" in line else line
            break
    if not steps:
        steps = full_text[:100]

    # 生成图片生成提示词
    ingredients_text = "、".join(used[:4])
    generation_prompt = (
        f"真实食物摄影风格的{name}，使用{ingredients_text}，"
        f"白色餐盘，自然光，高蛋白轻食餐，俯拍角度"
    )

    image = RecipeImage(
        url="/uploads/recipes/default-recipe.png",
        alt=f"{name}成品图",
        generation_prompt=generation_prompt,
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
            from app.schemas.vision import SubstituteItem
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
