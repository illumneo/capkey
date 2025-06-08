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


class Pad:
    """
    A class representing a capacitive touch pad with configurable parameters.

    Args:
        pad_function (Callable): Function that generates the pad shape
        pitch (float): Distance between pad centers
        radius (float): Corner radius and stroke width of the pad
        separation (float): Minimum spacing between adjacent pads
        trace_width (float): Width of connecting traces between pads
    """

    def __init__(self, pitch, radius, separation, trace_width):
        self.pitch = pitch
        self.radius = radius
        self.separation = separation
        self.trace_width = trace_width

    def generate(self, x, y, connection_type, edge_type):
        raise NotImplementedError("Subclasses must implement this method")


class DiamondPad(Pad):
    def __init__(self, pitch, radius, separation, trace_width):
        super().__init__(pitch, radius, separation, trace_width)

    def generate(self, x, y, connection_type, edge_type):
        """
        Creates an SVG polygon representing a diamond-shaped capacitive touch pad.

        Args:
            pad (Pad): Pad configuration object containing pad parameters
            x (float): X coordinate of the pad center
            y (float): Y coordinate of the pad center
            connection_type (str): Type of connection:
                - "via": Connect via
                - "trace": Connect with a trace
            edge_type (str): Type of pad edge shape:
                - "start": Triangle pointing upward
                - "end": Triangle pointing downward
                - "center": Diamond shape

        Returns:
            svg.G: SVG group containing the pad polygon and optional connecting trace
        """
        width = (self.pitch - self.radius) / 2 - self.separation
        if edge_type == "start":
            points = [x - width, y, x + width, y, x, y + width]
        elif edge_type == "end":
            points = [x - width, y, x + width, y, x, y - width]
        else:
            points = [x - width, y, x, y + width, x + width, y, x, y - width]
        diamond = svg.Polygon(
            points=points, stroke="black", fill="black", stroke_width=self.radius
        )
        if edge_type != "end" and connection_type == "trace":
            connector_line = svg.Line(
                x1=x,
                y1=y + self.pitch / 2 - self.separation - self.radius,
                x2=x,
                y2=y + self.pitch / 2 + self.separation + self.radius,
                stroke="black",
                stroke_width=self.trace_width / 3,
            )
        else:
            connector_line = None
        return svg.G(elements=[diamond, connector_line])


class FlowerPad(Pad):
    def __init__(self, pitch, radius, separation, trace_width):
        super().__init__(pitch, radius, separation, trace_width)

    def generate(self, x, y, connection_type, edge_type):
        """
        Creates an SVG group representing a flower-shaped capacitive touch pad.

        Args:
            pad (Pad): Pad configuration object containing pad parameters
            x (float): X coordinate of the pad center
            y (float): Y coordinate of the pad center
            connection_type (str): Type of connection:
                - "via": Connect via
                - "trace": Connect with a trace
            edge_type (str): Type of pad edge shape:
                - "start": Two petals pointing upward
                - "end": Two petals pointing downward
                - "center": Four petals in a flower shape

        Returns:
            svg.G: SVG group containing the flower pad elements (petals, stems, center)
                and optional connecting trace
        """
        width = (self.pitch) / 2 - self.radius
        diag = (self.radius + self.separation / 2) * sqrt(2)
        points = [
            x + self.radius,
            y + self.radius + diag,
            x + self.radius,
            y + width - self.separation,
            x + width - diag - self.separation,
            y + width - self.separation,
        ]

        parameters = {
            "points": points,
            "stroke": "black",
            "stroke_linejoin": "round",
            "fill": "black",
            "stroke_width": self.radius * 2,
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
        elements += [
            svg.Line(
                x1=x + self.trace_width / 2,
                y1=y,
                x2=x + self.trace_width / 2,
                y2=y + self.pitch / 4,
                stroke="black",
                stroke_width=self.trace_width,
                transform=[svg.Rotate(rot, x, y)],
            )
            for rot in rotations
        ]

        if edge_type != "end" and connection_type == "trace":
            elements += [
                svg.Line(
                    x1=x + self.radius,
                    y1=y + width - self.separation,
                    x2=x - self.radius,
                    y2=y + self.pitch / 2 + self.separation + self.radius,
                    stroke="black",
                    stroke_width=self.trace_width / 3,
                )
            ]

        return svg.G(elements=elements)


class TouchGrid:
    def __init__(self, pad: Pad, x_count: int, y_count: int):
        self.pad = pad
        self.x_count = x_count
        self.y_count = y_count

    def generate(self) -> svg.G:
        columns = [self._row(connection_type="trace") for i in range(self.x_count)]
        for i, e in enumerate(columns):
            e.transform = [svg.Translate(i * self.pad.pitch, 0)]
        rows = [self._row(connection_type="via") for i in range(self.y_count)]
        for i, e in enumerate(rows):
            e.transform = [
                svg.Rotate(-90, 0, 0),
                svg.Translate(
                    -(i + 1) * self.pad.pitch - self.pad.pitch / 2, self.pad.pitch / 2
                ),
            ]

        width = self.pad.pitch * (self.x_count + 1)
        height = self.pad.pitch * (self.y_count + 1)
        return svg.SVG(
            width=str(width) + "mm",
            height=str(height) + "mm",
            viewBox=f"0 0 {width} {height}",
            elements=columns + rows,
        )

    def _get_edge_type(self, i, count):
        """
        Determines the edge type for a pad based on its position in a row.
        """
        if i == 0:
            return "start"
        elif i == count - 1:
            return "end"
        else:
            return "center"

    def _row(self, connection_type: str) -> svg.G:
        """
        Creates an SVG element containing a row of connected capacitive touch pads.

        Args:
            pad (Pad): Pad configuration object containing pad parameters
            count (int): Number of pads in the row

        Returns:
            svg.G: SVG group element containing:
                - A row of pads with appropriate edge and connection types
        """
        count = self.x_count + 1  # +1 since edge pads are ~1/2 pitch
        elements = [
            self.pad.generate(
                self.pad.pitch,
                i * self.pad.pitch,
                connection_type=connection_type,
                edge_type=self._get_edge_type(i, count),
            )
            for i in range(count)
        ]
        return svg.G(elements=elements)


def draw() -> svg.SVG:

    pad = FlowerPad(
        pitch=4,
        radius=0.1,
        separation=0.25,
        trace_width=0.25,
    )
    return TouchGrid(pad, x_count=4, y_count=4).generate()

    # return svg.SVG(
    #     width="200mm",
    #     height="250mm",
    #     viewBox="0 0 200 250",
    #     elements=[
    #         # create_flower_pad(x=10, y=10, pitch=4, radius=.2, separation=.25, edge_type="center"),
    #         # grid(create_diamond_pad, x_count=4, y_count=4, pitch=4, radius=.2, separation=.25, trace_width=.25),
    #         # row(create_flower_pad, count=4, pitch=4, radius=.2, separation=.25, trace_width=.25),
    #         # grid(
    #         #     create_flower_pad,
    #         #     x_count=4,
    #         #     y_count=4,
    #         #     pitch=4,
    #         #     radius=0.1,
    #         #     separation=0.25,
    #         #     trace_width=0.25,
    #         # ),
    #         # grid(pad, x_count=4, y_count=4),
    #         TouchGrid(pad, x_count=4, y_count=4).generate(),
    #     ],
    # )


canvas = draw()

if __name__ == "__main__":
    with open("touch_pads.svg", "w") as f:
        f.write(str(draw()))
