from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gender: Mapped[str] = mapped_column(String(10))
    age: Mapped[int] = mapped_column(Integer)
    height: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    target_weight: Mapped[float] = mapped_column(Float)
    target_weeks: Mapped[int] = mapped_column(Integer, nullable=True)  # 目标周期（周）
    body_fat_rate: Mapped[float] = mapped_column(Float, nullable=True)
    activity_level: Mapped[str] = mapped_column(String(20), default="medium")
    diet_preference: Mapped[str] = mapped_column(String(50), default="balanced")
    goal_type: Mapped[str] = mapped_column(String(20), default="fat_loss")  # fat_loss / muscle_gain
    forbidden_foods: Mapped[str] = mapped_column(Text, default="[]")
    injuries: Mapped[str] = mapped_column(Text, default="[]")
    allergies: Mapped[str] = mapped_column(Text, default="[]")
    # 训练条件字段
    training_days_per_week: Mapped[int] = mapped_column(Integer, default=3)
    session_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    training_location: Mapped[str] = mapped_column(String(20), default="gym")  # gym / home / outdoor
    equipment: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    training_experience: Mapped[str] = mapped_column(String(20), default="beginner")  # beginner / intermediate / advanced
    preferred_training_time: Mapped[str] = mapped_column(String(20), default="morning")  # morning / afternoon / evening
    # 中国饮食习惯字段
    region_preference: Mapped[str] = mapped_column(String(30), default="balanced")  # south_china / north_china / sichuan / cantonese / balanced
    meal_scenario: Mapped[str] = mapped_column(String(30), default="home_cooking")  # home_cooking / takeout / canteen / convenience_store
    prep_time_limit_minutes: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    daily_calorie_target: Mapped[int] = mapped_column(Integer)
    calorie_info_json: Mapped[str] = mapped_column(Text, default="{}")
    macros_json: Mapped[str] = mapped_column(Text, default="{}")
    meal_plan: Mapped[str] = mapped_column(Text)
    workout_plan: Mapped[str] = mapped_column(Text)
    workout_plan_json: Mapped[str] = mapped_column(Text, default="")  # 结构化训练计划
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Checkin(Base):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    date: Mapped[str] = mapped_column(String(10))
    foods: Mapped[str] = mapped_column(Text, default="")
    exercises: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IngredientRecognition(Base):
    """食材识别记录"""
    __tablename__ = "ingredient_recognitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[str] = mapped_column(Text, default="")
    ingredients_json: Mapped[str] = mapped_column(Text, default="[]")  # 识别结果
    confirmed_json: Mapped[str] = mapped_column(Text, default="[]")    # 用户确认后的结果
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / confirmed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Recipe(Base):
    """菜谱记录"""
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    recognition_id: Mapped[int] = mapped_column(Integer)
    recipe_content: Mapped[str] = mapped_column(Text, default="")  # LLM 生成的菜谱文本
    nutrition_json: Mapped[str] = mapped_column(Text, default="{}")  # 营养成分估算
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RecipeImageJob(Base):
    """Persistent state for one generated recipe image."""
    __tablename__ = "recipe_image_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(Integer, index=True)
    recipe_index: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text)
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    image_url: Mapped[str] = mapped_column(Text, default="")
    provider_task_id: Mapped[str] = mapped_column(String(100), default="")
    provider_request_id: Mapped[str] = mapped_column(String(100), default="")
    error_code: Mapped[str] = mapped_column(String(100), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class MealLog(Base):
    """餐食热量识别记录"""
    __tablename__ = "meal_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    meal_type: Mapped[str] = mapped_column(String(20), default="lunch")  # breakfast / lunch / dinner / snack
    image_path: Mapped[str] = mapped_column(Text, default="")
    items_json: Mapped[str] = mapped_column(Text, default="[]")  # 识别的菜品列表
    meal_total_json: Mapped[str] = mapped_column(Text, default="{}")  # 本餐总营养
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MealRecognition(Base):
    """餐食识别暂存（识别 → 用户确认 → 计算营养 两步流程的中间态）。

    持久化到数据库，避免内存缓存重启即丢、多实例不一致的问题。
    计算成功后删除。
    """
    __tablename__ = "meal_recognitions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid hex
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    meal_type: Mapped[str] = mapped_column(String(20), default="lunch")
    image_path: Mapped[str] = mapped_column(Text, default="")
    ingredients_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Exercise(Base):
    """动作库：1,324 个结构化健身动作。

    数据来源 exercises-dataset（© Gym visual 媒体署名保留）。
    首次启动时从 data/exercises/exercises_zh.json 自动导入。
    """
    __tablename__ = "exercises"

    id: Mapped[str] = mapped_column(String(4), primary_key=True)  # "0025"
    name: Mapped[str] = mapped_column(String(200))  # 英文名
    name_zh: Mapped[str] = mapped_column(String(200), default="")  # 中文名（翻译后填入）
    body_part: Mapped[str] = mapped_column(String(50), index=True)  # chest/back/upper arms/...
    equipment: Mapped[str] = mapped_column(String(50), index=True)  # barbell/dumbbell/body weight/...
    target: Mapped[str] = mapped_column(String(100), default="")  # 目标肌
    muscle_group: Mapped[str] = mapped_column(String(100), default="")  # 主协同肌
    secondary_muscles: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    difficulty: Mapped[str] = mapped_column(String(20), default="intermediate", index=True)  # beginner/intermediate/advanced
    instructions_zh: Mapped[str] = mapped_column(Text, default="")
    instruction_steps_zh: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    image_path: Mapped[str] = mapped_column(String(200), default="")  # 缩略图文件名
    gif_path: Mapped[str] = mapped_column(String(200), default="")  # 动图文件名


class BodyAnalysis(Base):
    """Persisted body-composition analysis and comparison context."""
    __tablename__ = "body_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), default="completed", index=True)
    photo_urls_json: Mapped[str] = mapped_column(Text, default="{}")
    view_metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    measurements_json: Mapped[str] = mapped_column(Text, default="{}")
    quality_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    is_ai: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ChatConversation(Base):
    """聊天 Agent 会话。"""
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(100), default="新对话")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ChatMessage(Base):
    """聊天消息及其引用、业务上下文摘要。"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
