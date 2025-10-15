"""
Generate SVG files for capacitive touch pad silkscreen.

Usage:
    pip install svg.py
    python3 generate_touch_silkscreen.py
    xdg-open touch_silkscreen.svg
"""

import svg
from math import sqrt
from svg import mm
from textwrap import dedent


class Key:
    def __init__(self, letters, styles):
        self.letters = letters
        self.styles = styles


keys = [
    Key(
        ["A", " ", " ", " ", "$", " ", "V", "-", " "],
        [
            "center",
            " border",
            " border",
            " border",
            " special",
            " border",
            " border",
            " special",
            " border",
        ],
    ),
    Key(
        ["N", "^", "`", "+", "/", "L", "\\", "!", " "],
        [
            "center",
            "special",
            "special",
            "special",
            "special",
            " border",
            " special",
            " special",
            " border",
        ],
    ),
    Key(
        ["I", " ", " ", "?", "X", "=", " ", " ", " "],
        [
            "center",
            " border",
            " border",
            " special",
            " border",
            " special",
            " border",
            " border",
            " border",
        ],
    ),
    Key(
        ["H", " ", "{", "(", "[", " ", "_", "K", "%"],
        [
            "center",
            " border",
            " special",
            " special",
            " special",
            " border",
            " special",
            " border",
            " special",
        ],
    ),
    Key(
        ["O", "U", "Q", "C", "G", "D", "J", "B", "P"],
        [
            "center",
            " border",
            " border",
            " border",
            " border",
            " border",
            " border",
            " border",
            " border",
        ],
    ),
    Key(
        ["R", "▴", "|", "M", "@", "▾", "]", ")", "}"],
        [
            "center",
            " border",
            " special",
            " border",
            " special",
            " border",
            " special",
            " special",
            " special",
        ],
    ),
    Key(
        ["T", " ", "~", "<", " ", " ", "⇥", "*", "Y"],
        [
            "center",
            " border",
            " special",
            " special",
            " border",
            " border",
            " border",
            " special",
            " border",
        ],
    ),
    Key(
        ["E", "W", '"', " ", ",", ".", ":", "Z", "'"],
        [
            "center",
            " border",
            " border",
            " border",
            " border",
            " border",
            " border",
            " border",
            " border",
        ],
    ),
    Key(
        ["S", "＆", "F", "#", ";", " ", " ", ">", " "],
        [
            "center",
            " special",
            " border",
            " special",
            " border",
            " border",
            " border",
            " special",
            " special",
        ],
    ),
]


sidebar = [
    Key([" ", " ", " ", " ", " ", " ", " ", " ", " "], ["border"] * 9),
    Key([" ", " ", " ", " ", " ", " ", " ", " ", " "], ["border"] * 9),
    Key(["⌫", " ", " ", " ", " ", " ", " ", " ", " "],  ["center"] + ["border"] * 8),
    Key(["⮐", " ", " ", " ", " ", " ", " ", " ", " "], ["center"] + ["border"] * 8),
]


# create a square with a center letter, and letters around in each corner/edge
# inputs consist of: a list of the 9 letters, size of square, and x and y offsets
def create_square(key: Key, size, x_offset, y_offset):
    offset_from_edge = size / 5
    elements = []
    letter_offset = size / 2 - offset_from_edge
    positions = [
        (0, 0),  # center
        (0, -letter_offset),  # N
        (-letter_offset, -letter_offset),  # NW
        (-letter_offset, 0),  # W
        (-letter_offset, letter_offset),  # SW
        (0, letter_offset),  # S
        (letter_offset, letter_offset),  # SE
        (letter_offset, 0),  # E
        (letter_offset, -letter_offset),  # NE
    ]

    elements.append(
        svg.Style(
            text=dedent(
                """
                    .border { font: 1mm Helvetica Neue; font-weight: 400; text-anchor: middle; dominant-baseline: middle; }
                    .center { font:  1.1mm Helvetica Neue; font-weight: 800; text-anchor: middle; dominant-baseline: middle; }
                    .special { font: 0.9mm Helvetica Neue; font-weight: 300; text-anchor: middle; dominant-baseline: middle; }
                """
            )
        )
    )
    elements.append(
        svg.Rect(
            x=x_offset - size / 2,
            y=y_offset - size / 2,
            width=size,
            height=size,
            fill="none",
            stroke="black",
            stroke_width=0.2,
            rx=1,
            ry=1,
        )
    )

    #  Letters
    for letter, position, style in zip(key.letters, positions, key.styles):
        elements.append(
            svg.Text(
                x=position[0] + x_offset,
                y=position[1] + y_offset,
                class_=style,
                text=letter,
                fill="black",
            )
        )

    return elements


def create_whole_board():
    elements = []
    size = 48 / 4

    # Main keys
    for i in range(3):
        for j in range(3):
            elements.extend(
                create_square(
                    keys[i + 3 * j],
                    size,
                    i * size + size / 2,
                    j * size + size / 2,
                )
            )

    # Sidebar
    for i in range(4):
        elements.extend(
            create_square(sidebar[i], size, 3*size + size / 2, i * size + size / 2)
        )

    # Space bar
    elements.append(
        svg.Rect(
            x=0,
            y=3 * size,
            width=size * 3,
            height=size,
            fill="none",
            stroke="black",
            stroke_width=0.2,
            rx=1,
            ry=1,
        )
    )
    return svg.SVG(
        width="50mm",
        height="50mm",
        viewBox="0 0 50 50",
        elements=elements,
    )


if __name__ == "__main__":
    with open("touch_silkscreen.svg", "w") as f:
        # f.write(
        #     str(create_square(["A", "B", "C", "D", "E", "F", "G", "H", "I"], 100, 0, 0))
        # )
        # f.write(str(draw()))
        f.write(str(create_whole_board()))
