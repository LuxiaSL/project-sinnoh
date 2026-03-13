"""Cost tracking for the agent loop.

Calculates real dollar costs from Anthropic API token usage.
Pricing is hardcoded from https://platform.claude.com/docs/en/about-claude/pricing
(no programmatic pricing API available).

Token categories:
    input_tokens           — Base input tokens (uncached)
    output_tokens          — Output tokens
    cache_creation_input_tokens — Tokens written to prompt cache (1.25x input price)
    cache_read_input_tokens    — Tokens read from prompt cache (0.1x input price)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Pricing per million tokens (USD), as of March 2026
# Source: https://platform.claude.com/docs/en/about-claude/pricing
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,   # 1.25x input
        "cache_read": 0.30,    # 0.1x input
    },
    "claude-opus-4-6": {
        "input": 5.00,
        "output": 25.00,
        "cache_write": 6.25,   # 1.25x input
        "cache_read": 0.50,    # 0.1x input
    },
}

# Fallback: if model not in table, use Sonnet pricing
DEFAULT_MODEL = "claude-sonnet-4-6"


def _get_pricing(model: str) -> dict[str, float]:
    """Get pricing for a model, falling back to default."""
    # Strip any date suffixes: claude-sonnet-4-6-20250514 -> claude-sonnet-4-6
    for key in PRICING:
        if model.startswith(key):
            return PRICING[key]
    return PRICING[DEFAULT_MODEL]


@dataclass
class CostTracker:
    """Tracks cumulative token usage and calculates dollar costs.

    Updated after each API call. Provides per-turn and cumulative stats.
    """

    model: str = DEFAULT_MODEL

    # Cumulative token counts
    total_input: int = 0
    total_output: int = 0
    total_cache_write: int = 0
    total_cache_read: int = 0
    total_calls: int = 0

    # Per-turn tracking (reset each turn)
    turn_input: int = 0
    turn_output: int = 0
    turn_cache_write: int = 0
    turn_cache_read: int = 0
    turn_calls: int = 0

    # History for per-turn cost display
    turn_costs: list[float] = field(default_factory=list)

    def add_usage(self, usage: dict[str, Any]) -> None:
        """Record usage from one API call."""
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        cw = usage.get("cache_creation_input_tokens", 0)
        cr = usage.get("cache_read_input_tokens", 0)

        self.total_input += inp
        self.total_output += out
        self.total_cache_write += cw
        self.total_cache_read += cr
        self.total_calls += 1

        self.turn_input += inp
        self.turn_output += out
        self.turn_cache_write += cw
        self.turn_cache_read += cr
        self.turn_calls += 1

    def end_turn(self) -> float:
        """Mark end of a turn. Returns the turn cost and resets per-turn counters."""
        cost = self._compute_cost(
            self.turn_input, self.turn_output,
            self.turn_cache_write, self.turn_cache_read,
        )
        self.turn_costs.append(cost)
        self.turn_input = 0
        self.turn_output = 0
        self.turn_cache_write = 0
        self.turn_cache_read = 0
        self.turn_calls = 0
        return cost

    @property
    def total_cost(self) -> float:
        """Total cumulative cost in USD."""
        return self._compute_cost(
            self.total_input, self.total_output,
            self.total_cache_write, self.total_cache_read,
        )

    @property
    def last_turn_cost(self) -> float:
        """Cost of the most recent turn."""
        return self.turn_costs[-1] if self.turn_costs else 0.0

    @property
    def avg_turn_cost(self) -> float:
        """Average cost per turn."""
        if not self.turn_costs:
            return 0.0
        return sum(self.turn_costs) / len(self.turn_costs)

    def _compute_cost(self, inp: int, out: int, cw: int, cr: int) -> float:
        """Compute dollar cost from token counts."""
        p = _get_pricing(self.model)
        return (
            inp * p["input"] / 1_000_000
            + out * p["output"] / 1_000_000
            + cw * p["cache_write"] / 1_000_000
            + cr * p["cache_read"] / 1_000_000
        )

    def format_summary(self) -> str:
        """Human-readable cost summary."""
        p = _get_pricing(self.model)
        total = self.total_cost
        turns = len(self.turn_costs)

        lines = [
            f"=== Cost Summary ({self.model}) ===",
            f"Total: ${total:.4f} ({self.total_calls} API calls, {turns} turns)",
            f"",
            f"  Input:       {self.total_input:>10,} tokens  ${self.total_input * p['input'] / 1e6:.4f}",
            f"  Output:      {self.total_output:>10,} tokens  ${self.total_output * p['output'] / 1e6:.4f}",
            f"  Cache write: {self.total_cache_write:>10,} tokens  ${self.total_cache_write * p['cache_write'] / 1e6:.4f}",
            f"  Cache read:  {self.total_cache_read:>10,} tokens  ${self.total_cache_read * p['cache_read'] / 1e6:.4f}",
        ]

        if turns > 0:
            lines.extend([
                f"",
                f"  Avg/turn: ${self.avg_turn_cost:.4f}  |  Last turn: ${self.last_turn_cost:.4f}",
                f"  Projected $/hr @ 2 turns/min: ${self.avg_turn_cost * 120:.2f}",
            ])

        return "\n".join(lines)

    def format_oneliner(self) -> str:
        """One-line cost display for live viewer."""
        total = self.total_cost
        turns = len(self.turn_costs)
        avg = self.avg_turn_cost
        return (
            f"${total:.4f} total | ${avg:.4f}/turn | "
            f"{self.total_cache_read:,} cache reads"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "model": self.model,
            "total_cost_usd": round(self.total_cost, 6),
            "total_calls": self.total_calls,
            "total_turns": len(self.turn_costs),
            "tokens": {
                "input": self.total_input,
                "output": self.total_output,
                "cache_write": self.total_cache_write,
                "cache_read": self.total_cache_read,
            },
            "per_turn": {
                "avg_cost_usd": round(self.avg_turn_cost, 6),
                "last_cost_usd": round(self.last_turn_cost, 6),
            },
        }
