"""Battle state reader for Pokemon Platinum (US).

Detects whether the player is in a battle and reads enemy/active Pokemon data.

Key addresses:
- Battle indicator: 0x021D18F2 (fixed address, from pokebot-nds)
- Enemy Pokemon: via pointer chain from PID pointer (0x02101D2C)
- Player's active party Pokemon: from save block (already in memory.py)

The enemy Pokemon uses the same 236-byte encrypted structure as party Pokemon.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .crypto import decrypt_battle_stats, decrypt_blocks, unshuffle_blocks
from .models import (
    BattlePokemon,
    BattleState,
    Move,
)

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME

# Fixed address for battle detection (from pokebot-nds)
BATTLE_INDICATOR_ADDR = 0x021D18F2

# PID pointer base — used for enemy Pokemon access
PID_PTR_ADDR = 0x02101D2C
ENEMY_OFFSET = 0x58E3C  # Direct offset from PID base to first enemy Pokemon

# Trainer anchor pointer — alternative for reading foe data
TRAINER_ANCHOR_ADDR = 0x021C0794
FOE_ANCHOR_OFFSET = 0x217A8  # Deref anchor, then +0x217A8 → foe_anchor

# Battle-specific indicator values (from pokebot-nds)
BATTLE_VALUES = {0x41, 0x97, 0xC0}  # Wild, trainer, and variant battles

# Save block pointer (for reading player's active Pokemon)
SAVE_BLOCK_PTR_ADDR = 0x02101D40
SAVE_BLOCK_PTR_OFFSET = 0x14

# Pokemon structure size
POKEMON_SIZE = 0xEC  # 236 bytes


def _status_display(status: int) -> str:
    """Human-readable status string."""
    if status == 0:
        return "OK"
    conditions: list[str] = []
    sleep_turns = status & 0x07
    if sleep_turns:
        conditions.append(f"SLP({sleep_turns})")
    if status & 0x08:
        conditions.append("PSN")
    if status & 0x10:
        conditions.append("BRN")
    if status & 0x20:
        conditions.append("FRZ")
    if status & 0x40:
        conditions.append("PAR")
    if status & 0x80:
        conditions.append("TOX")
    return "/".join(conditions) if conditions else "OK"


class BattleReader:
    """Reads battle state from RAM."""

    def __init__(self, emu: DeSmuME) -> None:
        self._emu = emu
        self._species_table: dict[int, tuple[str, str, str | None]] = {}
        self._move_table: dict[int, tuple[str, str, int | None, int | None, int, str]] = {}
        self._ability_table: dict[int, str] = {}
        self._tables_loaded = False

    def _load_tables(self) -> None:
        """Lazy-load lookup tables."""
        if self._tables_loaded:
            return
        try:
            from .data.species import SPECIES
            self._species_table = SPECIES
        except ImportError:
            pass
        try:
            from .data.moves import MOVES
            self._move_table = MOVES
        except ImportError:
            pass
        try:
            from .data.abilities import ABILITIES
            self._ability_table = ABILITIES
        except ImportError:
            pass
        self._tables_loaded = True

    # === Low-level memory access ===

    def _read8(self, addr: int) -> int:
        return self._emu.memory.unsigned[addr]

    def _read16(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_short(addr)

    def _read32(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_long(addr)

    def _read_bytes(self, addr: int, count: int) -> bytes:
        return bytes([self._emu.memory.unsigned[addr + i] for i in range(count)])

    # === Battle detection ===

    def is_in_battle(self) -> bool:
        """Check if the player is currently in a battle.

        Reads the battle indicator byte at 0x021D18F2.
        Specific values indicate battle: 0x41 (wild), 0x97 (trainer), 0xC0 (variant).
        NOTE: This is a u8, not u16. Using read_short gives false positives.
        Source: pokebot-nds lua/helpers.lua update_foes()
        """
        try:
            value = self._read8(BATTLE_INDICATOR_ADDR)
            return value in BATTLE_VALUES
        except Exception:
            return False

    # === Battle state reading ===

    def read_battle_state(self) -> BattleState | None:
        """Read the current battle state. Returns None if not in battle."""
        if not self.is_in_battle():
            return None

        self._load_tables()

        # Try to read enemy Pokemon
        enemy = self._read_enemy_pokemon()

        # Read player's active Pokemon from party slot 0
        player = self._read_player_active()

        # Determine if wild or trainer battle
        # For now, default to wild — we'll refine with more research
        is_wild = True

        return BattleState(
            is_wild=is_wild,
            player_pokemon=player,
            enemy_pokemon=enemy,
        )

    def _read_enemy_pokemon(self) -> BattlePokemon | None:
        """Read the enemy's active Pokemon.

        Uses PokeLua/Real96 method: read32(0x02101D2C) + 0x58E3C
        gives the first enemy Pokemon directly (236-byte encrypted struct).
        Each additional enemy is 0xEC bytes further.

        Source: PokeLua Gen 4/DeSmuMe/Pt_RNG_DeSmuMe.lua
        """
        try:
            pid_base = self._read32(PID_PTR_ADDR)
            if pid_base < 0x02000000 or pid_base > 0x02FFFFFF:
                return None

            enemy_addr = pid_base + ENEMY_OFFSET
            return self._read_pokemon_at(enemy_addr)
        except Exception:
            return None

    def _read_player_active(self) -> BattlePokemon | None:
        """Read the player's active Pokemon from party slot 0."""
        try:
            ptr = self._read32(SAVE_BLOCK_PTR_ADDR)
            if ptr < 0x02000000 or ptr > 0x02FFFFFF:
                return None
            general = ptr + SAVE_BLOCK_PTR_OFFSET
            # Party starts at General + 0xA0, slot 0
            party_addr = general + 0x00A0
            return self._read_pokemon_at(party_addr)
        except Exception:
            return None

    def _read_pokemon_at(self, addr: int) -> BattlePokemon | None:
        """Read and decrypt a Pokemon at the given address."""
        raw = bytearray(self._read_bytes(addr, POKEMON_SIZE))

        pid = int.from_bytes(raw[0x00:0x04], "little")
        checksum = int.from_bytes(raw[0x06:0x08], "little")

        if pid == 0 and checksum == 0:
            return None

        # Decrypt using shared crypto module
        raw = decrypt_blocks(raw, checksum)
        raw = unshuffle_blocks(raw, pid)
        raw = decrypt_battle_stats(raw, pid)

        # Parse fields
        species_id = int.from_bytes(raw[0x08:0x0A], "little")
        ability_id = raw[0x15]

        # Moves
        moves: list[Move] = []
        for i in range(4):
            move_id = int.from_bytes(raw[0x28 + i * 2:0x2A + i * 2], "little")
            pp = raw[0x30 + i]
            if move_id != 0:
                move_name, move_type, move_power, _, move_pp_max, move_cat = (
                    self._move_table.get(move_id, (f"Move#{move_id}", "", None, None, 0, ""))
                )
                moves.append(Move(
                    id=move_id, name=move_name, type=move_type,
                    power=move_power, pp_current=pp, pp_max=move_pp_max,
                    category=move_cat,
                ))

        # Battle stats
        status = int.from_bytes(raw[0x88:0x8C], "little")
        level = raw[0x8C]
        hp_current = int.from_bytes(raw[0x8E:0x90], "little")
        hp_max = int.from_bytes(raw[0x90:0x92], "little")

        # Species lookup
        species_name = ""
        types: list[str] = []
        if species_id in self._species_table:
            sp = self._species_table[species_id]
            species_name = sp[0]
            types = [sp[1]]
            if sp[2]:
                types.append(sp[2])
        else:
            species_name = f"Pokemon#{species_id}"

        # Ability lookup
        ability_name = self._ability_table.get(ability_id, f"Ability#{ability_id}")

        # Shiny check (need TID/SID)
        try:
            save_ptr = self._read32(SAVE_BLOCK_PTR_ADDR)
            general = save_ptr + SAVE_BLOCK_PTR_OFFSET
            tid = self._read16(general + 0x0068 + 0x10)
            sid = self._read16(general + 0x0068 + 0x12)
            is_shiny = (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8
        except Exception:
            is_shiny = False

        return BattlePokemon(
            species_id=species_id,
            species_name=species_name,
            level=level if level > 0 else 1,
            hp_current=hp_current,
            hp_max=hp_max,
            types=types,
            status=status,
            status_name=_status_display(status),
            moves=moves,
            ability_name=ability_name,
            is_shiny=is_shiny,
        )
