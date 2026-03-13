"""Journal system for the Pokemon Platinum playthrough.

Claude's persistent memory — authored by Claude, not auto-summarized.
Structured with sections that can be independently read and written.

Sections:
- current_goals: What Claude is doing right now and why
- team_notes: Per-Pokemon notes, feelings, memories
- adventure_log: Narrative entries about what's happened
- strategy: Type matchup notes, gym observations, battle lessons
- map_notes: Observations about areas and routes

Pagination strategy:
- Always loaded: current_goals + team_notes (immediately relevant)
- Loaded by default: most recent N adventure_log entries
- On-demand: everything else via read_journal tool
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Valid section names
SECTIONS = [
    "current_goals",
    "team_notes",
    "adventure_log",
    "strategy",
    "map_notes",
]

# Sections always loaded into context
ALWAYS_LOAD_SECTIONS = ["current_goals", "team_notes"]

# Default number of recent adventure log entries to load
DEFAULT_RECENT_LOG_ENTRIES = 5


@dataclass
class JournalEntry:
    """A single entry in a journal section."""
    content: str
    timestamp: float = field(default_factory=time.time)
    in_game_time: str = ""  # e.g., "2:15:30"
    chapter: int = 0  # Which chapter this was written in

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "timestamp": self.timestamp,
            "in_game_time": self.in_game_time,
            "chapter": self.chapter,
        }

    @classmethod
    def from_dict(cls, data: dict) -> JournalEntry:
        return cls(
            content=data["content"],
            timestamp=data.get("timestamp", 0.0),
            in_game_time=data.get("in_game_time", ""),
            chapter=data.get("chapter", 0),
        )


class Journal:
    """Persistent structured journal for the playthrough.

    Each section holds a list of entries. Claude writes entries via the
    write_journal tool. The context manager loads relevant sections into
    each API call.
    """

    def __init__(self, save_path: Optional[str | Path] = None) -> None:
        self._save_path = Path(save_path) if save_path else None
        self._sections: dict[str, list[JournalEntry]] = {s: [] for s in SECTIONS}
        self._current_chapter: int = 1

        if self._save_path and self._save_path.exists():
            self._load()

    @property
    def current_chapter(self) -> int:
        return self._current_chapter

    @current_chapter.setter
    def current_chapter(self, value: int) -> None:
        self._current_chapter = value

    def write(
        self,
        section: str,
        content: str,
        in_game_time: str = "",
    ) -> bool:
        """Write an entry to a journal section.

        Args:
            section: Section name (must be one of SECTIONS).
            content: The text to write.
            in_game_time: Current in-game play time string.

        Returns:
            True if successful, False if invalid section.
        """
        if section not in self._sections:
            return False

        entry = JournalEntry(
            content=content,
            in_game_time=in_game_time,
            chapter=self._current_chapter,
        )
        self._sections[section].append(entry)
        self._autosave()
        return True

    def replace_section(self, section: str, content: str, in_game_time: str = "") -> bool:
        """Replace an entire section's content (for current_goals, team_notes).

        These sections are "living documents" that get overwritten rather
        than appended to.

        Args:
            section: Section name.
            content: New content (replaces all existing entries).
            in_game_time: Current in-game play time string.

        Returns:
            True if successful, False if invalid section.
        """
        if section not in self._sections:
            return False

        entry = JournalEntry(
            content=content,
            in_game_time=in_game_time,
            chapter=self._current_chapter,
        )
        self._sections[section] = [entry]
        self._autosave()
        return True

    def read(
        self,
        section: str,
        n: Optional[int] = None,
    ) -> list[JournalEntry]:
        """Read entries from a journal section.

        Args:
            section: Section name.
            n: Number of most recent entries to return (None = all).

        Returns:
            List of entries (most recent last).
        """
        entries = self._sections.get(section, [])
        if n is not None:
            return entries[-n:]
        return entries

    def read_all(self) -> dict[str, list[JournalEntry]]:
        """Read all sections."""
        return {s: list(entries) for s, entries in self._sections.items()}

    def format_for_context(
        self,
        recent_log_entries: int = DEFAULT_RECENT_LOG_ENTRIES,
    ) -> str:
        """Format journal sections for inclusion in the agent prompt.

        Always includes: current_goals + team_notes (full)
        Includes: most recent N adventure_log entries
        Excludes: strategy, map_notes (available via read_journal tool)

        This is the pagination strategy — keep immediate context small,
        rest available on demand.
        """
        lines: list[str] = []
        lines.append("=== YOUR JOURNAL ===")

        # Current goals (always loaded, full)
        goals = self._sections.get("current_goals", [])
        if goals:
            lines.append("")
            lines.append("--- Current Goals ---")
            for entry in goals:
                lines.append(entry.content)
        else:
            lines.append("")
            lines.append("--- Current Goals ---")
            lines.append("(No goals set yet. Use write_journal to set your current goals.)")

        # Team notes (always loaded, full)
        team = self._sections.get("team_notes", [])
        if team:
            lines.append("")
            lines.append("--- Team Notes ---")
            for entry in team:
                lines.append(entry.content)

        # Adventure log (recent N entries)
        log = self._sections.get("adventure_log", [])
        if log:
            recent = log[-recent_log_entries:]
            lines.append("")
            total = len(log)
            showing = len(recent)
            if total > showing:
                lines.append(
                    f"--- Adventure Log (showing {showing}/{total} entries, "
                    f"use read_journal for older entries) ---"
                )
            else:
                lines.append(f"--- Adventure Log ({total} entries) ---")
            for entry in recent:
                time_str = f" [{entry.in_game_time}]" if entry.in_game_time else ""
                lines.append(f"{time_str} {entry.content}")

        # Note about on-demand sections
        strategy = self._sections.get("strategy", [])
        map_notes = self._sections.get("map_notes", [])
        on_demand_parts: list[str] = []
        if strategy:
            on_demand_parts.append(f"strategy ({len(strategy)} entries)")
        if map_notes:
            on_demand_parts.append(f"map_notes ({len(map_notes)} entries)")
        if on_demand_parts:
            lines.append("")
            lines.append(f"(Also available via read_journal: {', '.join(on_demand_parts)})")

        return "\n".join(lines)

    def format_section(self, section: str, n: Optional[int] = None) -> str:
        """Format a single section for the read_journal tool response."""
        entries = self.read(section, n)
        if not entries:
            return f"Section '{section}' is empty."

        lines: list[str] = []
        lines.append(f"--- {section.replace('_', ' ').title()} ---")
        for entry in entries:
            time_str = f" [{entry.in_game_time}]" if entry.in_game_time else ""
            lines.append(f"{time_str} {entry.content}")
        return "\n".join(lines)

    def entry_count(self, section: Optional[str] = None) -> int:
        """Count entries in a section or total."""
        if section:
            return len(self._sections.get(section, []))
        return sum(len(entries) for entries in self._sections.values())

    # === Persistence ===

    def save(self) -> None:
        """Save journal to disk."""
        if not self._save_path:
            return

        self._save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "chapter": self._current_chapter,
            "sections": {
                name: [entry.to_dict() for entry in entries]
                for name, entries in self._sections.items()
            },
        }
        self._save_path.write_text(json.dumps(data, indent=2))

    def _autosave(self) -> None:
        """Save after every write (journal is precious)."""
        self.save()

    def _load(self) -> None:
        """Load journal from disk."""
        if not self._save_path or not self._save_path.exists():
            return

        try:
            raw = json.loads(self._save_path.read_text())
            self._current_chapter = raw.get("chapter", 1)
            sections = raw.get("sections", {})
            for name in SECTIONS:
                if name in sections:
                    self._sections[name] = [
                        JournalEntry.from_dict(e) for e in sections[name]
                    ]
        except (json.JSONDecodeError, KeyError, ValueError):
            # Corrupted save — start fresh but don't overwrite
            pass

    def __repr__(self) -> str:
        total = self.entry_count()
        return f"Journal(chapter={self._current_chapter}, entries={total})"
