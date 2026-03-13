"""Inventory/bag reader for Pokemon Platinum (US).

Reads all seven bag pockets from the General save block.
Each item slot is 4 bytes: u16 item_id + u16 quantity.

Offsets from PKHeX PlayerBag4Pt / InventoryPouch definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .models import Inventory, InventoryItem, InventoryPocket

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME


@dataclass(frozen=True)
class PocketDef:
    """Definition of a bag pocket: name, offset from General, max slots."""
    name: str
    offset: int
    max_slots: int


# Platinum bag pocket definitions.
# All offsets are relative to the General save buffer start.
# Base offset for the bag is General + 0x630, then each pocket has
# an additional offset from that base.
#
# Source: PKHeX PlayerBag4Pt / InventoryPouch4 (verified against source).
#
# Each slot is 4 bytes: u16 item_id (LE) + u16 quantity (LE).
# Empty slots have item_id == 0.
BAG_BASE_OFFSET = 0x0630

POCKET_DEFS: list[PocketDef] = [
    PocketDef(name="Items",        offset=BAG_BASE_OFFSET + 0x000, max_slots=207),
    PocketDef(name="Key Items",    offset=BAG_BASE_OFFSET + 0x294, max_slots=40),
    PocketDef(name="TMs & HMs",    offset=BAG_BASE_OFFSET + 0x35C, max_slots=100),
    PocketDef(name="Mail",         offset=BAG_BASE_OFFSET + 0x4EC, max_slots=12),
    PocketDef(name="Medicine",     offset=BAG_BASE_OFFSET + 0x51C, max_slots=38),
    PocketDef(name="Berries",      offset=BAG_BASE_OFFSET + 0x5BC, max_slots=64),
    PocketDef(name="Poke Balls",   offset=BAG_BASE_OFFSET + 0x6BC, max_slots=15),
    PocketDef(name="Battle Items", offset=BAG_BASE_OFFSET + 0x6F8, max_slots=13),
]


class InventoryReader:
    """Reads the player's bag contents from RAM."""

    def __init__(self, emu: DeSmuME) -> None:
        self._emu = emu
        self._item_table: dict[int, str] = {}
        self._loaded = False

    def _load_items(self) -> None:
        """Lazy-load item name table."""
        if self._loaded:
            return
        try:
            from .data.items import ITEMS
            self._item_table = ITEMS
        except ImportError:
            pass
        self._loaded = True

    def _read16(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_short(addr)

    def _read32(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_long(addr)

    def _get_general(self) -> int:
        """Dereference the save block pointer to get General buffer start."""
        ptr = self._read32(0x02101D40)
        if ptr < 0x02000000 or ptr > 0x02FFFFFF:
            raise RuntimeError(
                f"Save block pointer out of range: 0x{ptr:08X}. "
                "Game may not be fully loaded."
            )
        return ptr + 0x14

    def read_inventory(self) -> Inventory:
        """Read all bag pockets."""
        self._load_items()
        general = self._get_general()

        pockets: dict[str, InventoryPocket] = {}
        for pocket_def in POCKET_DEFS:
            pocket = self._read_pocket(general, pocket_def)
            pockets[pocket_def.name] = pocket

        return Inventory(pockets=pockets)

    def _read_pocket(self, general: int, pocket_def: PocketDef) -> InventoryPocket:
        """Read a single bag pocket."""
        items: list[InventoryItem] = []
        base = general + pocket_def.offset

        for slot in range(pocket_def.max_slots):
            addr = base + (slot * 4)
            item_id = self._read16(addr)
            quantity = self._read16(addr + 2)

            # Empty slot — stop reading this pocket
            if item_id == 0:
                break

            item_name = self._item_table.get(item_id, f"Item#{item_id}")
            items.append(InventoryItem(
                item_id=item_id,
                item_name=item_name,
                quantity=quantity,
            ))

        return InventoryPocket(name=pocket_def.name, items=items)

    def read_pocket_by_name(self, name: str) -> InventoryPocket | None:
        """Read a specific pocket by name."""
        self._load_items()
        general = self._get_general()

        for pocket_def in POCKET_DEFS:
            if pocket_def.name == name:
                return self._read_pocket(general, pocket_def)
        return None
