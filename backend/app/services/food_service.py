"""食物热量库导入服务。

首次启动时从 data/foods/foods_zh.json 导入自建食物营养数据。
已存在数据时跳过（幂等）。
"""
import json
import logging
from pathlib import Path
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import Food

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent.parent.parent / "data" / "foods" / "foods_zh.json"


async def import_foods_if_empty(db: AsyncSession) -> int:
    """如果 foods 表为空，从 JSON 导入。返回导入条数。"""
    count_stmt = select(func.count(Food.id))
    total = (await db.execute(count_stmt)).scalar() or 0
    if total > 0:
        logger.info("Foods already imported: %d records, skipping import.", total)
        return 0

    if not DATA_FILE.exists():
        logger.warning("Food data file not found: %s", DATA_FILE)
        return 0

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    logger.info("Importing %d foods from %s ...", len(data), DATA_FILE.name)

    for item in data:
        food = Food(
            name_zh=item["name_zh"],
            aliases=json.dumps(item.get("aliases", []), ensure_ascii=False),
            category=item.get("category", ""),
            calories_kcal=item.get("calories_kcal", 0),
            protein_g=item.get("protein_g", 0),
            carbs_g=item.get("carbs_g", 0),
            fat_g=item.get("fat_g", 0),
            fiber_g=item.get("fiber_g", 0),
            sodium_mg=item.get("sodium_mg", 0),
            default_portion_g=item.get("default_portion_g", 100),
            default_portion_name=item.get("default_portion_name", ""),
            diet_tags=json.dumps(item.get("diet_tags", []), ensure_ascii=False),
            common_dishes=json.dumps(item.get("common_dishes", []), ensure_ascii=False),
        )
        db.add(food)

    await db.commit()
    logger.info("Foods imported successfully: %d records.", len(data))
    return len(data)
