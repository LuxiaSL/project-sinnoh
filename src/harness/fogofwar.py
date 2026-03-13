"""Fog-of-war map — per-map persistent record of visited tiles.

Tracks which tiles the player has walked on, per map ID.
Provides visualization and persistence across sessions.

This is a perception aid: it gives Claude the same spatial memory
a human player builds naturally from walking around.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class FogOfWar:
    """Per-map visited tile tracking with persistence."""

    def __init__(self, save_path: Optional[str | Path] = None) -> None:
        """Initialize fog-of-war tracker.

        Args:
            save_path: Path to save/load exploration data.
                      If None, data is in-memory only.
        """
        # map_id → set of (x, y) tuples visited
        self._visited: dict[int, set[tuple[int, int]]] = {}
        self._save_path = Path(save_path) if save_path else None

        if self._save_path and self._save_path.exists():
            self._load()

    def visit(self, map_id: int, x: int, y: int) -> bool:
        """Mark a tile as visited. Returns True if this is a NEW tile."""
        if map_id not in self._visited:
            self._visited[map_id] = set()

        pos = (x, y)
        if pos in self._visited[map_id]:
            return False

        self._visited[map_id].add(pos)
        return True

    def is_visited(self, map_id: int, x: int, y: int) -> bool:
        """Check if a tile has been visited."""
        if map_id not in self._visited:
            return False
        return (x, y) in self._visited[map_id]

    def visited_maps(self) -> set[int]:
        """Get set of all visited map IDs."""
        return set(self._visited.keys())

    def is_new_map(self, map_id: int) -> bool:
        """Check if this map has never been visited."""
        return map_id not in self._visited

    def tiles_visited(self, map_id: int) -> int:
        """Count of visited tiles on a given map."""
        if map_id not in self._visited:
            return 0
        return len(self._visited[map_id])

    def get_visited_set(self, map_id: int) -> set[tuple[int, int]]:
        """Get the set of visited positions for a map."""
        return self._visited.get(map_id, set()).copy()

    def render_grid(
        self,
        map_id: int,
        player_x: int,
        player_y: int,
        radius: int = 5,
    ) -> str:
        """Render a text grid showing explored vs unexplored tiles.

        Args:
            map_id: Current map ID.
            player_x: Player's X coordinate.
            player_y: Player's Y coordinate.
            radius: Grid radius around the player (default 5 = 11x11 grid).

        Returns:
            ASCII grid string. Legend:
            @ = player, · = visited, ? = unvisited
        """
        visited = self._visited.get(map_id, set())
        lines: list[str] = []

        for dy in range(-radius, radius + 1):
            row: list[str] = []
            for dx in range(-radius, radius + 1):
                tx, ty = player_x + dx, player_y + dy
                if dx == 0 and dy == 0:
                    row.append("@")
                elif (tx, ty) in visited:
                    row.append("·")
                else:
                    row.append("?")
            lines.append(" ".join(row))

        return "\n".join(lines)

    def save(self) -> None:
        """Persist exploration data to disk."""
        if not self._save_path:
            return

        self._save_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert sets to sorted lists for JSON serialization
        data: dict[str, list[list[int]]] = {}
        for map_id, positions in self._visited.items():
            data[str(map_id)] = sorted([list(p) for p in positions])

        self._save_path.write_text(json.dumps(data, separators=(",", ":")))

    def _load(self) -> None:
        """Load exploration data from disk."""
        if not self._save_path or not self._save_path.exists():
            return

        try:
            raw = json.loads(self._save_path.read_text())
            for map_id_str, positions in raw.items():
                map_id = int(map_id_str)
                self._visited[map_id] = {(p[0], p[1]) for p in positions}
        except (json.JSONDecodeError, KeyError, IndexError, ValueError):
            # Corrupted save — start fresh
            self._visited = {}

    def clear(self) -> None:
        """Clear all exploration data."""
        self._visited = {}

    def __repr__(self) -> str:
        total = sum(len(v) for v in self._visited.values())
        return f"FogOfWar(maps={len(self._visited)}, tiles={total})"
