"""Tool definitions for the Claude agent's tool-use API.

These define the structured actions and reference tools available to Claude.
Each tool maps to a handler function in the agent loop.

Architecture:
- Game actions (press_button, walk, touch, wait) → ActionExecutor
- Reference tools (check_type_chart, check_bag, etc.) → read-only queries
- Journal tools (write_journal, read_journal) → Journal system

Tool definitions are stable and cacheable for prompt caching.
"""

from __future__ import annotations

from typing import Any

# === Tool Schemas for the Anthropic API ===
# These are passed as the `tools` parameter in API calls.
# They define what Claude can do at each turn.

GAME_ACTION_TOOLS: list[dict[str, Any]] = [
    {
        "name": "press_button",
        "description": (
            "Press a button on the NDS. A=confirm, B=cancel/back, "
            "X=menu, D-pad=navigate menus. For dialogue, prefer "
            "wait() to let text render, then one A to advance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "button": {
                    "type": "string",
                    "description": "The button to press.",
                    "enum": [
                        "a", "b", "x", "y", "l", "r",
                        "up", "down", "left", "right",
                        "start", "select",
                    ],
                },
            },
            "required": ["button"],
        },
    },
    {
        "name": "press_sequence",
        "description": (
            "Press multiple buttons in order with a short pause between each. "
            "Use for: multi-step menu navigation, confirming prompts. "
            "For name entry, use type_name() instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "buttons": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "a", "b", "x", "y", "l", "r",
                            "up", "down", "left", "right",
                            "start", "select",
                        ],
                    },
                    "description": "Sequence of buttons to press in order.",
                    "minItems": 1,
                    "maxItems": 20,
                },
            },
            "required": ["buttons"],
        },
    },
    {
        "name": "walk",
        "description": (
            "Walk in a direction for one or more steps. Each step = one tile. "
            "Use the spatial grid to plan your path — walk toward doors (D), "
            "stairs (S), or open tiles (.). Stops automatically before "
            "warps and ledges on multi-step walks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "Direction to walk.",
                    "enum": ["up", "down", "left", "right"],
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of tiles to walk (1-20). Default 1.",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 1,
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "touch",
        "description": (
            "Tap the bottom touch screen at a coordinate (256x192 pixels). "
            "Only the BOTTOM screen is touchable. Use for battle menu "
            "buttons and Poketch. x=0-255 left-to-right, y=0-191 top-to-bottom."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X coordinate on the bottom screen (0-255).",
                    "minimum": 0,
                    "maximum": 255,
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate on the bottom screen (0-191).",
                    "minimum": 0,
                    "maximum": 191,
                },
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_name",
        "description": (
            "Type a name on the name entry keyboard and confirm it. "
            "Handles uppercase/lowercase switching and key positions "
            "automatically. Use this whenever the name entry screen appears "
            "(for your character, rival, or Pokemon nicknames). "
            "Supports letters A-Z, a-z, digits 0-9, and basic punctuation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name to type (max 7 characters for trainer/rival, 10 for Pokemon).",
                    "maxLength": 10,
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Whether to press OK after typing. Default true.",
                    "default": True,
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "wait",
        "description": (
            "Do nothing and let the game run for a number of frames. "
            "Use for: watching an evolution, taking in a new area, letting "
            "dialogue finish, or just pausing to observe. Not every moment "
            "requires an action — sometimes the right thing is to watch."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "frames": {
                    "type": "integer",
                    "description": (
                        "Number of frames to advance (1-600). The game runs at 60fps. "
                        "60 = 1 second, 180 = 3 seconds, 300 = 5 seconds, 600 = 10 seconds. "
                        "Use longer waits for cutscenes and animations."
                    ),
                    "minimum": 1,
                    "maximum": 600,
                    "default": 60,
                },
            },
            "required": [],
        },
    },
]

REFERENCE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_type_chart",
        "description": (
            "Look up type effectiveness — like checking a reference book. "
            "Tells you how effective an attacking type is against one or "
            "two defending types. Useful before choosing a move in battle."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "attacking_type": {
                    "type": "string",
                    "description": "The type of the attacking move.",
                },
                "defending_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The defending Pokemon's type(s). One or two types.",
                    "minItems": 1,
                    "maxItems": 2,
                },
            },
            "required": ["attacking_type", "defending_types"],
        },
    },
    {
        "name": "check_bag",
        "description": (
            "Check your bag contents. Shows all items organized by pocket "
            "(Items, Key Items, TMs & HMs, Medicine, Berries, Poke Balls, "
            "Battle Items). Like opening the bag menu but without using a turn."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "check_party",
        "description": (
            "Get detailed information about your party Pokemon. Shows full "
            "stats, movesets with PP, abilities, natures, held items, EVs/IVs. "
            "More detail than the always-visible party summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

JOURNAL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "write_journal",
        "description": (
            "Write to your journal. This is YOUR notebook — write whatever "
            "you want to remember. Sections:\n"
            "- current_goals: What you're doing right now (overwrites previous)\n"
            "- team_notes: Notes about your Pokemon (overwrites previous)\n"
            "- adventure_log: Your story so far (appends new entry)\n"
            "- strategy: Battle lessons, type notes (appends)\n"
            "- map_notes: Observations about areas (appends)\n\n"
            "current_goals and team_notes are always visible in your context. "
            "The rest are available via read_journal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Which journal section to write to.",
                    "enum": [
                        "current_goals",
                        "team_notes",
                        "adventure_log",
                        "strategy",
                        "map_notes",
                    ],
                },
                "content": {
                    "type": "string",
                    "description": "The text to write. Be yourself — this is your notebook.",
                },
            },
            "required": ["section", "content"],
        },
    },
    {
        "name": "read_journal",
        "description": (
            "Read a section of your journal. current_goals and team_notes "
            "are always in your context, but you can use this to read "
            "strategy notes, map notes, or older adventure log entries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Which section to read.",
                    "enum": [
                        "current_goals",
                        "team_notes",
                        "adventure_log",
                        "strategy",
                        "map_notes",
                    ],
                },
                "entries": {
                    "type": "integer",
                    "description": "Number of most recent entries to return (default: all).",
                    "minimum": 1,
                },
            },
            "required": ["section"],
        },
    },
]


def get_all_tools() -> list[dict[str, Any]]:
    """Get all tool definitions for the API call."""
    return GAME_ACTION_TOOLS + REFERENCE_TOOLS + JOURNAL_TOOLS


def get_tool_names() -> list[str]:
    """Get all tool names."""
    return [t["name"] for t in get_all_tools()]


# Tool name sets for routing
GAME_ACTION_NAMES = {t["name"] for t in GAME_ACTION_TOOLS}
REFERENCE_TOOL_NAMES = {t["name"] for t in REFERENCE_TOOLS}
JOURNAL_TOOL_NAMES = {t["name"] for t in JOURNAL_TOOLS}
