"""Novelty detection — flags new maps, species, items, and near-evolutions.

Tracks sets of "seen" things and flags when something new appears.
These flags are included in the state formatter to draw Claude's attention.

This is a perception aid: it mirrors the natural excitement a human feels
when encountering something for the first time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .models import Party, PlayerState


class NoveltyTracker:
    """Tracks seen maps, species, and items to flag new encounters."""

    def __init__(self, save_path: Optional[str | Path] = None) -> None:
        """Initialize novelty tracker.

        Args:
            save_path: Path to save/load novelty data.
                      If None, data is in-memory only.
        """
        self._seen_maps: set[int] = set()
        self._seen_species: set[int] = set()
        self._seen_items: set[int] = set()
        self._save_path = Path(save_path) if save_path else None

        if self._save_path and self._save_path.exists():
            self._load()

    def check(
        self,
        player: PlayerState,
        party: Party,
        *,
        encountered_species: int | None = None,
    ) -> list[str]:
        """Check for novelty events and return flag strings.

        Call this each game step. Returns a list of novelty flag strings
        to include in the state formatter.

        Args:
            player: Current player state.
            party: Current party state.
            encountered_species: Species ID if a new Pokemon was just encountered
                               (e.g., at battle start).

        Returns:
            List of novelty flag strings (may be empty).
        """
        flags: list[str] = []

        # New map?
        if player.map_id not in self._seen_maps:
            map_label = player.map_name or f"Map #{player.map_id}"
            flags.append(f"First visit to {map_label}")
            self._seen_maps.add(player.map_id)

        # New species encountered?
        if encountered_species is not None and encountered_species not in self._seen_species:
            species_name = self._get_species_name(encountered_species)
            flags.append(f"New Pokemon: {species_name}!")
            self._seen_species.add(encountered_species)

        # Also track species from party (catches, evolutions)
        for pkmn in party.pokemon:
            if pkmn.species_id not in self._seen_species:
                flags.append(f"New Pokemon in party: {pkmn.species_name}!")
                self._seen_species.add(pkmn.species_id)

        # Near evolution check
        for pkmn in party.pokemon:
            if pkmn.is_egg:
                continue
            evo_level = self._get_evolution_level(pkmn.species_id)
            if evo_level is not None and 0 < (evo_level - pkmn.level) <= 2:
                flags.append(
                    f"{pkmn.nickname} is close to evolving! "
                    f"(Lv.{pkmn.level}, evolves at Lv.{evo_level})"
                )

        return flags

    def mark_species_seen(self, species_id: int) -> None:
        """Manually mark a species as seen."""
        self._seen_species.add(species_id)

    def mark_item_seen(self, item_id: int) -> None:
        """Manually mark an item as seen."""
        self._seen_items.add(item_id)

    @property
    def species_seen_count(self) -> int:
        return len(self._seen_species)

    @property
    def maps_visited_count(self) -> int:
        return len(self._seen_maps)

    def _get_species_name(self, species_id: int) -> str:
        """Look up species name."""
        try:
            from .data.species import SPECIES
            sp = SPECIES.get(species_id)
            return sp[0] if sp else f"Pokemon#{species_id}"
        except ImportError:
            return f"Pokemon#{species_id}"

    def _get_evolution_level(self, species_id: int) -> int | None:
        """Get the level at which this species evolves, if applicable.

        Returns None if species doesn't evolve by level, or if
        the evolution table isn't available yet.
        """
        try:
            from .data.evolutions import EVOLUTION_LEVELS
            return EVOLUTION_LEVELS.get(species_id)
        except ImportError:
            return None

    def save(self) -> None:
        """Persist novelty data to disk."""
        if not self._save_path:
            return

        self._save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "maps": sorted(self._seen_maps),
            "species": sorted(self._seen_species),
            "items": sorted(self._seen_items),
        }
        self._save_path.write_text(json.dumps(data, separators=(",", ":")))

    def _load(self) -> None:
        """Load novelty data from disk."""
        if not self._save_path or not self._save_path.exists():
            return

        try:
            raw = json.loads(self._save_path.read_text())
            self._seen_maps = set(raw.get("maps", []))
            self._seen_species = set(raw.get("species", []))
            self._seen_items = set(raw.get("items", []))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # Corrupted save — start fresh

    def clear(self) -> None:
        """Clear all novelty tracking data."""
        self._seen_maps = set()
        self._seen_species = set()
        self._seen_items = set()

    def __repr__(self) -> str:
        return (
            f"NoveltyTracker(maps={len(self._seen_maps)}, "
            f"species={len(self._seen_species)}, "
            f"items={len(self._seen_items)})"
        )
