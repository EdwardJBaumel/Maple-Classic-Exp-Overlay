"""Status-bar HP/MP: current/max in green brackets, same font as EXP.

Classic shows e.g. [1033/1134] above the red HP bar and the same for blue MP.
find_vitals() finds those pairs (slash inside, not a % like EXP). VitalsTracker
watches increases: a jump with a matching potion-bar use is a drink; a jump with
no drink is treated as a skill heal (Critical Recovery / similar) — not potion cost.
"""
from collections import namedtuple

import cv2
import numpy as np

# Reuse EXP digit helpers from maple_exp without importing the whole App at module load.
# Callers pass DigitTemplates + the maple_exp helpers they already use for EXP.

Vital = namedtuple("Vital", "current max")       # one pool
Vitals = namedtuple("Vitals", "hp mp")           # either side may be None

# Heal amount as a share of max that looks like Crit Recovery (skill %), not a tiny regen tick.
SKILL_HEAL_MIN = 0.04
SKILL_HEAL_MAX = 0.15
# Absolute floor so tiny OCR noise isn't a heal.
HEAL_MIN = 15


def _slash_index(inside, bh):
    """Index of the '/' blob among white blobs inside [ … ], or None."""
    if len(inside) < 3:
        return None
    med_h = float(sorted(b.h for b in inside)[len(inside) // 2])
    best = None
    for i, b in enumerate(inside[1:-1], 1):
        short = med_h - b.h
        if short < 0.08 * bh:
            continue
        # Prefer the shortest interior blob; break ties toward the middle.
        score = -short + 0.01 * abs(i - (len(inside) - 1) / 2)
        if best is None or score < best[0]:
            best = (score, i)
    return None if best is None else best[1]


def find_vital_layouts(bgr, helpers):
    """Layouts for each [current/max] on the status bar, left→right (HP then MP).

    helpers: namespace/module with _blobs, _cells, Layout (maple_exp).
    Skips EXP ([n%] with a percent glyph) by requiring a shorter '/' blob.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    green = (sat >= 90) & (val >= 110) & (hue >= 26) & (hue <= 50)
    white = (sat < 70) & (val >= 140)
    _, gblobs = helpers._blobs(green)
    _, wblobs = helpers._blobs(white)
    brackets = sorted((b for b in gblobs if b.h >= 5 and b.w <= 0.6 * b.h), key=lambda b: b.x)
    V = val.astype(np.float32)
    found = []
    used = set()
    for o in brackets:
        if id(o) in used:
            continue
        bh, cy = float(o.h), o.y + o.h / 2.0
        on_line = lambda b, cy=cy, bh=bh: abs(b.y + b.h / 2 - cy) <= 0.3 * bh
        rights = [c for c in brackets if c.x > o.x + o.w and c.x - o.x <= 14 * bh
                  and on_line(c) and abs(c.h - bh) <= 0.25 * bh]
        if not rights:
            continue
        c = rights[0]
        inside = sorted((b for b in wblobs if on_line(b) and b.x >= o.x + o.w
                         and b.x + b.w <= c.x and b.h >= 0.45 * bh), key=lambda b: b.x)
        si = _slash_index(inside, bh)
        if si is None:
            continue
        left, right = inside[:si], inside[si + 1:]
        if not left or not right or not (1 <= len(left) <= 5 and 1 <= len(right) <= 5):
            continue
        if not 5 <= bh <= 34:
            continue
        used.add(id(o))
        used.add(id(c))
        box = (left[0].x, int(cy - bh), c.x + c.w, int(cy + bh))
        cur = helpers.Layout(bh, cy, helpers._cells(left, bh), [], box, V)
        mx = helpers.Layout(bh, cy, helpers._cells(right, bh), [], box, V)
        found.append((o.x, cur, mx))
    found.sort(key=lambda t: t[0])
    return [(cur, mx) for _, cur, mx in found]


def read_vital(tpl, helpers, cur_lay, max_lay):
    """(current, max) integers, or None if either side is unclear."""
    cur_s = helpers._read_digits(tpl, cur_lay, cur_lay.exp)
    max_s = helpers._read_digits(tpl, max_lay, max_lay.exp)
    if not cur_s or not max_s:
        return None
    if cur_s[0] == "0" or max_s[0] == "0":
        return None
    try:
        cur_n, max_n = int(cur_s), int(max_s)
    except ValueError:
        return None
    if not (1 <= cur_n <= max_n <= 99_999):
        return None
    return Vital(cur_n, max_n)


def read_vitals(bgr, tpl, helpers):
    """Vitals(hp, mp) from a status-bar crop or full window strip; sides may be None."""
    pairs = find_vital_layouts(bgr, helpers)
    read = [read_vital(tpl, helpers, a, b) for a, b in pairs]
    hp = read[0] if len(read) >= 1 else None
    mp = read[1] if len(read) >= 2 else None
    return Vitals(hp, mp)


def looks_like_skill_heal(delta, pool_max):
    """True if this increase looks like Critical Recovery (a % of max), not regen noise."""
    if delta is None or pool_max is None or pool_max <= 0 or delta < HEAL_MIN:
        return False
    share = delta / pool_max
    return SKILL_HEAL_MIN <= share <= SKILL_HEAL_MAX


class VitalsTracker:
    """Tracks HP/MP and classifies increases as potion drinks vs skill heals.

    Potion cost still comes from the quick-slot bar. This only discerns Critical Recovery
    (and similar) so Details can show skill heals separately and so a drink that didn't
    move the bar isn't confused with Crit Recovery.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.hp = self.mp = None          # last Vital
        self.skill_heals = 0              # how many Crit-Recovery-like jumps
        self.skill_hp = 0                 # HP restored by those jumps
        self.skill_mp = 0
        self.potion_heals = 0             # increases that lined up with a bar use
        self.seen_at = None
        self.drank_until = 0.0            # potion-bar use still "counts" for a few seconds
        self.last_lines = ()

    def pause(self):
        self.hp = self.mp = None          # baselines only while tracking

    def observe(self, vitals, potion_used_delta, now, running):
        """vitals: Vitals; potion_used_delta: {name: n} used since last look (may be empty)."""
        if vitals is None:
            return
        self.seen_at = now
        if potion_used_delta and sum(potion_used_delta.values()) > 0:
            self.drank_until = now + 4.0  # bar and HP/MP may be polled a tick apart
        hp, mp = vitals.hp, vitals.mp
        drank = now <= self.drank_until
        if running:
            self._note_pool("hp", hp, drank)
            self._note_pool("mp", mp, drank)
        if hp is not None:
            self.hp = hp
        if mp is not None:
            self.mp = mp
        bits = []
        if self.hp:
            bits.append(f"HP {self.hp.current}/{self.hp.max}")
        if self.mp:
            bits.append(f"MP {self.mp.current}/{self.mp.max}")
        self.last_lines = tuple(bits)

    def _note_pool(self, which, vital, drank):
        prev = self.hp if which == "hp" else self.mp
        if vital is None or prev is None:
            return
        if vital.max != prev.max:
            return                            # level-up / gear: ignore this jump
        delta = vital.current - prev.current
        if delta < HEAL_MIN:
            return
        if drank:
            self.potion_heals += 1
            return
        if looks_like_skill_heal(delta, vital.max):
            self.skill_heals += 1
            if which == "hp":
                self.skill_hp += delta
            else:
                self.skill_mp += delta
