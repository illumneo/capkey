
# Intro

<img src="./docs/demo.svg">
# Dev Logs


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
