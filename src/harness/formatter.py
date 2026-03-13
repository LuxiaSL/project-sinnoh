"""State formatter — combines game state into structured text for the agent prompt.

Formats differ by game mode:
- Overworld: location, position, party summary, badges, money
- Battle: enemy Pokemon, player's active Pokemon with moves
- Menu/dialogue: lighter format, just current context

The formatter produces scannable, consistent text that Claude can quickly parse
alongside the screenshot.
"""

from __future__ import annotations

from .models import GameState, Inventory, Party, PlayerState, Pokemon


def format_state(
    state: GameState,
    novelty_flags: list[str] | None = None,
    game_mode: str = "",
    available_actions: list[str] | None = None,
) -> str:
    """Format the full game state for the agent prompt.

    This is the primary entry point. Produces an overworld-style readout.
    """
    lines: list[str] = []
    lines.append("=== GAME STATE ===")

    # Game mode + available actions
    if game_mode:
        lines.append(f"Mode: {game_mode}")
    if available_actions:
        lines.append(f"Available actions: {', '.join(available_actions)}")

    # Location & position
    p = state.player
    loc_str = p.map_name if p.map_name else f"Map #{p.map_id}"
    lines.append(f"Location: {loc_str}")
    lines.append(f"Position: ({p.x}, {p.y})")

    # Trainer info
    lines.append(f"Badges: {p.badge_count}/8")
    lines.append(f"Money: ¥{p.money:,}")
    lines.append(f"Play Time: {p.play_time_str}")

    # Party summary
    party = state.party
    if party.count > 0:
        lines.append("")
        lines.append(f"--- PARTY ({party.count}/6) ---")
        for pkmn in party.pokemon:
            lines.append(_format_party_member(pkmn))
    else:
        lines.append("")
        lines.append("--- PARTY (empty) ---")

    # Novelty flags
    if novelty_flags:
        lines.append("")
        for flag in novelty_flags:
            lines.append(f"[!] {flag}")

    return "\n".join(lines)


def format_battle(
    player_pokemon: Pokemon,
    enemy_species: str = "???",
    enemy_level: int = 0,
    enemy_types: list[str] | None = None,
    enemy_hp_fraction: float = 1.0,
    is_wild: bool = True,
    novelty_flags: list[str] | None = None,
) -> str:
    """Format battle state for the agent prompt.

    Args:
        player_pokemon: The player's active Pokemon.
        enemy_species: Name of the opposing Pokemon.
        enemy_level: Level of the opposing Pokemon.
        enemy_types: Type(s) of the opposing Pokemon.
        enemy_hp_fraction: Approximate HP fraction (0.0-1.0).
        is_wild: Whether this is a wild encounter.
        novelty_flags: Any novelty flags to display.
    """
    lines: list[str] = []
    lines.append("=== BATTLE ===")

    # Enemy info
    battle_type = "Wild" if is_wild else "Trainer's"
    type_str = "/".join(enemy_types) if enemy_types else "???"
    hp_bar = _hp_bar(enemy_hp_fraction)
    lines.append(f"{battle_type} {enemy_species} Lv.{enemy_level}  [{type_str}]  HP: {hp_bar}")

    # Player's Pokemon
    lines.append("")
    pp = player_pokemon
    type_str = "/".join(pp.types) if pp.types else ""
    lines.append(f"Your {pp.nickname} Lv.{pp.level}  [{type_str}]  HP {pp.hp_current}/{pp.hp_max}")

    # Moves
    for i, move in enumerate(pp.moves):
        power_str = f"Pow:{move.power}" if move.power else "Status"
        lines.append(f"  {i+1}. {move.name:<14} [{move.type}]  {power_str}  PP {move.pp_current}/{move.pp_max}")

    # Pad if fewer than 4 moves
    for i in range(len(pp.moves), 4):
        lines.append(f"  {i+1}. —")

    # Novelty flags
    if novelty_flags:
        lines.append("")
        for flag in novelty_flags:
            lines.append(f"[!] {flag}")

    return "\n".join(lines)


def format_party_detail(party: Party) -> str:
    """Detailed party readout (for the check_party tool)."""
    if party.count == 0:
        return "Party is empty."

    lines: list[str] = []
    lines.append(f"=== PARTY ({party.count}/6) ===")
    for pkmn in party.pokemon:
        lines.append("")
        lines.append(_format_party_detail(pkmn))
    return "\n".join(lines)


def format_inventory(inventory: Inventory) -> str:
    """Format full bag contents for the check_bag tool."""
    if inventory.total_items == 0:
        return "Bag is empty."

    lines: list[str] = []
    lines.append(f"=== BAG ({inventory.total_items} items) ===")

    for pocket_name, pocket in inventory.pockets.items():
        if pocket.count == 0:
            continue
        lines.append("")
        lines.append(f"--- {pocket_name} ({pocket.count}) ---")
        for item in pocket.items:
            lines.append(f"  {item.item_name} ×{item.quantity}")

    return "\n".join(lines)


# === Internal helpers ===

def _format_party_member(pkmn: Pokemon) -> str:
    """One-line party member summary for the state readout."""
    type_str = "/".join(pkmn.types) if pkmn.types else ""
    gender = "♂" if not pkmn.is_egg else ""  # simplified for now
    status = pkmn.status_display()
    status_str = f"  {status}" if status != "OK" else ""

    name = pkmn.nickname if pkmn.nickname != pkmn.species_name else pkmn.species_name
    held = f" @{pkmn.held_item_name}" if pkmn.held_item_name else ""

    move_names = [m.name for m in pkmn.moves]
    moves_str = " | ".join(move_names) if move_names else "—"

    return (
        f"{pkmn.slot + 1}. {name} Lv.{pkmn.level}  [{type_str}]  "
        f"HP {pkmn.hp_current}/{pkmn.hp_max}{status_str}{held}\n"
        f"   Moves: {moves_str}"
    )


def _format_party_detail(pkmn: Pokemon) -> str:
    """Multi-line detailed info for a single Pokemon."""
    lines: list[str] = []
    type_str = "/".join(pkmn.types) if pkmn.types else ""
    nature_str = pkmn.nature.name if pkmn.nature else "???"
    shiny_str = " ★" if pkmn.is_shiny else ""

    lines.append(f"{pkmn.nickname} ({pkmn.species_name}) Lv.{pkmn.level}{shiny_str}")
    lines.append(f"  Type: {type_str}  Nature: {nature_str}  Ability: {pkmn.ability_name}")
    lines.append(f"  HP: {pkmn.hp_current}/{pkmn.hp_max}  Status: {pkmn.status_display()}")
    lines.append(f"  Atk:{pkmn.attack} Def:{pkmn.defense} SpA:{pkmn.sp_attack} SpD:{pkmn.sp_defense} Spe:{pkmn.speed}")

    if pkmn.held_item_name:
        lines.append(f"  Held: {pkmn.held_item_name}")

    lines.append("  Moves:")
    for move in pkmn.moves:
        power_str = f"Pow:{move.power}" if move.power else "Status"
        lines.append(f"    {move.name} [{move.type}/{move.category}] {power_str} PP {move.pp_current}/{move.pp_max}")

    return "\n".join(lines)


def _hp_bar(fraction: float, width: int = 10) -> str:
    """Simple text HP bar: ██████░░░░ ~60%"""
    filled = round(fraction * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = round(fraction * 100)
    return f"{bar} ~{pct}%"
