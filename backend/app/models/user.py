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
    body_fat_rate: Mapped[float] = mapped_column(Float, nullable=True)
    activity_level: Mapped[str] = mapped_column(String(20), default="medium")
    diet_preference: Mapped[str] = mapped_column(String(50), default="balanced")
    goal_type: Mapped[str] = mapped_column(String(20), default="fat_loss")  # fat_loss / muscle_gain
    forbidden_foods: Mapped[str] = mapped_column(Text, default="[]")
    injuries: Mapped[str] = mapped_column(Text, default="[]")
    allergies: Mapped[str] = mapped_column(Text, default="[]")
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
