#!/usr/bin/env python3
"""Live debug viewer — shows DS screens + real-time event stream.

Run this in a separate terminal while the agent loop is running.
Tails the event stream for real-time updates as actions happen.

Usage:
    python viewer.py [--live-dir PATH] [--scale N]

Default live dir: platinum_save/live/
"""

from __future__ import annotations

import argparse
import json
import time
from collections import deque
from pathlib import Path

import pygame
from PIL import Image

# Layout
DS_WIDTH = 256
DS_HEIGHT = 192
SCALE = 2
PANEL_WIDTH = 520  # Wider panel for debug info

SCALED_W = DS_WIDTH * SCALE
SCALED_H = DS_HEIGHT * SCALE

WINDOW_W = SCALED_W + PANEL_WIDTH
WINDOW_H = SCALED_H * 2

# Colors
BG = (20, 20, 28)
PANEL_BG = (28, 28, 36)
CONTEXT_BG = (24, 30, 40)  # Slightly different for context panel
TEXT = (200, 200, 210)
ACCENT = (100, 180, 255)
DIM = (110, 110, 130)
GOOD = (100, 210, 140)
WARN = (220, 180, 80)
ERR = (220, 80, 80)
SEPARATOR = (50, 50, 60)

MODE_COLORS = {
    "overworld": (80, 200, 120),
    "battle": (220, 80, 80),
    "battle_menu": (220, 120, 80),
    "dialogue": (100, 160, 220),
    "menu": (180, 140, 220),
    "transition": (140, 140, 140),
    "unknown": (90, 90, 100),
}

EVENT_COLORS = {
    "turn_start": ACCENT,
    "api_response": (180, 160, 255),
    "action_exec": GOOD,
    "turn_end": DIM,
    "error": ERR,
    "loop_start": WARN,
    "loop_stop": WARN,
}


def load_surface(path: Path, size: tuple[int, int]) -> pygame.Surface | None:
    """Load an image file as a scaled pygame surface."""
    try:
        if not path.exists():
            return None
        img = Image.open(path).convert("RGB")
        data = img.tobytes()
        surface = pygame.image.fromstring(data, img.size, "RGB")
        return pygame.transform.scale(surface, size)
    except Exception:
        return None


def wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if font.size(test)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class EventLog:
    """Tails the events.jsonl file and maintains a display buffer."""

    MAX_DISPLAY = 80  # Max lines to keep for display

    def __init__(self, events_path: Path) -> None:
        self._path = events_path
        self._file_pos = 0
        self._lines: deque[dict] = deque(maxlen=200)
        self._display: deque[tuple[str, tuple[int, int, int]]] = deque(maxlen=self.MAX_DISPLAY)

        # Current state extracted from events
        self.turn = 0
        self.mode = "unknown"
        self.map_name = ""
        self.pos = (0, 0)
        self.tokens_in = 0
        self.tokens_out = 0
        self.cache_read = 0
        self.duration_ms = 0.0
        self.api_calls = 0
        self.claude_text = ""
        self.context_text = ""
        self.dialogue = ""
        self.spatial = ""
        self.model = ""
        self.turn_cost = 0.0
        self.total_cost = 0.0

    def poll(self) -> int:
        """Read new events from the file. Returns number of new events."""
        if not self._path.exists():
            return 0

        count = 0
        try:
            with open(self._path, "r") as f:
                f.seek(self._file_pos)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        self._process_event(event)
                        count += 1
                    except json.JSONDecodeError:
                        pass
                self._file_pos = f.tell()
        except Exception:
            pass
        return count

    def _process_event(self, event: dict) -> None:
        """Process an event and update state + display log."""
        etype = event.get("type", "?")
        color = EVENT_COLORS.get(etype, DIM)

        if etype == "loop_start":
            self.model = event.get("model", "")
            fresh = "fresh" if event.get("fresh") else "savestate"
            self._add_line(f"=== Loop started ({self.model}, {fresh}) ===", WARN)

        elif etype == "turn_start":
            self.turn = event.get("turn", 0)
            self.mode = event.get("mode", "unknown")
            self.map_name = event.get("map", "")
            self.pos = tuple(event.get("pos", [0, 0]))
            self.context_text = event.get("state_text", "")
            self.dialogue = event.get("dialogue", "")
            self.spatial = event.get("spatial", "")
            self._add_line(f"--- Turn {self.turn} [{self.mode}] {self.map_name} {self.pos} ---", ACCENT)

        elif etype == "api_response":
            text = event.get("text", "")
            tool_calls = event.get("tool_calls", [])
            rnd = event.get("round", 0)
            prefix = f"  [round {rnd}] " if rnd else "  "

            # Show Claude's text (full — word wrap handles display)
            if text:
                for line in text.split("\n")[:8]:
                    line = line.strip()
                    if line:
                        self._add_line(f"{prefix}Claude: {line}", (180, 160, 255))
            self.claude_text = text

            # Show tool calls
            for tc in tool_calls:
                name = tc.get("name", "?")
                inp = tc.get("input", {})
                inp_str = ", ".join(f"{k}={v!r}" for k, v in inp.items())
                self._add_line(f"{prefix}  -> {name}({inp_str})", GOOD)

        elif etype == "action_exec":
            action = event.get("action", "?")
            inp = event.get("input", {})
            result = event.get("result", "")
            inp_str = ", ".join(f"{k}={v!r}" for k, v in inp.items())
            self._add_line(f"  <- {action}({inp_str}): {result}", (140, 200, 160))

        elif etype == "turn_end":
            self.duration_ms = event.get("duration_ms", 0)
            self.api_calls = event.get("api_calls", 0)
            self.tokens_in = event.get("tokens_in", 0)
            self.tokens_out = event.get("tokens_out", 0)
            self.cache_read = event.get("cache_read", 0)
            self.turn_cost = event.get("cost_usd", 0)
            self.total_cost = event.get("total_cost_usd", 0)
            frames = event.get("frames", 0)
            err = event.get("error")
            stats = (
                f"  [{self.duration_ms:.0f}ms | {self.api_calls} calls | "
                f"in={self.tokens_in} out={self.tokens_out} cache={self.cache_read} | "
                f"${self.turn_cost:.4f} this turn | ${self.total_cost:.4f} total]"
            )
            self._add_line(stats, DIM)
            if err:
                self._add_line(f"  ERROR: {err}", ERR)

        elif etype == "loop_stop":
            total = event.get("total_cost_usd", 0)
            calls = event.get("total_calls", 0)
            turns = event.get("total_turns", 0)
            self._add_line(f"=== Loop stopped: ${total:.4f} total, {calls} calls, {turns} turns ===", WARN)

        elif etype == "error":
            self._add_line(f"  ERROR: {event.get('error', '?')}", ERR)

    def _add_line(self, text: str, color: tuple[int, int, int]) -> None:
        self._display.append((text, color))

    def get_display_lines(self, n: int = 40) -> list[tuple[str, tuple[int, int, int]]]:
        """Get the most recent N display lines."""
        lines = list(self._display)
        return lines[-n:]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pokemon Platinum Debug Viewer")
    parser.add_argument("--live-dir", default="platinum_save/live",
                        help="Path to live frame directory")
    parser.add_argument("--scale", type=int, default=2,
                        help="Display scale (1-4)")
    args = parser.parse_args()

    live_dir = Path(args.live_dir)
    global SCALE, SCALED_W, SCALED_H, WINDOW_W, WINDOW_H, PANEL_WIDTH
    SCALE = max(1, min(4, args.scale))
    SCALED_W = DS_WIDTH * SCALE
    SCALED_H = DS_HEIGHT * SCALE
    WINDOW_W = SCALED_W + PANEL_WIDTH
    WINDOW_H = SCALED_H * 2

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.RESIZABLE)
    pygame.display.set_caption("Pokemon Platinum — Debug Viewer")

    # Fonts
    try:
        font = pygame.font.SysFont("monospace", 13)
        font_small = pygame.font.SysFont("monospace", 11)
        font_title = pygame.font.SysFont("monospace", 15, bold=True)
    except Exception:
        font = pygame.font.Font(None, 15)
        font_small = pygame.font.Font(None, 13)
        font_title = pygame.font.Font(None, 17)

    clock = pygame.time.Clock()
    event_log = EventLog(live_dir / "events.jsonl")
    last_frame_mtime = 0.0

    # Tab state for context panel
    context_tab = 0  # 0=event log, 1=full context
    TAB_NAMES = ["Events", "Context"]

    print(f"Watching: {live_dir}")
    print("Waiting for agent loop...")
    print("Keys: [1/2] switch tabs, [Q/Esc] quit, [C] clear log")

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif ev.key == pygame.K_1:
                    context_tab = 0
                elif ev.key == pygame.K_2:
                    context_tab = 1
                elif ev.key == pygame.K_c:
                    event_log._display.clear()

        # Poll for new events
        event_log.poll()

        # Check for frame updates
        top_path = live_dir / "top.png"
        try:
            if top_path.exists():
                mtime = top_path.stat().st_mtime
                if mtime != last_frame_mtime:
                    last_frame_mtime = mtime
        except Exception:
            pass

        # === RENDER ===
        screen.fill(BG)

        # --- Left side: DS screens ---
        top_surface = load_surface(live_dir / "top.png", (SCALED_W, SCALED_H))
        bot_surface = load_surface(live_dir / "bot.png", (SCALED_W, SCALED_H))

        if top_surface:
            screen.blit(top_surface, (0, 0))
        else:
            pygame.draw.rect(screen, (35, 35, 45), (0, 0, SCALED_W, SCALED_H))
            msg = font.render("Waiting for game...", True, DIM)
            screen.blit(msg, (SCALED_W // 2 - msg.get_width() // 2, SCALED_H // 2))

        if bot_surface:
            screen.blit(bot_surface, (0, SCALED_H))
        else:
            pygame.draw.rect(screen, (35, 35, 45), (0, SCALED_H, SCALED_W, SCALED_H))

        # Screen divider
        pygame.draw.line(screen, SEPARATOR, (0, SCALED_H), (SCALED_W, SCALED_H), 2)

        # Screen labels
        screen.blit(font_small.render("TOP", True, DIM), (4, 2))
        screen.blit(font_small.render("BOTTOM", True, DIM), (4, SCALED_H + 2))

        # --- Right side: debug panel ---
        panel_x = SCALED_W
        pygame.draw.rect(screen, PANEL_BG, (panel_x, 0, PANEL_WIDTH, WINDOW_H))
        pygame.draw.line(screen, SEPARATOR, (panel_x, 0), (panel_x, WINDOW_H), 2)

        px = panel_x + 8
        py = 6
        pw = PANEL_WIDTH - 16

        # Header: turn + mode + location
        turn_text = f"Turn {event_log.turn}" if event_log.turn else "Waiting..."
        header = font_title.render(turn_text, True, ACCENT)
        screen.blit(header, (px, py))

        if event_log.mode != "unknown":
            mode_color = MODE_COLORS.get(event_log.mode, DIM)
            mode_surf = font.render(f"[{event_log.mode.upper()}]", True, mode_color)
            screen.blit(mode_surf, (px + header.get_width() + 10, py + 1))
        py += 20

        # Location + model
        if event_log.map_name:
            loc = font_small.render(
                f"{event_log.map_name} ({event_log.pos[0]},{event_log.pos[1]})  |  {event_log.model}",
                True, DIM
            )
            screen.blit(loc, (px, py))
        py += 16

        # Token stats + cost
        if event_log.tokens_in or event_log.tokens_out:
            stats = font_small.render(
                f"in={event_log.tokens_in:,} out={event_log.tokens_out:,} "
                f"cache={event_log.cache_read:,} | "
                f"{event_log.api_calls} calls | {event_log.duration_ms:.0f}ms",
                True, DIM,
            )
            screen.blit(stats, (px, py))
        py += 14

        # Cost line
        if event_log.total_cost > 0:
            cost_color = WARN if event_log.total_cost > 0.10 else DIM
            cost = font_small.render(
                f"${event_log.turn_cost:.4f} this turn | ${event_log.total_cost:.4f} total",
                True, cost_color,
            )
            screen.blit(cost, (px, py))
        py += 18

        # Separator
        pygame.draw.line(screen, SEPARATOR, (px, py), (px + pw, py), 1)
        py += 4

        # Tab bar
        tab_x = px
        for i, name in enumerate(TAB_NAMES):
            is_active = i == context_tab
            color = ACCENT if is_active else DIM
            label = font.render(f"[{i+1}] {name}", True, color)
            screen.blit(label, (tab_x, py))
            tab_x += label.get_width() + 16

            if is_active:
                # Underline
                uw = label.get_width()
                pygame.draw.line(screen, color,
                                 (tab_x - 16 - uw, py + 16),
                                 (tab_x - 16, py + 16), 2)
        py += 22

        # Separator
        pygame.draw.line(screen, SEPARATOR, (px, py), (px + pw, py), 1)
        py += 4

        # Content area
        content_top = py
        content_height = WINDOW_H - content_top - 4

        if context_tab == 0:
            # === Event log (autoscroll — most recent at bottom) ===
            line_height = 14
            max_visible_lines = content_height // line_height

            # Pre-wrap all display lines
            all_wrapped: list[tuple[str, tuple[int, int, int]]] = []
            for text, color in event_log.get_display_lines(200):
                for wline in wrap_text(text, font_small, pw):
                    all_wrapped.append((wline, color))

            # Take only the last N that fit on screen
            visible = all_wrapped[-max_visible_lines:]
            for wline, color in visible:
                rendered = font_small.render(wline, True, color)
                screen.blit(rendered, (px, py))
                py += line_height

        elif context_tab == 1:
            # === Full context: state + dialogue + spatial ===
            pygame.draw.rect(screen, CONTEXT_BG, (px - 4, py, pw + 8, content_height))
            has_content = False

            # Section helper
            def _render_section(
                label: str, text: str, color: tuple[int, int, int]
            ) -> None:
                nonlocal py, has_content
                if not text:
                    return
                if has_content:
                    py += 4
                    pygame.draw.line(screen, SEPARATOR, (px, py), (px + pw, py), 1)
                    py += 4
                screen.blit(font_small.render(label, True, DIM), (px, py))
                py += 14
                for line in text.split("\n"):
                    if py > WINDOW_H - 4:
                        break
                    wrapped = wrap_text(line, font_small, pw) if line.strip() else [""]
                    for wline in wrapped:
                        rendered = font_small.render(wline, True, color)
                        screen.blit(rendered, (px, py))
                        py += 13
                        if py > WINDOW_H - 4:
                            break
                has_content = True

            _render_section("Game State:", event_log.context_text, (160, 180, 200))
            _render_section("Dialogue:", event_log.dialogue, (160, 200, 180))
            _render_section("Spatial:", event_log.spatial, (140, 160, 180))

            if not has_content:
                screen.blit(font.render("No context yet", True, DIM), (px, py))

        pygame.display.flip()
        clock.tick(15)  # 15fps for smoother updates

    pygame.quit()


if __name__ == "__main__":
    main()
