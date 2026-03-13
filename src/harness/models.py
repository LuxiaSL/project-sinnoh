"""Pydantic models for all game state data structures."""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from pydantic import BaseModel, Field


class StatusCondition(IntEnum):
    """Pokemon status conditions from the status bitfield."""
    NONE = 0
    SLEEP = 1  # bits 0-2: turns remaining
    POISON = 8  # bit 3
    BURN = 16  # bit 4
    FREEZE = 32  # bit 5
    PARALYSIS = 64  # bit 6
    TOXIC = 128  # bit 7


class NatureInfo(BaseModel):
    """Pokemon nature with stat modifiers."""
    id: int
    name: str
    increased_stat: Optional[str] = None  # None for neutral natures
    decreased_stat: Optional[str] = None


class MoveInfo(BaseModel):
    """Move data."""
    id: int
    name: str
    type: str
    power: Optional[int] = None  # None for status moves
    accuracy: Optional[int] = None
    pp: int
    category: str  # "Physical", "Special", "Status"


class Move(BaseModel):
    """A Pokemon's move slot."""
    id: int
    name: str
    type: str = ""
    power: Optional[int] = None
    pp_current: int = 0
    pp_max: int = 0
    category: str = ""


class Pokemon(BaseModel):
    """A party Pokemon with all relevant data."""
    slot: int = Field(ge=0, le=5)
    species_id: int
    species_name: str = ""
    nickname: str = ""
    level: int = Field(ge=1, le=100)
    hp_current: int
    hp_max: int
    attack: int = 0
    defense: int = 0
    speed: int = 0
    sp_attack: int = 0
    sp_defense: int = 0
    moves: list[Move] = Field(default_factory=list)
    ability_id: int = 0
    ability_name: str = ""
    nature: NatureInfo | None = None
    held_item_id: int = 0
    held_item_name: str = ""
    experience: int = 0
    status: int = 0  # raw status bitfield
    status_name: str = "OK"
    is_egg: bool = False
    is_shiny: bool = False
    pid: int = 0
    evs: dict[str, int] = Field(default_factory=dict)
    ivs: dict[str, int] = Field(default_factory=dict)
    types: list[str] = Field(default_factory=list)

    @property
    def hp_fraction(self) -> float:
        if self.hp_max == 0:
            return 0.0
        return self.hp_current / self.hp_max

    def status_display(self) -> str:
        """Human-readable status for the state formatter."""
        if self.status == 0:
            return "OK"
        conditions: list[str] = []
        sleep_turns = self.status & 0x07
        if sleep_turns:
            conditions.append(f"SLP({sleep_turns})")
        if self.status & 0x08:
            conditions.append("PSN")
        if self.status & 0x10:
            conditions.append("BRN")
        if self.status & 0x20:
            conditions.append("FRZ")
        if self.status & 0x40:
            conditions.append("PAR")
        if self.status & 0x80:
            conditions.append("TOX")
        return "/".join(conditions) if conditions else "OK"


class BadgeInfo(BaseModel):
    """A gym badge."""
    bit: int
    name: str
    leader: str
    city: str


class PlayerState(BaseModel):
    """Current player/trainer state."""
    name: str = ""
    trainer_id: int = 0
    secret_id: int = 0
    money: int = 0
    gender: int = 0  # 0=Male, 1=Female
    gender_name: str = "Male"
    badges: int = 0  # raw bitfield
    badge_count: int = 0
    badge_list: list[str] = Field(default_factory=list)
    play_hours: int = 0
    play_minutes: int = 0
    play_seconds: int = 0
    map_id: int = 0
    map_name: str = ""
    x: int = 0
    y: int = 0
    party_count: int = 0

    @property
    def play_time_str(self) -> str:
        return f"{self.play_hours}:{self.play_minutes:02d}:{self.play_seconds:02d}"


class Party(BaseModel):
    """The player's party."""
    count: int = 0
    pokemon: list[Pokemon] = Field(default_factory=list)


class InventoryItem(BaseModel):
    """A single item in the bag."""
    item_id: int
    item_name: str = ""
    quantity: int = 0


class InventoryPocket(BaseModel):
    """A bag pocket containing items."""
    name: str
    items: list[InventoryItem] = Field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)


class Inventory(BaseModel):
    """The player's full bag contents."""
    pockets: dict[str, InventoryPocket] = Field(default_factory=dict)

    @property
    def total_items(self) -> int:
        return sum(p.count for p in self.pockets.values())


class BattlePokemon(BaseModel):
    """A Pokemon as seen during battle (may be enemy or player's active)."""
    species_id: int = 0
    species_name: str = ""
    level: int = 0
    hp_current: int = 0
    hp_max: int = 0
    types: list[str] = Field(default_factory=list)
    status: int = 0
    status_name: str = "OK"
    # Player's active Pokemon will have moves; enemy won't (unless we can read them)
    moves: list[Move] = Field(default_factory=list)
    ability_name: str = ""
    is_shiny: bool = False

    @property
    def hp_fraction(self) -> float:
        if self.hp_max == 0:
            return 0.0
        return self.hp_current / self.hp_max


class BattleState(BaseModel):
    """State during a battle."""
    is_wild: bool = True
    player_pokemon: BattlePokemon | None = None
    enemy_pokemon: BattlePokemon | None = None
    # Future: weather, turn count, stat stages


class GameState(BaseModel):
    """Complete game state snapshot."""
    player: PlayerState
    party: Party
    inventory: Inventory | None = None
    in_battle: bool = False
    battle: BattleState | None = None
    # Screenshots added separately (not serialized in the model)


# Badge data (hardcoded, 8 entries)
BADGES: list[BadgeInfo] = [
    BadgeInfo(bit=0, name="Coal Badge", leader="Roark", city="Oreburgh"),
    BadgeInfo(bit=1, name="Forest Badge", leader="Gardenia", city="Eterna"),
    BadgeInfo(bit=2, name="Cobble Badge", leader="Maylene", city="Veilstone"),
    BadgeInfo(bit=3, name="Fen Badge", leader="Crasher Wake", city="Pastoria"),
    BadgeInfo(bit=4, name="Relic Badge", leader="Fantina", city="Hearthome"),
    BadgeInfo(bit=5, name="Mine Badge", leader="Byron", city="Canalave"),
    BadgeInfo(bit=6, name="Icicle Badge", leader="Candice", city="Snowpoint"),
    BadgeInfo(bit=7, name="Beacon Badge", leader="Volkner", city="Sunyshore"),
]

# Nature table (hardcoded, 25 entries)
NATURES: list[NatureInfo] = [
    NatureInfo(id=0, name="Hardy"),
    NatureInfo(id=1, name="Lonely", increased_stat="Attack", decreased_stat="Defense"),
    NatureInfo(id=2, name="Brave", increased_stat="Attack", decreased_stat="Speed"),
    NatureInfo(id=3, name="Adamant", increased_stat="Attack", decreased_stat="Sp. Attack"),
    NatureInfo(id=4, name="Naughty", increased_stat="Attack", decreased_stat="Sp. Defense"),
    NatureInfo(id=5, name="Bold", increased_stat="Defense", decreased_stat="Attack"),
    NatureInfo(id=6, name="Docile"),
    NatureInfo(id=7, name="Relaxed", increased_stat="Defense", decreased_stat="Speed"),
    NatureInfo(id=8, name="Impish", increased_stat="Defense", decreased_stat="Sp. Attack"),
    NatureInfo(id=9, name="Lax", increased_stat="Defense", decreased_stat="Sp. Defense"),
    NatureInfo(id=10, name="Timid", increased_stat="Speed", decreased_stat="Attack"),
    NatureInfo(id=11, name="Hasty", increased_stat="Speed", decreased_stat="Defense"),
    NatureInfo(id=12, name="Serious"),
    NatureInfo(id=13, name="Jolly", increased_stat="Speed", decreased_stat="Sp. Attack"),
    NatureInfo(id=14, name="Naive", increased_stat="Speed", decreased_stat="Sp. Defense"),
    NatureInfo(id=15, name="Modest", increased_stat="Sp. Attack", decreased_stat="Attack"),
    NatureInfo(id=16, name="Mild", increased_stat="Sp. Attack", decreased_stat="Defense"),
    NatureInfo(id=17, name="Quiet", increased_stat="Sp. Attack", decreased_stat="Speed"),
    NatureInfo(id=18, name="Bashful"),
    NatureInfo(id=19, name="Rash", increased_stat="Sp. Attack", decreased_stat="Sp. Defense"),
    NatureInfo(id=20, name="Calm", increased_stat="Sp. Defense", decreased_stat="Attack"),
    NatureInfo(id=21, name="Gentle", increased_stat="Sp. Defense", decreased_stat="Defense"),
    NatureInfo(id=22, name="Sassy", increased_stat="Sp. Defense", decreased_stat="Speed"),
    NatureInfo(id=23, name="Careful", increased_stat="Sp. Defense", decreased_stat="Sp. Attack"),
    NatureInfo(id=24, name="Quirky"),
]
