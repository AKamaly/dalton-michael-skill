#!/usr/bin/env python3
"""Generate the Dalton + Michael pixel-art app icon for the README.

Unofficial fan art: Dalton Caldwell (left) and Michael Seibel (right) at the
show's table, with the orange "+" from the DALTON + MICHAEL wordmark.

The art is a 48x48 character map (one character per palette color, "." is the
tile background). Each cell is scaled up with hard edges, then the tile is cut
to a rounded square (corner radius 22% of the size) with transparent corners.

Usage (needs Pillow):  python3 docs/icon/make_icon.py
Writes docs/icon.png (512x512) and docs/icon-1024.png (1024x1024).
"""
from pathlib import Path

from PIL import Image, ImageDraw

BG = "#141416"  # tile background, matches the player

PALETTE = {
    # shared warm ramp: Dalton skin (1-3), Michael skin (3-5), Dalton hair (5-7), table (4-6)
    "1": "#f4cfb8",
    "2": "#e6ad92",
    "3": "#c68c72",
    "4": "#9b6a54",
    "5": "#6c4636",
    "6": "#3f2618",
    "7": "#24160f",
    # Dalton's mustard shirt
    "a": "#dca34a",
    "b": "#bb8434",
    "c": "#8a5c24",
    # grays: beard and teeth, Michael's charcoal shirt, glasses, mics
    "w": "#ece8e0",
    "x": "#b0ada6",
    "y": "#6e7076",
    "z": "#46484e",
    "q": "#2c2d31",
    "k": "#0d0d0f",
    # the one accent: the "+"
    "o": "#ff6b35",
}

ART = [
    "................................................",  #  0
    "................................................",  #  1
    "................................................",  #  2
    "........656..656................................",  #  3
    "......665566655666..............................",  #  4
    "....6655665556655666............................",  #  5
    "...66556675566755666............................",  #  6
    "...65566755667556676.............3334444........",  #  7
    "..665667556675566766...........43334444444......",  #  8
    "..666675667556675666..........4331144444445.....",  #  9
    "..666765666722222676.........433334444444445....",  # 10
    "..667656722222222766...oo....433444444444445....",  # 11
    "..667672222222222766...oo...43344444444444445...",  # 12
    "..667622222222223676.oooooo.44455544455544445...",  # 13
    "..667626662226663676.oooooo.44444444444444445...",  # 14
    "..667222w7222w72366....oo...kkkkkkk4kkkkkkkkk...",  # 15
    "...6732222222322326....oo..44kx444kkkx444k4455..",  # 16
    "....62222222232233.........34k4774k3k4774k4454..",  # 17
    ".....3222222232233.........44kkkkkk3kkkkkk4454..",  # 18
    "......22222333223..........5443344434444344455..",  # 19
    "......22252222523...........43344533454434445...",  # 20
    ".......2225555223...........44444455544444445...",  # 21
    ".......2222222223............444y666666y4455....",  # 22
    "........22222223.............44x6wwwwww6x445....",  # 23
    "........22222223..............4xx5kkkk5xx45.....",  # 24
    ".........222223...............4xxwxwxxxxy45.....",  # 25
    "..........3333.................4xwwxxxxyy5......",  # 26
    "........ab2223ba................5xwxxxxy5.......",  # 27
    ".....bbbbaaqqaabbbb..............yxxxxyy........",  # 28
    "....bbbbbcaqqacbbbbb.........zzyz5yxxy5zyzz.....",  # 29
    "...abbbbbbcaaacbbbbbb......zzzzzyykkkkyyzzzzz...",  # 30
    "..abbbbbbbbccccbbbbbbc....yyzzzzzyykkyyzzzzzyy..",  # 31
    "..abbbbbbbbbcbbbbbbbbc....yzzzzzzzzzzzzzzzzzzz..",  # 32
    "..abbbbbbbbbcbbbbbbbbc...yzzzzzzzzzzqzzzzzzzzzq.",  # 33
    "..abbbcbbbbbabbbkkkbbc...yzzzkkkzzzzqzzzzzzzzzq.",  # 34
    "..abbbcbbbbbcbbkyqykbc...yzzkyqykzzzqzzzzzzzzzq.",  # 35
    "..abbbcbbbbbcbbkqyqkbc...yzzkqyqkzzzqzzqqqqqzzq.",  # 36
    "..abbbcbbbbbcbbkyqykbc...yzzkyqykzzzqzzqzzzqzzq.",  # 37
    "..abbbcbbbbbabbbkkkbbc...yzzzkkkzzzzyzzzzzzzzzq.",  # 38
    "..abbbcbbbbbcbbbbkbbbc...yzzzzkzzzzzqzzzzzzzzzq.",  # 39
    ".abbbbcbbbbbcbbbbkbbbc...yzzzzkzzzzzqzzzzzzzzzq.",  # 40
    "4444444444444444kkk4444444444kkk4444444444444444",  # 41
    "666666666666666666666666666666666666666666666666",  # 42
    "555555555555555555555555555555555555555555555555",  # 43
    "555555555555555555555555555555555555555555555555",  # 44
    "555555555555555555555555555555555555555555555555",  # 45
    "555555555555555555555555555555555555555555555555",  # 46
    "555555555555555555555555555555555555555555555555",  # 47
]

GRID = len(ART)
CORNER = 0.22  # corner radius as a fraction of the tile size


def render(size: int) -> Image.Image:
    cell = size * 10 // 512  # 10 px per cell at 512, 20 px at 1024
    margin = (size - GRID * cell) // 2
    tile = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(tile)
    for y, row in enumerate(ART):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            x0, y0 = margin + x * cell, margin + y * cell
            x1, y1 = x0 + cell - 1, y0 + cell - 1
            # edge cells bleed into the margin so the table runs to the tile edge
            if x == 0:
                x0 = 0
            if x == GRID - 1:
                x1 = size - 1
            if y == GRID - 1:
                y1 = size - 1
            draw.rectangle([x0, y0, x1, y1], fill=PALETTE[ch])
    # rounded-square mask, supersampled so only the tile outline is smooth
    ss = 4
    mask = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size * ss - 1, size * ss - 1], radius=round(CORNER * size * ss), fill=255
    )
    mask = mask.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(tile, (0, 0), mask)
    return out


def main() -> None:
    assert GRID == 48 and all(len(r) == GRID for r in ART), "ART must be 48x48"
    unknown = {ch for r in ART for ch in r} - set(PALETTE) - {"."}
    assert not unknown, f"unknown palette keys: {unknown}"
    docs = Path(__file__).resolve().parent.parent
    render(512).save(docs / "icon.png", optimize=True)
    render(1024).save(docs / "icon-1024.png", optimize=True)
    print(f"wrote {docs / 'icon.png'} and {docs / 'icon-1024.png'}")


if __name__ == "__main__":
    main()
