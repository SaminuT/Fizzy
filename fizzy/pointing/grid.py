"""Ask the vision model to locate something, in two passes over a labelled grid.

Models are poor at reading raw pixel coordinates but good at reading a
label printed on the picture. Pass one lays a coarse grid over the whole
screenshot and asks which cell holds the target; pass two zooms into that
cell (with a margin) and asks again on a finer grid.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from fizzy.ai.base import Provider, Request
from fizzy.context.screen import Shot, encode_jpeg
from fizzy.pointing.uia import Found

log = logging.getLogger(__name__)

COARSE = (10, 6)            # columns, rows
FINE = (5, 5)
ZOOM_WIDTH = 900
_CELL = re.compile(r"\b([A-Z])\s*-?\s*(\d{1,2})\b")


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    width: float
    height: float

    def cell(self, cols: int, rows: int, col: int, row: int) -> "Box":
        w, h = self.width / cols, self.height / rows
        return Box(self.left + col * w, self.top + row * h, w, h)

    def grown(self, by: float, limit: "Box") -> "Box":
        """Expand by a fraction of the size on each side, clipped to limit."""
        dx, dy = self.width * by, self.height * by
        left = max(limit.left, self.left - dx)
        top = max(limit.top, self.top - dy)
        right = min(limit.left + limit.width, self.left + self.width + dx)
        bottom = min(limit.top + limit.height, self.top + self.height + dy)
        return Box(left, top, right - left, bottom - top)

    @property
    def centre(self) -> tuple[float, float]:
        return self.left + self.width / 2, self.top + self.height / 2


def cell_name(col: int, row: int) -> str:
    return f"{chr(ord('A') + col)}{row + 1}"


def parse_cell(reply: str, cols: int, rows: int) -> Optional[tuple[int, int]]:
    if re.search(r"\bnone\b", reply, re.IGNORECASE):
        return None
    for m in _CELL.finditer(reply.upper()):
        col, row = ord(m.group(1)) - ord("A"), int(m.group(2)) - 1
        if 0 <= col < cols and 0 <= row < rows:
            return col, row
    return None


def draw_grid(img, cols: int, rows: int):
    """A copy of img with thin lines and a label in every cell."""
    from PIL import ImageDraw, ImageFont

    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out, "RGBA")
    w, h = out.size
    cw, ch = w / cols, h / rows
    size = max(12, int(min(cw, ch) / 4))
    try:
        font = ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    for c in range(1, cols):
        d.line([(c * cw, 0), (c * cw, h)], fill=(255, 0, 140, 170), width=2)
    for r in range(1, rows):
        d.line([(0, r * ch), (w, r * ch)], fill=(255, 0, 140, 170), width=2)
    for c in range(cols):
        for r in range(rows):
            label = cell_name(c, r)
            x, y = c * cw + 4, r * ch + 3
            box = d.textbbox((x, y), label, font=font)
            d.rectangle([box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1], fill=(20, 16, 30, 190))
            d.text((x, y), label, fill=(255, 255, 255, 255), font=font)
    return out


def _question(target: str, cols: int, rows: int, zoomed: bool) -> str:
    last = cell_name(cols - 1, rows - 1)
    where = "This is a zoomed-in part of the screen. " if zoomed else ""
    return (f"{where}The image has a grid with cells labelled A1 to {last} (letter = column from the left, "
            f"number = row from the top). Which cell contains the centre of: {target}? "
            "Reply with only the cell label, for example C4. If it isn't visible, reply NONE.")


async def _ask(provider: Provider, model: Optional[str], img, prompt: str) -> str:
    image = await asyncio.to_thread(encode_jpeg, img)
    req = Request(system="You locate things in screenshots. Answer with a grid cell label only.",
                  text=prompt, images=[image], model=model, max_tokens=300)
    return await provider.complete(req)


async def find(provider: Provider, model: Optional[str], shot: Shot, target: str) -> Optional[Found]:
    img = shot.pil
    whole = Box(0, 0, img.width, img.height)

    reply = await _ask(provider, model, await asyncio.to_thread(draw_grid, img, *COARSE),
                       _question(target, *COARSE, zoomed=False))
    hit = parse_cell(reply, *COARSE)
    log.info("grid pass 1: %r → %s", reply.strip()[:40], hit)
    if hit is None:
        return None
    region = whole.cell(*COARSE, *hit).grown(0.5, whole)

    crop = img.crop((round(region.left), round(region.top),
                     round(region.left + region.width), round(region.top + region.height)))
    scale = ZOOM_WIDTH / crop.width
    if scale > 1:
        crop = crop.resize((ZOOM_WIDTH, round(crop.height * scale)))
    reply = await _ask(provider, model, await asyncio.to_thread(draw_grid, crop, *FINE),
                       _question(target, *FINE, zoomed=True))
    fine = parse_cell(reply, *FINE)
    log.info("grid pass 2: %r → %s", reply.strip()[:40], fine)
    spot = region.cell(*FINE, *fine) if fine else region.cell(1, 1, 0, 0)
    ix, iy = spot.centre
    px, py = shot.image_to_physical(ix, iy)
    return Found(px, py, target, 0.6 if fine else 0.4, "grid")
