# Project Sinnoh

An AI harness for Claude to play Pokemon Platinum (NDS) — for fun, not as a benchmark.

## What This Is

A harness that connects Claude to a Pokemon Platinum emulator via [py-desmume](https://github.com/SkyTemple/py-desmume), giving it:

- **Vision**: Screenshots of both DS screens, delivered with clear top/bottom labels
- **Game state from RAM**: Player position, party Pokemon, badges, inventory, battle state — all read directly from emulator memory
- **Spatial awareness**: A collision grid read from RAM showing walls, doors, stairs, NPCs, grass, water, and warps with destination names
- **Dialogue transcript**: Live text read from the game's String buffers in RAM, covering both overworld NPC dialogue and battle messages
- **A journal**: Claude's own persistent notebook for goals, team notes, adventure log, and strategy
- **Tools**: Walk, press buttons, check type chart, write journal entries — all via Claude's tool-use API

No autopilot, no pathfinding, no battle AI. Claude plays the game.

## Architecture

```
Claude (Sonnet/Opus)
    |
    | tool-use API
    |
Agent Loop (perceive -> think -> act)
    |
    +-- Memory Reader -----> RAM state (player, party, battle)
    +-- Screenshot Pipeline -> JPEG frames (both screens)
    +-- Collision Reader ---> 32x32 tile grid from FieldSystem
    +-- Dialogue Transcript -> Live text from String buffers
    +-- Spatial Grid -------> 11x11 ASCII map around player
    +-- Journal System -----> Persistent markdown notebook
    +-- Action Executor ----> Button presses, walks, touch input
    |
py-desmume (headless NDS emulator)
    |
Pokemon Platinum (US) ROM
```

Each turn: wait for the game to idle, capture state + screenshots, send to Claude, parse tool calls, execute actions, repeat.

## Design Philosophy

**Scaffold the interface, not the cognition.** Give Claude human-equivalent perception and memory aids. Don't play the game for it.

- The spatial grid shows what a human player sees at a glance — walls, doors, NPCs
- The dialogue transcript provides short-term memory that a human has naturally
- The journal is Claude's own notebook, not an auto-summary
- No walkthrough knowledge, no optimal strategies, no forced behaviors

The question isn't "can it beat the game?" — it's "is Claude having a good time?"

## Setup

### Requirements

- Python 3.10+
- Pokemon Platinum (US) ROM (v1.0, CRC `9253921D`)
- Anthropic API key

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
# From the golden savestate (post-intro, in bedroom):
python run.py --max-turns 50

# From ROM boot (full intro sequence):
python run.py --fresh --max-turns 0

# Resume from where the last run left off:
python run.py --resume --max-turns 50
```

Set your API key via `--api-key` or the `ANTHROPIC_API_KEY` environment variable.

The ROM goes in `roms/Pokemon - Platinum Version (USA).nds`.

### Optional: Reference Decompilation

For development, the [pret/pokeplatinum](https://github.com/pret/pokeplatinum) decompilation is useful for RAM offset research:

```bash
git clone https://github.com/pret/pokeplatinum references/pokeplatinum
```

## Project Status

**Phases 0-2 complete.** Claude can:
- Navigate the overworld using the spatial grid
- Read and respond to NPC dialogue
- Enter/exit buildings (doors and stairs detected from RAM)
- Pick a starter Pokemon and battle
- Write journal entries about the experience

**In progress:** Battle tools, streaming integration, context management tuning.

## How It Works

### Perception Layer (Phase 1)
- **Memory Reader**: Reads player state, party Pokemon (with Gen 4 PRNG decryption), inventory, badges from the save block in RAM
- **Screenshot Pipeline**: Captures both DS screens, encodes as JPEG, labels top (view-only) vs bottom (touchable)
- **Collision Reader**: Finds the FieldSystem in the heap via structural fingerprinting, reads the LandDataManager's active quadrant to get the 32x32 tile grid with collision, behavior, and warp data
- **Dialogue Transcript**: Scans RAM for live String structs (integrity magic `0xB6F8D2EC`), reads both overworld buffers (maxSize=1024) and battle message buffers (maxSize=320)

### Agent Loop (Phase 2)
- Tool-use API with Claude (Sonnet or Opus)
- Rolling context window with automatic rotation at 170K tokens
- Prompt caching for the static system prompt + tools
- Game state delivered every turn (not just on "fresh" turns)
- Walk-before-warp clamping prevents accidentally entering buildings during multi-step movement

### Key Technical Details
- `SDL_VIDEODRIVER=dummy` must be set before importing py-desmume (headless mode)
- Gen 4 Pokemon encryption: PRNG seed from checksum, block shuffle by `(PID >> 0xD) & 0x1F) % 24`
- Character encoding: Gen 4 table with A=0x012B (not Unicode, not Bulbapedia's claimed 0x0133)
- Save block base: `read32(0x02101D40) + 0x14` — all PKHeX offsets work from here
- Battle indicator: u8 at `0x021D18F2` (values 0x41/0x97/0xC0 = in battle)

## Cost

With Sonnet: ~$0.01-0.07 per turn depending on context size. A full bedroom-to-starter run (~200 turns) costs ~$5-10. Opus would be ~5x that.

## Acknowledgments

- [py-desmume](https://github.com/SkyTemple/py-desmume) — Python bindings for DeSmuME
- [pret/pokeplatinum](https://github.com/pret/pokeplatinum) — Pokemon Platinum decompilation (invaluable for RAM research)
- [PKHeX](https://github.com/kwsch/PKHeX) — Save block structure reference
- [ClaudePlaysPokemonStarter](https://github.com/anthropics/anthropic-quickstarts/tree/main/claude-plays-pokemon) — Anthropic's official starter (canonical tool-use pattern)
- [pokebot-nds](https://github.com/40Cakes/pokebot-nds) — Battle state pointer chains

## License

MIT
