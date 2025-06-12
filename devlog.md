
# Intro

<img src="./docs/demo.svg">
# Dev Logs


## 2025-06-11
I added a method for generating the traces on the back of the board. This will be helpful to align
all of the vias correctly since they can then 'snap' to the trace line ends. I also added an
'origin' circle to the generated svg files so that they can more easily be lined up in kicad since
kicad does not seem to respect transformations fully.

Next steps will be to generate a single kicad footprint, then use it to make a board.

## 2025-06-09
It's almost time to start ordering HW. I was originally planning on ordering a board with a few
different pad layouts from jlcpcb, but then realized that since my plan is to make a small board,
OSH Park is actually very competetive, has quicker shipping, and ENIG by default! To get 3 copies of
the 18x18mm board would be about $2.50. They don't list their capablities quite as clearly as
jlcpcb, but here is I think the important info:
- 6 mil (0.1524mm) trace width/spacing
- 10 mil (0.254mm) min drill size
- 5 mil (0.127mm) anular ring size (given as radius?)
  - So total via diameter = 20 mil (0.508mm)

Looking at the Pi Pico datasheet, their footprint pads extend ~.8mm beyond the module, so I think I
will plan on making a board that is 18x20mm.

## 2025-06-08
Started working on refactoring the touchpad python generation code to be more readable. Also added
a demo function that generates a few different shapes (though they don't all render properly in the
browser).

## 2025-06-07
### Start
Right now I'm working on adding the final touches to the flower petals pad type by connecting the
rows to each other. I'm not using just a vertical line since the petals are rotated. I think it
will be easier/cleaner to just add a small diagonal line connecting each pad to the next.

TODO:
- I also want to clean up how the center of the flower is made (and the spacing for that)
- Connect pads together
- Maybe also generate the traces for connecting the pads on the back side? Then adding vias would
   be easy since they could snap to place.

### Also started using the black formatter

## 2025-06-07 Project Intro
I'm designing a capacitive touch key cap for use as a keyboard using a messagease like input, but
the first step is generate the geometry of the touch pads. I'm using Microchip's
[AN2934](https://ww1.microchip.com/downloads/aemDocuments/documents/TXFG/ApplicationNotes/ApplicationNotes/Capacitive-Touch-Sensor-Design-Guide-DS00002934-B.pdf) as a guide.


My plan is to generate a few different pad geometries (the 'diamond' and 'flower' patterns) at a
few different pitches/dimensions (2x2, 3x3, 4x4, etc) and potentially with different seperation
values as well. Instead of manually laying out these pads in kicad, I wanted to programatically
generate them. I first was trying to do it in CadQuery, but was running into a lot of issues and so
finally switched to svg.py, which doesn't have all of the features of a CAD program, but does make
it easy to make SVG's which are easy to import (and would probably be easier to fully encapsulate
into a kicad script at some point).
My goal currently is to make it easy to generate the top copper layer, and then manually add the
vias and traces on the bottom copper.
