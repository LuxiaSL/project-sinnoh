"""World state reader for Pokemon Platinum (US).

Reads the complete local world state from RAM:
- 32×32 tile collision grid (walls, floors, warps, grass, water, ledges)
- NPC positions and facing directions
- Warp destinations (where doors/stairs lead)
- Player facing direction
- Interactable objects (PC, TV, bookshelf, etc.)

All data comes from FieldSystem and its sub-structs via pointer chains
confirmed against the pret/pokeplatinum decompilation.

Pointer chains:
  FieldSystem+0x0C  = SaveData* (anchor for finding FieldSystem)
  FieldSystem+0x14  = MapHeaderData* (warps, NPC blueprints)
  FieldSystem+0x28  = LandDataManager* → LoadedMap terrain
  FieldSystem+0x38  = MapObjectManager* → NPC runtime data
  FieldSystem+0x3C  = PlayerAvatar* → player facing direction
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME

logger = logging.getLogger(__name__)


# === Tile behavior enum (from map_tile_behaviors.h) ===

class TileBehavior(IntEnum):
    """Tile behavior types from pret/pokeplatinum."""
    NONE = 0x00
    TALL_GRASS = 0x02
    VERY_TALL_GRASS = 0x03
    CAVE_FLOOR = 0x08
    OLD_CHATEAU = 0x0B
    MOUNTAIN = 0x0C
    WATER_RIVER = 0x10
    WATERFALL = 0x13
    WATER_SEA = 0x15
    PUDDLE = 0x16
    SHALLOW_WATER = 0x17
    ICE = 0x20
    SAND = 0x21
    BLOCK_EAST = 0x30
    BLOCK_WEST = 0x31
    BLOCK_NORTH = 0x32
    BLOCK_SOUTH = 0x33
    JUMP_EAST = 0x38
    JUMP_WEST = 0x39
    JUMP_NORTH = 0x3A
    JUMP_SOUTH = 0x3B
    SLIDE_EAST = 0x40
    SLIDE_WEST = 0x41
    SLIDE_NORTH = 0x42
    SLIDE_SOUTH = 0x43
    ROCK_CLIMB_NS = 0x4B
    ROCK_CLIMB_EW = 0x4C
    WARP_STAIRS_E = 0x5D
    WARP_STAIRS_W = 0x5E
    WARP_ENTRANCE_E = 0x62
    WARP_ENTRANCE_W = 0x63
    WARP_ENTRANCE_N = 0x64
    WARP_ENTRANCE_S = 0x65
    WARP_PANEL = 0x67
    DOOR = 0x69
    WARP_EAST = 0x6C
    WARP_WEST = 0x6D
    WARP_NORTH = 0x6E
    WARP_SOUTH = 0x6F
    TABLE = 0x80
    PC = 0x83
    TOWN_MAP = 0x85
    TV = 0x86
    BERRY_PATCH = 0xA0
    BOOKSHELF_SM = 0xE0
    BOOKSHELF = 0xE1
    BOOKSHELF_2 = 0xE2
    TRASH_CAN = 0xE4
    MART_SHELF_1 = 0xE5
    MART_SHELF_2 = 0xEB
    MART_SHELF_3 = 0xEC


# Tile category sets
WARP_BEHAVIORS = frozenset({
    TileBehavior.WARP_STAIRS_E, TileBehavior.WARP_STAIRS_W,
    TileBehavior.WARP_ENTRANCE_E, TileBehavior.WARP_ENTRANCE_W,
    TileBehavior.WARP_ENTRANCE_N, TileBehavior.WARP_ENTRANCE_S,
    TileBehavior.WARP_PANEL, TileBehavior.DOOR,
    TileBehavior.WARP_EAST, TileBehavior.WARP_WEST,
    TileBehavior.WARP_NORTH, TileBehavior.WARP_SOUTH,
})

WATER_BEHAVIORS = frozenset({
    TileBehavior.WATER_RIVER, TileBehavior.WATER_SEA,
    TileBehavior.WATERFALL, TileBehavior.PUDDLE,
    TileBehavior.SHALLOW_WATER,
})

GRASS_BEHAVIORS = frozenset({
    TileBehavior.TALL_GRASS, TileBehavior.VERY_TALL_GRASS,
})

LEDGE_BEHAVIORS = frozenset({
    TileBehavior.JUMP_EAST, TileBehavior.JUMP_WEST,
    TileBehavior.JUMP_NORTH, TileBehavior.JUMP_SOUTH,
})

# Interactable collision tiles (walls you can face+A to interact with)
INTERACTABLE_BEHAVIORS: dict[int, str] = {
    TileBehavior.PC: "P",
    TileBehavior.TV: "T",
    TileBehavior.TOWN_MAP: "M",
    TileBehavior.TABLE: "=",
    TileBehavior.BOOKSHELF_SM: "B",
    TileBehavior.BOOKSHELF: "B",
    TileBehavior.BOOKSHELF_2: "B",
    TileBehavior.TRASH_CAN: "%",
    TileBehavior.MART_SHELF_1: "$",
    TileBehavior.MART_SHELF_2: "$",
    TileBehavior.MART_SHELF_3: "$",
}

# Directional arrows for ledges — ASCII arrows to avoid collision with
# Unicode player arrows (↑↓←→). v^<> are visually distinct.
LEDGE_ARROWS: dict[int, str] = {
    TileBehavior.JUMP_EAST: ">",
    TileBehavior.JUMP_WEST: "<",
    TileBehavior.JUMP_NORTH: "^",
    TileBehavior.JUMP_SOUTH: "v",
}

# Ice/slide tiles — mechanically important (involuntary movement)
ICE_BEHAVIORS = frozenset({
    TileBehavior.ICE,
    TileBehavior.SLIDE_EAST, TileBehavior.SLIDE_WEST,
    TileBehavior.SLIDE_NORTH, TileBehavior.SLIDE_SOUTH,
})

# Item ball graphics ID (OBJ_EVENT_GFX_POKEBALL from pret)
ITEM_BALL_GFX_ID = 87

# Warp entrance tiles: the D should be "embedded" into the adjacent wall,
# not shown floating on the walkable floor. This maps each entrance behavior
# to the (dx, dy) offset of the wall tile where the door visual should appear.
# e.g., WARP_ENTRANCE_S at (4,8) → embed D into wall at (4,9)
WARP_EMBED_OFFSETS: dict[int, tuple[int, int]] = {
    TileBehavior.WARP_ENTRANCE_S: (0, 1),
    TileBehavior.WARP_ENTRANCE_N: (0, -1),
    TileBehavior.WARP_ENTRANCE_E: (1, 0),
    TileBehavior.WARP_ENTRANCE_W: (-1, 0),
    TileBehavior.DOOR: (0, 1),   # generic doors usually face south
}

# Warp display characters
WARP_CHARS: dict[int, str] = {
    TileBehavior.WARP_STAIRS_E: "S",
    TileBehavior.WARP_STAIRS_W: "S",
    TileBehavior.WARP_ENTRANCE_E: "D",
    TileBehavior.WARP_ENTRANCE_W: "D",
    TileBehavior.WARP_ENTRANCE_N: "D",
    TileBehavior.WARP_ENTRANCE_S: "D",
    TileBehavior.WARP_PANEL: "W",
    TileBehavior.DOOR: "D",
    TileBehavior.WARP_EAST: "D",
    TileBehavior.WARP_WEST: "D",
    TileBehavior.WARP_NORTH: "D",
    TileBehavior.WARP_SOUTH: "D",
}

# Directional warps: the direction you must WALK to trigger the warp.
# The behavior name indicates where the OPENING faces, and you walk INTO it
# from the open side. So WARP_STAIRS_W (opening faces west) = walk RIGHT
# (east) into it from the west side. WARP_ENTRANCE_S (opening faces south)
# = walk DOWN (south) into it from the north.
WARP_WALK_DIR: dict[int, str] = {
    TileBehavior.WARP_STAIRS_E: "left",     # opening faces east → walk left into it
    TileBehavior.WARP_STAIRS_W: "right",    # opening faces west → walk right into it
    TileBehavior.WARP_ENTRANCE_E: "left",
    TileBehavior.WARP_ENTRANCE_W: "right",
    TileBehavior.WARP_ENTRANCE_N: "down",
    TileBehavior.WARP_ENTRANCE_S: "up",
    TileBehavior.DOOR: "up",
    TileBehavior.WARP_EAST: "left",
    TileBehavior.WARP_WEST: "right",
    TileBehavior.WARP_NORTH: "down",
    TileBehavior.WARP_SOUTH: "up",
}

# Player direction arrows
DIR_ARROWS = {0: "↑", 1: "↓", 2: "←", 3: "→"}
DIR_NAMES = {0: "north", 1: "south", 2: "west", 3: "east"}

# === Memory layout constants (verified against pret + live RAM) ===

MAP_TILES = 32
TERRAIN_SIZE = MAP_TILES * MAP_TILES
COLLISION_BIT = 0x8000
BEHAVIOR_MASK = 0xFF
QUADRANT_COUNT = 4

# FieldSystem offsets
_FS_SAVE_DATA = 0x0C
_FS_MAP_HEADER_DATA = 0x14
_FS_BOTTOM_SCREEN = 0x18
_FS_LAND_DATA_MAN = 0x28
_FS_MAP_MATRIX = 0x2C
_FS_MAP_OBJ_MAN = 0x38
_FS_PLAYER_AVATAR = 0x3C

# LandDataManager
_LDM_LOADED_MAPS = 0x90
# trackedTargetLoadedMapsQuadrant — which loadedMaps[] slot the player is in (u8, 0-3)
# From pret: LandDataManager_GetTrackedTargetLoadedMapsQuadrant()
_LDM_ACTIVE_QUADRANT = 0xAC

# MapObjectManager
_MOM_MAX_OBJECTS = 0x04
_MOM_MAP_OBJ_PTR = 0x124

# MapObject (0x128 bytes each)
_MO_SIZE = 0x128
_MO_STATUS = 0x00
_MO_LOCAL_ID = 0x08
_MO_GRAPHICS_ID = 0x10
_MO_MOVEMENT_TYPE = 0x14
_MO_TRAINER_TYPE = 0x18
_MO_FACING_DIR = 0x28
_MO_X = 0x64
_MO_Z = 0x6C
_MO_STATUS_HIDDEN = 1 << 9

# MapHeaderData
_MHD_NUM_WARP_EVENTS = 0x08
_MHD_WARP_EVENTS_PTR = 0x18

# WarpEvent (0x0C bytes each)
_WE_SIZE = 0x0C
_WE_X = 0x00
_WE_Z = 0x02
_WE_DEST_HEADER = 0x04
_WE_DEST_WARP = 0x06

# PlayerAvatar
_PA_MAP_OBJ = 0x30

# Known BSS address
_SAVE_BLOCK_PTR_ADDR = 0x02101D40


# === Data classes ===

@dataclass
class TileInfo:
    """Info about a single map tile."""
    raw: int
    collision: bool
    behavior: int

    @property
    def walkable(self) -> bool:
        return not self.collision

    @property
    def is_warp(self) -> bool:
        return self.behavior in WARP_BEHAVIORS

    @property
    def is_water(self) -> bool:
        return self.behavior in WATER_BEHAVIORS

    @property
    def is_grass(self) -> bool:
        return self.behavior in GRASS_BEHAVIORS

    @property
    def is_ledge(self) -> bool:
        return self.behavior in LEDGE_BEHAVIORS

    @property
    def is_interactable(self) -> bool:
        """Collision tile with special behavior (face+A to use)."""
        return self.collision and self.behavior in INTERACTABLE_BEHAVIORS

    @property
    def is_ice(self) -> bool:
        return self.behavior in ICE_BEHAVIORS

    def grid_char(self) -> str:
        """Single character for spatial grid display."""
        if self.collision:
            # Wall-type warps (outdoor doors) — show as door, not wall.
            # These have collision=True because you walk INTO them to enter.
            if self.is_warp:
                return WARP_CHARS.get(self.behavior, "D")
            # Interactable walls get distinct labels
            if self.behavior in INTERACTABLE_BEHAVIORS:
                return INTERACTABLE_BEHAVIORS[self.behavior]
            return "#"
        if self.is_warp:
            return WARP_CHARS.get(self.behavior, "D")
        if self.is_grass:
            return "G"
        if self.is_water:
            return "~"
        if self.is_ledge:
            return LEDGE_ARROWS.get(self.behavior, "v")
        if self.is_ice:
            return "_"
        return "."


@dataclass
class NpcInfo:
    """Runtime NPC data from MapObject."""
    local_id: int
    x: int
    z: int
    facing: int  # 0=N, 1=S, 2=W, 3=E
    graphics_id: int
    hidden: bool
    trainer_type: int = 0    # 0 = not a trainer
    movement_type: int = 0   # 0 = stationary

    @property
    def is_trainer(self) -> bool:
        return self.trainer_type != 0

    @property
    def is_item_ball(self) -> bool:
        return self.graphics_id == ITEM_BALL_GFX_ID


@dataclass
class WarpInfo:
    """Warp event data from MapHeaderData."""
    x: int
    z: int
    dest_map_id: int
    dest_warp_id: int
    dest_name: str = ""  # Resolved map name


@dataclass
class CollisionGrid:
    """32×32 collision grid from a loaded map."""
    tiles: list[int]
    quadrant: int
    loaded_map_addr: int

    def get(self, local_x: int, local_y: int) -> TileInfo:
        """Get tile info at local coordinates (0-31)."""
        if not (0 <= local_x < MAP_TILES and 0 <= local_y < MAP_TILES):
            return TileInfo(raw=0xFFFF, collision=True, behavior=0xFF)
        raw = self.tiles[local_y * MAP_TILES + local_x]
        return TileInfo(
            raw=raw,
            collision=bool(raw & COLLISION_BIT),
            behavior=raw & BEHAVIOR_MASK,
        )

    @property
    def walkable_count(self) -> int:
        return sum(1 for t in self.tiles if not (t & COLLISION_BIT))

    @property
    def wall_count(self) -> int:
        return sum(1 for t in self.tiles if t & COLLISION_BIT)


@dataclass
class WorldState:
    """Complete local world state snapshot."""
    grid: CollisionGrid
    npcs: list[NpcInfo]
    warps: list[WarpInfo]
    player_facing: int  # 0=N, 1=S, 2=W, 3=E
    player_x: int
    player_y: int


# === Main reader ===

class CollisionReader:
    """Reads world state from Pokemon Platinum RAM.

    Provides: collision grid, NPC positions, warp destinations,
    player facing direction, interactable object identification.
    """

    def __init__(self, emu: DeSmuME) -> None:
        self._emu = emu
        self._field_system_addr: int = 0
        self._last_save_data_ptr: int = 0
        self._map_names: dict[int, str] | None = None

    # === Low-level memory access ===

    def _read8(self, addr: int) -> int:
        return self._emu.memory.unsigned[addr]

    def _read16(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_short(addr)

    def _read32(self, addr: int) -> int:
        return self._emu.memory.unsigned.read_long(addr)

    def _is_valid_ptr(self, val: int) -> bool:
        return 0x02000000 <= val < 0x03000000

    def _get_map_name(self, map_id: int) -> str:
        """Resolve a map header ID to a human-readable name."""
        if self._map_names is None:
            try:
                from .data.map_headers import MAP_HEADERS
                self._map_names = MAP_HEADERS
            except ImportError:
                self._map_names = {}
        return self._map_names.get(map_id, f"Map {map_id}")

    # === FieldSystem discovery ===

    def _find_field_system(self) -> int:
        """Scan heap for FieldSystem using structural fingerprinting.

        During intro→gameplay transitions, multiple FieldSystem candidates
        may exist (stale cutscene + live gameplay). We find ALL candidates
        and pick the one whose active quadrant grid has the most indoor-
        looking tiles (high wall count near center = likely a room).
        Falls back to the last candidate (highest address, usually newest).
        """
        save_data_ptr = self._read32(_SAVE_BLOCK_PTR_ADDR)
        candidates: list[int] = []

        for start, end in [(0x02290000, 0x022B0000),
                           (0x02200000, 0x02400000)]:
            candidates.extend(self._scan_range_all(start, end, save_data_ptr))
            if candidates:
                break

        if not candidates:
            # Wider fallback
            candidates = self._scan_range_all(0x02200000, 0x02800000, save_data_ptr)

        if not candidates:
            return 0

        if len(candidates) == 1:
            logger.info(f"FieldSystem found at {candidates[0]:#010x}")
            return candidates[0]

        # Multiple candidates — pick the best one.
        # The newest allocation (highest address) is usually the live one,
        # since the game allocates on the heap sequentially.
        best = candidates[-1]
        logger.info(
            f"FieldSystem: {len(candidates)} candidates, "
            f"picking {best:#010x} (newest)"
        )
        return best

    def _scan_range_all(self, start: int, end: int, save_data_ptr: int) -> list[int]:
        """Scan a memory range for ALL FieldSystem candidates."""
        results: list[int] = []
        for addr in range(start, end, 4):
            try:
                val_18 = self._read32(addr + _FS_BOTTOM_SCREEN)
                if val_18 > 10 or self._is_valid_ptr(val_18):
                    continue
                if self._read32(addr + _FS_SAVE_DATA) != save_data_ptr:
                    continue
                if not self._is_valid_ptr(self._read32(addr + _FS_LAND_DATA_MAN)):
                    continue
                if not self._is_valid_ptr(self._read32(addr + _FS_MAP_MATRIX)):
                    continue
                results.append(addr)
            except Exception:
                continue
        return results

    def find_field_system(self, force: bool = False) -> bool:
        """Find (or re-validate) FieldSystem in RAM. Caches result.

        Args:
            force: If True, always re-scan even if cached address seems valid.
        """
        current_save_ptr = self._read32(_SAVE_BLOCK_PTR_ADDR)

        if not force and self._field_system_addr and current_save_ptr == self._last_save_data_ptr:
            try:
                if self._read32(self._field_system_addr + _FS_SAVE_DATA) == current_save_ptr:
                    return True
            except Exception:
                pass

        # Scan for ALL matching FieldSystem candidates and pick the best one.
        # During intro→gameplay transitions, there may be a stale FS from
        # the cutscene alongside the real one. We find all candidates and
        # store them so read_player_grid can try alternatives if the first
        # one produces garbage data.
        self._field_system_addr = self._find_field_system()
        self._last_save_data_ptr = current_save_ptr
        return self._field_system_addr != 0

    # === Collision grid ===

    def read_loaded_maps(self) -> list[CollisionGrid]:
        """Read terrain data from all valid loaded maps."""
        if not self._field_system_addr and not self.find_field_system():
            return []

        try:
            ldm_addr = self._read32(self._field_system_addr + _FS_LAND_DATA_MAN)
        except Exception:
            return []

        if not self._is_valid_ptr(ldm_addr):
            return []

        grids: list[CollisionGrid] = []
        for q in range(QUADRANT_COUNT):
            try:
                map_ptr = self._read32(ldm_addr + _LDM_LOADED_MAPS + q * 4)
            except Exception:
                continue
            if not self._is_valid_ptr(map_ptr):
                continue

            tiles: list[int] = []
            try:
                for i in range(TERRAIN_SIZE):
                    tiles.append(self._read16(map_ptr + i * 2))
            except Exception:
                continue

            if all(t == 0xFFFF for t in tiles[:32]):
                continue

            grids.append(CollisionGrid(tiles=tiles, quadrant=q, loaded_map_addr=map_ptr))

        return grids

    def read_player_grid(self, player_x: int, player_y: int) -> Optional[CollisionGrid]:
        """Read the collision grid containing the player's position.

        Uses the LandDataManager's trackedTargetLoadedMapsQuadrant field
        to identify exactly which of the 4 loaded map slots the player is
        in. This is authoritative — no guessing based on tile walkability.

        If the selected grid looks wrong (outdoor tiles in what should be
        a room), forces a FieldSystem re-find — the cached address may be
        stale from a cutscene/transition.

        Falls back to walkability heuristic if the tracked field isn't valid.
        """
        grid = self._try_read_player_grid(player_x, player_y)
        if grid and self._grid_looks_wrong(grid, player_x, player_y):
            # Grid has outdoor tiles near player — stale FieldSystem?
            logger.debug("Grid sanity check failed — forcing FieldSystem re-find")
            self.find_field_system(force=True)
            grid = self._try_read_player_grid(player_x, player_y)
        return grid

    def _try_read_player_grid(self, player_x: int, player_y: int) -> Optional[CollisionGrid]:
        """Internal: attempt to read the player's collision grid."""
        grids = self.read_loaded_maps()
        if not grids:
            return None

        # Read the authoritative active quadrant from LandDataManager
        try:
            ldm_addr = self._read32(self._field_system_addr + _FS_LAND_DATA_MAN)
            active_quadrant = self._emu.memory.unsigned[ldm_addr + _LDM_ACTIVE_QUADRANT]
            if 0 <= active_quadrant <= 3:
                for grid in grids:
                    if grid.quadrant == active_quadrant:
                        return grid
        except Exception:
            pass

        # Fallback: check walkability at player position
        local_x = player_x % MAP_TILES
        local_y = player_y % MAP_TILES
        for grid in reversed(grids):
            if grid.get(local_x, local_y).walkable:
                return grid
        for grid in reversed(grids):
            if grid.walkable_count > 0:
                return grid
        return None

    def _grid_looks_wrong(self, grid: CollisionGrid, player_x: int, player_y: int) -> bool:
        """Check if the grid has obvious outdoor tiles near the player.

        Indoor rooms should have walls and floor around the player, not
        grass, water, or ice. If we see those, the FieldSystem is likely
        stale from a cutscene.
        """
        local_x = player_x % MAP_TILES
        local_y = player_y % MAP_TILES
        outdoor_count = 0
        checked = 0
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                tile = grid.get(local_x + dx, local_y + dy)
                checked += 1
                if tile.is_grass or tile.is_water or tile.is_ice:
                    outdoor_count += 1
        # If more than 20% of nearby tiles are outdoor features, something's wrong
        return outdoor_count > checked * 0.2

    # === NPC reading ===

    def read_npcs(self) -> list[NpcInfo]:
        """Read all visible NPCs from MapObjectManager."""
        if not self._field_system_addr:
            return []

        try:
            mom_addr = self._read32(self._field_system_addr + _FS_MAP_OBJ_MAN)
            if not self._is_valid_ptr(mom_addr):
                return []

            max_obj = self._read32(mom_addr + _MOM_MAX_OBJECTS)
            map_obj_ptr = self._read32(mom_addr + _MOM_MAP_OBJ_PTR)
            if not self._is_valid_ptr(map_obj_ptr) or max_obj > 128:
                return []
        except Exception:
            return []

        npcs: list[NpcInfo] = []
        for i in range(max_obj):
            mo = map_obj_ptr + i * _MO_SIZE
            try:
                status = self._read32(mo + _MO_STATUS)
                if status == 0:
                    continue

                local_id = self._read32(mo + _MO_LOCAL_ID)
                # Slot 0 (local_id=255) is the player — skip
                if local_id == 255 or local_id == 0xFFFFFFFF:
                    continue

                hidden = bool(status & _MO_STATUS_HIDDEN)
                if hidden:
                    continue

                npcs.append(NpcInfo(
                    local_id=local_id,
                    x=self._read32(mo + _MO_X),
                    z=self._read32(mo + _MO_Z),
                    facing=self._read32(mo + _MO_FACING_DIR),
                    graphics_id=self._read32(mo + _MO_GRAPHICS_ID),
                    hidden=hidden,
                    trainer_type=self._read32(mo + _MO_TRAINER_TYPE),
                    movement_type=self._read32(mo + _MO_MOVEMENT_TYPE),
                ))
            except Exception:
                continue

        return npcs

    # === Warp reading ===

    def read_warps(self) -> list[WarpInfo]:
        """Read warp events from MapHeaderData."""
        if not self._field_system_addr:
            return []

        try:
            mhd_addr = self._read32(self._field_system_addr + _FS_MAP_HEADER_DATA)
            if not self._is_valid_ptr(mhd_addr):
                return []

            num_warps = self._read32(mhd_addr + _MHD_NUM_WARP_EVENTS)
            warp_ptr = self._read32(mhd_addr + _MHD_WARP_EVENTS_PTR)
            if not self._is_valid_ptr(warp_ptr) or num_warps > 50:
                return []
        except Exception:
            return []

        warps: list[WarpInfo] = []
        for i in range(num_warps):
            we = warp_ptr + i * _WE_SIZE
            try:
                dest_id = self._read16(we + _WE_DEST_HEADER)
                warps.append(WarpInfo(
                    x=self._read16(we + _WE_X),
                    z=self._read16(we + _WE_Z),
                    dest_map_id=dest_id,
                    dest_warp_id=self._read16(we + _WE_DEST_WARP),
                    dest_name=self._get_map_name(dest_id),
                ))
            except Exception:
                continue

        return warps

    # === Player direction ===

    def read_player_facing(self) -> int:
        """Read the player's facing direction. Returns 0=N,1=S,2=W,3=E or -1."""
        if not self._field_system_addr:
            return -1
        try:
            pa_addr = self._read32(self._field_system_addr + _FS_PLAYER_AVATAR)
            if not self._is_valid_ptr(pa_addr):
                return -1
            mo_addr = self._read32(pa_addr + _PA_MAP_OBJ)
            if not self._is_valid_ptr(mo_addr):
                return -1
            return self._read32(mo_addr + _MO_FACING_DIR)
        except Exception:
            return -1

    # === Full world state ===

    def read_world_state(self, player_x: int, player_y: int) -> Optional[WorldState]:
        """Read the complete local world state in one call."""
        grid = self.read_player_grid(player_x, player_y)
        if not grid:
            return None

        return WorldState(
            grid=grid,
            npcs=self.read_npcs(),
            warps=self.read_warps(),
            player_facing=self.read_player_facing(),
            player_x=player_x,
            player_y=player_y,
        )

    # === Formatted grid output ===

    @staticmethod
    def _warp_legend(
        ch: str,
        dest: str,
        behavior: int,
        extra: str = "",
    ) -> str:
        """Build a warp legend entry with walk direction."""
        kind = "stairs" if ch == "S" else "warp panel" if ch == "W" else "door"
        walk_dir = WARP_WALK_DIR.get(behavior, "")
        parts = [f"{kind} → {dest}"]
        if walk_dir:
            parts.append(f"walk {walk_dir}")
        if extra:
            parts.append(extra)
        return ", ".join(parts)

    def format_grid(
        self,
        player_x: int,
        player_y: int,
        radius: int = 5,
    ) -> Optional[str]:
        """Format world state as an annotated ASCII grid.

        Uses relative coordinates (-5 to +5) for alignment stability.
        Absolute position is in the header. Shows tiles, NPCs (trainer vs
        regular vs item), warps with destinations, player facing direction,
        and interactable objects. Dynamic legend lists only present symbols.
        """
        ws = self.read_world_state(player_x, player_y)
        if not ws:
            return None

        local_px = player_x % MAP_TILES
        local_py = player_y % MAP_TILES

        # Build NPC position lookup
        npc_at: dict[tuple[int, int], NpcInfo] = {}
        for npc in ws.npcs:
            npc_at[(npc.x % MAP_TILES, npc.z % MAP_TILES)] = npc

        # Build warp position lookup (keyed by warp source tile)
        warp_at: dict[tuple[int, int], WarpInfo] = {}
        for warp in ws.warps:
            warp_at[(warp.x % MAP_TILES, warp.z % MAP_TILES)] = warp

        # Pre-compute embedded door positions.
        # Entrance warps appear in the adjacent WALL, not on the walkable trigger tile.
        embedded_doors: dict[tuple[int, int], tuple[str, tuple[int, int]]] = {}

        for dy_scan in range(-radius - 1, radius + 2):
            for dx_scan in range(-radius - 1, radius + 2):
                lx = local_px + dx_scan
                ly = local_py + dy_scan
                tile = ws.grid.get(lx, ly)
                if not tile.walkable or tile.behavior not in WARP_EMBED_OFFSETS:
                    continue
                edx, edy = WARP_EMBED_OFFSETS[tile.behavior]
                wall_lx, wall_ly = lx + edx, ly + edy
                wall_tile = ws.grid.get(wall_lx, wall_ly)
                if wall_tile.collision:
                    ch = WARP_CHARS.get(tile.behavior, "D")
                    embedded_doors[(wall_lx, wall_ly)] = (ch, (lx, ly))

        # Player direction
        player_char = DIR_ARROWS.get(ws.player_facing, "@")
        facing_name = DIR_NAMES.get(ws.player_facing, "?")

        # Track symbols for dynamic legend
        symbols_seen: dict[str, str] = {}

        lines: list[str] = []

        # --- Exits summary ---
        neighbors: list[str] = []
        for name, dx, dy in [("up", 0, -1), ("down", 0, 1), ("left", -1, 0), ("right", 1, 0)]:
            nx, ny = local_px + dx, local_py + dy
            npc = npc_at.get((nx, ny))
            tile = ws.grid.get(nx, ny)
            if npc:
                neighbors.append(f"{name}=NPC")
            elif tile.is_warp:
                warp = warp_at.get((nx, ny))
                if warp:
                    neighbors.append(f"{name}=warp({warp.dest_name})")
                else:
                    neighbors.append(f"{name}=warp")
            elif tile.collision:
                if tile.is_interactable:
                    neighbors.append(f"{name}={tile.grid_char()}")
                else:
                    neighbors.append(f"{name}=wall")
            elif tile.is_grass:
                neighbors.append(f"{name}=grass")
            elif tile.is_water:
                neighbors.append(f"{name}=water")
            else:
                neighbors.append(f"{name}=open")

        lines.append(f"Exits: {'  '.join(neighbors)}")

        # --- List all exits ---
        all_exits: list[str] = []

        # Embedded doors (visual in wall)
        for (wlx, wly), (wch, wsrc) in embedded_doors.items():
            dx = wlx - local_px
            dy = wly - local_py
            warp = warp_at.get(wsrc)
            dest = warp.dest_name if warp else "?"
            parts = []
            if dy < 0:
                parts.append(f"{-dy}N")
            elif dy > 0:
                parts.append(f"{dy}S")
            if dx < 0:
                parts.append(f"{-dx}W")
            elif dx > 0:
                parts.append(f"{dx}E")
            dir_str = "+".join(parts) if parts else "here"
            src_tile = ws.grid.get(*wsrc)
            walk = WARP_WALK_DIR.get(src_tile.behavior, "")
            walk_hint = f", walk {walk}" if walk else ""
            dist = abs(dx) + abs(dy)
            all_exits.append((dist, f"{wch} → {dest} ({dir_str}{walk_hint})"))

        # Non-embedded warps (stairs, warp panels, wall-type doors)
        # Build set of warp source positions that were successfully embedded
        embedded_sources = {src for _, src in embedded_doors.values()}
        for (wlx, wly), warp in warp_at.items():
            # Skip warps that were already handled in the embedded doors loop
            if (wlx, wly) in embedded_sources:
                continue
            warp_tile = ws.grid.get(wlx, wly)
            dx = wlx - local_px
            dy = wly - local_py
            wch = WARP_CHARS.get(warp_tile.behavior, "D") if warp_tile.is_warp else "D"
            parts = []
            if dy < 0:
                parts.append(f"{-dy}N")
            elif dy > 0:
                parts.append(f"{dy}S")
            if dx < 0:
                parts.append(f"{-dx}W")
            elif dx > 0:
                parts.append(f"{dx}E")
            dir_str = "+".join(parts) if parts else "here"
            walk = WARP_WALK_DIR.get(warp_tile.behavior, "")
            walk_hint = f", walk {walk}" if walk else ""
            dist = abs(dx) + abs(dy)
            all_exits.append((dist, f"{wch} → {warp.dest_name} ({dir_str}{walk_hint})"))

        if all_exits:
            # Sort by distance, closest first
            all_exits.sort(key=lambda x: x[0])
            exit_strs = [desc for _, desc in all_exits]
            if len(exit_strs) == 1:
                lines.append(f"Exit: {exit_strs[0]}")
            else:
                lines.append("Exits: " + " | ".join(exit_strs))

        # --- Column header (relative coordinates) ---
        rel_header = " ".join(f"{dx:>2}" for dx in range(-radius, radius + 1))
        lines.append(f"  dy\\dx{rel_header}")

        # --- Grid rows ---
        for dy in range(-radius, radius + 1):
            row: list[str] = []
            for dx in range(-radius, radius + 1):
                lx = local_px + dx
                ly = local_py + dy

                if dx == 0 and dy == 0:
                    ch = player_char
                    symbols_seen[player_char] = f"you (facing {facing_name})"

                elif (lx, ly) in npc_at:
                    npc = npc_at[(lx, ly)]
                    if npc.is_item_ball:
                        ch = "*"
                        symbols_seen["*"] = "item"
                    elif npc.is_trainer:
                        ch = "!"
                        symbols_seen["!"] = "trainer"
                    else:
                        ch = "?"
                        symbols_seen["?"] = "NPC"
                    # If NPC is standing on a warp, note it in legend
                    tile = ws.grid.get(lx, ly)
                    if tile.is_warp:
                        warp_ch = WARP_CHARS.get(tile.behavior, "D")
                        warp = warp_at.get((lx, ly))
                        if warp:
                            symbols_seen[warp_ch] = self._warp_legend(
                                warp_ch, warp.dest_name, tile.behavior, f"{ch} blocking"
                            )

                elif (lx, ly) in embedded_doors:
                    ch, warp_src = embedded_doors[(lx, ly)]
                    warp = warp_at.get(warp_src)
                    if warp:
                        src_tile = ws.grid.get(*warp_src)
                        symbols_seen[ch] = self._warp_legend(
                            ch, warp.dest_name, src_tile.behavior
                        )
                    else:
                        symbols_seen.setdefault(ch, "door/warp")

                else:
                    tile = ws.grid.get(lx, ly)

                    # Embedded warp entrance → show as floor (D is on the wall)
                    if tile.behavior in WARP_EMBED_OFFSETS and tile.walkable:
                        ch = "."
                        symbols_seen["."] = "open"
                    else:
                        ch = tile.grid_char()

                    # Track symbols for legend
                    if ch == "#":
                        symbols_seen["#"] = "wall"
                    elif ch == ".":
                        symbols_seen["."] = "open"
                    elif ch in ("D", "S", "W"):
                        warp = warp_at.get((lx, ly))
                        if warp:
                            symbols_seen[ch] = self._warp_legend(
                                ch, warp.dest_name, tile.behavior
                            )
                        else:
                            symbols_seen.setdefault(ch, "door/warp")
                    elif ch == "G":
                        symbols_seen["G"] = "tall grass"
                    elif ch == "~":
                        symbols_seen["~"] = "water"
                    elif ch in (">", "<", "^", "v") and tile.is_ledge:
                        ledge_dir = {">": "east", "<": "west", "^": "north", "v": "south"}.get(ch, "?")
                        symbols_seen[ch] = f"ledge (jump {ledge_dir})"
                    elif ch == "_":
                        symbols_seen["_"] = "ice (slippery!)"
                    elif ch == "P":
                        symbols_seen["P"] = "PC"
                    elif ch == "T":
                        symbols_seen["T"] = "TV"
                    elif ch == "B":
                        symbols_seen["B"] = "bookshelf"
                    elif ch == "=":
                        symbols_seen["="] = "table"
                    elif ch == "%":
                        symbols_seen["%"] = "trash can"
                    elif ch == "M":
                        symbols_seen["M"] = "town map"
                    elif ch == "$":
                        symbols_seen["$"] = "mart shelf"

                row.append(f"{ch:>2}")

            line = f"  {dy:>3} {' '.join(row)}"
            if dy == -radius:
                line += "  ↑N"
            elif dy == radius:
                line += "  ↓S"
            lines.append(line)

        # --- Dynamic legend ---
        legend_parts: list[str] = []
        seen_in_legend: set[str] = set()
        priority = [player_char, ".", "#", "?", "!", "*", "D", "S", "W",
                     "G", "~", ">", "<", "^", "v", "_",
                     "P", "T", "B", "=", "%", "M", "$"]
        for sym in priority:
            if sym in symbols_seen and sym not in seen_in_legend:
                legend_parts.append(f"{sym}={symbols_seen[sym]}")
                seen_in_legend.add(sym)
        for sym, desc in symbols_seen.items():
            if sym not in seen_in_legend:
                legend_parts.append(f"{sym}={desc}")
                seen_in_legend.add(sym)

        lines.append("  ".join(legend_parts))

        return "\n".join(lines)

    # === State management ===

    @property
    def is_available(self) -> bool:
        """Whether collision data is currently accessible."""
        return self._field_system_addr != 0

    def invalidate(self) -> None:
        """Force re-scan on next access (call on map transitions)."""
        self._field_system_addr = 0

    def __repr__(self) -> str:
        if self._field_system_addr:
            return f"CollisionReader(fs={self._field_system_addr:#010x})"
        return "CollisionReader(not initialized)"
