"""Spatial grid generator for Pokemon Platinum (US).

Generates a tile grid centered on the player, showing walkable/wall/etc tiles.

Two data sources (best available wins):
1. COLLISION DATA FROM RAM (preferred): Reads actual 32×32 tile collision maps
   via FieldSystem → LandDataManager → LoadedMap. Perfect information — knows
   every wall, door, grass patch, and warp tile. See collision.py.
2. MOVEMENT-BASED (fallback): Tracks movement results as fog-of-war.
   If player moves and coords change → walkable. If blocked → wall.

When collision data is available, Claude sees the actual room layout.
When not (e.g., during transitions or if FieldSystem isn't active),
falls back to movement history.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .fogofwar import FogOfWar

if TYPE_CHECKING:
    from .collision import CollisionReader

logger = logging.getLogger(__name__)


class TileType(str, Enum):
    """Tile classification for the spatial grid."""
    UNKNOWN = "?"  # Never visited or tested
    WALKABLE = "."  # Confirmed walkable
    WALL = "#"  # Confirmed impassable
    PLAYER = "@"  # Player's current position
    GRASS = "G"  # Tall grass (if detectable)
    WATER = "~"  # Water tile (if detectable)
    DOOR = "D"  # Warp point (if detectable)
    NPC = "!"  # NPC present (if detectable)
    ITEM = "*"  # Item ball (if detectable)


class SpatialGrid:
    """Movement-based spatial grid centered on the player.

    Tracks tile walkability from observed movement results.
    Integrates with FogOfWar for visited tile data.
    """

    def __init__(
        self,
        fog_of_war: Optional[FogOfWar] = None,
        radius: int = 5,
        save_path: Optional[Path] = None,
    ) -> None:
        """Initialize the spatial grid.

        Args:
            fog_of_war: Optional FogOfWar instance for visited tile data.
            radius: Grid radius (default 5 = 11×11 grid).
            save_path: Path to persist tile data as JSON. Loaded on init.
        """
        self._fow = fog_of_war
        self._radius = radius
        self._save_path = save_path

        # Per-map tile type cache: map_id → {(x,y) → TileType}
        self._tile_types: dict[int, dict[tuple[int, int], TileType]] = {}

        # Load from disk if available
        if save_path:
            self._load(save_path)

    def record_move_result(
        self,
        map_id: int,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        direction: str,
    ) -> None:
        """Record the result of a movement attempt.

        Call this after the player tries to move. If coordinates changed,
        the destination tile AND all intermediate tiles along the path
        are marked walkable. If movement failed completely, the tile in
        that direction is marked as a wall.

        For multi-step walks (e.g., walk right 5), the path from
        (from_x, from_y) to (to_x, to_y) is interpolated — every tile
        along the straight line is marked walkable. If the walk was
        partially blocked, a wall is placed one step past the endpoint.

        Args:
            map_id: Current map ID.
            from_x, from_y: Position before movement.
            to_x, to_y: Position after movement.
            direction: "up", "down", "left", or "right".
        """
        if map_id not in self._tile_types:
            self._tile_types[map_id] = {}

        tiles = self._tile_types[map_id]

        # Mark origin as walkable
        tiles[(from_x, from_y)] = TileType.WALKABLE

        dx, dy = _direction_delta(direction)

        if from_x != to_x or from_y != to_y:
            # Movement succeeded — fill in ALL tiles along the path
            cx, cy = from_x, from_y
            while (cx, cy) != (to_x, to_y):
                cx += dx
                cy += dy
                tiles[(cx, cy)] = TileType.WALKABLE
                # Safety: break if we overshoot (shouldn't happen on straight walks)
                if abs(cx - from_x) + abs(cy - from_y) > 25:
                    break

            # If the walk was requested as multi-step and got blocked
            # partway, mark the tile PAST the endpoint as a wall.
            # (The loop caller handles this via the "Partially blocked" check,
            # but we can also infer it here by checking if we stopped early.)
        else:
            # Movement failed entirely — the adjacent tile is a wall
            wall_pos = (from_x + dx, from_y + dy)
            tiles[wall_pos] = TileType.WALL

    def set_tile(self, map_id: int, x: int, y: int, tile_type: TileType) -> None:
        """Manually set a tile type (e.g., from visual detection)."""
        if map_id not in self._tile_types:
            self._tile_types[map_id] = {}
        self._tile_types[map_id][(x, y)] = tile_type

    def get_tile(self, map_id: int, x: int, y: int) -> TileType:
        """Get the tile type at a position."""
        tiles = self._tile_types.get(map_id, {})
        return tiles.get((x, y), TileType.UNKNOWN)

    def render(
        self,
        map_id: int,
        player_x: int,
        player_y: int,
    ) -> str:
        """Render the spatial grid as ASCII text.

        Returns an (2*radius+1) × (2*radius+1) grid centered on the player,
        with coordinate labels on axes and a compass indicator.
        """
        tiles = self._tile_types.get(map_id, {})
        lines: list[str] = []

        # Column header: x coordinates
        x_labels = " ".join(f"{player_x + dx}" for dx in range(-self._radius, self._radius + 1))
        # Pad to align with row prefix (y label is 4 chars + space)
        lines.append(f"  y\\x {x_labels}")

        for dy in range(-self._radius, self._radius + 1):
            row: list[str] = []
            for dx in range(-self._radius, self._radius + 1):
                tx, ty = player_x + dx, player_y + dy

                if dx == 0 and dy == 0:
                    row.append(TileType.PLAYER.value)
                elif (tx, ty) in tiles:
                    row.append(tiles[(tx, ty)].value)
                elif self._fow and self._fow.is_visited(map_id, tx, ty):
                    row.append(TileType.WALKABLE.value)
                else:
                    row.append(TileType.UNKNOWN.value)

            y_coord = player_y + dy
            # Add compass on first/last rows
            compass = ""
            if dy == -self._radius:
                compass = "  ↑ up"
            elif dy == self._radius:
                compass = "  ↓ down"

            lines.append(f"  {y_coord:>3} {' '.join(row)}{compass}")

        return "\n".join(lines)

    def _neighbor_summary(
        self, map_id: int, player_x: int, player_y: int
    ) -> str:
        """Summarize the 4 cardinal neighbors as a quick navigation hint."""
        tiles = self._tile_types.get(map_id, {})
        dirs = [
            ("up", 0, -1),
            ("down", 0, 1),
            ("left", -1, 0),
            ("right", 1, 0),
        ]
        parts: list[str] = []
        for name, dx, dy in dirs:
            pos = (player_x + dx, player_y + dy)
            tile = tiles.get(pos, TileType.UNKNOWN)
            if tile == TileType.WALKABLE:
                parts.append(f"{name}=open")
            elif tile == TileType.WALL:
                parts.append(f"{name}=wall")
            else:
                parts.append(f"{name}=?")
        return "  ".join(parts)

    def format_grid(
        self,
        map_id: int,
        player_x: int,
        player_y: int,
        map_name: str = "",
        collision_reader: Optional[CollisionReader] = None,
    ) -> str:
        """Format the grid with neighbor summary + compact view.

        If collision_reader is provided and has data, uses perfect collision
        info from RAM (shows walls, doors, grass, water). Otherwise falls
        back to movement-based fog-of-war grid.

        Shows:
        1. Header with location and coordinates
        2. Cardinal direction summary (can I go N/S/E/W?)
        3. Compact grid (radius 5 with collision data, radius 3 without)
        4. Tile legend
        """
        # Try collision data first (perfect information)
        if collision_reader:
            collision_grid = collision_reader.format_grid(player_x, player_y, radius=5)
            if collision_grid:
                header = f"--- SPATIAL GRID ---"
                if map_name:
                    header += f" [{map_name}]"
                header += f"  You: ({player_x},{player_y})"
                return f"{header}\n{collision_grid}"

        # Fallback: movement-based fog-of-war grid
        header = f"--- SPATIAL GRID ---"
        if map_name:
            header += f" [{map_name}]"
        header += f"  You: ({player_x},{player_y})"

        neighbors = self._neighbor_summary(map_id, player_x, player_y)
        compact = self._render_compact(map_id, player_x, player_y, radius=3)

        tiles = self._tile_types.get(map_id, {})
        walkable = sum(1 for t in tiles.values() if t == TileType.WALKABLE)
        walls = sum(1 for t in tiles.values() if t == TileType.WALL)

        legend = f"@ you  . open  # wall  ? unexplored  |  {walkable} open, {walls} walls mapped"

        return f"{header}\nExits: {neighbors}\n{compact}\n{legend}"

    def _render_compact(
        self, map_id: int, player_x: int, player_y: int, radius: int = 3
    ) -> str:
        """Render a compact grid with coordinate labels."""
        tiles = self._tile_types.get(map_id, {})
        lines: list[str] = []

        # Column header
        x_labels = " ".join(
            f"{player_x + dx}" for dx in range(-radius, radius + 1)
        )
        lines.append(f"  y\\x {x_labels}")

        for dy in range(-radius, radius + 1):
            row: list[str] = []
            for dx in range(-radius, radius + 1):
                tx, ty = player_x + dx, player_y + dy
                if dx == 0 and dy == 0:
                    row.append(TileType.PLAYER.value)
                elif (tx, ty) in tiles:
                    row.append(tiles[(tx, ty)].value)
                elif self._fow and self._fow.is_visited(map_id, tx, ty):
                    row.append(TileType.WALKABLE.value)
                else:
                    row.append(TileType.UNKNOWN.value)

            y_coord = player_y + dy
            lines.append(f"  {y_coord:>3} {' '.join(row)}")

        return "\n".join(lines)

    def clear_map(self, map_id: int) -> None:
        """Clear tile data for a specific map."""
        self._tile_types.pop(map_id, None)

    def save(self) -> None:
        """Persist tile data to disk."""
        if not self._save_path:
            return
        try:
            # Serialize: map_id → list of [x, y, tile_value]
            data: dict[str, list[list[int | str]]] = {}
            for map_id, tiles in self._tile_types.items():
                entries: list[list[int | str]] = []
                for (x, y), tile in tiles.items():
                    entries.append([x, y, tile.value])
                data[str(map_id)] = entries

            self._save_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_path.write_text(json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to save spatial grid: {e}")

    def _load(self, path: Path) -> None:
        """Load tile data from disk."""
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            # Reverse lookup for tile values
            value_to_type = {t.value: t for t in TileType}

            for map_id_str, entries in data.items():
                map_id = int(map_id_str)
                tiles: dict[tuple[int, int], TileType] = {}
                for entry in entries:
                    x, y, val = int(entry[0]), int(entry[1]), str(entry[2])
                    tile_type = value_to_type.get(val, TileType.UNKNOWN)
                    if tile_type != TileType.UNKNOWN:
                        tiles[(x, y)] = tile_type
                self._tile_types[map_id] = tiles

            total = sum(len(t) for t in self._tile_types.values())
            logger.info(f"Loaded spatial grid: {total} tiles across {len(self._tile_types)} maps")
        except Exception as e:
            logger.error(f"Failed to load spatial grid: {e}")

    def __repr__(self) -> str:
        total = sum(len(t) for t in self._tile_types.values())
        return f"SpatialGrid(maps={len(self._tile_types)}, tiles={total})"


def _direction_delta(direction: str) -> tuple[int, int]:
    """Convert a direction string to (dx, dy) delta."""
    return {
        "up": (0, -1),
        "down": (0, 1),
        "left": (-1, 0),
        "right": (1, 0),
    }.get(direction.lower(), (0, 0))
