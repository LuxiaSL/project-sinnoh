#!/usr/bin/env python3
"""Interactive keyboard mapper — click to record key positions.

Displays the bottom screen screenshot at 3x scale. Click anywhere
and the pixel coordinates (in original 256x192 space) are printed
to the console. Use this to map out the name entry keyboard grid.

Usage:
    python tools/keyboard_mapper.py [screenshot_path]

Default: /tmp/platinum_bot.png
"""

import sys
from pathlib import Path

import pygame
from PIL import Image

SCALE = 3


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/platinum_bot.png")
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    img = Image.open(path).convert("RGB")
    w, h = img.size
    print(f"Image: {w}x{h}, displayed at {w*SCALE}x{h*SCALE}")
    print("Click to record coordinates. Press Q/Esc to quit.")
    print("Coordinates are in ORIGINAL pixel space (not scaled).\n")

    pygame.init()
    screen = pygame.display.set_mode((w * SCALE, h * SCALE))
    pygame.display.set_caption(f"Keyboard Mapper — {path.name}")

    # Convert PIL image to pygame surface
    data = img.tobytes()
    surface = pygame.image.fromstring(data, img.size, "RGB")
    surface = pygame.transform.scale(surface, (w * SCALE, h * SCALE))

    font = pygame.font.SysFont("monospace", 14)
    clicks: list[tuple[int, int]] = []

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                sx, sy = ev.pos
                # Convert to original pixel space
                ox = sx // SCALE
                oy = sy // SCALE
                clicks.append((ox, oy))
                print(f"  Click #{len(clicks):2d}: ({ox:3d}, {oy:3d})")

        # Draw
        screen.blit(surface, (0, 0))

        # Draw crosshairs on all clicks
        for i, (ox, oy) in enumerate(clicks):
            sx, sy = ox * SCALE, oy * SCALE
            color = (255, 80, 80) if i == len(clicks) - 1 else (80, 200, 80)
            pygame.draw.line(screen, color, (sx - 8, sy), (sx + 8, sy), 1)
            pygame.draw.line(screen, color, (sx, sy - 8), (sx, sy + 8), 1)
            label = font.render(f"{ox},{oy}", True, color)
            screen.blit(label, (sx + 6, sy - 14))

        pygame.display.flip()
        pygame.time.Clock().tick(30)

    pygame.quit()

    if clicks:
        print(f"\n=== {len(clicks)} points recorded ===")
        for i, (x, y) in enumerate(clicks):
            print(f"  {i+1}: ({x}, {y})")


if __name__ == "__main__":
    main()
