"""RAG 知识层 — 结构化模型定义

KnowledgeDocument: 知识文档元数据
KnowledgeChunk:   知识块（检索最小单元）
SearchQuery:      检索请求
SearchResult:     检索结果
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ──── 枚举 ────

class KnowledgeCategory(str, Enum):
    """知识域分类"""
    fat_loss_standards = "fat_loss_standards"
    muscle_gain_standards = "muscle_gain_standards"
    nutrition_planning = "nutrition_planning"
    chinese_meals = "chinese_meals"
    training_principles = "training_principles"
    exercise_technique = "exercise_technique"
    risk_rules = "risk_rules"


class EvidenceLevel(str, Enum):
    """证据等级"""
    guideline = "guideline"           # 权威指南 / 行业标准
    research = "research"             # 研究文献 / 实验数据
    expert = "expert"                 # 专家建议 / 教练经验
    community = "community"           # 社区经验 / 常见做法
    internal = "internal"             # 项目内部规则


class GoalType(str, Enum):
    fat_loss = "fat_loss"
    muscle_gain = "muscle_gain"
    general = "general"


class Audience(str, Enum):
    general = "general"
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"
    elderly = "elderly"
    female = "female"


class DocStatus(str, Enum):
    active = "active"
    deprecated = "deprecated"
    draft = "draft"


# ──── ID 生成 ────

def make_stable_id(content: str, prefix: str = "doc") -> str:
    """基于内容哈希生成稳定的 UUID（确定性，相同内容永远相同）"""
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{uuid.UUID(h[:32].ljust(32, '0')).hex[:12]}"


def content_hash(text: str) -> str:
    """返回内容的 SHA-256 短哈希（用于去重判断）"""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


# ──── 知识文档 ────

class KnowledgeDocument(BaseModel):
    """知识文档元数据"""
    document_id: str = Field(default="", description="稳定文档 ID")
    title: str = Field(..., min_length=1, max_length=200, description="文档标题")
    category: KnowledgeCategory = Field(..., description="知识域分类")
    source_name: str = Field(default="", max_length=200, description="来源名称")
    source_url: str = Field(default="", max_length=500, description="来源链接")
    published_at: Optional[date] = Field(default=None, description="发布日期")
    reviewed_at: Optional[date] = Field(default=None, description="最后复核日期")
    evidence_level: EvidenceLevel = Field(
        default=EvidenceLevel.internal,
        description="证据等级",
    )
    version: str = Field(default="1.0", max_length=20, description="文档版本")
    status: DocStatus = Field(default=DocStatus.active, description="文档状态")
    content_hash: str = Field(default="", description="文档内容哈希")
    chunk_count: int = Field(default=0, ge=0, description="切分后的知识块数量")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _auto_id_and_hash(self) -> "KnowledgeDocument":
        if not self.document_id:
            self.document_id = make_stable_id(
                f"{self.category.value}:{self.title}", prefix="doc"
            )
        return self

    @field_validator("source_url")
    @classmethod
    def _validate_source_url(cls, v: str) -> str:
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("source_url must start with http:// or https://")
        return v

    @model_validator(mode="after")
    def _validate_evidence_without_source(self) -> "KnowledgeDocument":
        if self.evidence_level in (EvidenceLevel.guideline, EvidenceLevel.research):
            if not self.source_name and not self.source_url:
                raise ValueError(
                    f"evidence_level={self.evidence_level.value} requires source_name or source_url"
                )
        return self


# ──── 知识块 ────

class KnowledgeChunk(BaseModel):
    """知识块 — 检索的最小单元"""
    chunk_id: str = Field(default="", description="稳定知识块 ID")
    document_id: str = Field(..., description="所属文档 ID")
    title: str = Field(..., min_length=1, max_length=200, description="知识块标题")
    content: str = Field(..., min_length=1, description="知识块正文")
    topic: str = Field(default="", max_length=100, description="主题标签")
    goal_types: list[GoalType] = Field(
        default_factory=lambda: [GoalType.general],
        description="适用目标类型",
    )
    audiences: list[Audience] = Field(
        default_factory=lambda: [Audience.general],
        description="适用人群",
    )
    applicable_conditions: list[str] = Field(
        default_factory=list, max_length=10, description="适用条件",
    )
    contraindications: list[str] = Field(
        default_factory=list, max_length=10, description="禁忌条件",
    )
    tags: list[str] = Field(
        default_factory=list, max_length=20, description="标签",
    )
    category: KnowledgeCategory = Field(
        default=KnowledgeCategory.fat_loss_standards,
        description="继承自文档的知识域",
    )
    evidence_level: EvidenceLevel = Field(
        default=EvidenceLevel.internal,
        description="继承自文档的证据等级",
    )
    source_name: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=500)
    content_hash: str = Field(default="", description="内容哈希")
    chunk_version: str = Field(default="1.0", max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _auto_id_and_hash(self) -> "KnowledgeChunk":
        if not self.chunk_id:
            self.chunk_id = make_stable_id(
                f"{self.document_id}:{self.title}:{self.content[:200]}",
                prefix="chk",
            )
        if not self.content_hash:
            self.content_hash = content_hash(self.content)
        return self

    @field_validator("tags", "applicable_conditions", "contraindications", mode="before")
    @classmethod
    def _normalize_str_list(cls, v: list) -> list:
        if not isinstance(v, list):
            return []
        return [str(item).strip().lower() for item in v if item]


# ──── 检索相关 ────

class SearchQuery(BaseModel):
    """检索请求"""
    query: str = Field(..., min_length=1, max_length=500)
    goal_type: Optional[GoalType] = Field(default=None)
    current_page: str = Field(default="", max_length=100)
    training_level: Optional[str] = Field(default=None)
    dietary_restrictions: list[str] = Field(default_factory=list)
    injuries: list[str] = Field(default_factory=list)
    categories: list[KnowledgeCategory] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievedChunk(BaseModel):
    """检索返回的知识块"""
    chunk_id: str
    document_id: str
    title: str
    content: str
    source_name: str = ""
    source_url: str = ""
    evidence_level: str = ""
    applicable_conditions: list[str] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_method: str = Field(default="vector")


class SearchResult(BaseModel):
    """检索结果"""
    query: str
    documents: list[RetrievedChunk] = Field(default_factory=list)
    insufficient_evidence: bool = Field(default=False)
    total_candidates: int = Field(default=0, ge=0)
    retrieval_time_ms: float = Field(default=0.0, ge=0.0)


class IndexStats(BaseModel):
    """索引统计"""
    total_documents: int = 0
    total_chunks: int = 0
    categories: dict[str, int] = Field(default_factory=dict)
    index_version: str = ""
    last_rebuild: Optional[datetime] = None
    content_hashes: int = 0


class ImportReport(BaseModel):
    """导入报告"""
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    deprecated: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
