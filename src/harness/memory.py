"""Memory reader for Pokemon Platinum (US).

Reads game state from RAM via py-desmume's memory interface.
All offsets are relative to the General save block, located at:
    General_start = read32(0x02101D40) + 0x14

Offset scheme confirmed against PKHeX SAV4Pt.cs / SAV4.cs source code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .crypto import decrypt_battle_stats, decrypt_blocks, decrypt_pokemon, unshuffle_blocks
from .data.chars import TERMINATOR, decode_gen4_string
from .models import (
    BADGES,
    NATURES,
    BadgeInfo,
    GameState,
    Move,
    Party,
    PlayerState,
    Pokemon,
)

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME

# The pointer at this address must be dereferenced to find the save block.
# General_start = read32(SAVE_BLOCK_PTR_ADDR) + SAVE_BLOCK_PTR_OFFSET
SAVE_BLOCK_PTR_ADDR = 0x02101D40
SAVE_BLOCK_PTR_OFFSET = 0x14

# PKHeX SAV4Pt.cs offsets (relative to General buffer start)
OFFSET_TRAINER1 = 0x0068      # Trainer info block
OFFSET_PARTY = 0x00A0         # Party Pokemon data (6 × 236 bytes)
OFFSET_PARTY_COUNT = 0x009C   # Number of Pokemon in party (u8)
OFFSET_MAP_ID = 0x1280        # Current map/location ID (u16)
OFFSET_X = 0x1288             # Player X coordinate (u16)
OFFSET_Y = 0x128C             # Player Y coordinate (u16)
OFFSET_RIVAL_NAME = 0x27E8    # Rival's name (8 × u16)

# Trainer1-relative offsets (from SAV4.cs)
TR_NAME = 0x00         # 16 bytes (8 × u16 Gen4-encoded)
TR_TID = 0x10          # u16
TR_SID = 0x12          # u16
TR_MONEY = 0x14        # u32
TR_GENDER = 0x18       # u8 (0=Male, 1=Female)
TR_BADGES = 0x1A       # u8 bitfield
TR_PLAYTIME_HOURS = 0x22  # u16
TR_PLAYTIME_MINS = 0x24  # u8
TR_PLAYTIME_SECS = 0x25  # u8

# Pokemon data structure size
POKEMON_SIZE = 0xEC  # 236 bytes


class MemoryReader:
    """Reads structured game state from Platinum's RAM."""

    def __init__(self, emu: DeSmuME) -> None:
        self._emu = emu
        self._general: int = 0  # cached General buffer address
        self._species_table: dict[int, tuple[str, str, str | None]] = {}
        self._move_table: dict[int, tuple[str, str, int | None, int | None, int, str]] = {}
        self._item_table: dict[int, str] = {}
        self._ability_table: dict[int, str] = {}
        self._tables_loaded = False

    def _load_tables(self) -> None:
        """Lazy-load lookup tables on first use."""
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
            from .data.items import ITEMS
            self._item_table = ITEMS
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

    def _read_gen4_string(self, addr: int, max_chars: int = 8) -> str:
        """Read a Gen 4 encoded string from memory."""
        codes: list[int] = []
        for i in range(max_chars):
            code = self._read16(addr + i * 2)
            codes.append(code)
            if code == TERMINATOR:
                break
        return decode_gen4_string(codes)

    # === General buffer location ===

    def _refresh_general(self) -> int:
        """Dereference the save block pointer to find General buffer start.

        Must be called each time before reading, as the pointer can change
        (e.g., after map transitions, battle overlays, etc.).
        """
        ptr = self._read32(SAVE_BLOCK_PTR_ADDR)
        if ptr < 0x02000000 or ptr > 0x02FFFFFF:
            raise RuntimeError(
                f"Save block pointer out of range: 0x{ptr:08X}. "
                "Game may not be fully loaded."
            )
        self._general = ptr + SAVE_BLOCK_PTR_OFFSET
        return self._general

    @property
    def general(self) -> int:
        """Address of the General save buffer in RAM."""
        if self._general == 0:
            self._refresh_general()
        return self._general

    # === Player state ===

    def read_player(self) -> PlayerState:
        """Read current player/trainer state."""
        g = self._refresh_general()
        t1 = g + OFFSET_TRAINER1
        self._load_tables()

        # Player name — try save block first, fall back to empty
        name = self._read_gen4_string(t1 + TR_NAME)

        # Core trainer data
        tid = self._read16(t1 + TR_TID)
        sid = self._read16(t1 + TR_SID)
        money = self._read32(t1 + TR_MONEY)
        gender = self._read8(t1 + TR_GENDER)
        badge_bits = self._read8(t1 + TR_BADGES)

        # Play time
        hours = self._read16(t1 + TR_PLAYTIME_HOURS)
        minutes = self._read8(t1 + TR_PLAYTIME_MINS)
        seconds = self._read8(t1 + TR_PLAYTIME_SECS)

        # Position
        map_id = self._read16(g + OFFSET_MAP_ID)
        x = self._read16(g + OFFSET_X)
        y = self._read16(g + OFFSET_Y)

        # Party count
        party_count = self._read8(g + OFFSET_PARTY_COUNT)
        if party_count > 6:
            party_count = 0  # sanity check

        # Decode badges
        badge_list: list[str] = []
        for badge in BADGES:
            if badge_bits & (1 << badge.bit):
                badge_list.append(badge.name)

        # Map name lookup (use map header table, NOT met-location table)
        map_name = ""
        try:
            from .data.map_headers import get_map_name
            map_name = get_map_name(map_id)
        except ImportError:
            map_name = f"Map #{map_id}"

        return PlayerState(
            name=name,
            trainer_id=tid,
            secret_id=sid,
            money=money,
            gender=gender,
            gender_name="Male" if gender == 0 else "Female",
            badges=badge_bits,
            badge_count=len(badge_list),
            badge_list=badge_list,
            play_hours=hours,
            play_minutes=minutes,
            play_seconds=seconds,
            map_id=map_id,
            map_name=map_name,
            x=x,
            y=y,
            party_count=party_count,
        )

    # === Party Pokemon ===

    def read_party(self) -> Party:
        """Read all party Pokemon."""
        g = self._refresh_general()
        self._load_tables()

        count = self._read8(g + OFFSET_PARTY_COUNT)
        if count > 6:
            count = 0

        pokemon_list: list[Pokemon] = []
        for slot in range(count):
            try:
                pkmn = self._read_party_pokemon(slot)
                if pkmn is not None:
                    pokemon_list.append(pkmn)
            except Exception:
                # Skip unreadable slots rather than crash
                continue

        return Party(count=count, pokemon=pokemon_list)

    def _read_party_pokemon(self, slot: int) -> Pokemon | None:
        """Read and decrypt a single party Pokemon from the save block."""
        g = self._general
        addr = g + OFFSET_PARTY + (slot * POKEMON_SIZE)

        # Read raw 236 bytes
        raw = bytearray(self._read_bytes(addr, POKEMON_SIZE))

        # Unencrypted header
        pid = int.from_bytes(raw[0x00:0x04], "little")
        checksum = int.from_bytes(raw[0x06:0x08], "little")

        # Skip empty slots
        if pid == 0 and checksum == 0:
            return None

        # Full decryption pipeline (shared crypto module)
        raw = decrypt_blocks(raw, checksum)
        raw = unshuffle_blocks(raw, pid)
        raw = decrypt_battle_stats(raw, pid)

        # Parse fields
        species_id = int.from_bytes(raw[0x08:0x0A], "little")
        held_item_id = int.from_bytes(raw[0x0A:0x0C], "little")
        experience = int.from_bytes(raw[0x10:0x14], "little")
        ability_id = raw[0x15]

        # EVs
        evs = {
            "hp": raw[0x18], "attack": raw[0x19], "defense": raw[0x1A],
            "speed": raw[0x1B], "sp_attack": raw[0x1C], "sp_defense": raw[0x1D],
        }

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

        # IVs (packed in 32-bit value at 0x38)
        iv_word = int.from_bytes(raw[0x38:0x3C], "little")
        ivs = {
            "hp": iv_word & 0x1F,
            "attack": (iv_word >> 5) & 0x1F,
            "defense": (iv_word >> 10) & 0x1F,
            "speed": (iv_word >> 15) & 0x1F,
            "sp_attack": (iv_word >> 20) & 0x1F,
            "sp_defense": (iv_word >> 25) & 0x1F,
        }
        is_egg = bool(iv_word & (1 << 30))

        # Nickname (block C, offset 0x48)
        nick_codes: list[int] = []
        for i in range(11):
            c = int.from_bytes(raw[0x48 + i * 2:0x4A + i * 2], "little")
            nick_codes.append(c)
            if c == TERMINATOR:
                break
        nickname = decode_gen4_string(nick_codes)

        # Battle stats (decrypted)
        status = int.from_bytes(raw[0x88:0x8C], "little")
        level = raw[0x8C]
        hp_current = int.from_bytes(raw[0x8E:0x90], "little")
        hp_max = int.from_bytes(raw[0x90:0x92], "little")
        attack = int.from_bytes(raw[0x92:0x94], "little")
        defense = int.from_bytes(raw[0x94:0x96], "little")
        speed = int.from_bytes(raw[0x96:0x98], "little")
        sp_attack = int.from_bytes(raw[0x98:0x9A], "little")
        sp_defense = int.from_bytes(raw[0x9A:0x9C], "little")

        # Nature (derived from PID)
        nature_id = pid % 25
        nature = NATURES[nature_id] if nature_id < len(NATURES) else None

        # Shiny check
        tid = self._read16(self._general + OFFSET_TRAINER1 + TR_TID)
        sid = self._read16(self._general + OFFSET_TRAINER1 + TR_SID)
        is_shiny = (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8

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

        # Ability & item lookup
        ability_name = self._ability_table.get(ability_id, f"Ability#{ability_id}")
        held_item_name = self._item_table.get(held_item_id, "") if held_item_id else ""

        pkmn = Pokemon(
            slot=slot,
            species_id=species_id,
            species_name=species_name,
            nickname=nickname if nickname else species_name,
            level=level if level > 0 else 1,
            hp_current=hp_current,
            hp_max=hp_max,
            attack=attack,
            defense=defense,
            speed=speed,
            sp_attack=sp_attack,
            sp_defense=sp_defense,
            moves=moves,
            ability_id=ability_id,
            ability_name=ability_name,
            nature=nature,
            held_item_id=held_item_id,
            held_item_name=held_item_name,
            experience=experience,
            status=status,
            status_name="OK",
            is_egg=is_egg,
            is_shiny=is_shiny,
            pid=pid,
            evs=evs,
            ivs=ivs,
            types=types,
        )
        pkmn.status_name = pkmn.status_display()
        return pkmn

    # === Full state ===

    def read_state(self) -> GameState:
        """Read the complete game state."""
        player = self.read_player()
        party = self.read_party()
        return GameState(player=player, party=party)
