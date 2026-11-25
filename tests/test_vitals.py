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
    got, boxes = vitals.read_vitals(img, tpl, m)
    check(f"read HP on {name}",
          got.hp == vitals.Vital(*want) and got.mp is None)
    check(f"HP digit boxes on {name}",
          boxes and all(b[4] == "hp" for b in boxes))

# ---- skill heal vs potion
# +90 on 1000 = 9% Crit band, and 90 is not a Classic potion size (100 would be Red Potion).
t = vitals.VitalsTracker()
t.observe(vitals.Vitals(vitals.Vital(900, 1000), vitals.Vital(400, 500)), {}, now=1, running=True)
t.observe(vitals.Vitals(vitals.Vital(990, 1000), vitals.Vital(400, 500)), {}, now=2, running=True)
check("Crit-% HP jump that isn't a potion size is a skill heal",
      t.skill_heals == 1 and t.skill_hp == 90 and t.potion_heals == 0 and t.heal_cost() == 0)

t2 = vitals.VitalsTracker()
t2.observe(vitals.Vitals(vitals.Vital(800, 1000), None), {}, now=1, running=True)
t2.observe(vitals.Vitals(vitals.Vital(900, 1000), None), {"Orange Potion": 1}, now=2, running=True)
check("HP jump with a potion use counts as potion heal, not skill",
      t2.potion_heals == 1 and t2.skill_heals == 0 and t2.potion_hp == 100)
check("potion HP costs 1 meso each", t2.heal_cost() == 100)  # 100 HP × 1

t3 = vitals.VitalsTracker()
t3.observe(vitals.Vitals(None, vitals.Vital(200, 1000)), {}, now=1, running=True)
t3.observe(vitals.Vitals(None, vitals.Vital(400, 1000)), {"Blue Potion": 1}, now=2, running=True)
check("potion MP costs 2 mesos each", t3.potion_mp == 200 and t3.heal_cost() == 400)  # 200 × 2

# Large non-skill heal without a bar use still counts as potion (bar empty / unread).
t4 = vitals.VitalsTracker()
t4.observe(vitals.Vitals(vitals.Vital(500, 1000), None), {}, now=1, running=True)
t4.observe(vitals.Vitals(vitals.Vital(800, 1000), None), {}, now=2, running=True)  # +300 = 30%
check("big non-Crit heal without bar use is potion cost",
      t4.potion_hp == 300 and t4.skill_heals == 0 and t4.heal_cost() == 300)

# Orange Potion 250 HP ≈ 10% of 2500 — Crit-shaped, but a known consumable size.
t5 = vitals.VitalsTracker()
t5.observe(vitals.Vitals(vitals.Vital(2000, 2500), None), {}, now=1, running=True)
t5.observe(vitals.Vitals(vitals.Vital(2250, 2500), None), {}, now=2, running=True)
check("Orange Potion-sized HP counts as potion even without bar (not Crit)",
      t5.potion_hp == 250 and t5.skill_heals == 0 and t5.heal_cost() == 250)

# Lemon 150 MP ≈ 15% of 1000 — same trap for Assassin Crit Recovery + Lemon.
t6 = vitals.VitalsTracker()
t6.observe(vitals.Vitals(None, vitals.Vital(700, 1000)), {}, now=1, running=True)
t6.observe(vitals.Vitals(None, vitals.Vital(850, 1000)), {}, now=2, running=True)
check("Lemon-sized MP counts as potion even without bar",
      t6.potion_mp == 150 and t6.skill_heals == 0 and t6.heal_cost() == 300)

# True Crit % that isn't a known potion size stays a skill heal.
t7 = vitals.VitalsTracker()
t7.observe(vitals.Vitals(vitals.Vital(1800, 2000), None), {}, now=1, running=True)
t7.observe(vitals.Vitals(vitals.Vital(1980, 2000), None), {}, now=2, running=True)  # +180 = 9%
check("Crit-sized heal that isn't a potion size stays a skill heal",
      t7.skill_heals == 1 and t7.skill_hp == 180 and t7.heal_cost() == 0)

check("tiny regen is ignored",
      not vitals.looks_like_skill_heal(5, 1000))
check("Crit Recovery-sized share is a skill heal",
      vitals.looks_like_skill_heal(100, 1000))
check("Orange Potion size is a consumable restore",
      vitals.looks_like_consumable_restore(250, "hp"))
check("Lemon size is a consumable restore",
      vitals.looks_like_consumable_restore(150, "mp"))

cfg = m.load_config()
check("vitals_on defaults on", cfg.get("vitals_on") is True)

print()
if failures:
    print(f"{failures} failed")
    sys.exit(1)
print("all passed")
