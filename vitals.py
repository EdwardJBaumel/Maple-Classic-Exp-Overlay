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
# Potion cost from what HP/MP potions restored (not NPC shop sticker): 1 meso per HP, 2 per MP.
MESO_PER_HP = 1
MESO_PER_MP = 2
# Classic World consumable restores (game data). Orange Potion / Lemon sit inside the Crit %
# band at mid levels, so matching these beats the % heuristic when the quick-slot bar misses a drink.
# Slack covers OCR ± a couple of HP/MP and "almost full" clamps.
RESTORE_SLACK = 3
HP_RESTORES = (40, 60, 100, 120, 160, 250, 300, 360, 500, 1000, 2500)
MP_RESTORES = (30, 50, 150, 200, 300, 1000)


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


def _digit_boxes(lay, kind):
    """View-capture / Show-reading boxes for one side's digits: (x0, y0, x1, y1, kind)."""
    g = lay.gh
    return [(c[0] - c[1] / 2, lay.cy - g / 2, c[0] + c[1] / 2, lay.cy + g / 2, kind)
            for c in lay.exp]


def read_vitals(bgr, tpl, helpers):
    """(Vitals(hp, mp), boxes) from a status-bar crop; sides may be None.

    boxes are digit rects tagged "hp" / "mp" for Show reading and View capture.
    """
    pairs = find_vital_layouts(bgr, helpers)
    read, boxes = [], []
    for i, (cur, mx) in enumerate(pairs):
        kind = "hp" if i == 0 else "mp"
        got = read_vital(tpl, helpers, cur, mx)
        read.append(got)
        if got:
            boxes.extend(_digit_boxes(cur, kind))
            boxes.extend(_digit_boxes(mx, kind))
    hp = read[0] if len(read) >= 1 else None
    mp = read[1] if len(read) >= 2 else None
    return Vitals(hp, mp), boxes


def looks_like_skill_heal(delta, pool_max):
    """True if this increase looks like Critical Recovery (a % of max), not regen noise."""
    if delta is None or pool_max is None or pool_max <= 0 or delta < HEAL_MIN:
        return False
    share = delta / pool_max
    return SKILL_HEAL_MIN <= share <= SKILL_HEAL_MAX


def looks_like_consumable_restore(delta, which="hp", room=None):
    """True if delta matches a known potion/food restore (or a clamp to full of that size).

    which: 'hp' or 'mp'. room: how much was missing before the heal (max - prev); when the
    pool hit max, a White Potion that only filled 80 still counts if room <= a known restore.
    """
    if delta is None or delta < HEAL_MIN:
        return False
    known = HP_RESTORES if which == "hp" else MP_RESTORES
    if any(abs(delta - n) <= RESTORE_SLACK for n in known):
        return True
    # Clamped to full: restored `delta` (== room) from a drink bigger than the gap.
    if room is not None and room == delta:
        return any(n >= room - RESTORE_SLACK for n in known if n >= HEAL_MIN)
    return False


class VitalsTracker:
    """Tracks HP/MP and classifies increases as potion drinks vs skill heals.

    Critical Recovery (and similar) is not charged. Potion cost is HP/MP restored by
    drinks × MESO_PER_HP / MESO_PER_MP (1 meso per HP, 2 per MP). A quick-slot use still
    marks a window as "drank"; a clear non-skill heal without a bar match is also counted
    as a potion restore so cost works when the bar is empty or unread.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.hp = self.mp = None          # last Vital
        self.skill_heals = 0              # how many Crit-Recovery-like jumps
        self.skill_hp = 0                 # HP restored by those jumps
        self.skill_mp = 0
        self.potion_heals = 0             # increases counted as potion restores
        self.potion_hp = 0                # HP restored by those (for cost)
        self.potion_mp = 0
        self.seen_at = None
        self.drank_until = 0.0            # potion-bar use still "counts" for a few seconds
        self.last_lines = ()

    def pause(self):
        self.hp = self.mp = None          # baselines only while tracking

    def heal_cost(self):
        """Mesos for potion HP/MP restored: potion_hp × 1 + potion_mp × 2."""
        return self.potion_hp * MESO_PER_HP + self.potion_mp * MESO_PER_MP

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
        room = prev.max - prev.current
        # Known potion/food sizes win over Crit % (Orange Potion 250 / Lemon 150 look Crit-shaped).
        if drank or looks_like_consumable_restore(delta, which, room=room):
            self.potion_heals += 1
            if which == "hp":
                self.potion_hp += delta
            else:
                self.potion_mp += delta
            return
        if looks_like_skill_heal(delta, vital.max):
            self.skill_heals += 1
            if which == "hp":
                self.skill_hp += delta
            else:
                self.skill_mp += delta
            return
        # Other clear heals (big food, elixirs) still count as potion cost.
        self.potion_heals += 1
        if which == "hp":
            self.potion_hp += delta
        else:
            self.potion_mp += delta
