
# Intro

<img src="./docs/demo.svg">
# Dev Logs

## 2025-10-21
I've cleaned up the code a bit and I'll commit it now in it's mostly working state. I think I want
to reverse the direction of x and y so that up and to the right is positive. And I want to make it
so that the value ranges from about -1 to 1 instead of the 1.5 right now. I'll also rename the
touchpads so that they are named with the x_y coordinates instead of numbers so that they could be
reused for the 4x4 board.


## 2025-10-20
I've been working on cleaning up the code a bit and on adding better gesture detection. I used some
AI code generation with somewhat mixed results. It was able to generate stuff that mostly work but
was overly complicated and not idea. It was however a good starting point for refactoring the code
to separate the keymap/config from the gesture detection class. Using switch statements might not be
the most extensible option, but it's better then what I had previously.

The method's it uses for detecting circles and swipe-returns still leave a bit to be desired, but I
can work on cleaning those up later. For now I'm going to clean up the code, make sure the AI
generated code is okay and that the keyboard still works, and then I'll commit the code


## 2025-10-14
I finished the front graphics enough for me to order the pcbs. Now I'm just cleaning up the commit
history (I really should have committed stuff more often, but I've been rushing to get it done in
time for HaD SuperCon).


## 2025-10-13
Next time I lay out the pcb, I should name the nets first, and then manually connect it.

I Also made a script to generate the silkscreen images for the keyboard. Unfortunately kicad doesn't
process text elements in svg, so I have to use inkscape to convert the svg text elements to paths.
Then Kicad is able to read it correctly.


## 2025-10-10
Actually, I think I'll go in the other direction and make it bigger (maybe 42 to 50 mm), that way it
can be actually useful for some people. That is also the typical width of a business card. And this
time I can try and keep a document of how to use the tool and the steps along the way. (I think I'll
still order some of the smaller ones but it would be cool to have the bigger ones too.)

so new plan:
- Make small changes to the existing design (mainly via diameter and silkscreen changes)
- Make new larger design too, documenting it

jlcpcb specifications:
- via hole diameter: .3mm
- via diameter (+.1/.15): .4mm or .45mm

## 2025-10-08
I want to try and get something finished and ready to be passed out for the Hackaday SuperCon.
It should be minimal changes from my first rev so that it doesn't take too long, but at least:
- add url and QR code for github
- change via diameter to .3mm for jlcpcb
- maybe shrink sides a bit?
- update silkscreen to be thicker, & add more characters

## 2025-08-16
I'm thinking that the gesture processing logic should be in it's own thread, and that way it can be
waiting for data, and then immediately start processing it.

I created a class for gestures and moved the existing gesture logic into it. It still need some
clean up and improvements, but I'm happy to see that it still works. I think next I'll see about
making the configuration more robust (maybe json based?) and adding additional gesture detection.

## 2025-08-15
I refactored the 'touchpad' portion of the code into it's own class. It still needs some work, but
it is at least a start at encapsulating the different functionalities separately. The Touchpad class
contains (most of) the logic for setting up the capacitive touch sensors, reading the values, and
calculating the x, y, and z values.

## 2025-08-14
It works! I'm able to type all of the lower case characters and I even added backspace. When I
refactor, I want to see about adding additional gestures (such as swipe there and back, long press,
and circles). I also want to move the statemachine into a callback so that it runs once a new
measurement has been made. I also want to add some statefulness to it so I can trigger the shift key
for example, or switch to a mouse mode.

It could be broken down into ~3 logical pieces: Setting up and reading touch, capturing a gesture,
and converting that gesture to some action.

## 2025-08-13
Now I want to try and improve the gesture detection because it isn't very reliable. I'm going to
start by switching to the esp idf touch interface so I have more control.

I have the esp idf example working and somewhat stripped down now. I think the next step will be to
encapsulate it into a class and combine it with the other test program I had before.

Wow, the readings from using the esp idf (with subtracting the benchmark) is so much better and
consistent then the arduino one. It even corrects for the differences in capacitance between rows
and columns. It probably still needs some improvements but as-is it is still so much better than
before.

I'll need to refactor the code, but I might start by adding the usb keyboard library to reach a v0.1
milestone.

## 2025-08-01
I got some of the basic gestures working and can now detect taps, or swipes in any of the 8
directions. Next steps will be to add all of the characters and print the right one based on where
the gesture started.

One issue I ran into was that the X and Y axis aren't scaled properly. I believe this is because one
of the axis has to go through the board and so maybe it is more/less sensitive to touch. I fixed that
by slightly scaling the Y axis, but more work needs to go into that.

I think next I'm going to see how to make it more accurate. To do that, I'll add something to print
out the values only when they are above some threshold, and then I can plot the data and see what it looks like. I also could see about using an IIR filter on X, Y, and Z to smooth out the response.
And I think I might need to weight the edges higher (for Z at least) since they are less sensitive.


## 2025-07-03
For now I'll leave off the time component since it can always be added later.

Should I also include distance? or min/max for x and y (to get a sense of scale?)

Once a touch is registered, we'll add the center zone to the vector. Then we'll monitor the distance
each time and see if it exceeds some constant. If so, then we check which direction we're going in
and then we'll transition to that zone. Once we're in an 'arc' zone, we can transition into 4
possible zones: back to center, cw, ccw, and 'out'. The logic is the same for all of them, I just
need to shift the angle by some offset.

Or, instead of trying to track all of the zones, do I just try and detect the gestures I actually
want to track? it would be pretty easy to track taps, swipes, and swipe backs (i think). I just need
to figure out how to track circles, but I can add that later.

## 2025-07-01
I wrote some rudimentary code that outputs the numbers 1-9 based on which position you click on. Now
I need to decide how to capture gestures. I need to detect taps, swipes, long swipes, out and back
movements, cw/ccw circles, and maybe holds? A gesture will start when a touch event is registered,
I can then track it's movements to determine which type of move it is, and then convert that to some
action. Gestures definitely start on a touch, but we can't always wait till a release since, for
example, we might want to allow people to move the cursor around by sliding and we'd want to
recognize and take action while they are still holding the button.

For now though, I think I will start with just detecting gestures once released. I think I'll set it
up where I'll have different 'zones' and I'll track which zones we enter to determine the gesture.
There will be the center zone (used for taps without intenional movements), and then octants
radiating out (so we can detect diagonal and 90 degree swipes). This will also allow us to
potentially track circular moves by seeing that we go through all of the octants. Eventually I might
see about adding another zone that is outside the normal octants to detect long moves.

So the state machine would look something like this:
- Wait till a touch event is triggered
- Take note of its starting location (x, y) and maybe time?
- Every tick check which zone it is in based off of it's starting location
- If it is in a new zone, add it to the list (and maybe the time?)
- Once the touch has been released, identify which gesture it was

(This probably could be modified to check if a character should be output while a gesture is in
motion)

## 2025-06-29
I got the PCB's in and now I'm going to see about writing some code to calculate finger position.
I'll start by just outputing the 8 touch values, and then I'll start to see about writing some code
to calculate x and y position (and maybe 'Z' position to indicate how close the finger is?)

## 2025-06-12
Need to use "Edit Pad as Graphic Shape" in footprint to be able to generate it (more) correctly.

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
