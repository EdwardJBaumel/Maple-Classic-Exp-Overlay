"""HP/MP status-bar reading and Crit Recovery vs potion heal classification.

Run from the project folder:  py -3 tests/test_vitals.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["MAPLE_EXP_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import maple_exp as m  # noqa: E402
import vitals  # noqa: E402

failures = 0
FRAMES = Path(__file__).resolve().parent / "frames"


def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    failures += not ok


tpl = m.DigitTemplates.load()

# ---- read known status crops (HP only — frames are cropped left of EXP)
for name, want in (("status_gh11.png", (1033, 1134)),
                   ("status_gh28.png", (482, 1178)),
                   ("status_gh7.png", (993, 1134))):
    img = __import__("cv2").imread(str(FRAMES / name))
    got = vitals.read_vitals(img, tpl, m)
    check(f"read HP on {name}",
          got.hp == vitals.Vital(*want) and got.mp is None)

# ---- skill heal vs potion
t = vitals.VitalsTracker()
t.observe(vitals.Vitals(vitals.Vital(900, 1000), vitals.Vital(400, 500)), {}, now=1, running=True)
t.observe(vitals.Vitals(vitals.Vital(1000, 1000), vitals.Vital(400, 500)), {}, now=2, running=True)
check("10% HP jump with no pot is a skill heal (Crit Recovery)",
      t.skill_heals == 1 and t.skill_hp == 100 and t.potion_heals == 0)

t2 = vitals.VitalsTracker()
t2.observe(vitals.Vitals(vitals.Vital(800, 1000), None), {}, now=1, running=True)
t2.observe(vitals.Vitals(vitals.Vital(900, 1000), None), {"Orange Potion": 1}, now=2, running=True)
check("HP jump with a potion use counts as potion heal, not skill",
      t2.potion_heals == 1 and t2.skill_heals == 0)

check("tiny regen is ignored",
      not vitals.looks_like_skill_heal(5, 1000))
check("Crit Recovery-sized share is a skill heal",
      vitals.looks_like_skill_heal(100, 1000))

cfg = m.load_config()
check("vitals_on defaults on", cfg.get("vitals_on") is True)

print()
if failures:
    print(f"{failures} failed")
    sys.exit(1)
print("all passed")
