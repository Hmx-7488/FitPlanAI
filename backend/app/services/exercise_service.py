"""动作库导入服务。

首次启动时从 data/exercises/exercises_zh.json 导入 1,324 条动作记录。
已存在数据时跳过（幂等）。
"""
import json
import logging
from pathlib import Path
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import Exercise

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent.parent.parent / "data" / "exercises" / "exercises_zh.json"


async def import_exercises_if_empty(db: AsyncSession) -> int:
    """如果 exercises 表为空，从 JSON 导入。返回导入条数。"""
    count_stmt = select(func.count(Exercise.id))
    total = (await db.execute(count_stmt)).scalar() or 0
    if total > 0:
        logger.info("Exercises already imported: %d records, skipping import.", total)
        return 0

    if not DATA_FILE.exists():
        logger.warning("Exercise data file not found: %s", DATA_FILE)
        return 0

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    logger.info("Importing %d exercises from %s ...", len(data), DATA_FILE.name)

    for item in data:
        exercise = Exercise(
            id=item["id"],
            name=item.get("name", ""),
            name_zh=item.get("name_zh", ""),  # 首次为空，后续翻译脚本填入
            body_part=item.get("body_part", ""),
            equipment=item.get("equipment", ""),
            target=item.get("target", ""),
            muscle_group=item.get("muscle_group", ""),
            secondary_muscles=json.dumps(
                item.get("secondary_muscles", []), ensure_ascii=False
            ),
            difficulty=item.get("difficulty", "intermediate"),
            instructions_zh=item.get("instructions_zh", ""),
            instruction_steps_zh=json.dumps(
                item.get("instruction_steps_zh", []), ensure_ascii=False
            ),
            image_path=item.get("image", ""),
            gif_path=item.get("gif_url", ""),
        )
        db.add(exercise)

    await db.commit()
    logger.info("Exercises imported successfully: %d records.", len(data))
    return len(data)
