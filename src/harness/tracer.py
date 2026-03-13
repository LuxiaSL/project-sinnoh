"""Tracing infrastructure for the agent loop.

Captures full traces of every turn:
- Game state (RAM readout, formatted text)
- Screenshots (saved as images on disk)
- Spatial grid, dialogue, journal context
- Full API request content (what Claude received)
- Full API response (what Claude said + tool calls)
- Action execution results
- Timing data, token usage, mode

Trace directory structure:
    traces/run_YYYYMMDD_HHMMSS/
    ├── run_config.json          # Config + metadata
    ├── summary.log              # Human-readable turn-by-turn summary
    ├── turns.jsonl              # Machine-readable turn data (one JSON per line)
    └── turns/
        ├── turn_0001/
        │   ├── top_screen.jpg   # Top screen screenshot
        │   ├── bot_screen.jpg   # Bottom screen screenshot
        │   ├── state.txt        # Formatted game state
        │   ├── spatial.txt      # Spatial grid
        │   ├── dialogue.txt     # Dialogue transcript
        │   ├── journal.txt      # Journal context
        │   ├── prompt.txt       # Full text content sent to Claude
        │   ├── response.json    # Claude's response (text + tool calls)
        │   └── actions.json     # Actions executed + outcomes
        └── turn_0002/
            └── ...
"""

from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PIL import Image


@dataclass
class TurnTrace:
    """All data captured for a single turn."""
    turn_number: int = 0
    timestamp: float = field(default_factory=time.time)

    # Game state
    game_mode: str = ""
    player_name: str = ""
    map_name: str = ""
    map_id: int = 0
    x: int = 0
    y: int = 0
    party_count: int = 0
    badge_count: int = 0
    in_battle: bool = False

    # Content sent to Claude
    state_text: str = ""
    spatial_grid: str = ""
    dialogue_text: str = ""
    journal_text: str = ""
    novelty_flags: list[str] = field(default_factory=list)
    screenshots_b64: list[dict[str, str]] = field(default_factory=list)

    # Claude's response
    agent_text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""

    # Tool execution
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    actions_executed: list[dict[str, Any]] = field(default_factory=list)

    # Raw harness state (not sent to Claude — for debugging/validation)
    raw_state: dict[str, Any] = field(default_factory=dict)
    # Contains: player_state, party, fog_of_war_grid, fog_tiles_visited,
    #           novelty_tracker_stats, battle_state, inventory_summary

    # Metrics
    api_calls_this_turn: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    turn_duration_ms: float = 0
    idle_wait_frames: int = 0
    frames_advanced: int = 0

    # Error
    error: str = ""


class Tracer:
    """Captures and persists full traces of every agent loop turn."""

    def __init__(self, trace_dir: Optional[Path] = None) -> None:
        if trace_dir is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            trace_dir = Path(f"traces/run_{ts}")

        self._dir = trace_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / "turns").mkdir(exist_ok=True)

        self._summary_path = self._dir / "summary.log"
        self._turns_path = self._dir / "turns.jsonl"
        self._turn_count = 0

        # Write header to summary log
        with open(self._summary_path, "w") as f:
            f.write(f"=== Agent Loop Trace — {datetime.now().isoformat()} ===\n\n")

    @property
    def trace_dir(self) -> Path:
        return self._dir

    @property
    def turn_count(self) -> int:
        return self._turn_count

    def save_config(self, config: dict[str, Any]) -> None:
        """Save run configuration."""
        (self._dir / "run_config.json").write_text(
            json.dumps(config, indent=2, default=str)
        )

    def record_turn(self, trace: TurnTrace) -> None:
        """Record a complete turn trace to disk."""
        self._turn_count += 1
        turn_num = trace.turn_number or self._turn_count

        # Create turn directory
        turn_dir = self._dir / "turns" / f"turn_{turn_num:04d}"
        turn_dir.mkdir(parents=True, exist_ok=True)

        # Save screenshots as images
        for i, shot in enumerate(trace.screenshots_b64):
            try:
                img_data = base64.b64decode(shot.get("data", ""))
                img = Image.open(io.BytesIO(img_data))
                label = "top_screen" if i == 0 else "bot_screen"
                img.save(turn_dir / f"{label}.jpg")
            except Exception:
                pass

        # Save text content
        self._write_if_nonempty(turn_dir / "state.txt", trace.state_text)
        self._write_if_nonempty(turn_dir / "spatial.txt", trace.spatial_grid)
        self._write_if_nonempty(turn_dir / "dialogue.txt", trace.dialogue_text)
        self._write_if_nonempty(turn_dir / "journal.txt", trace.journal_text)

        # Save the full prompt text (everything Claude received)
        # Formatters already include their own headers (=== GAME STATE ===,
        # --- SPATIAL GRID ---, etc.) so we don't add extra wrapper labels.
        prompt_parts = []
        if trace.journal_text:
            prompt_parts.append(trace.journal_text)
        if trace.state_text:
            prompt_parts.append(trace.state_text)
        if trace.spatial_grid:
            prompt_parts.append(trace.spatial_grid)
        if trace.dialogue_text:
            prompt_parts.append(trace.dialogue_text)
        if trace.novelty_flags:
            prompt_parts.append("\n".join(f"[!] {f}" for f in trace.novelty_flags))
        prompt_parts.append(f"[+ {len(trace.screenshots_b64)} screenshot(s)]")
        self._write_if_nonempty(turn_dir / "prompt.txt", "\n\n".join(prompt_parts))

        # Save response
        response_data = {
            "text": trace.agent_text,
            "tool_calls": trace.tool_calls,
            "stop_reason": trace.stop_reason,
        }
        (turn_dir / "response.json").write_text(json.dumps(response_data, indent=2))

        # Save actions + results
        actions_data = {
            "tool_results": trace.tool_results,
            "actions_executed": trace.actions_executed,
        }
        (turn_dir / "actions.json").write_text(json.dumps(actions_data, indent=2))

        # Save raw harness state (not sent to Claude — for debugging)
        if trace.raw_state:
            (turn_dir / "raw_state.json").write_text(
                json.dumps(trace.raw_state, indent=2, default=str)
            )

        # Save metadata
        metadata = {
            "turn": turn_num,
            "timestamp": trace.timestamp,
            "game_mode": trace.game_mode,
            "location": f"{trace.map_name} (#{trace.map_id})",
            "position": f"({trace.x}, {trace.y})",
            "party_count": trace.party_count,
            "badge_count": trace.badge_count,
            "in_battle": trace.in_battle,
            "api_calls": trace.api_calls_this_turn,
            "input_tokens": trace.input_tokens,
            "output_tokens": trace.output_tokens,
            "cache_read_tokens": trace.cache_read_tokens,
            "cache_creation_tokens": trace.cache_creation_tokens,
            "turn_duration_ms": trace.turn_duration_ms,
            "idle_wait_frames": trace.idle_wait_frames,
            "frames_advanced": trace.frames_advanced,
            "error": trace.error,
        }
        (turn_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

        # Append to JSONL (machine-readable, no images)
        jsonl_entry = {
            **metadata,
            "agent_text": trace.agent_text[:500],
            "tool_calls": trace.tool_calls,
            "novelty_flags": trace.novelty_flags,
        }
        with open(self._turns_path, "a") as f:
            f.write(json.dumps(jsonl_entry, default=str) + "\n")

        # Append to summary log (human-readable)
        self._write_summary(trace, turn_num)

    def _write_summary(self, trace: TurnTrace, turn_num: int) -> None:
        """Write a human-readable summary line."""
        with open(self._summary_path, "a") as f:
            f.write(f"--- Turn {turn_num} [{trace.game_mode}] "
                    f"{trace.map_name} ({trace.x},{trace.y}) ---\n")

            if trace.agent_text:
                # Truncate long text but keep it readable
                text = trace.agent_text.replace("\n", " ")
                if len(text) > 200:
                    text = text[:200] + "..."
                f.write(f"  Claude: {text}\n")

            for tc in trace.tool_calls:
                inp = tc.get("input", {})
                inp_str = ", ".join(f"{k}={v!r}" for k, v in inp.items())
                f.write(f"  → {tc['name']}({inp_str})\n")

            for tr in trace.tool_results:
                result_text = tr.get("result", "")[:100]
                f.write(f"  ← {tr['name']}: {result_text}\n")

            tokens = f"in={trace.input_tokens} out={trace.output_tokens}"
            if trace.cache_read_tokens:
                tokens += f" cache_read={trace.cache_read_tokens}"
            f.write(f"  [{tokens} | {trace.turn_duration_ms:.0f}ms | "
                    f"{trace.frames_advanced} frames]\n\n")

    def _write_if_nonempty(self, path: Path, content: str) -> None:
        """Write content to file only if non-empty."""
        if content and content.strip():
            path.write_text(content)

    def __repr__(self) -> str:
        return f"Tracer(dir={self._dir}, turns={self._turn_count})"
