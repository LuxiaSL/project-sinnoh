#!/usr/bin/env python3
"""Run the Pokemon Platinum agent loop.

Usage:
    # From golden savestate (post-intro, in bedroom):
    python run.py --max-turns 30

    # From scratch (ROM boot, title screen, full intro):
    python run.py --fresh --max-turns 45

    # Resume from where the last run left off:
    python run.py --resume --max-turns 30

    # View live in another terminal:
    python viewer.py --live-dir platinum_save/live

Environment variables:
    ANTHROPIC_API_KEY: API key (alternative to --api-key)
    SDL_VIDEODRIVER: Set to "dummy" automatically for headless mode
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Must set SDL_VIDEODRIVER before any desmume import
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pokemon Platinum Agent Loop")
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY", ""),
                        help="Anthropic API key")
    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Model to use")
    parser.add_argument("--rom", default="roms/Pokemon - Platinum Version (USA).nds",
                        help="Path to ROM file")
    parser.add_argument("--savestate",
                        default="tests/output/clean_intro/golden_gameplay.dst",
                        help="Savestate to load (use --fresh to skip)")
    parser.add_argument("--fresh", action="store_true",
                        help="Start from ROM boot — no savestate, full intro")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from where the last run left off")
    parser.add_argument("--save-dir", default="platinum_save",
                        help="Directory for save data")
    parser.add_argument("--format", default="jpeg", choices=["png", "jpeg"],
                        help="Screenshot format (jpeg saves tokens)")
    parser.add_argument("--max-turns", type=int, default=0,
                        help="Maximum turns (0 = unlimited)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("pkmn")

    if not args.api_key:
        logger.error("No API key provided. Use --api-key or set ANTHROPIC_API_KEY.")
        sys.exit(1)

    # Initialize emulator
    from desmume.emulator import DeSmuME
    from pathlib import Path

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    resume_savestate = save_dir / "emulator.dst"

    logger.info("Initializing emulator...")
    emu = DeSmuME()
    emu.open(args.rom)

    savestate_used = ""
    if args.fresh:
        logger.info("Fresh start — ROM boot, no savestate")
        for _ in range(30):
            emu.cycle(with_joystick=False)
    elif args.resume and resume_savestate.exists():
        logger.info(f"Resuming from: {resume_savestate}")
        emu.savestate.load_file(str(resume_savestate))
        savestate_used = str(resume_savestate)
        for _ in range(60):
            emu.cycle(with_joystick=False)
    elif args.resume and not resume_savestate.exists():
        logger.warning(f"No resume savestate found at {resume_savestate} — using golden savestate")
        emu.savestate.load_file(args.savestate)
        savestate_used = args.savestate
        for _ in range(60):
            emu.cycle(with_joystick=False)
    else:
        logger.info(f"Loading savestate: {args.savestate}")
        emu.savestate.load_file(args.savestate)
        savestate_used = args.savestate
        for _ in range(60):
            emu.cycle(with_joystick=False)

    # Initialize loop
    from harness.loop import AgentLoop, LoopConfig

    config = LoopConfig(
        save_dir=save_dir,
        rom_path=args.rom,
        savestate_path=savestate_used,
        api_key=args.api_key,
        model=args.model,
        screenshot_format=args.format,
        live_frame_path=save_dir / "live",
    )

    loop = AgentLoop(emu, config)
    loop.setup()

    # Load conversation history if resuming
    history_path = save_dir / "history.json"
    if args.resume and history_path.exists() and loop._agent:
        loop._agent.load_history(history_path)

    logger.info(f"Agent loop ready. Model: {args.model}")
    logger.info(f"Traces: {loop.tracer.trace_dir}")
    logger.info(f"Live viewer: python viewer.py --live-dir {save_dir / 'live'}")
    logger.info("Starting game loop... (Ctrl+C to stop)")

    turn_count = 0
    try:
        while loop.running:
            trace = loop.step()

            turn_count += 1
            if args.max_turns > 0 and turn_count >= args.max_turns:
                logger.info(f"Reached max turns ({args.max_turns})")
                break

            # Print agent's thoughts
            if trace.agent_text:
                text_preview = trace.agent_text[:300]
                print(f"\n--- Turn {turn_count} [{trace.game_mode}] "
                      f"{trace.map_name or '???'} ({trace.x},{trace.y}) ---")
                print(text_preview)
                if len(trace.agent_text) > 300:
                    print("...")
                for tc in trace.tool_calls:
                    print(f"  -> {tc['name']}({tc['input']})")
                for tr in trace.tool_results:
                    result_preview = tr.get("result", "")[:80]
                    print(f"  <- {tr['name']}: {result_preview}")

            if trace.error:
                print(f"  ERROR: {trace.error}")

    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        # Save emulator state + conversation history for --resume
        try:
            emu.savestate.save_file(str(resume_savestate))
            logger.info(f"Emulator state saved to: {resume_savestate}")
        except Exception as e:
            logger.error(f"Failed to save emulator state: {e}")

        if loop._agent:
            try:
                loop._agent.save_history(history_path)
            except Exception as e:
                logger.error(f"Failed to save conversation history: {e}")

        loop.stop()
        if loop._agent:
            print(f"\nAPI usage: {loop._agent.usage.summary()}")
            print(f"Cost: {loop._agent.costs.format_oneliner()}")
        print(f"Traces saved to: {loop.tracer.trace_dir}")
        logger.info("Done.")


if __name__ == "__main__":
    main()
