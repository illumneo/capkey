"""
Generate SVG files for capacitive touch pad layouts.

This script creates SVG files containing capacitive touch pad layouts with:
- Diamond-shaped pads arranged in rows and columns
- Connecting traces between pads
- Configurable pad spacing, size and corner radius

Usage:
    python3 generate_svg_capacitive_touch.py
    xdg-open touch_pads.svg
"""
import svg


def create_pad(x, y, pitch, radius, separation, edge_type=None):
    """
    Creates an SVG polygon representing a capacitive touch pad.

    Args:
        x (float): X coordinate of the pad center
        y (float): Y coordinate of the pad center
        pitch (float): Distance between pad centers
        radius (float): Corner radius and stroke width of the pad
        separation (float): Minimum spacing between adjacent pads
        edge_type (str, optional): Type of pad edge shape:
            - "start": Triangle pointing upward
            - "end": Triangle pointing downward
            - None: Diamond shape (default)

    Returns:
        svg.Polygon: SVG polygon element representing the pad
    """
    width = (pitch - radius) / 2 - separation
    if edge_type == "start":
        points = [ x-width, y, x+width, y, x, y+width]
    elif edge_type == "end":
        points = [ x-width, y, x+width, y, x, y-width]
    else:
        points = [ x-width, y, x, y+width, x+width, y, x, y-width]
    return svg.Polygon(
        points=points,
        stroke="black",
        fill="black",
        stroke_width=radius)


def create_flower_pad(x, y, pitch, radius, separation, edge_type=None):
    width = (pitch-radius)/2
    d_shift = separation
    points = [x-separation-d_shift, y+separation,
              x - width + separation, y+separation,
              x - width + separation, y+width - separation - d_shift,
            ]
    parameters = {
        "points": points,
        "stroke": "black",
        "fill": "black",
        "stroke_width": radius,
    }
    if edge_type == "start":
        rotations = [0, -90 ]
    elif edge_type == "end":
        rotations = [90, 180]
    else:
        rotations = [0, 90, 180, 270]
    return svg.G(elements=[svg.Polygon(**parameters, transform=[svg.Rotate(rot, x, y)]) for rot in rotations])


def create_flower_pad_old(x, y, pitch, radius, separation, edge_type=None):
    """
    Creates an SVG polygon representing a flower-shaped capacitive touch pad.

    Args:
        x (float): X coordinate of the pad center
        y (float): Y coordinate of the pad center
        pitch (float): Distance between pad centers
        radius (float): Corner radius and stroke width of the pad
        separation (float): Minimum spacing between adjacent pads
        edge_type (str, optional): Type of pad edge shape:
            - "start": Only top petals
            - "end": Only bottom petals
            - None: Full flower shape (default)

    Returns:
        svg.Polygon: SVG polygon element representing the flower-shaped pad

    """
    #width = (pitch - radius) / 2 - separation
    width = pitch/2 - separation/4
    points = []
    if edge_type == "start" or edge_type is None:
        points += [x - width, y,
                   x - width, y+width,
                   x-separation/2, y,
                   x, y,
                   x, y + width,
                   x + width, y+width,
                   x, y + separation/2
                ]

    if edge_type == "end" or edge_type is None:
        points += [x, y,
                    x, y - width,
                    x - width, y-width,
                    x, y-separation/2,
                    x, y, # maybe remove this? or modify to radius
                    x + width, y,
                    x + width, y-width,
                    x + separation/2, y,
                    x, y
                  ]


    return svg.Polygon(
        points=points,
        stroke="black",
        fill="black",
        stroke_width=radius)

def get_edge_type(i, count):
    """
    Determines the edge type for a pad based on its position in a row.
    """
    if i == 0:
        return "start"
    elif i == count-1:
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
            pad_function(pitch, i*pitch, pitch, radius, separation, edge_type=get_edge_type(i, count))
            for i in range(count)
        ]
    if trace_width > 0:
        elements.append(svg.Line(
            x1=pitch, x2=pitch,
            y1=0, y2=pitch * (count-1),
            stroke="black",
            stroke_width=trace_width,
        ))
    return svg.G(elements=elements)


def grid(pad_function, x_count, y_count, pitch, radius, separation, trace_width):
    columns = [
        row(pad_function, y_count + 1, pitch, radius, separation, trace_width)
        for i in range(x_count)
    ]
    for i, e in enumerate(columns):
        e.transform = [
            svg.Translate(i*pitch, 0)
        ]

    rows = [
        row(pad_function, x_count + 1, pitch, radius, separation, 0)
        for i in range(y_count)
    ]
    for i, e in enumerate(rows):
        e.transform = [
            svg.Rotate(-90, 0, 0),
            svg.Translate(-(i+1)*pitch - pitch/2, pitch/2),
        ]

    return svg.G(elements= columns + rows)

def draw() -> svg.SVG:
    return svg.SVG(
        width="200mm",
        height="250mm",
        viewBox="0 0 200 250",
        elements=[
            # create_flower_pad(x=10, y=10, pitch=4, radius=.2, separation=.25, edge_type=None),
             grid(create_pad, x_count=4, y_count=4, pitch=4, radius=.2, separation=.25, trace_width=.25),
            #row(create_flower_pad, count=4, pitch=4, radius=.2, separation=.25, trace_width=.25),
            # grid(create_flower_pad, x_count=4, y_count=4, pitch=10, radius=0, separation=.05, trace_width=0.05),


        ],
    )

canvas = draw()

if __name__ == '__main__':
    with open("touch_pads.svg", "w") as f:
        f.write(str(draw()))
