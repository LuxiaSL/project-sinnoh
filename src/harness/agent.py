"""Agent client — Anthropic API integration for the game agent.

Handles:
- Claude API calls with vision (screenshots) and tool-use
- Prompt construction with cache-friendly layout
- Response parsing (extract tool calls from responses)
- Token usage tracking
- Error handling and retries

Prompt caching strategy:
- System prompt + tool definitions = fully static → cache_control: ephemeral
- Journal section = semi-static → cache_control: ephemeral (after system)
- Game state + screenshots = dynamic → no caching
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import anthropic

from .costs import CostTracker
from .prompt import build_system_prompt
from .tools import get_all_tools

logger = logging.getLogger(__name__)

# Default model for development
DEFAULT_MODEL = "claude-sonnet-4-6"

# Rolling window context management thresholds (tokens)
# These use the ACTUAL token count from the most recent API response,
# not heuristic estimates. input_tokens + cache_read + cache_write = full context.
CONTEXT_ROTATE_THRESHOLD = 170_000   # Trigger window rotation
CONTEXT_ROTATE_TRIM = 50_000         # Approximate tokens to trim (oldest turns)
CONTEXT_HARD_CEILING = 195_000       # Force rotation regardless of pause

# Image limit — Anthropic API enforces max 100 images per request.
# Stripping images modifies messages and invalidates the cache prefix,
# so we trigger late (95) and trim hard (down to 8 — just the last
# few turns' screenshots). This means one cache break every ~40+ turns
# instead of constant invalidation.
MAX_IMAGES_TRIGGER = 95   # Only trim when this close to the 100 limit
MAX_IMAGES_TARGET = 8     # Keep only the most recent ~2 turns of screenshots


@dataclass
class TokenUsage:
    """Token usage tracking for cost estimation."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, usage: dict[str, int]) -> None:
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        self.cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
        self.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
        self.total_calls += 1

    def summary(self) -> str:
        return (
            f"Tokens: {self.total_tokens:,} total "
            f"({self.input_tokens:,} in, {self.output_tokens:,} out) | "
            f"Cache: {self.cache_read_tokens:,} read, {self.cache_creation_tokens:,} created | "
            f"Calls: {self.total_calls}"
        )


@dataclass
class ToolCall:
    """A parsed tool call from Claude's response."""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class AgentResponse:
    """Parsed response from the agent."""
    text: str = ""                              # Claude's natural language reasoning
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: Any = None


class AgentClient:
    """Claude API client for the game agent.

    Manages conversation history, constructs prompts with caching,
    and handles tool-use flow.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 2048,
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._usage = TokenUsage()
        self._costs = CostTracker(model=model)

        # Conversation history (user/assistant message pairs)
        self._messages: list[dict[str, Any]] = []

        # Actual token count from most recent API call (for window rotation)
        self._last_context_tokens: int = 0

        # Cached system prompt blocks (built once)
        self._system_blocks: list[dict[str, Any]] = []
        self._tools = get_all_tools()
        self._build_system_blocks()

    @property
    def usage(self) -> TokenUsage:
        return self._usage

    @property
    def costs(self) -> CostTracker:
        return self._costs

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def model(self) -> str:
        return self._model

    def _build_system_blocks(self) -> None:
        """Build the system prompt blocks.

        The system prompt is static across calls. Caching is handled
        automatically via top-level cache_control on the API call.
        """
        self._system_blocks = [
            {
                "type": "text",
                "text": build_system_prompt(),
            }
        ]

    def _build_user_message(
        self,
        game_state_text: str,
        screenshots: list[dict[str, str]] | None = None,
        journal_text: str = "",
        dialogue_text: str = "",
        spatial_grid: str = "",
        novelty_flags: list[str] | None = None,
        extra_context: str = "",
    ) -> dict[str, Any]:
        """Build a user message with game state, screenshots, and context.

        Layout (cache-friendly — static parts first):
        1. Journal (semi-static, changes only on writes)
        2. Game state text (dynamic)
        3. Spatial grid (dynamic)
        4. Dialogue (dynamic)
        5. Novelty flags (dynamic)
        6. Screenshots (dynamic, most tokens)
        """
        content: list[dict[str, Any]] = []

        # Journal context
        if journal_text:
            content.append({
                "type": "text",
                "text": journal_text,
            })

        # Game state
        content.append({
            "type": "text",
            "text": game_state_text,
        })

        # Spatial grid
        if spatial_grid:
            content.append({
                "type": "text",
                "text": spatial_grid,
            })

        # Dialogue transcript
        if dialogue_text:
            content.append({
                "type": "text",
                "text": dialogue_text,
            })

        # Novelty flags
        if novelty_flags:
            flags_text = "\n".join(f"[!] {flag}" for flag in novelty_flags)
            content.append({
                "type": "text",
                "text": flags_text,
            })

        # Extra context (tool results, etc.)
        if extra_context:
            content.append({
                "type": "text",
                "text": extra_context,
            })

        # Screenshots (most expensive — put last)
        if screenshots:
            _screen_labels = [
                "TOP SCREEN (gameplay, dialogue, battles — view only, not touchable)",
                "BOTTOM SCREEN (touch screen — Poketch, menus, battle UI)",
            ]
            for i, shot in enumerate(screenshots):
                label = _screen_labels[i] if i < len(_screen_labels) else f"Screen {i}"
                content.append({"type": "text", "text": label})
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": shot["media_type"],
                        "data": shot["data"],
                    },
                })

        return {"role": "user", "content": content}

    def _build_tool_result_message(
        self,
        tool_call_id: str,
        result: str,
        is_error: bool = False,
    ) -> dict[str, Any]:
        """Build a tool result message to send back to Claude."""
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": result,
                    "is_error": is_error,
                }
            ],
        }

    def _build_batch_tool_result_message(
        self,
        results: list[dict[str, Any]],
        game_context: str = "",
    ) -> dict[str, Any]:
        """Build a message with multiple tool results at once.

        When Claude returns multiple tool_use blocks in one response,
        ALL results must be sent back in a single user message.

        Args:
            results: List of dicts with keys:
                - tool_call_id: str
                - result: str (text result)
                - is_error: bool (optional)
                - images: list of {"media_type": ..., "data": ...} (optional)
            game_context: Optional updated game state/grid/dialogue text
                to append after tool results so Claude always has current info.
        """
        content = []
        for r in results:
            images = r.get("images")
            if images:
                # Build content as list of blocks: text first, then labeled images
                _screen_labels = [
                    "TOP SCREEN (view only)",
                    "BOTTOM SCREEN (touch screen)",
                ]
                result_content: list[dict[str, Any]] = [
                    {"type": "text", "text": r["result"]},
                ]
                for i, img in enumerate(images):
                    label = _screen_labels[i] if i < len(_screen_labels) else f"Screen {i}"
                    result_content.append({"type": "text", "text": label})
                    result_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img["media_type"],
                            "data": img["data"],
                        },
                    })
                content.append({
                    "type": "tool_result",
                    "tool_use_id": r["tool_call_id"],
                    "content": result_content,
                    "is_error": r.get("is_error", False),
                })
            else:
                content.append({
                    "type": "tool_result",
                    "tool_use_id": r["tool_call_id"],
                    "content": r["result"],
                    "is_error": r.get("is_error", False),
                })

        # Append updated game context so Claude always sees current state
        if game_context:
            content.append({
                "type": "text",
                "text": game_context,
            })

        return {"role": "user", "content": content}

    def send_turn(
        self,
        game_state_text: str,
        screenshots: list[dict[str, str]] | None = None,
        journal_text: str = "",
        dialogue_text: str = "",
        spatial_grid: str = "",
        novelty_flags: list[str] | None = None,
        extra_context: str = "",
    ) -> AgentResponse:
        """Send a game turn to Claude and get a response.

        This is the main entry point for each tick of the agent loop.
        Constructs the message, sends it, and parses the response.

        Args:
            game_state_text: Formatted game state from the state formatter.
            screenshots: List of {"media_type": ..., "data": ...} dicts.
            journal_text: Formatted journal context.
            dialogue_text: Formatted dialogue transcript.
            spatial_grid: Formatted spatial grid.
            novelty_flags: List of novelty flag strings.
            extra_context: Any additional context text.

        Returns:
            AgentResponse with text, tool calls, and usage.
        """
        user_msg = self._build_user_message(
            game_state_text=game_state_text,
            screenshots=screenshots,
            journal_text=journal_text,
            dialogue_text=dialogue_text,
            spatial_grid=spatial_grid,
            novelty_flags=novelty_flags,
            extra_context=extra_context,
        )

        self._messages.append(user_msg)

        return self._call_api()

    def send_tool_result(
        self,
        tool_call_id: str,
        result: str,
        is_error: bool = False,
    ) -> AgentResponse:
        """Send a single tool result back to Claude.

        For a single tool call, this works fine. For multiple tool calls
        in one response, use send_batch_tool_results instead.
        """
        result_msg = self._build_tool_result_message(tool_call_id, result, is_error)
        self._messages.append(result_msg)
        return self._call_api()

    def send_batch_tool_results(
        self,
        results: list[dict[str, Any]],
        game_context: str = "",
    ) -> AgentResponse:
        """Send multiple tool results back to Claude in one message.

        When Claude returns multiple tool_use blocks in one response,
        ALL results must be sent in a single user message. This method
        handles that correctly.

        Args:
            results: List of {"tool_call_id": ..., "result": ..., "is_error": ...}
            game_context: Updated game state/grid/dialogue text to include.
        """
        result_msg = self._build_batch_tool_result_message(results, game_context=game_context)
        self._messages.append(result_msg)
        return self._call_api()

    def _strip_old_images(self) -> None:
        """Strip base64 image data from all but the 2 most recent user messages.

        Reduces context size without breaking caching (automatic top-level
        caching doesn't depend on content block structure). Modifies
        self._messages in-place. Idempotent — already-stripped messages
        have no image blocks left.
        """
        # Find indices of the last 2 user messages
        user_indices: list[int] = []
        for i in range(len(self._messages) - 1, -1, -1):
            if self._messages[i].get("role") == "user":
                user_indices.append(i)
                if len(user_indices) == 2:
                    break

        if len(user_indices) < 2:
            return  # Fewer than 2 user messages, nothing to strip

        cutoff = user_indices[-1]  # The earlier of the two indices

        for i in range(cutoff):
            msg = self._messages[i]
            content = msg.get("content")
            if not isinstance(content, list):
                continue

            for j, block in enumerate(content):
                if not isinstance(block, dict):
                    continue

                # Strip top-level image blocks
                if block.get("type") == "image":
                    content[j] = {
                        "type": "text",
                        "text": "(screenshot from earlier — not shown)",
                    }

                # Strip images inside tool_result content lists
                elif block.get("type") == "tool_result":
                    sub_content = block.get("content")
                    if isinstance(sub_content, list):
                        new_sub = []
                        had_image = False
                        for sub_block in sub_content:
                            if isinstance(sub_block, dict) and sub_block.get("type") == "image":
                                had_image = True
                            else:
                                new_sub.append(sub_block)
                        if had_image:
                            new_sub.append({
                                "type": "text",
                                "text": "(screenshot from earlier — not shown)",
                            })
                        block["content"] = new_sub

    def _call_api(self, retries: int = 3) -> AgentResponse:
        """Make the actual API call with retry logic."""
        msg_count_before = len(self._messages)

        # Trim old images if approaching the 100-image API limit.
        images_trimmed = self.trim_old_images()

        # Fix any orphaned tool_use blocks before calling the API.
        self._fix_orphaned_tool_uses()

        msg_count_after = len(self._messages)

        # Log context mutations for debugging cache behavior
        if images_trimmed or msg_count_after != msg_count_before:
            img_count = self.count_images()
            logger.info(
                f"Context mutated before API call: "
                f"msgs {msg_count_before}->{msg_count_after}, "
                f"images_trimmed={images_trimmed}, "
                f"images_remaining={img_count}"
            )

        last_error: Exception | None = None

        for attempt in range(retries):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=self._system_blocks,
                    tools=self._tools,
                    messages=self._messages,
                    cache_control={"type": "ephemeral"},
                )

                # Parse the response
                parsed = self._parse_response(response)

                # Add assistant response to history
                self._messages.append({
                    "role": "assistant",
                    "content": response.content,
                })

                # Track usage
                if response.usage:
                    usage_dict = {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    }
                    # Cache usage is in a separate field
                    if hasattr(response.usage, "cache_creation_input_tokens"):
                        usage_dict["cache_creation_input_tokens"] = (
                            response.usage.cache_creation_input_tokens or 0
                        )
                    if hasattr(response.usage, "cache_read_input_tokens"):
                        usage_dict["cache_read_input_tokens"] = (
                            response.usage.cache_read_input_tokens or 0
                        )
                    self._usage.add(usage_dict)
                    self._costs.add_usage(usage_dict)
                    parsed.usage = usage_dict

                    # Track actual context size for window rotation.
                    # Total input context = uncached input + cache read + cache write
                    self._last_context_tokens = (
                        usage_dict.get("input_tokens", 0)
                        + usage_dict.get("cache_read_input_tokens", 0)
                        + usage_dict.get("cache_creation_input_tokens", 0)
                    )

                return parsed

            except anthropic.RateLimitError as e:
                last_error = e
                wait_time = 2 ** attempt * 5  # 5, 10, 20 seconds
                logger.warning(f"Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{retries})")
                time.sleep(wait_time)

            except anthropic.APIError as e:
                last_error = e
                logger.error(f"API error: {e}")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                break

        # All retries failed
        return AgentResponse(
            text=f"API error after {retries} retries: {last_error}",
            stop_reason="error",
        )

    def _parse_response(self, response: Any) -> AgentResponse:
        """Parse a raw API response into AgentResponse."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                ))

        return AgentResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            raw_response=response,
        )

    # === Context management ===

    @property
    def last_context_tokens(self) -> int:
        """Actual token count from the most recent API call.

        This is the real context size as reported by the API — no estimation.
        input_tokens + cache_read + cache_write = full context that was sent.
        """
        return self._last_context_tokens

    def should_rotate_window(self) -> str:
        """Check if the context window needs rotation.

        Uses actual token counts from the API, not heuristic estimates.

        Returns:
            "none" — no rotation needed
            "soft" — approaching limit, rotate at next natural pause
            "hard" — at ceiling, rotate now
        """
        tokens = self._last_context_tokens
        if tokens >= CONTEXT_HARD_CEILING:
            return "hard"
        elif tokens >= CONTEXT_ROTATE_THRESHOLD:
            return "soft"
        return "none"

    def rotate_window(self, trim_tokens: int = CONTEXT_ROTATE_TRIM) -> int:
        """Trim the oldest turns from conversation history.

        Removes message pairs from the front of the history until
        approximately `trim_tokens` worth of content has been removed.
        Uses the same heuristic as before for estimating per-message
        token sizes (since we only have the total, not per-message).

        Preserves the most recent messages so Claude has continuity.

        Returns:
            Number of messages removed.
        """
        if len(self._messages) < 4:
            return 0  # Need at least a couple of turns to trim

        # Estimate tokens per message for trimming purposes
        removed = 0
        tokens_removed = 0

        while tokens_removed < trim_tokens and len(self._messages) > 2:
            msg = self._messages[0]
            # Estimate this message's token contribution
            msg_tokens = self._estimate_message_tokens(msg)
            self._messages.pop(0)
            tokens_removed += msg_tokens
            removed += 1

        # Ensure we start with a user message (proper alternation)
        while self._messages and self._messages[0].get("role") == "assistant":
            self._messages.pop(0)
            removed += 1

        # Strip leading tool_result messages — their tool_use was trimmed.
        # The API requires every tool_result to have a matching tool_use in
        # the preceding assistant message. After trimming, the first user
        # message may be a tool_result whose tool_use is gone.
        while self._messages and self._messages[0].get("role") == "user":
            content = self._messages[0].get("content", [])
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            ):
                self._messages.pop(0)
                removed += 1
                # Also drop the next assistant message to maintain alternation
                if self._messages and self._messages[0].get("role") == "assistant":
                    self._messages.pop(0)
                    removed += 1
            else:
                break  # First user message is clean text — we're good

        logger.info(
            f"Window rotation: removed {removed} messages "
            f"(~{tokens_removed:,} tokens). "
            f"{len(self._messages)} messages remain."
        )
        return removed

    def count_images(self) -> int:
        """Count total image blocks across all messages in history."""
        count = 0
        for msg in self._messages:
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image":
                    count += 1
                elif hasattr(block, "type") and block.type == "image":
                    count += 1
                # Also count images inside tool_result content lists
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    sub = block.get("content", [])
                    if isinstance(sub, list):
                        for s in sub:
                            if isinstance(s, dict) and s.get("type") == "image":
                                count += 1
        return count

    def trim_old_images(self) -> int:
        """Strip image blocks from the oldest messages to stay under the API limit.

        Walks from the front of the message list (oldest), removing image
        blocks until the total count is under MAX_IMAGES_SOFT. Text content
        is preserved — only the image blocks are dropped.

        This is much less destructive than rotating the full window. Claude
        loses old screenshots but keeps all text context.

        Returns number of images removed.
        """
        total = self.count_images()
        if total <= MAX_IMAGES_TRIGGER:
            return 0

        target_remove = total - MAX_IMAGES_TARGET
        removed = 0

        for msg in self._messages:
            if removed >= target_remove:
                break

            content = msg.get("content", [])
            if not isinstance(content, list):
                continue

            # Filter out image blocks from this message
            new_content: list[Any] = []
            for block in content:
                is_image = False
                if isinstance(block, dict) and block.get("type") == "image":
                    is_image = True
                elif hasattr(block, "type") and block.type == "image":
                    is_image = True

                if is_image and removed < target_remove:
                    removed += 1
                    continue  # Drop this image

                # For tool_result blocks, strip images from their content too
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    sub = block.get("content", [])
                    if isinstance(sub, list):
                        new_sub: list[Any] = []
                        for s in sub:
                            if isinstance(s, dict) and s.get("type") == "image" and removed < target_remove:
                                removed += 1
                            else:
                                new_sub.append(s)
                        block = {**block, "content": new_sub}

                new_content.append(block)

            msg["content"] = new_content

        if removed > 0:
            logger.warning(
                f"Image trim: removed {removed} images ({total} -> {total - removed}). "
                f"CACHE WILL BREAK — next API call will be a full cache write."
            )
        return removed

    def _estimate_message_tokens(self, msg: dict[str, Any]) -> int:
        """Estimate token count for a single message (for trimming only).

        This is a rough heuristic used to decide how many messages to
        remove during window rotation. The actual context size is always
        measured via API-reported token counts.
        """
        content = msg.get("content", [])
        if isinstance(content, str):
            return len(content) // 4

        total = 0
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "text":
                        total += len(block.get("text", "")) // 4
                    elif block_type == "image":
                        total += 300  # DS screenshots are small (256x192 JPEG)
                    elif block_type == "tool_use":
                        total += 100
                    elif block_type == "tool_result":
                        sub = block.get("content", "")
                        if isinstance(sub, str):
                            total += len(sub) // 4
                        elif isinstance(sub, list):
                            for s in sub:
                                if isinstance(s, dict):
                                    if s.get("type") == "text":
                                        total += len(s.get("text", "")) // 4
                                    elif s.get("type") == "image":
                                        total += 300
        return total

    def clear_history(self) -> list[dict[str, Any]]:
        """Clear conversation history entirely (for chapter breaks).

        Returns the cleared messages for archival.
        """
        old_messages = self._messages
        self._messages = []
        return old_messages

    def _fix_orphaned_tool_uses(self) -> None:
        """Scan the ENTIRE history and fix any orphaned tool_use blocks.

        The API requires that every assistant message containing tool_use
        blocks is immediately followed by a user message with matching
        tool_result blocks. This method enforces that invariant.

        This runs before every _call_api() as a safety net. No matter
        how the orphans were created (drain loops, pending responses,
        context rotation, chapter breaks, whatever), this fixes them.

        The fix: for each assistant message with tool_use blocks that
        ISN'T followed by matching tool_results, insert a stub user
        message with the required tool_results.
        """
        if len(self._messages) < 2:
            return

        i = 0
        fixes = 0
        while i < len(self._messages):
            msg = self._messages[i]
            if msg.get("role") != "assistant":
                i += 1
                continue

            # Extract tool_use IDs from this assistant message
            content = msg.get("content", [])
            if not isinstance(content, list):
                i += 1
                continue

            tool_use_ids: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_ids.append(block.get("id", ""))
                elif hasattr(block, "type") and getattr(block, "type", None) == "tool_use":
                    tool_use_ids.append(getattr(block, "id", ""))

            if not tool_use_ids:
                i += 1
                continue

            # Check if the next message has matching tool_results
            next_msg = self._messages[i + 1] if i + 1 < len(self._messages) else None
            has_results = False
            if next_msg and next_msg.get("role") == "user":
                next_content = next_msg.get("content", [])
                if isinstance(next_content, list):
                    for block in next_content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            has_results = True
                            break

            if not has_results:
                # Insert stub tool_results after this assistant message
                stub_msg = {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "content": "(turn ended before execution)",
                            "is_error": True,
                        }
                        for tid in tool_use_ids
                    ],
                }
                self._messages.insert(i + 1, stub_msg)
                fixes += 1

            i += 2  # Skip past the assistant + its tool_results

        # After inserting stubs, merge any consecutive same-role messages
        if fixes:
            merged: list[dict[str, Any]] = []
            for msg in self._messages:
                if merged and merged[-1].get("role") == msg.get("role"):
                    # Merge content
                    prev = merged[-1].get("content", [])
                    curr = msg.get("content", [])
                    if not isinstance(prev, list):
                        prev = [{"type": "text", "text": str(prev)}]
                    if not isinstance(curr, list):
                        curr = [{"type": "text", "text": str(curr)}]
                    merged[-1]["content"] = prev + curr
                else:
                    merged.append(msg)
            self._messages = merged
            logger.warning(f"Fixed {fixes} orphaned tool_use block(s) in history")

    def fix_orphaned_tool_uses(self) -> None:
        """Public wrapper for backward compatibility."""
        self._fix_orphaned_tool_uses()

    def save_history(self, path: Path) -> None:
        """Save conversation history to a JSON file for --resume.

        Strips all tool_use/tool_result blocks and keeps only text + image
        content. This produces a clean transcript that won't trigger orphaned
        tool_use errors on resume. Tool call details are preserved in traces.

        The sanitization:
        1. Serialize SDK objects to plain dicts
        2. Strip tool_use blocks from assistant messages (keep text only)
        3. Strip tool_result blocks from user messages (keep text + image)
        4. Drop empty messages (assistant with no text after stripping)
        5. Merge consecutive same-role messages (can happen after drops)
        6. Ensure proper user/assistant alternation
        """
        import json

        # Step 1: Serialize all SDK objects to plain dicts
        raw_messages: list[dict[str, Any]] = []
        for msg in self._messages:
            role = msg.get("role", "user")
            content = msg.get("content", [])
            if isinstance(content, str):
                raw_messages.append({"role": role, "content": content})
                continue

            serialized_blocks: list[dict[str, Any]] = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        serialized_blocks.append(block)
                    elif hasattr(block, "model_dump"):
                        serialized_blocks.append(block.model_dump())
                    elif hasattr(block, "to_dict"):
                        serialized_blocks.append(block.to_dict())
                    else:
                        d: dict[str, Any] = {"type": getattr(block, "type", "unknown")}
                        if hasattr(block, "text"):
                            d["text"] = block.text
                        serialized_blocks.append(d)
            raw_messages.append({"role": role, "content": serialized_blocks})

        # Step 2-3: Strip tool blocks, keep text + image
        cleaned: list[dict[str, Any]] = []
        for msg in raw_messages:
            role = msg["role"]
            content = msg.get("content", [])

            if isinstance(content, str):
                cleaned.append(msg)
                continue

            kept_blocks: list[dict[str, Any]] = []
            for block in content:
                block_type = block.get("type", "")
                if block_type in ("tool_use", "tool_result"):
                    continue  # Strip tool blocks
                if block_type in ("text", "image"):
                    kept_blocks.append(block)
                # Drop unknown block types

            if not kept_blocks:
                continue  # Step 4: drop empty messages

            cleaned.append({"role": role, "content": kept_blocks})

        # Step 5: Merge consecutive same-role messages
        merged: list[dict[str, Any]] = []
        for msg in cleaned:
            if merged and merged[-1]["role"] == msg["role"]:
                # Merge content blocks into the previous message
                prev_content = merged[-1].get("content", [])
                curr_content = msg.get("content", [])
                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{"type": "text", "text": curr_content}]
                merged[-1]["content"] = prev_content + curr_content
            else:
                merged.append(msg)

        # Step 6: Ensure it starts with user and ends cleanly
        # Trim any leading assistant messages
        while merged and merged[0]["role"] == "assistant":
            merged.pop(0)
        # Trim trailing message if it would leave orphaned state
        # (ending on user is fine — resume will append the new turn)
        # (ending on assistant is fine — resume will add new user turn)

        path.write_text(json.dumps(merged, default=str))
        logger.info(
            f"Saved {len(merged)} messages to {path} "
            f"(sanitized from {len(self._messages)} raw)"
        )

    def load_history(self, path: Path) -> None:
        """Load conversation history from a JSON file.

        Validates the loaded history to catch any remaining issues:
        - Ensures proper user/assistant alternation
        - Strips any tool blocks that survived (legacy files)
        - Fixes orphaned tool_use blocks as a safety net
        """
        import json

        if not path.exists():
            logger.warning(f"No history file at {path}")
            return

        try:
            data = json.loads(path.read_text())
            if not isinstance(data, list):
                logger.warning(f"Invalid history format in {path}")
                return

            # Validate: check for any remaining tool blocks (from old saves)
            has_tool_blocks = False
            for msg in data:
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                            has_tool_blocks = True
                            break

            if has_tool_blocks:
                logger.warning(
                    f"History at {path} contains tool blocks — "
                    f"stripping for clean resume"
                )
                data = self._strip_tool_blocks_from_history(data)

            self._messages = data
            logger.info(f"Loaded {len(data)} messages from {path}")

        except Exception as e:
            logger.error(f"Failed to load history from {path}: {e}")

    @staticmethod
    def _strip_tool_blocks_from_history(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Strip tool_use/tool_result blocks from a loaded history.

        Same sanitization logic as save_history, applied to legacy files
        that were saved before sanitization was added.
        """
        cleaned: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", [])

            if isinstance(content, str):
                cleaned.append(msg)
                continue

            kept: list[dict[str, Any]] = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type in ("tool_use", "tool_result"):
                        continue
                    if block_type in ("text", "image"):
                        kept.append(block)

            if not kept:
                continue

            cleaned.append({"role": role, "content": kept})

        # Merge consecutive same-role messages
        merged: list[dict[str, Any]] = []
        for msg in cleaned:
            if merged and merged[-1]["role"] == msg["role"]:
                prev = merged[-1].get("content", [])
                curr = msg.get("content", [])
                if isinstance(prev, str):
                    prev = [{"type": "text", "text": prev}]
                if isinstance(curr, str):
                    curr = [{"type": "text", "text": curr}]
                merged[-1]["content"] = prev + curr
            else:
                merged.append(msg)

        # Trim leading assistant messages
        while merged and merged[0]["role"] == "assistant":
            merged.pop(0)

        return merged

    def reset(self) -> None:
        """Full reset — clear history and usage."""
        self._messages = []
        self._usage = TokenUsage()

    def __repr__(self) -> str:
        return (
            f"AgentClient(model={self._model}, "
            f"messages={len(self._messages)}, "
            f"last_ctx={self._last_context_tokens:,})"
        )
