"""Screenshot capture and encoding for the Claude vision API.

Captures both DS screens from py-desmume and encodes them as base64
JPEG/PNG for inclusion in API requests.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from desmume.emulator import DeSmuME


@dataclass
class ScreenCapture:
    """A captured frame from both DS screens."""
    top: np.ndarray  # (192, 256, 3) RGB
    bottom: np.ndarray  # (192, 256, 3) RGB
    top_b64: str = ""
    bottom_b64: str = ""
    format: str = "png"

    @property
    def top_image(self) -> Image.Image:
        return Image.fromarray(self.top)

    @property
    def bottom_image(self) -> Image.Image:
        return Image.fromarray(self.bottom)


class ScreenshotPipeline:
    """Captures and encodes DS screens for the Claude vision API."""

    def __init__(
        self,
        emu: DeSmuME,
        format: Literal["png", "jpeg"] = "png",
        jpeg_quality: int = 85,
    ) -> None:
        self._emu = emu
        self._format = format
        self._jpeg_quality = jpeg_quality

    def capture(self, encode: bool = True) -> ScreenCapture:
        """Capture both screens, optionally encode to base64.

        Args:
            encode: If True, also generate base64 strings for API use.

        Returns:
            ScreenCapture with numpy arrays and optional base64 data.
        """
        buf = self._emu.display_buffer_as_rgbx()
        # NOTE: Despite the name, display_buffer_as_rgbx() returns BGRX.
        # We must swap B↔R to get proper RGB.
        raw = np.frombuffer(buf, dtype=np.uint8).reshape(384, 256, 4)
        frame = raw[:, :, 2::-1].copy()  # BGRX → RGB (take channels 2,1,0)
        top = frame[:192]
        bottom = frame[192:]

        cap = ScreenCapture(top=top, bottom=bottom, format=self._format)

        if encode:
            cap.top_b64 = self._encode_image(top)
            cap.bottom_b64 = self._encode_image(bottom)

        return cap

    def _encode_image(self, array: np.ndarray) -> str:
        """Encode a numpy RGB array to base64 string."""
        img = Image.fromarray(array)
        buf = io.BytesIO()
        if self._format == "jpeg":
            img.save(buf, format="JPEG", quality=self._jpeg_quality)
        else:
            img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    @property
    def media_type(self) -> str:
        """MIME type for the encoded images."""
        return f"image/{'jpeg' if self._format == 'jpeg' else 'png'}"

    def save(self, capture: ScreenCapture, path_prefix: str) -> None:
        """Save captured screens to disk."""
        Image.fromarray(capture.top).save(f"{path_prefix}_top.{self._format}")
        Image.fromarray(capture.bottom).save(f"{path_prefix}_bot.{self._format}")
