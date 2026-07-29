"""
Pydantic v2 数据模型 — 无限流规则怪谈六类实体

tag_detail 的 JSON schema 定义 + 输出校验
"""

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


# ── Category 枚举 ──────────────────────────────────────

class Category(str, Enum):
    WORLD = "world"
    MAP = "map"
    RULE = "rule"
    CHARACTER = "character"
    ITEM = "item"
    MEMORY = "memory"


class CharacterType(str, Enum):
    NPC = "NPC"
    MONSTER = "monster"
    PLAYER = "player"


class ItemType(str, Enum):
    WEAPON = "武器"
    TOOL = "工具"
    CONSUMABLE = "消耗品"
    CLUE = "线索"
    CURSED = "诅咒物"


class RuleTriggerType(str, Enum):
    LOCATION = "location"
    ITEM = "item"
    CHARACTER = "character"
    TIME = "time"
    ACTION = "action"


class RuleDiscovery(str, Enum):
    HIDDEN = "hidden"
    HINTED = "hinted"
    KNOWN = "known"


# ── Rule 子结构 ────────────────────────────────────────

class RuleTrigger(BaseModel):
    type: RuleTriggerType
    value: str


class SubRule(BaseModel):
    name: str
    content: str = Field(description="玩家可见的规则条文")
    explanation: str = Field(description="AI可见的详细解释")
    triggers: list[RuleTrigger] = Field(default_factory=list)
    consequence: str = Field(default="", description="AI执行的后果")
    priority: int = Field(default=5, ge=1, le=10)


# ── 六类 tag_detail ────────────────────────────────────

class WorldDetail(BaseModel):
    surface_intro: str
    hidden_truth: str
    entry_condition: str = ""
    clear_condition: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)


class MapDetail(BaseModel):
    parent_world: str
    surface_desc: str
    hidden_info: str
    connected_to: list[str] = Field(default_factory=list)
    danger_level: int = Field(default=0, ge=0, le=5)
    extras: dict[str, Any] = Field(default_factory=dict)


class RuleDetail(BaseModel):
    parent_world: str
    discovery: RuleDiscovery = RuleDiscovery.KNOWN
    sub_rules: list[SubRule] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


class CharacterDetail(BaseModel):
    is_player: bool = False
    character_type: Optional[CharacterType] = None
    parent_world: str = ""
    current_map: Optional[str] = None
    hp: int = 100
    sanity: int = 100
    personality: str = ""
    appearance: str = ""
    behavior_logic: str = Field(default="", description="仅NPC——AI生成行为的依据")
    items: list[str] = Field(default_factory=list)
    intent: str = Field(default="", description="仅NPC——当前想法/目标")
    attitude: str = Field(default="", description="仅NPC——对玩家态度")
    extras: dict[str, Any] = Field(default_factory=dict)


class ItemDetail(BaseModel):
    parent_world: str = ""
    item_type: Optional[ItemType] = None
    surface_desc: str = ""
    hidden_info: str = ""
    location: str = ""
    effect: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)


class MemoryDetail(BaseModel):
    content: str


# ── category → detail model 映射 ────────────────────────

DETAIL_MODEL = {
    Category.WORLD: WorldDetail,
    Category.MAP: MapDetail,
    Category.RULE: RuleDetail,
    Category.CHARACTER: CharacterDetail,
    Category.ITEM: ItemDetail,
    Category.MEMORY: MemoryDetail,
}


def validate_detail(category: Category, detail: dict) -> dict:
    """校验 tag_detail 并返回验证后的 dict"""
    model = DETAIL_MODEL[category]
    return model(**detail).model_dump()


# ── AI-2 输出结构 ──────────────────────────────────────

class CreateOp(BaseModel):
    tag_name: str
    category: Category
    tag_hint: str
    tag_detail: dict[str, Any]


class UpdateOp(BaseModel):
    tag_name: str
    tag_detail: dict[str, Any]  # 完整的新 tag_detail（全量覆盖）


class DataOps(BaseModel):
    create: list[CreateOp] = Field(default_factory=list)
    update: list[UpdateOp] = Field(default_factory=list)
    drop: list[str] = Field(default_factory=list)


class AI2Output(BaseModel):
    narrative: str
    data_ops: DataOps


# ── AI-1 输出结构 ──────────────────────────────────────

class AI1Output(BaseModel):
    keepTags: list[str] = Field(default_factory=list)
    fetchTags: list[str] = Field(default_factory=list)
    dropTags: list[str] = Field(default_factory=list)
    keepMemories: list[str] = Field(default_factory=list)
    fetchMemories: list[str] = Field(default_factory=list)
    dropMemories: list[str] = Field(default_factory=list)


# ── 标签库行 ────────────────────────────────────────────

class TagRow(BaseModel):
    player_id: str
    tag_name: str
    tag_hint: str
    category: Category


class DetailRow(BaseModel):
    player_id: str
    tag_name: str
    tag_detail: dict[str, Any]


class MemoryRow(BaseModel):
    player_id: str
    memory_id: str
    memory_hint: str


class MemoryDetailRow(BaseModel):
    player_id: str
    memory_id: str
    memory_detail: dict[str, Any]
