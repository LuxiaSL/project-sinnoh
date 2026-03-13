"""Live event stream for the debug viewer.

Writes timestamped events to an append-only JSONL file that the viewer
tails in real-time. Decouples "things happening in the loop" from
"viewer polling" — the loop writes events as they happen, the viewer
reads them as they appear.

Event types:
    turn_start    — New turn beginning, includes full context sent to Claude
    api_request   — About to call the API (shows what Claude will see)
    api_response  — Claude's response (text + tool calls)
    action_exec   — Action executed with result
    frame_update  — New screenshot written to disk
    turn_end      — Turn complete with timing/token summary
    loop_start    — Loop initialized
    loop_stop     — Loop shutting down
    error         — Something went wrong
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class EventStream:
    """Append-only event stream for live debugging.

    Usage:
        stream = EventStream(live_dir)
        stream.emit("turn_start", {"turn": 1, "context": ...})
        stream.emit("api_response", {"text": "...", "tool_calls": [...]})
    """

    def __init__(self, live_dir: Path) -> None:
        self._live_dir = live_dir
        self._live_dir.mkdir(parents=True, exist_ok=True)
        self._events_path = live_dir / "events.jsonl"
        self._seq = 0

        # Clear previous events on init (fresh run = fresh stream)
        self._events_path.write_text("")

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Write an event to the stream.

        Args:
            event_type: One of the event type strings (turn_start, api_response, etc.)
            data: Event-specific payload. Kept small — no base64 images.
        """
        self._seq += 1
        event = {
            "seq": self._seq,
            "t": time.time(),
            "type": event_type,
            **(data or {}),
        }

        try:
            line = json.dumps(event, default=str, separators=(",", ":"))
            with open(self._events_path, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass  # Never crash the game loop for viewer issues

    @property
    def path(self) -> Path:
        return self._events_path

    @property
    def live_dir(self) -> Path:
        return self._live_dir
