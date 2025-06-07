"""
Generate SVG files for capacitive touch pad layouts.

This script creates SVG files containing capacitive touch pad layouts with:
- Diamond-shaped or flower-shaped pads arranged in rows and columns
- Connecting traces between pads
- Configurable pad spacing, size and corner radius
- Multiple pad styles including diamond and flower shapes

Usage:
    python3 generate_svg_capacitive_touch.py
    xdg-open touch_pads.svg
"""

import svg
from math import sqrt


def create_pad(x, y, pitch, radius, separation, trace_width, edge_type=None):
    """
    Creates an SVG polygon representing a capacitive touch pad.

    Args:
        x (float): X coordinate of the pad center
        y (float): Y coordinate of the pad center
        pitch (float): Distance between pad centers
        radius (float): Corner radius and stroke width of the pad
        separation (float): Minimum spacing between adjacent pads
        trace_width (float): Width of connecting traces between pads
        edge_type (str, optional): Type of pad edge shape:
            - "start": Triangle pointing upward
            - "end": Triangle pointing downward
            - None: Diamond shape (default)

    Returns:
        svg.G: SVG group containing the pad polygon and optional connecting trace
    """
    width = (pitch - radius) / 2 - separation
    if edge_type == "start":
        points = [x - width, y, x + width, y, x, y + width]
    elif edge_type == "end":
        points = [x - width, y, x + width, y, x, y - width]
    else:
        points = [x - width, y, x, y + width, x + width, y, x, y - width]
    pad = svg.Polygon(points=points, stroke="black", fill="black", stroke_width=radius)
    if edge_type != "end" and trace_width > 0:
        connector_line = svg.Line(
            x1=x,
            y1=y + pitch / 2 - separation - radius,
            x2=x,
            y2=y + pitch / 2 + separation + radius,
            stroke="red",
            stroke_width=trace_width / 3,
        )
    else:
        connector_line = None
    return svg.G(elements=[pad, connector_line])


def create_flower_pad(x, y, pitch, radius, separation, trace_width, edge_type=None):
    """
    Creates an SVG group representing a flower-shaped capacitive touch pad.

    Args:
        x (float): X coordinate of the pad center
        y (float): Y coordinate of the pad center
        pitch (float): Distance between pad centers
        radius (float): Corner radius and stroke width of the pad petals
        separation (float): Minimum spacing between adjacent pads
        trace_width (float): Width of connecting traces between pads
        edge_type (str, optional): Type of pad edge shape:
            - "start": Two petals pointing upward
            - "end": Two petals pointing downward
            - None: Four petals in a flower shape (default)

    Returns:
        svg.G: SVG group containing the flower pad elements (petals, stems, center)
               and optional connecting trace
    """
    width = (pitch) / 2 - radius
    diag = (radius + separation / 2) * sqrt(2)
    points = [
        x + radius,
        y + radius + diag,
        x + radius,
        y + width - separation,
        x + width - diag - separation,
        y + width - separation,
    ]

    parameters = {
        "points": points,
        "stroke": "black",
        "stroke_linejoin": "round",
        "fill": "black",
        "stroke_width": radius * 2,
    }
    if edge_type == "start":
        rotations = [0, 90]
    elif edge_type == "end":
        rotations = [-90, 180]
    else:
        rotations = [0, 90, 180, 270]

    elements = []
    # petal
    elements += [
        svg.Polygon(**parameters, transform=[svg.Rotate(rot, x, y)])
        for rot in rotations
    ]
    # stem of petal
    tw = trace_width
    elements += [
        svg.Line(
            x1=x + tw / 2,
            y1=y,
            x2=x + tw / 2,
            y2=y + pitch / 4,
            stroke="black",
            stroke_width=tw,
            transform=[svg.Rotate(rot, x, y)],
        )
        for rot in rotations
    ]
    # center of pad
    elements += [
        svg.Rect(
            x=x - tw,
            y=y - tw,
            width=tw * 2,
            height=tw * 2,
            fill="black",
            transform=[svg.Rotate(rot, x, y)],
        )
        for rot in rotations
    ]

    if edge_type != "end" and trace_width > 0:
        elements += [
            svg.Line(
                x1=x + radius,
                y1=y + width - separation,
                x2=x - radius,
                y2=y + pitch / 2 + separation + radius,
                stroke="black",
                stroke_width=trace_width / 3,
            )
        ]

    return svg.G(elements=elements)


def get_edge_type(i, count):
    """
    Determines the edge type for a pad based on its position in a row.
    """
    if i == 0:
        return "start"
    elif i == count - 1:
        return "end"
    else:
        return None


def row(pad_function, count, pitch, radius, separation, trace_width):
    """
    Creates an SVG element containing a row of connected capacitive touch pads.

    Args:
        count (int): Number of pads in the row
        pitch (float): Distance between pad centers
        radius (float): Corner radius and stroke width of the pads
        separation (float): Minimum spacing between adjacent pads
        trace_width (float): Width of the connecting trace line

    Returns:
        svg.G: SVG group element containing:
            - A row of pads with appropriate edge types
            - A vertical trace line connecting all pads
    """
    elements = [
        pad_function(
            pitch,
            i * pitch,
            pitch,
            radius,
            separation,
            trace_width,
            edge_type=get_edge_type(i, count),
        )
        for i in range(count)
    ]
    return svg.G(elements=elements)


def grid(pad_function, x_count, y_count, pitch, radius, separation, trace_width):
    columns = [
        row(pad_function, y_count + 1, pitch, radius, separation, trace_width)
        for i in range(x_count)
    ]
    for i, e in enumerate(columns):
        e.transform = [svg.Translate(i * pitch, 0)]

    rows = [
        row(pad_function, x_count + 1, pitch, radius, separation, 0)
        for i in range(y_count)
    ]
    for i, e in enumerate(rows):
        e.transform = [
            svg.Rotate(-90, 0, 0),
            svg.Translate(-(i + 1) * pitch - pitch / 2, pitch / 2),
        ]

    return svg.G(elements=columns + rows)


def draw() -> svg.SVG:
    return svg.SVG(
        width="200mm",
        height="250mm",
        viewBox="0 0 200 250",
        elements=[
            # create_flower_pad(x=10, y=10, pitch=4, radius=.2, separation=.25, edge_type=None),
            # grid(create_pad, x_count=4, y_count=4, pitch=4, radius=.2, separation=.25, trace_width=.25),
            # row(create_flower_pad, count=4, pitch=4, radius=.2, separation=.25, trace_width=.25),
            grid(
                create_flower_pad,
                x_count=4,
                y_count=4,
                pitch=4,
                radius=0.1,
                separation=0.25,
                trace_width=0.25,
            ),
        ],
    )


canvas = draw()

if __name__ == "__main__":
    with open("touch_pads.svg", "w") as f:
        f.write(str(draw()))
