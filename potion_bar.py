"""Reader v2 for the potion bar: finds the bar in any layout (keyboard or controller UI) at any UI size, and
says what each slot holds and how many are left.

These are the shapes every part of it hands around (agreed in the v2 plan before any of it was built):
the finder makes a BarLook, read_potions() turns it into a PotionLook, the tracker counts uses from those.
Rects are (x, y, w, h) in the game window's own pixels.
"""
from collections import namedtuple

LAYOUTS = ("keyboard", "controller-standard", "controller-cross")    # "D-pad Slots": Standard / Cross-Style
STYLES = ("keyboard", "controller")      # how a slot is drawn (key-label plate and light inside, or dark rounded)
KINDS = ("consumable", "other", "skill", "empty")                    # what a slot holds, when it can be told

# One slot where the finder put it. index is stable within a layout (keyboard: row * 4 + col).
SlotSpot = namedtuple("SlotSpot", "index rect style")

# Where the bar is: layout (one of LAYOUTS), mode ("default" / "ideal" / None when both draw the same),
# scale (screen pixels per design pixel), origin (the bar's top left in the window), slots (SlotSpot, ...).
BarLook = namedtuple("BarLook", "layout mode scale origin slots")

# One slot read: item is the item's name or None when it can't be told; kind one of KINDS or None;
# count the number shown or None when it isn't certain (0 is a real count).
SlotRead = namedtuple("SlotRead", "index rect style item kind count")

# What a look at the potion bar saw. seen False: no bar to read (covered, hidden, off-screen, no window);
# seen True with no consumable slots: the bar is there and holds no potions.
PotionLook = namedtuple("PotionLook", "seen layout mode scale slots")

# What read_potions may start from: last (the BarLook of the last good look, tried first) and mode_scale
# ((mode, scale) from the EXP bar's digit height, see ui_layout.mode_from_gh), either may be None.
Hint = namedtuple("Hint", "last mode_scale")

NOT_SEEN = PotionLook(False, None, None, None, ())


def is_controller(layout):
    return bool(layout) and layout.startswith("controller")


def read_potions(img, window_w, window_h, at=(0, 0), hint=None, assets=None):
    """What the potion bar shows, as a PotionLook.

    img is a picture (BGR) of the game window or of part of it, whose top left is at `at` in the window.
    Not built yet: answers "not seen" until the finder, the count reader and the item matcher are in."""
    return NOT_SEEN
