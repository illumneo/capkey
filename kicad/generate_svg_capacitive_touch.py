"""
Generate SVG files for capacitive touch pad layouts.

This script creates SVG files containing capacitive touch pad layouts with:
- Diamond-shaped or flower-shaped pads arranged in rows and columns
- Connecting traces between pads
- Configurable pad spacing, size and corner radius

Usage:
    python3 generate_svg_capacitive_touch.py
    xdg-open touch_pads.svg

Example:
    >>> pad = DiamondTouchPad(pitch=4, radius=0.1, separation=0.25, trace_width=0.25, x_count=3, y_count=4)
    >>> svg_content = pad.generate()
    >>> with open("touch_pads.svg", "w") as f:
    ...     f.write(str(svg_content))
"""

import svg
from math import sqrt
from svg import mm

# origin circle to help with alignment in kicad
origin = svg.Circle(cx=0, cy=0, r=0.1, stroke="black", stroke_width=0.1, fill="none")


class Pad:
    """
    A base class representing a capacitive touch pad with configurable parameters.

    This abstract base class defines the common interface and properties for all touch pad types.
    Subclasses must implement the generate() method to create specific pad shapes.

    Attributes:
        pitch (float): Distance between pad centers in millimeters
        radius (float): Corner radius and stroke width of the pad in millimeters
        separation (float): Minimum spacing between adjacent pads in millimeters
        trace_width (float): Width of connecting traces between pads in millimeters
    """

    def __init__(
        self, pitch: float, radius: float, separation: float, trace_width: float
    ) -> None:
        """
        Initialize a new Pad instance.

        Args:
            pitch: Distance between pad centers in millimeters
            radius: Corner radius and stroke width of the pad in millimeters
            separation: Minimum spacing between adjacent pads in millimeters
            trace_width: Width of connecting traces between pads in millimeters
        """
        self.pitch = pitch
        self.radius = radius
        self.separation = separation
        self.trace_width = trace_width

    def generate(
        self, x: float, y: float, connection_type: str, edge_type: str
    ) -> svg.G:
        """
        Generate an SVG representation of the pad.

        Args:
            x: X coordinate of the pad center in millimeters
            y: Y coordinate of the pad center in millimeters
            connection_type: Type of connection ("via" or "trace")
            edge_type: Type of pad edge shape ("start", "end", or "center")

        Returns:
            An SVG group element containing the pad and its connections

        Raises:
            NotImplementedError: This method must be implemented by subclasses
        """
        raise NotImplementedError("Subclasses must implement this method")


class DiamondPad(Pad):
    """
    A class representing a diamond-shaped capacitive touch pad.

    This class creates diamond-shaped touch pads with configurable dimensions and connections.
    The diamond shape can be modified at the edges to create triangular shapes for the start
    and end of rows to make a straighter edge.

    Attributes:
        Inherits all attributes from the Pad base class.
    """

    def __init__(
        self, pitch: float, radius: float, separation: float, trace_width: float
    ) -> None:
        """
        Initialize a new DiamondPad instance.

        Args:
            pitch: Distance between pad centers in millimeters
            radius: Corner radius and stroke width of the pad in millimeters
            separation: Minimum spacing between adjacent pads in millimeters
            trace_width: Width of connecting traces between pads in millimeters
        """
        super().__init__(pitch, radius, separation, trace_width)

    def __str__(self) -> str:
        """
        Return a string representation of the DiamondPad configuration.

        Returns:
            A string containing the pad's configuration parameters
        """
        return f"DiamondPad(pitch={self.pitch}, radius={self.radius}, separation={self.separation}, trace_width={self.trace_width})"

    def generate(
        self, x: float, y: float, connection_type: str, edge_type: str
    ) -> svg.G:
        """
        Creates an SVG polygon representing a diamond-shaped capacitive touch pad.

        Args:
            x: X coordinate of the pad center in millimeters
            y: Y coordinate of the pad center in millimeters
            connection_type: Type of connection:
                - "via": Don't connect, that will be handled by a via
                - "trace": Connect with a trace
            edge_type: Type of pad edge shape:
                - "start": Triangle pointing upward
                - "end": Triangle pointing downward
                - "center": Diamond shape

        Returns:
            An SVG group containing the pad polygon and optional connecting trace
        """
        diag = (self.radius + self.separation / 2) * sqrt(2)
        width = (self.pitch / 2) - diag
        if edge_type == "start":
            points = [x - width, y, x + width, y, x, y + width]
        elif edge_type == "end":
            points = [x - width, y, x + width, y, x, y - width]
        else:
            points = [x - width, y, x, y + width, x + width, y, x, y - width]
        diamond = svg.Polygon(
            points=points, stroke="black", fill="black", stroke_width=self.radius * 2
        )
        if edge_type != "end" and connection_type == "trace":
            connector_line = svg.Line(
                x1=x,
                y1=y + self.pitch / 2 - self.separation - self.radius,
                x2=x,
                y2=y + self.pitch / 2 + self.separation + self.radius,
                stroke="black",
                stroke_width=self.trace_width,
            )
        else:
            connector_line = None
        return svg.G(elements=[diamond, connector_line])

    def generate_back_traces(
        self, x: float, y: float, via_diameter: float = 0
    ) -> svg.G:
        """
        Creates an SVG group containing just the trace that will connect vias
        on the back side of the board.

        Args:
            x: X coordinate of the pad center in millimeters
            y: Y coordinate of the pad center in millimeters
            via_diameter: Diameter of the via in millimeters, defaults to 2x radius of the pad.

        Returns:
            An SVG group containing the connecting trace
        """
        offset = min(self.radius, via_diameter / 2)
        elements = [
            svg.Line(
                x1=x,
                y1=y + self.pitch / 2 - self.separation - offset,
                x2=x,
                y2=y + self.pitch / 2 + self.separation + offset,
                stroke="black",
                stroke_width=self.trace_width,
            )
        ]
        return svg.G(elements=elements)


class FlowerPad(Pad):
    """
    A class representing a flower-shaped capacitive touch pad.

    This class creates flower-shaped touch pads with configurable dimensions.
    The flower shape can be modified at the edges to create different petal arrangements
    for the start and end of rows to make a straighter edge.

    Attributes:
        Inherits all attributes from the Pad base class.
    """

    def __init__(
        self, pitch: float, radius: float, separation: float, trace_width: float
    ) -> None:
        """
        Initialize a new FlowerPad instance.

        Args:
            pitch: Distance between pad centers in millimeters
            radius: Corner radius and stroke width of the pad in millimeters
            separation: Minimum spacing between adjacent pads in millimeters
            trace_width: Width of connecting traces between pads in millimeters
        """
        super().__init__(pitch, radius, separation, trace_width)

    def __str__(self) -> str:
        """
        Return a string representation of the FlowerPad configuration.

        Returns:
            A string containing the pad's configuration parameters
        """
        return f"FlowerPad(pitch={self.pitch}, radius={self.radius}, separation={self.separation}, trace_width={self.trace_width})"

    def generate(
        self, x: float, y: float, connection_type: str, edge_type: str
    ) -> svg.G:
        """
        Creates an SVG group representing a flower-shaped capacitive touch pad.

        Args:
            x: X coordinate of the pad center in millimeters
            y: Y coordinate of the pad center in millimeters
            connection_type: Type of connection:
                - "via": Connect via
                - "trace": Connect with a trace
            edge_type: Type of pad edge shape:
                - "start": Two petals pointing upward
                - "end": Two petals pointing downward
                - "center": Four petals in a flower shape

        Returns:
            An SVG group containing the flower pad elements (petals, stems, center)
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
                    stroke_width=self.trace_width,
                )
            ]

        return svg.G(elements=elements)

    def generate_back_traces(
        self, x: float, y: float, via_diameter: float = 0
    ) -> svg.G:
        """
        Creates an SVG group with just the trace to connect vias on the back side of the board.

        Args:
            x: X coordinate of the pad center in millimeters
            y: Y coordinate of the pad center in millimeters
            via_diameter: Diameter of the via in millimeters, defaults to 2x radius of the pad.

        Returns:
            An SVG group containing the connecting trace
        """
        width = (self.pitch) / 2 - via_diameter / 2
        offset = min(self.radius, via_diameter / 2)
        elements = [
            svg.Line(
                x1=x + offset,
                y1=y + width - self.separation,
                x2=x - offset,
                y2=y + self.pitch / 2 + self.separation + offset,
                stroke="black",
                stroke_width=self.trace_width,
            )
        ]
        return svg.G(elements=elements)


class TouchGrid:
    """
    A class representing a grid of capacitive touch pads.

    This class manages the layout and generation of a grid of touch pads, handling
    the arrangement of pads in rows and columns with appropriate connections.

    Attributes:
        pad (Pad): The pad configuration to use for the grid
        x_count (int): Number of columns in the grid
        y_count (int): Number of rows in the grid
    """

    def __init__(self, pad: Pad, x_count: int, y_count: int) -> None:
        """
        Initialize a new TouchGrid instance.

        Args:
            pad: The pad configuration to use for the grid
            x_count: Number of columns in the grid
            y_count: Number of rows in the grid
        """
        self.pad = pad
        self.x_count = x_count
        self.y_count = y_count

    def generate(self) -> svg.SVG:
        """
        Generate an SVG representation of the touch pad grid.

        Returns:
            An SVG document containing the complete touch pad grid layout
        """
        columns = [
            self._row(self.y_count, connection_type="trace")
            for i in range(self.x_count)
        ]
        for i, e in enumerate(columns):
            e.transform = [svg.Translate(i * self.pad.pitch, 0)]
        rows = [
            self._row(self.x_count, connection_type="via") for i in range(self.y_count)
        ]
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
            elements=[origin] + columns + rows,
        )

    def generate_back_traces(self, via_diameter: float = 0) -> svg.SVG:
        """
        Generate an SVG representation of just the back traces, which will be
        connected to the pads on the front side using vias.

        Args:
            via_diameter: Diameter of the vias in millimeters, defaults to 2x radius of the pad.

        Returns:
            An SVG document containing just the back traces that will connect the vias
        """
        elements = []
        for i in range(self.x_count):
            for j in range(self.y_count):
                trace = self.pad.generate_back_traces(
                    self.pad.pitch,
                    0,
                    via_diameter=via_diameter,
                )
                trace.transform = [
                    svg.Rotate(-90, 0, 0),
                    svg.Translate(
                        -(i + 1) * self.pad.pitch - self.pad.pitch / 2,
                        self.pad.pitch / 2 + j * self.pad.pitch,
                    ),
                ]
                elements += [trace]

        width = self.pad.pitch * (self.x_count + 1)
        height = self.pad.pitch * (self.y_count + 1)
        return svg.SVG(
            width=str(width) + "mm",
            height=str(height) + "mm",
            viewBox=f"0 0 {width} {height}",
            elements=elements + [origin],
        )

    def _get_edge_type(self, i: int, count: int) -> str:
        """
        Determine the edge type for a pad based on its position in a row.

        Args:
            i: Index of the pad in the row
            count: Total number of pads in the row

        Returns:
            The edge type: "start", "end", or "center"
        """
        if i == 0:
            return "start"
        elif i == count - 1:
            return "end"
        else:
            return "center"

    def _row(self, count: int, connection_type: str) -> svg.G:
        """
        Create an SVG element containing a row of connected capacitive touch pads.

        Args:
            count: Number of pads in the row
            connection_type: Type of connection between pads ("via" or "trace")

        Returns:
            An SVG group element containing the row of pads with appropriate
            edge and connection types
        """
        count += 1  # +1 since edge pads are ~1/2 pitch
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


class FlowerTouchPad(TouchGrid):
    """
    A specialized TouchGrid that uses FlowerPad for its touch pads.
    """

    def __init__(
        self,
        pitch: float,
        radius: float,
        separation: float,
        trace_width: float,
        x_count: int,
        y_count: int,
    ) -> None:
        """
        Initialize a new FlowerTouchPad instance.

        Args:
            pitch: Distance between pad centers in millimeters
            radius: Corner radius and stroke width of the pad in millimeters
            separation: Minimum spacing between adjacent pads in millimeters
            trace_width: Width of connecting traces between pads in millimeters
            x_count: Number of columns in the grid
            y_count: Number of rows in the grid
        """
        super().__init__(
            FlowerPad(
                pitch=pitch,
                radius=radius,
                separation=separation,
                trace_width=trace_width,
            ),
            x_count,
            y_count,
        )


class DiamondTouchPad(TouchGrid):
    """
    A specialized TouchGrid that uses DiamondPad for its touch pads.
    """

    def __init__(
        self,
        pitch: float,
        radius: float,
        separation: float,
        trace_width: float,
        x_count: int,
        y_count: int,
    ) -> None:
        """
        Initialize a new DiamondTouchPad instance.

        Args:
            pitch: Distance between pad centers in millimeters
            radius: Corner radius and stroke width of the pad in millimeters
            separation: Minimum spacing between adjacent pads in millimeters
            trace_width: Width of connecting traces between pads in millimeters
            x_count: Number of columns in the grid
            y_count: Number of rows in the grid
        """
        super().__init__(
            DiamondPad(
                pitch=pitch,
                radius=radius,
                separation=separation,
                trace_width=trace_width,
            ),
            x_count,
            y_count,
        )


def demo_place(touch_pad: TouchGrid, x: float, y: float) -> svg.G:
    """
    Create a demo placement of a touch pad grid with title and configuration text.

    Args:
        touch_pad: The touch pad grid to display
        x: X coordinate for placement in millimeters
        y: Y coordinate for placement in millimeters

    Returns:
        An SVG group containing the touch pad grid, title, and configuration text
    """
    title = svg.Text(
        x=mm(x),
        y=mm(y + 2),
        text=f"{touch_pad.__class__.__name__} ({touch_pad.x_count}x{touch_pad.y_count}):",
        font_size=6,
        fill="red",
        text_anchor="start",
    )
    pad_text = svg.Text(
        x=mm(x),
        y=mm(y + 3),
        text=f"{touch_pad.pad}",
        font_size=3,
        fill="red",
        text_anchor="start",
    )
    grid = touch_pad.generate()
    grid.x = mm(x)
    grid.y = mm(y + 3.5)
    return svg.G(elements=[grid, title, pad_text])


def demo_pads() -> svg.SVG:
    """
    Create a demo SVG showing various touch pad configurations.

    This function creates a demonstration SVG containing multiple touch pad grids
    with different configurations, including:
    - A small flower pad grid (4x4)
    - A small diamond pad grid (3x4)
    - A wide flower pad grid (10x2)
    - A large diamond pad grid (4x4)

    Returns:
        An SVG document containing all demo touch pad grids
    """
    flower_min = FlowerTouchPad(
        pitch=4,
        radius=0.1,
        separation=0.5,
        trace_width=0.25,
        x_count=4,
        y_count=4,
    )
    diamond_min = DiamondTouchPad(
        pitch=4,
        radius=0.1,
        separation=0.25,
        trace_width=0.25,
        x_count=3,
        y_count=4,
    )

    flower_other = FlowerTouchPad(
        pitch=5,
        radius=0.1,
        separation=0.25,
        trace_width=0.25,
        x_count=10,
        y_count=2,
    )
    diamond_max = DiamondTouchPad(
        pitch=10,
        radius=1,
        separation=0.25,
        trace_width=0.25,
        x_count=4,
        y_count=4,
    )
    return svg.SVG(
        width="300mm",
        height="250mm",
        viewBox="0 0 300 250",
        elements=[
            demo_place(diamond_min, 0, 0),
            demo_place(flower_min, 0, 22),
            demo_place(flower_other, 0, 44),
            demo_place(diamond_max, 30, 0),
        ],
    )


def pcb():
    flower4x4 = FlowerTouchPad(
        pitch=18 / 4,
        radius=0.15,
        separation=0.2,
        trace_width=0.16,
        x_count=4,
        y_count=4,
    )

    return svg.SVG(
        width="18mm",
        height="18mm",
        viewBox="0 0 18 18",
        elements=[
            # flower4x4.generate(),
            flower4x4.generate_back_traces(via_diameter=1)
        ],
    )


if __name__ == "__main__":
    with open("touch_pads.svg", "w") as f:
        f.write(str(demo_pads()))
        # f.write(str(pcb()))
