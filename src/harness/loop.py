"""Main agent loop — the core perceive → think → act cycle.

Orchestrates all harness components:
1. Advance emulator until idle (game waiting for input)
2. Capture game state (RAM + screenshots)
3. Send to Claude (with journal, dialogue, spatial grid)
4. Parse response (tool calls)
5. Execute actions (button press, walk, touch, wait)
6. Handle tool results (reference queries, journal writes)
7. Update spatial grid, fog-of-war, novelty
8. Record full trace
9. Repeat

Chapter break management:
- Monitor token usage
- Soft trigger: start watching for natural pauses at ~60K tokens
- Hard trigger: force break at ~80K tokens
- On break: prompt Claude to write summary, archive history, continue
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .actions import ActionExecutor, ActionResult
from .agent import AgentClient, AgentResponse, ToolCall
from .battle import BattleReader
from .collision import CollisionReader
from .dialogue import DialogueTranscript
from .events import EventStream
from .fogofwar import FogOfWar
from .formatter import format_battle, format_inventory, format_party_detail, format_state
from .game_state import BattleMenuState, GameMode, GameStateDetector
from .inventory import InventoryReader
from .journal import Journal
from .memory import MemoryReader
from .models import GameState
from .novelty import NoveltyTracker
from .screenshot import ScreenshotPipeline
from .spatial import SpatialGrid
from .tools import GAME_ACTION_NAMES, JOURNAL_TOOL_NAMES, REFERENCE_TOOL_NAMES
from .tracer import Tracer, TurnTrace

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME

logger = logging.getLogger(__name__)

# How many frames to advance per idle-check tick
FRAMES_PER_TICK = 4

# Max frames to advance while waiting for idle before forcing a query
MAX_IDLE_WAIT_FRAMES = 1200  # ~20 seconds at 60fps (needs headroom for fresh boot)

# Frames to advance after an action to let it settle
FRAMES_POST_ACTION = 10

# Dialogue text stability detection
# When text is scrolling, the dialogue box region (y=130-185) has high pixel diff.
# Once text is fully printed, diff drops to near zero (just the ▼ arrow bouncing).
DIALOGUE_BOX_DIFF_THRESHOLD = 0.005  # Fraction of pixels changed
DIALOGUE_STABLE_REQUIRED = 12  # Consecutive stable checks (~48 frames) before declaring idle
# Need enough checks to span the gap between characters (4fps text speed)


@dataclass
class LoopConfig:
    """Configuration for the agent loop."""
    # Paths
    save_dir: Path = field(default_factory=lambda: Path("platinum_save"))
    rom_path: str = ""
    savestate_path: str = ""

    # API
    api_key: str = ""
    model: str = "claude-sonnet-4-6"

    # Screenshot format
    screenshot_format: str = "png"  # "png" or "jpeg"
    include_bottom_screen: bool = True

    # Timing
    max_idle_wait: int = MAX_IDLE_WAIT_FRAMES
    frames_per_tick: int = FRAMES_PER_TICK

    # Context management (rolling window, actual token counts from API)
    # These are configured in agent.py constants — kept here for reference only

    # Live display
    live_frame_path: Optional[Path] = None  # Write latest frame here for external viewer

    # Tracing
    trace_dir: Optional[Path] = None  # None = auto-generate timestamped dir

    # Logging (legacy, kept for compat)
    log_screenshots: bool = True
    log_dir: Path = field(default_factory=lambda: Path("platinum_save/logs"))


@dataclass
class LoopStats:
    """Running statistics for the loop."""
    total_turns: int = 0
    total_actions: int = 0
    total_frames: int = 0
    chapter: int = 1
    start_time: float = field(default_factory=time.time)

    @property
    def elapsed_minutes(self) -> float:
        return (time.time() - self.start_time) / 60

    def summary(self) -> str:
        return (
            f"Turn {self.total_turns} | "
            f"Actions: {self.total_actions} | "
            f"Frames: {self.total_frames:,} | "
            f"Chapter: {self.chapter} | "
            f"Time: {self.elapsed_minutes:.1f}min"
        )


class AgentLoop:
    """The main game loop — perceive → think → act.

    Usage:
        loop = AgentLoop(emu, config)
        loop.setup()
        while loop.running:
            loop.step()
    """

    def __init__(self, emu: DeSmuME, config: LoopConfig) -> None:
        self._emu = emu
        self._config = config
        self._running = False
        self._stats = LoopStats()

        # Core components
        self._memory = MemoryReader(emu)
        self._screenshots = ScreenshotPipeline(emu, format=config.screenshot_format)
        self._actions = ActionExecutor(emu)
        self._game_state = GameStateDetector(emu)
        self._battle = BattleReader(emu)
        self._inventory = InventoryReader(emu)
        self._dialogue = DialogueTranscript(emu)

        # Persistence components
        save_dir = config.save_dir
        self._fog = FogOfWar(save_path=save_dir / "fogofwar.json")
        self._novelty = NoveltyTracker(save_path=save_dir / "novelty.json")
        self._spatial = SpatialGrid(
            fog_of_war=self._fog,
            save_path=save_dir / "spatial.json",
        )
        self._collision = CollisionReader(emu)
        self._journal = Journal(save_path=save_dir / "journal.json")

        # Fresh boot detection: the Rowan intro cutscene creates a stale
        # FieldSystem. When play time first becomes nonzero (gameplay starts),
        # we invalidate the collision reader so it re-finds the live FieldSystem.
        self._gameplay_started = False

        # Agent
        self._agent: Optional[AgentClient] = None
        self._pending_response: Optional[AgentResponse] = None  # Carried from previous step

        # Tracer
        self._tracer = Tracer(trace_dir=config.trace_dir)

        # Live event stream for debug viewer
        live_dir = config.live_frame_path or (config.save_dir / "live")
        self._events = EventStream(live_dir)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def stats(self) -> LoopStats:
        return self._stats

    @property
    def tracer(self) -> Tracer:
        return self._tracer

    def setup(self) -> None:
        """Initialize the agent and prepare for the loop."""
        # Initialize agent client
        self._agent = AgentClient(
            api_key=self._config.api_key,
            model=self._config.model,
        )

        # Ensure save directories exist
        self._config.save_dir.mkdir(parents=True, exist_ok=True)

        # Save run config to trace dir
        self._tracer.save_config({
            "model": self._config.model,
            "rom_path": self._config.rom_path,
            "savestate_path": self._config.savestate_path,
            "screenshot_format": self._config.screenshot_format,
            "include_bottom_screen": self._config.include_bottom_screen,
            "max_idle_wait": self._config.max_idle_wait,
            "frames_per_tick": self._config.frames_per_tick,
            "context_rotate_threshold": 170_000,
            "context_hard_ceiling": 195_000,
        })

        # Try to find dialogue buffers (may not exist yet in fresh boot)
        # The dialogue system will periodically rescan during poll() calls
        try:
            addr = self._dialogue.find_buffer()
            if addr:
                n = len(self._dialogue._known_addrs)
                logger.info(f"Dialogue: found {n} buffer(s) at setup")
            else:
                logger.info("Dialogue: no buffers yet (will rescan during play)")
        except Exception:
            logger.info("Dialogue: initial scan failed (will rescan during play)")

        self._running = True
        logger.info(f"Agent loop initialized. Model: {self._config.model}")
        logger.info(f"Trace dir: {self._tracer.trace_dir}")

        self._events.emit("loop_start", {
            "model": self._config.model,
            "rom": self._config.rom_path,
            "fresh": not bool(self._config.savestate_path),
        })

    def step(self) -> TurnTrace:
        """Execute one full turn of the agent loop.

        Returns a TurnTrace with all captured data.
        """
        if not self._running or self._agent is None:
            trace = TurnTrace(error="Loop not running")
            return trace

        turn_start = time.time()
        trace = TurnTrace(turn_number=self._stats.total_turns + 1)
        api_calls_before = self._agent.usage.total_calls

        try:
            # Check if we have pending tool calls from the previous step
            if self._pending_response and self._pending_response.tool_calls:
                response = self._pending_response
                self._pending_response = None

                trace.agent_text = response.text or ""
                trace.tool_calls = [
                    {"name": tc.name, "input": tc.input} for tc in response.tool_calls
                ]
                trace.stop_reason = response.stop_reason

                # Still need game state for trace metadata
                try:
                    player = self._memory.read_player()
                    trace.map_name = player.map_name
                    trace.map_id = player.map_id
                    trace.x = player.x
                    trace.y = player.y
                    trace.party_count = player.party_count
                    trace.badge_count = player.badge_count
                except Exception:
                    pass

                # Poll dialogue so mode detection works on pending turns
                self._dialogue.poll()
                has_dialogue = self._dialogue.is_active
                mode = self._game_state.detect(has_dialogue=has_dialogue)
                trace.game_mode = mode.value

                # Capture state for the viewer and trace even on pending turns
                dialogue_text = self._dialogue.format_transcript()
                spatial_grid = ""
                state_text = ""
                try:
                    player = self._memory.read_player()
                    party = self._memory.read_party()
                    game_state = GameState(player=player, party=party)
                    available_actions = self._game_state.available_action_types(mode)
                    state_text = format_state(
                        game_state,
                        game_mode=mode.value,
                        available_actions=available_actions,
                    )
                    spatial_grid = self._spatial.format_grid(
                        map_id=player.map_id,
                        player_x=player.x,
                        player_y=player.y,
                        map_name=player.map_name,
                        collision_reader=self._collision,
                    )
                except Exception:
                    pass

                # Populate trace fields for the tracer
                trace.state_text = state_text
                trace.spatial_grid = spatial_grid
                trace.dialogue_text = dialogue_text

                self._events.emit("turn_start", {
                    "turn": trace.turn_number,
                    "mode": mode.value,
                    "map": trace.map_name,
                    "pos": [trace.x, trace.y],
                    "pending": True,
                    "state_text": state_text,
                    "dialogue": dialogue_text,
                    "spatial": spatial_grid,
                })

                # Handle the pending tool calls
                frames_before = self._actions.total_frames
                self._handle_tool_calls(response, trace)
                trace.frames_advanced = self._actions.total_frames - frames_before

            else:
                self._pending_response = None

                # 1. Wait for idle state
                idle_start_frames = self._actions.total_frames
                mode = self._wait_for_idle()
                trace.game_mode = mode.value
                trace.idle_wait_frames = self._actions.total_frames - idle_start_frames

                # 2. Capture game state
                capture = self._capture_state(mode)
                trace.state_text = capture["state_text"]
                trace.spatial_grid = capture["spatial_grid"]
                trace.dialogue_text = capture["dialogue_text"]
                trace.journal_text = capture["journal_text"]
                trace.novelty_flags = capture["novelty_flags"] or []
                trace.screenshots_b64 = capture["screenshots"] or []

                # Player info for trace
                trace.player_name = capture["player_name"]
                trace.map_name = capture["map_name"]
                trace.map_id = capture["map_id"]
                trace.x = capture["x"]
                trace.y = capture["y"]
                trace.party_count = capture["party_count"]
                trace.badge_count = capture["badge_count"]
                trace.in_battle = capture["in_battle"]
                trace.raw_state = capture.get("raw_state", {})

                # Emit turn_start with Claude's full context
                self._update_live_frame()
                self._events.emit("turn_start", {
                    "turn": trace.turn_number,
                    "mode": mode.value,
                    "map": trace.map_name,
                    "pos": [trace.x, trace.y],
                    "state_text": trace.state_text,
                    "dialogue": trace.dialogue_text[:500] if trace.dialogue_text else "",
                    "spatial": trace.spatial_grid[:300] if trace.spatial_grid else "",
                    "novelty": trace.novelty_flags,
                    "journal_preview": (trace.journal_text[:200] + "...") if len(trace.journal_text or "") > 200 else trace.journal_text,
                })

                # 3. Send to Claude
                response = self._agent.send_turn(
                    game_state_text=capture["state_text"],
                    screenshots=capture["screenshots"],
                    journal_text=capture["journal_text"],
                    dialogue_text=capture["dialogue_text"],
                    spatial_grid=capture["spatial_grid"],
                    novelty_flags=capture["novelty_flags"],
                )

                trace.agent_text = response.text
                trace.tool_calls = [
                    {"name": tc.name, "input": tc.input} for tc in response.tool_calls
                ]
                trace.stop_reason = response.stop_reason

                # Emit Claude's response
                self._events.emit("api_response", {
                    "turn": trace.turn_number,
                    "text": response.text,
                    "tool_calls": [
                        {"name": tc.name, "input": tc.input}
                        for tc in response.tool_calls
                    ],
                    "stop_reason": response.stop_reason,
                })

                # 4. Handle tool calls
                frames_before_actions = self._actions.total_frames
                self._handle_tool_calls(response, trace)
                trace.frames_advanced = self._actions.total_frames - frames_before_actions

            # 5. Check if context window needs rotation
            self._check_context_rotation(mode)

            # 6. Update stats
            self._stats.total_turns += 1
            self._stats.total_frames = self._actions.total_frames

            # 7. Token usage
            trace.api_calls_this_turn = self._agent.usage.total_calls - api_calls_before
            usage = response.usage
            trace.input_tokens = usage.get("input_tokens", 0)
            trace.output_tokens = usage.get("output_tokens", 0)
            trace.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            trace.cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)

            # Log to console
            text_preview = response.text[:100].replace("\n", " ")
            logger.info(
                f"Turn {self._stats.total_turns}: [{mode.value}] "
                f"{trace.map_name} ({trace.x},{trace.y}) — "
                f"{text_preview}{'...' if len(response.text) > 100 else ''}"
            )

        except KeyboardInterrupt:
            self._running = False
            logger.info("Loop interrupted by user")
            trace.error = "interrupted"
        except Exception as e:
            logger.error(f"Error in turn: {e}", exc_info=True)
            trace.error = str(e)

        # 8. Record timing and persist trace
        trace.turn_duration_ms = (time.time() - turn_start) * 1000
        self._tracer.record_turn(trace)

        # 9. Write live frame for external viewer
        self._write_live_frame(trace)

        # 10. End turn on cost tracker + emit turn_end event
        turn_cost = 0.0
        if self._agent:
            turn_cost = self._agent.costs.end_turn()

        self._events.emit("turn_end", {
            "turn": trace.turn_number,
            "duration_ms": trace.turn_duration_ms,
            "api_calls": trace.api_calls_this_turn,
            "tokens_in": trace.input_tokens,
            "tokens_out": trace.output_tokens,
            "cache_read": trace.cache_read_tokens,
            "frames": trace.frames_advanced,
            "cost_usd": round(turn_cost, 6),
            "total_cost_usd": round(self._agent.costs.total_cost, 6) if self._agent else 0,
            "error": trace.error or None,
        })

        return trace

    def _wait_for_idle(self) -> GameMode:
        """Advance frames until the game is idle and waiting for input.

        Also auto-advances through trivial states (blank screens, logos)
        that don't need Claude's attention. Dialogue is NOT auto-advanced —
        Claude reads that.

        For dialogue: uses dual-signal stability detection:
        1. Dialogue buffer (RAM) — stops changing when full text is loaded
        2. Pixel diff (screen) — stops changing when TextPrinter finishes
        Both must be stable before we declare idle.
        """
        import numpy as np

        frames_waited = 0
        has_dialogue = False
        auto_advance_cooldown = 0
        last_buffer_text: str | None = None
        buffer_stable_count = 0
        pixel_stable_count = 0

        while frames_waited < self._config.max_idle_wait:
            # Advance a few frames
            for _ in range(self._config.frames_per_tick):
                self._emu.cycle(with_joystick=False)
                frames_waited += 1

            # Poll dialogue
            self._dialogue.poll()
            current_text = self._dialogue.read_current()
            has_dialogue = self._dialogue.is_active

            # Capture frame for pixel diff + blank detection
            frame = None
            try:
                buf = self._emu.display_buffer_as_rgbx()
                frame = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)[:, :, :3].copy()
            except Exception:
                pass

            # Auto-advance trivial states (logos, health warnings, fades)
            if frame is not None and not has_dialogue and auto_advance_cooldown <= 0:
                if self._is_trivial_screen(frame):
                    self._auto_advance_trivial()
                    auto_advance_cooldown = 30
                    logger.debug(f"Auto-advancing trivial screen at frame {frames_waited}")
                    continue

            auto_advance_cooldown -= self._config.frames_per_tick

            # Check base idle state
            if not self._game_state.is_idle(frame=frame, has_dialogue=has_dialogue):
                buffer_stable_count = 0
                pixel_stable_count = 0
                continue

            # If dialogue is active, wait for BOTH buffer and pixel stability
            if has_dialogue:
                # Signal 1: Buffer content stability
                if current_text != last_buffer_text:
                    last_buffer_text = current_text
                    buffer_stable_count = 0
                    pixel_stable_count = 0
                else:
                    buffer_stable_count += 1

                if buffer_stable_count < DIALOGUE_STABLE_REQUIRED:
                    continue  # Buffer still changing

                # Signal 2: Pixel stability (rendering done)
                if frame is not None:
                    box_diff = self._dialogue_box_diff(frame)
                    if box_diff > DIALOGUE_BOX_DIFF_THRESHOLD:
                        pixel_stable_count = 0
                        continue
                    else:
                        pixel_stable_count += 1
                        if pixel_stable_count < 4:  # ~16 frames after buffer settles
                            continue
                # Both signals stable — fall through to idle

            break

        return self._game_state.detect(has_dialogue=has_dialogue)

    def _settle_after_actions(self, after_button_press: bool = False) -> None:
        """Wait for screen to stabilize after executing game actions.

        Runs after tool execution in _handle_tool_calls(). Ensures the
        screenshot Claude sees in tool results shows fully-rendered text
        and settled animations. Without this, pending turns skip
        _wait_for_idle() and Claude sees mid-render text.

        Uses TWO signals for dialogue stability:
        1. **Dialogue buffer (RAM)**: The msgBuf gets the full formatted
           message BEFORE the TextPrinter starts rendering. When it stops
           changing, the full text is ready.
        2. **Pixel diff (screen)**: After the buffer stabilizes, wait for
           the dialogue box pixels to settle (rendering done).

        Falls back to pixel-only stability when dialogue buffers haven't
        been discovered yet (e.g., after a resume from savestate).

        Args:
            after_button_press: If True, a button was pressed that could
                advance dialogue. We wait longer for potential new text
                to appear, preventing rapid A-mash chains where Claude
                sees the same screenshot repeatedly.
        """
        import numpy as np

        MAX_SETTLE_FRAMES = 600  # ~10 seconds at 60fps
        # After a button press, wait longer — new dialogue text takes
        # ~120 frames to fully render after pressing A. During the gap
        # between old text disappearing and new text appearing,
        # is_active returns False (stale). We must wait past this gap
        # before trusting the dialogue status.
        # Pokemon is never truly time-sensitive, so err on the side of
        # waiting longer to get a clean screenshot with fully rendered text.
        MIN_SETTLE_FRAMES = 300 if after_button_press else 30

        frames_waited = 0
        last_buffer_text: str | None = None
        buffer_stable_count = 0
        pixel_stable_count = 0

        # How many consecutive stable checks before we're confident.
        # More conservative values prevent exiting during brief gaps
        # between rendered characters (text prints char-by-char).
        BUFFER_STABLE_REQUIRED = 10   # ~40 frames of unchanged buffer
        PIXEL_STABLE_AFTER_BUFFER = 8  # ~32 frames of stable pixels after buffer settles
        PIXEL_ONLY_STABLE_REQUIRED = DIALOGUE_STABLE_REQUIRED  # Fallback when no buffers

        # Force a buffer rescan at the start if we have no known buffers.
        # This is critical after resume — the old buffer addresses are stale.
        if not self._dialogue._known_addrs:
            self._dialogue._rescan_buffers()

        while frames_waited < MAX_SETTLE_FRAMES:
            for _ in range(self._config.frames_per_tick):
                self._emu.cycle(with_joystick=False)
                frames_waited += 1

            # Poll dialogue buffers
            self._dialogue.poll()
            current_text = self._dialogue.read_current()
            has_dialogue = self._dialogue.is_active

            # --- Path A: No active dialogue detected ---
            # Either buffers haven't been discovered, text is stale, or
            # we're in the gap between pressing A and new text appearing.
            # Always wait at least MIN_SETTLE_FRAMES before exiting.
            # After that, if dialogue becomes active, switch to Path B.
            if not has_dialogue:
                if frames_waited >= MIN_SETTLE_FRAMES:
                    break
                continue

            # --- Path B: Dialogue buffer available (preferred) ---
            # Signal 1: Buffer content stability
            if current_text != last_buffer_text:
                last_buffer_text = current_text
                buffer_stable_count = 0
                pixel_stable_count = 0  # Reset pixel too — new content
            else:
                buffer_stable_count += 1

            if buffer_stable_count < BUFFER_STABLE_REQUIRED:
                continue  # Buffer still changing

            # Signal 2: Pixel stability (rendering done)
            try:
                buf = self._emu.display_buffer_as_rgbx()
                frame = np.frombuffer(buf, dtype=np.uint8).reshape(
                    384, 256, 4
                )[:, :, :3].copy()
                box_diff = self._dialogue_box_diff(frame)

                if box_diff > DIALOGUE_BOX_DIFF_THRESHOLD:
                    pixel_stable_count = 0
                else:
                    pixel_stable_count += 1
                    if pixel_stable_count >= PIXEL_STABLE_AFTER_BUFFER:
                        break  # Both buffer and pixels stable
            except Exception:
                break

        if frames_waited > MIN_SETTLE_FRAMES:
            logger.debug(
                f"Settled after {frames_waited} frames "
                f"(buf_stable={buffer_stable_count}, px_stable={pixel_stable_count}, "
                f"has_dlg={has_dialogue})"
            )

    def _dialogue_box_diff(self, frame: "np.ndarray") -> float:
        """Compute pixel diff in the dialogue box region of the top screen.

        The dialogue box occupies roughly y=130-185 on the top screen.
        Returns fraction of pixels that changed since last check.
        Returns 1.0 on the first call (no previous frame to compare) to
        force at least one real comparison before declaring stable.
        """
        import numpy as np

        # Extract dialogue box region from top screen
        box = frame[130:185, :, :3]

        if not hasattr(self, "_last_dialogue_box") or self._last_dialogue_box is None:
            self._last_dialogue_box = box.copy()
            return 1.0  # Force unstable on first call — need real comparison

        diff = np.abs(box.astype(np.int16) - self._last_dialogue_box.astype(np.int16))
        changed = np.any(diff > 10, axis=2).sum()
        total = box.shape[0] * box.shape[1]

        self._last_dialogue_box = box.copy()
        return changed / total

    def _is_trivial_screen(self, frame: "np.ndarray") -> bool:
        """Check if the current frame is a trivial screen that can be auto-advanced.

        Trivial screens:
        - All black or all white (fade transitions, loading)
        - Nearly uniform color (logo screens with minimal content)

        NOT trivial:
        - Screens with dialogue text (Claude reads these)
        - Screens with meaningful game content (overworld, battle, menus)
        """
        import numpy as np

        # Check top screen only (192x256x3)
        top = frame[:192]

        # Compute color variance — trivial screens have very low variance
        # A blank screen has variance ≈ 0, a logo screen might be ~5-15,
        # actual gameplay is typically 30+
        mean_color = top.mean(axis=(0, 1))
        variance = np.mean((top.astype(np.float32) - mean_color) ** 2)

        # Threshold: screens with very low visual complexity
        # Tuned conservatively — only catch truly blank/logo screens
        return variance < 200.0

    def _auto_advance_trivial(self) -> None:
        """Press A + touch center to auto-advance trivial blank screens.

        Both inputs are needed because different screens respond to different
        inputs: health/safety screen requires touch, logos require A, etc.
        """
        from desmume.controls import keymask, Keys

        # Press A
        mask = keymask(Keys.KEY_A)
        self._emu.input.keypad_add_key(mask)
        # Also touch center of bottom screen (128, 96)
        self._emu.input.touch_set_pos(128, 96)
        for _ in range(6):
            self._emu.cycle(with_joystick=False)
        self._emu.input.keypad_rm_key(mask)
        self._emu.input.touch_release()
        for _ in range(4):
            self._emu.cycle(with_joystick=False)

    def _capture_state(self, mode: GameMode) -> dict[str, Any]:
        """Capture all game state for the current turn.

        Returns a dict with all captured data (for both API call and tracing).
        """
        # Read game state from RAM
        try:
            player = self._memory.read_player()
            party = self._memory.read_party()
            game_state = GameState(player=player, party=party)
        except Exception as e:
            logger.error(f"Error reading game state: {e}")
            from .models import Party, PlayerState
            player = PlayerState()
            party = Party()
            game_state = GameState(player=player, party=party)

        # Fresh boot detection: invalidate collision reader when gameplay starts.
        # The Rowan intro cutscene creates a stale FieldSystem with outdoor data.
        # When play_time first ticks above 0, the real gameplay FieldSystem exists.
        if not self._gameplay_started:
            total_play = player.play_hours * 3600 + player.play_minutes * 60 + player.play_seconds
            if total_play > 0:
                self._gameplay_started = True
                self._collision.invalidate()
                logger.info("Gameplay started — invalidated collision reader for fresh FieldSystem")

        # Battle state (if in battle)
        in_battle = False
        if mode in (GameMode.BATTLE, GameMode.BATTLE_MENU):
            try:
                battle_state = self._battle.read_battle_state()
                if battle_state:
                    game_state.in_battle = True
                    game_state.battle = battle_state
                    in_battle = True
            except Exception as e:
                logger.error(f"Error reading battle state: {e}")

        # Available actions for this mode
        available_actions = self._game_state.available_action_types(mode)

        # Format state text
        if game_state.in_battle and game_state.battle:
            bs = game_state.battle
            state_text = format_battle(
                player_pokemon=party.pokemon[0] if party.pokemon else None,
                enemy_species=bs.enemy_pokemon.species_name if bs.enemy_pokemon else "???",
                enemy_level=bs.enemy_pokemon.level if bs.enemy_pokemon else 0,
                enemy_types=bs.enemy_pokemon.types if bs.enemy_pokemon else None,
                enemy_hp_fraction=bs.enemy_pokemon.hp_fraction if bs.enemy_pokemon else 1.0,
                is_wild=bs.is_wild,
            )
        else:
            state_text = format_state(
                game_state,
                game_mode=mode.value,
                available_actions=available_actions,
            )

        # Update fog-of-war
        self._fog.visit(player.map_id, player.x, player.y)

        # Initialize collision reader (lazy — finds FieldSystem on first call).
        # Also re-find if returning no valid grid (stale from cutscene).
        if not self._collision.is_available:
            try:
                self._collision.find_field_system()
            except Exception as e:
                logger.debug(f"Collision reader init: {e}")
        elif self._collision.read_player_grid(player.x, player.y) is None:
            try:
                self._collision.find_field_system(force=True)
            except Exception as e:
                logger.debug(f"Collision reader re-find: {e}")

        # Screenshots
        screenshots: list[dict[str, str]] | None = None
        try:
            cap = self._screenshots.capture(encode=True)
            screenshots = [
                {"media_type": self._screenshots.media_type, "data": cap.top_b64},
            ]
            if self._config.include_bottom_screen:
                screenshots.append(
                    {"media_type": self._screenshots.media_type, "data": cap.bottom_b64},
                )
        except Exception as e:
            logger.error(f"Error capturing screenshots: {e}")

        # Journal
        journal_text = self._journal.format_for_context()

        # Dialogue
        dialogue_text = self._dialogue.format_transcript()

        # Spatial grid (with collision data from RAM when available)
        spatial_grid = self._spatial.format_grid(
            map_id=player.map_id,
            player_x=player.x,
            player_y=player.y,
            map_name=player.map_name,
            collision_reader=self._collision,
        )

        # Novelty
        encountered_species = None
        if game_state.in_battle and game_state.battle and game_state.battle.enemy_pokemon:
            encountered_species = game_state.battle.enemy_pokemon.species_id

        novelty_flags = self._novelty.check(
            player=player,
            party=party,
            encountered_species=encountered_species,
        )

        return {
            "state_text": state_text,
            "screenshots": screenshots,
            "journal_text": journal_text,
            "dialogue_text": dialogue_text,
            "spatial_grid": spatial_grid,
            "novelty_flags": novelty_flags or None,
            # Player data for trace
            "player_name": player.name,
            "map_name": player.map_name,
            "map_id": player.map_id,
            "x": player.x,
            "y": player.y,
            "party_count": player.party_count,
            "badge_count": player.badge_count,
            "in_battle": in_battle,
            # Raw harness state for trace debugging
            "raw_state": self._build_raw_state(player, party, game_state),
        }

    def _build_raw_state(self, player: Any, party: Any, game_state: Any) -> dict[str, Any]:
        """Build raw harness state dump for trace debugging.

        This captures the actual underlying state — not what's formatted for
        Claude, but the real data from RAM and harness modules. Useful for
        validating that perception is working correctly.
        """
        raw: dict[str, Any] = {}

        # Full player state
        try:
            raw["player"] = {
                "name": player.name,
                "trainer_id": player.trainer_id,
                "secret_id": player.secret_id,
                "money": player.money,
                "gender_name": player.gender_name,
                "badges": player.badge_list,
                "badge_bits": player.badges,
                "play_time": player.play_time_str,
                "map_id": player.map_id,
                "map_name": player.map_name,
                "x": player.x,
                "y": player.y,
                "party_count": player.party_count,
            }
        except Exception as e:
            raw["player_error"] = str(e)

        # Full party data
        try:
            raw["party"] = []
            for p in party.pokemon:
                raw["party"].append({
                    "slot": p.slot,
                    "species": f"{p.species_name} (#{p.species_id})",
                    "nickname": p.nickname,
                    "level": p.level,
                    "hp": f"{p.hp_current}/{p.hp_max}",
                    "types": p.types,
                    "status": p.status_display(),
                    "nature": p.nature.name if p.nature else "???",
                    "ability": p.ability_name,
                    "held_item": p.held_item_name or "None",
                    "moves": [
                        {"name": m.name, "type": m.type, "pp": f"{m.pp_current}/{m.pp_max}"}
                        for m in p.moves
                    ],
                    "stats": {
                        "atk": p.attack, "def": p.defense,
                        "spa": p.sp_attack, "spd": p.sp_defense, "spe": p.speed,
                    },
                    "is_egg": p.is_egg,
                    "is_shiny": p.is_shiny,
                })
        except Exception as e:
            raw["party_error"] = str(e)

        # Fog of war stats
        try:
            raw["fog_of_war"] = {
                "maps_explored": len(self._fog.visited_maps()),
                "tiles_on_current_map": self._fog.tiles_visited(player.map_id),
                "total_tiles": sum(
                    self._fog.tiles_visited(m) for m in self._fog.visited_maps()
                ),
                "current_map_grid": self._fog.render_grid(
                    player.map_id, player.x, player.y, radius=5
                ),
            }
        except Exception as e:
            raw["fog_of_war_error"] = str(e)

        # Spatial grid raw tile data
        try:
            tiles = self._spatial._tile_types.get(player.map_id, {})
            raw["spatial"] = {
                "known_tiles": len(tiles),
                "walkable": sum(1 for t in tiles.values() if t.value == "."),
                "walls": sum(1 for t in tiles.values() if t.value == "#"),
            }
        except Exception as e:
            raw["spatial_error"] = str(e)

        # Novelty tracker stats
        try:
            raw["novelty"] = {
                "species_seen": self._novelty.species_seen_count,
                "maps_visited": self._novelty.maps_visited_count,
            }
        except Exception as e:
            raw["novelty_error"] = str(e)

        # Dialogue buffer info
        try:
            raw["dialogue"] = {
                "buffer_found": self._dialogue.buffer_found,
                "transcript_lines": self._dialogue.line_count,
                "recent_lines": self._dialogue.get_transcript(5),
            }
        except Exception as e:
            raw["dialogue_error"] = str(e)

        # Battle state
        if game_state.in_battle and game_state.battle:
            try:
                bs = game_state.battle
                raw["battle"] = {
                    "is_wild": bs.is_wild,
                    "enemy": {
                        "species": bs.enemy_pokemon.species_name if bs.enemy_pokemon else "?",
                        "level": bs.enemy_pokemon.level if bs.enemy_pokemon else 0,
                        "hp": f"{bs.enemy_pokemon.hp_current}/{bs.enemy_pokemon.hp_max}" if bs.enemy_pokemon else "?",
                        "types": bs.enemy_pokemon.types if bs.enemy_pokemon else [],
                    } if bs.enemy_pokemon else None,
                    "player_active": {
                        "species": bs.player_pokemon.species_name if bs.player_pokemon else "?",
                        "level": bs.player_pokemon.level if bs.player_pokemon else 0,
                        "hp": f"{bs.player_pokemon.hp_current}/{bs.player_pokemon.hp_max}" if bs.player_pokemon else "?",
                    } if bs.player_pokemon else None,
                }
            except Exception as e:
                raw["battle_error"] = str(e)

        # Journal stats
        try:
            raw["journal"] = {
                "total_entries": self._journal.entry_count(),
                "current_chapter": self._journal.current_chapter,
                "sections": {
                    s: self._journal.entry_count(s) for s in ["current_goals", "team_notes", "adventure_log", "strategy", "map_notes"]
                },
            }
        except Exception as e:
            raw["journal_error"] = str(e)

        return raw

    def _capture_game_context(self) -> str:
        """Capture current game state, spatial grid, and dialogue as text.

        This is included in tool result messages so Claude always has
        up-to-date spatial awareness — not just screenshots. Without this,
        pending turns (which are the majority) would have no grid, no
        dialogue transcript, and no state text.
        """
        parts: list[str] = []

        try:
            player = self._memory.read_player()
            party = self._memory.read_party()
            game_state = GameState(player=player, party=party)

            # Force a buffer rescan so we catch newly-allocated dialogue
            # buffers (e.g., NPC dialogue after pressing A through prior text).
            # With the narrowed scan range (skip RAM mirror), this takes ~0.4s.
            self._dialogue._rescan_buffers()
            self._dialogue.poll()
            has_dialogue = self._dialogue.is_active
            mode = self._game_state.detect(has_dialogue=has_dialogue)
            available_actions = self._game_state.available_action_types(mode)

            # Game state text
            state_text = format_state(
                game_state,
                game_mode=mode.value,
                available_actions=available_actions,
            )
            parts.append(state_text)

            # Update fog-of-war
            self._fog.visit(player.map_id, player.x, player.y)

            # Initialize collision reader if needed.
            # Also re-find if available but returning no valid grid — the
            # FieldSystem may be stale from an intro/cutscene transition.
            if not self._collision.is_available:
                try:
                    self._collision.find_field_system()
                except Exception:
                    pass
            elif self._collision.read_player_grid(player.x, player.y) is None:
                try:
                    self._collision.find_field_system(force=True)
                except Exception:
                    pass

            # Spatial grid
            spatial_grid = self._spatial.format_grid(
                map_id=player.map_id,
                player_x=player.x,
                player_y=player.y,
                map_name=player.map_name,
                collision_reader=self._collision,
            )
            if spatial_grid:
                parts.append(spatial_grid)

            # Dialogue transcript
            dialogue_text = self._dialogue.format_transcript()
            if dialogue_text:
                parts.append(dialogue_text)

        except Exception as e:
            logger.debug(f"Error capturing game context: {e}")

        return "\n\n".join(parts)

    def _handle_tool_calls(self, response: AgentResponse, trace: TurnTrace) -> None:
        """Process tool calls from Claude's response.

        Simple approach (matches Claude Plays Pokemon starter pattern):
        - Execute ALL tool calls from the response
        - Send ALL results back in one message
        - That's it. One round per step(). No inner loop.

        Claude's response to the tool results becomes the starting point
        for the NEXT step(). Any tool calls in that response are handled
        by storing the pending response and processing it next step.

        This avoids the orphaned-tool-use problem entirely — there's always
        exactly one send_batch_tool_results per step, and the response is
        always properly paired.
        """
        if not self._agent:
            return

        if not response.tool_calls:
            return

        # Execute ALL tool calls from this response
        batch_results: list[dict[str, Any]] = []
        last_game_action_idx = -1

        for tc in response.tool_calls:
            result = self._execute_tool(tc)

            # Record in trace
            trace.tool_results.append({
                "name": tc.name,
                "input": tc.input,
                "result": result["text"],
                "is_error": result.get("is_error", False),
            })

            if tc.name in GAME_ACTION_NAMES:
                trace.actions_executed.append({
                    "action": tc.name,
                    "input": tc.input,
                    "result": result["text"],
                })
                last_game_action_idx = len(batch_results)

            batch_results.append({
                "tool_call_id": tc.id,
                "result": result["text"],
                "is_error": result.get("is_error", False),
            })

        # After all game actions, wait for the screen to stabilize before
        # capturing the screenshot. This ensures Claude sees fully-rendered
        # text and settled animations, not mid-scroll garbage. Without this,
        # pending turns skip _wait_for_idle() and Claude wastes turns saying
        # "still animating, let me wait."
        game_context = ""
        if last_game_action_idx >= 0:
            # Check if any action was a button press (could advance dialogue)
            had_button_press = any(
                tc.name == "press_button" for tc in response.tool_calls
                if tc.name in GAME_ACTION_NAMES
            )
            self._settle_after_actions(after_button_press=had_button_press)
            try:
                cap = self._screenshots.capture(encode=True)
                images = [
                    {"media_type": self._screenshots.media_type, "data": cap.top_b64},
                ]
                if self._config.include_bottom_screen:
                    images.append(
                        {"media_type": self._screenshots.media_type, "data": cap.bottom_b64},
                    )
                batch_results[last_game_action_idx]["images"] = images
            except Exception as e:
                logger.debug(f"Failed to capture mid-turn screenshot: {e}")

            # Capture updated game state so Claude always has current info.
            # Without this, pending turns chain indefinitely with no spatial
            # grid, no dialogue updates, and no game state — Claude navigates
            # blind using only screenshots.
            game_context = self._capture_game_context()

        # Send ALL results back in one message. Claude's response to this
        # becomes the pending state for next step — we don't loop.
        continuation = self._agent.send_batch_tool_results(
            batch_results, game_context=game_context,
        )

        # Record continuation text
        if continuation.text:
            trace.agent_text += "\n" + continuation.text

        # If Claude wants more tools, store them as pending for next step.
        # They'll be the first thing handled when step() runs again.
        #
        # EXCEPTION: if the continuation has tool calls but NO text, don't
        # store as pending. This breaks the A-mash chain — when Claude sends
        # raw tool calls without commentary, we force a full fresh turn
        # (wait for idle → capture state → send to Claude) so it sees the
        # updated game state and has to engage with what's on screen.
        if continuation.tool_calls and continuation.text:
            self._pending_response = continuation
            new_calls = [
                {"name": tc.name, "input": tc.input}
                for tc in continuation.tool_calls
            ]
            trace.tool_calls.extend(new_calls)
            self._events.emit("api_response", {
                "turn": trace.turn_number,
                "text": continuation.text or "",
                "tool_calls": new_calls,
                "pending": True,
            })
        else:
            if continuation.tool_calls and not continuation.text:
                # Claude sent tool calls without any commentary — A-mashing.
                # Don't execute these. The _fix_orphaned_tool_uses safety net
                # in _call_api will clean up the orphaned tool_use blocks
                # before the next API call.
                logger.debug(
                    f"Dropping text-less pending chain "
                    f"({len(continuation.tool_calls)} tool calls) — "
                    f"orphan fixer will handle cleanup"
                )
            self._pending_response = None

    def _execute_tool(self, tc: ToolCall) -> dict[str, Any]:
        """Execute a single tool call and return the result."""

        # === Game actions ===
        if tc.name in GAME_ACTION_NAMES:
            return self._execute_game_action(tc)

        # === Reference tools ===
        if tc.name in REFERENCE_TOOL_NAMES:
            return self._execute_reference_tool(tc)

        # === Journal tools ===
        if tc.name in JOURNAL_TOOL_NAMES:
            return self._execute_journal_tool(tc)

        return {"text": f"Unknown tool: {tc.name}", "is_error": True}

    def _clamp_walk_to_hazards(
        self, tc: ToolCall, px: int, py: int,
    ) -> tuple[ToolCall, str]:
        """Check the walk path for warps/ledges and reduce steps to stop before them.

        Prevents accidentally walking through building doors or off ledges
        during multi-step walks. If a hazard is found, the step count is
        reduced so Claude stops one tile before it, and a message explains
        what's ahead.

        Returns (possibly modified ToolCall, reason string or "").
        """
        from .collision import WARP_BEHAVIORS, LEDGE_BEHAVIORS, WARP_CHARS
        from .agent import ToolCall as TC

        direction = tc.input.get("direction", "").lower().strip()
        steps = tc.input.get("steps", 1)
        if steps <= 1:
            return tc, ""  # Single step — let it happen

        dx, dy = {
            "up": (0, -1), "down": (0, 1),
            "left": (-1, 0), "right": (1, 0),
        }.get(direction, (0, 0))
        if dx == 0 and dy == 0:
            return tc, ""

        try:
            ws = self._collision.read_world_state(px, py)
            if not ws:
                return tc, ""

            warp_at = {(w.x, w.z): w for w in ws.warps}

            for step in range(1, steps + 1):
                check_x = px + dx * step
                check_y = py + dy * step
                local_x = check_x % 32
                local_y = check_y % 32
                tile = ws.grid.get(local_x, local_y)

                # Check for warp tiles (doors, stairs, warp panels)
                if tile.behavior in WARP_BEHAVIORS:
                    warp = warp_at.get((check_x, check_y))
                    dest = warp.dest_name if warp else "unknown area"
                    ch = WARP_CHARS.get(tile.behavior, "door")
                    safe_steps = step - 1
                    if safe_steps < 1:
                        return tc, ""  # Warp is the very first tile — let it happen
                    new_input = dict(tc.input)
                    new_input["steps"] = safe_steps
                    new_tc = ToolCall(id=tc.id, name=tc.name, input=new_input)
                    return new_tc, f"(Stopped before {ch} → {dest} at ({check_x},{check_y}))"

                # Check for ledge tiles (one-way jumps)
                if tile.behavior in LEDGE_BEHAVIORS:
                    safe_steps = step - 1
                    if safe_steps < 1:
                        return tc, ""
                    new_input = dict(tc.input)
                    new_input["steps"] = safe_steps
                    new_tc = ToolCall(id=tc.id, name=tc.name, input=new_input)
                    return new_tc, f"(Stopped before ledge at ({check_x},{check_y}))"

        except Exception as e:
            logger.debug(f"Walk hazard check failed: {e}")

        return tc, ""

    def _execute_game_action(self, tc: ToolCall) -> dict[str, Any]:
        """Execute a game action (press_button, walk, touch, wait)."""
        # Read position before action (for spatial grid updates + blocked detection)
        try:
            pre_player = self._memory.read_player()
            pre_x, pre_y, pre_map = pre_player.x, pre_player.y, pre_player.map_id
        except Exception:
            pre_x, pre_y, pre_map = -1, -1, -1

        # For walk actions, check the collision grid for warps/ledges along
        # the path and stop before them. This prevents accidentally walking
        # through doors or off ledges during multi-step walks.
        walk_stopped_reason = ""
        if tc.name == "walk" and pre_x >= 0 and self._collision.is_available:
            tc, walk_stopped_reason = self._clamp_walk_to_hazards(
                tc, pre_x, pre_y,
            )

        # Execute the action
        outcome = self._actions.execute(tc.name, **tc.input)
        self._stats.total_actions += 1

        # Advance a few frames to let the action settle
        for _ in range(FRAMES_POST_ACTION):
            self._emu.cycle(with_joystick=False)

        result_text = outcome.detail
        if walk_stopped_reason:
            result_text += f" {walk_stopped_reason}"

        # Read position after action (for spatial grid + walk honesty)
        if tc.name == "walk" and pre_x >= 0:
            try:
                post_player = self._memory.read_player()
                direction = tc.input.get("direction", "")
                steps = tc.input.get("steps", 1)

                # Invalidate collision cache on map transition
                if post_player.map_id != pre_map:
                    self._collision.invalidate()

                # Record for spatial grid (fills intermediate tiles)
                self._spatial.record_move_result(
                    map_id=pre_map,
                    from_x=pre_x, from_y=pre_y,
                    to_x=post_player.x, to_y=post_player.y,
                    direction=direction,
                )

                # Visit all tiles along the path in fog-of-war
                dir_dx, dir_dy = {
                    "up": (0, -1), "down": (0, 1),
                    "left": (-1, 0), "right": (1, 0),
                }.get(direction, (0, 0))
                cx, cy = pre_x, pre_y
                while (cx, cy) != (post_player.x, post_player.y):
                    cx += dir_dx
                    cy += dir_dy
                    self._fog.visit(post_player.map_id, cx, cy)
                    if abs(cx - pre_x) + abs(cy - pre_y) > 25:
                        break  # Safety

                # Honest walk result: report actual movement
                dx = post_player.x - pre_x
                dy = post_player.y - pre_y
                tiles_moved = abs(dx) + abs(dy)

                if tiles_moved == 0:
                    result_text = (
                        f"Blocked — walked {direction} {steps} step(s) "
                        f"but position unchanged at ({pre_x}, {pre_y}). "
                        f"Something is in the way (wall, NPC, or locked movement)."
                    )
                elif tiles_moved < steps:
                    # Mark the tile past the endpoint as a wall
                    dir_dx, dir_dy = {
                        "up": (0, -1), "down": (0, 1),
                        "left": (-1, 0), "right": (1, 0),
                    }.get(direction, (0, 0))
                    wall_x = post_player.x + dir_dx
                    wall_y = post_player.y + dir_dy
                    from .spatial import TileType
                    self._spatial.set_tile(
                        pre_map, wall_x, wall_y, TileType.WALL
                    )

                    result_text = (
                        f"Partially blocked — walked {direction} {steps} step(s) "
                        f"but only moved {tiles_moved} tile(s): "
                        f"({pre_x},{pre_y}) → ({post_player.x},{post_player.y})"
                    )
                else:
                    result_text = (
                        f"Walked {direction} {steps} step(s): "
                        f"({pre_x},{pre_y}) → ({post_player.x},{post_player.y})"
                    )
            except Exception:
                pass

        # Poll dialogue after action
        self._dialogue.poll()

        # Update live frame + emit event so viewer sees each action immediately
        self._update_live_frame()
        self._events.emit("action_exec", {
            "action": tc.name,
            "input": tc.input,
            "result": result_text,
        })

        return {"text": result_text}

    def _execute_reference_tool(self, tc: ToolCall) -> dict[str, Any]:
        """Execute a reference tool (type chart, bag, party)."""
        if tc.name == "check_type_chart":
            from .data.type_chart import format_matchup
            atk_type = tc.input.get("attacking_type", "")
            def_types = tc.input.get("defending_types", [])
            return {"text": format_matchup(atk_type, def_types)}

        elif tc.name == "check_bag":
            try:
                inventory = self._inventory.read_inventory()
                return {"text": format_inventory(inventory)}
            except Exception as e:
                return {"text": f"Error reading bag: {e}", "is_error": True}

        elif tc.name == "check_party":
            try:
                party = self._memory.read_party()
                return {"text": format_party_detail(party)}
            except Exception as e:
                return {"text": f"Error reading party: {e}", "is_error": True}

        return {"text": f"Unknown reference tool: {tc.name}", "is_error": True}

    def _execute_journal_tool(self, tc: ToolCall) -> dict[str, Any]:
        """Execute a journal tool (write, read)."""
        if tc.name == "write_journal":
            section = tc.input.get("section", "")
            content = tc.input.get("content", "")

            # current_goals and team_notes are "living documents" — overwrite
            if section in ("current_goals", "team_notes"):
                success = self._journal.replace_section(section, content)
            else:
                # Get in-game time for the entry
                try:
                    player = self._memory.read_player()
                    in_game_time = player.play_time_str
                except Exception:
                    in_game_time = ""
                success = self._journal.write(section, content, in_game_time=in_game_time)

            if success:
                return {"text": f"Written to {section}."}
            else:
                return {
                    "text": f"Invalid section: {section}. Valid: current_goals, team_notes, adventure_log, strategy, map_notes",
                    "is_error": True,
                }

        elif tc.name == "read_journal":
            section = tc.input.get("section", "")
            n = tc.input.get("entries")
            return {"text": self._journal.format_section(section, n)}

        return {"text": f"Unknown journal tool: {tc.name}", "is_error": True}

    def _check_context_rotation(self, mode: GameMode) -> None:
        """Check if the context window needs rotation and handle it.

        Rolling window approach: when context exceeds the threshold, trim
        the oldest turns instead of clearing everything. This preserves
        continuity — Claude keeps its recent context while older turns
        are shed. The journal carries long-term memory.

        Uses actual token counts from the API, not heuristics.
        """
        if not self._agent:
            return

        rotate_status = self._agent.should_rotate_window()

        if rotate_status == "none":
            return

        # For soft rotations, prefer natural pauses
        if rotate_status == "soft":
            natural_pause = mode in (
                GameMode.OVERWORLD,
                GameMode.DIALOGUE,  # Between dialogue pages is OK
            )
            if not natural_pause:
                return

        # Drop pending response — tool IDs may reference trimmed messages
        self._pending_response = None

        context_tokens = self._agent.last_context_tokens
        removed = self._agent.rotate_window()

        logger.info(
            f"Context rotation ({rotate_status}) at turn {self._stats.total_turns}: "
            f"removed {removed} messages, was {context_tokens:,} tokens"
        )

        # Emit event for viewer
        self._events.emit("context_rotation", {
            "turn": self._stats.total_turns,
            "trigger": rotate_status,
            "tokens_before": context_tokens,
            "messages_removed": removed,
            "messages_remaining": self._agent.message_count,
        })

    def _save_all(self) -> None:
        """Save all persistent state to disk."""
        try:
            self._fog.save()
            self._novelty.save()
            self._journal.save()
            self._spatial.save()
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def _update_live_frame(self) -> None:
        """Write current game frame to disk for the live viewer.

        Called after every action execution so the viewer shows
        real-time game state, not just end-of-turn snapshots.
        """
        try:
            cap = self._screenshots.capture(encode=False)
            from PIL import Image
            live_dir = self._events.live_dir
            Image.fromarray(cap.top).save(live_dir / "top.png")
            Image.fromarray(cap.bottom).save(live_dir / "bot.png")
        except Exception:
            pass

    def _write_live_frame(self, trace: TurnTrace) -> None:
        """Write the current frame + agent state to disk for the live viewer."""
        self._update_live_frame()

        try:
            # Write agent state as JSON for the viewer (legacy compat)
            state = {
                "turn": trace.turn_number,
                "mode": trace.game_mode,
                "map": trace.map_name,
                "pos": f"({trace.x}, {trace.y})",
                "party": trace.party_count,
                "badges": trace.badge_count,
                "text": trace.agent_text[:500],
                "tool_calls": trace.tool_calls,
                "tool_results": [
                    {"name": r["name"], "result": r["result"][:80]}
                    for r in trace.tool_results
                ],
                "tokens_in": trace.input_tokens,
                "tokens_out": trace.output_tokens,
                "cache_read": trace.cache_read_tokens,
                "duration_ms": trace.turn_duration_ms,
                "error": trace.error,
            }
            (self._events.live_dir / "state.json").write_text(
                json.dumps(state, indent=2, default=str)
            )
        except Exception as e:
            logger.debug(f"Live frame write error: {e}")

    def stop(self) -> None:
        """Gracefully stop the loop."""
        self._running = False
        self._save_all()
        logger.info(f"Loop stopped. {self._stats.summary()}")
        if self._agent:
            logger.info(f"API usage: {self._agent.usage.summary()}")
            # Print full cost breakdown
            print(f"\n{self._agent.costs.format_summary()}")
            # Emit to event stream
            self._events.emit("loop_stop", self._agent.costs.to_dict())
        logger.info(f"Traces: {self._tracer.trace_dir}")

    def __repr__(self) -> str:
        return f"AgentLoop({self._stats.summary()})"
