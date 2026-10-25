"""Tests for the daily health report (healthlog.py and how maple_exp.py sends it). No game or screen needed.

Run from the project folder:  python tests/test_health.py
"""
import calendar
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["MAPLE_EXP_DATA"] = tempfile.mkdtemp()           # never touch your real data
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import healthlog  # noqa: E402
import maple_exp as m  # noqa: E402
assert Path(os.environ["MAPLE_EXP_DATA"]) == m.DATA_DIR, "tests must run on their own temp data folder, never on real data"

failures = 0


def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    failures += not ok


contract = json.loads((Path(__file__).parent / "health_contract.json").read_text(encoding="utf-8"))
TODAY = contract["today"]
full = next(c["body"] for c in contract["health_valid"] if c["name"] == "full")

# ---- the same cases the site is tested with
for case in contract["health_valid"]:
    check(f"contract: '{case['name']}' passes the overlay's own check", healthlog.bad_field(case["body"], TODAY) is None)
for case in contract["health_invalid"]:
    body = {**copy.deepcopy(full), **case["change"]}
    got = healthlog.bad_field(body, TODAY)
    check(f"contract: a bad {case['field']} ({json.dumps(case['change'])[:60]}) is refused as {case['field']}",
          got == case["field"] or (case["field"] in ("map_name",) and got == "map_name"))

# ---- the ID
cfg = {}
check("the health ID is made once, 16 lowercase hex characters", healthlog.ensure_id(cfg) and healthlog.good_id(cfg["health_id"])
      and not healthlog.ensure_id(cfg))
first = cfg["health_id"]
cfg["health_id"] = "NOT-HEX"
check("a damaged ID is replaced", healthlog.ensure_id(cfg) and healthlog.good_id(cfg["health_id"]) and cfg["health_id"] != first)

# ---- counting
NOON = float(calendar.timegm((2026, 10, 25, 12, 0, 0)))                           # noon UTC on the 25th
clock = [NOON]
assert healthlog.utc_day(clock[0]) == "2026-10-25", healthlog.utc_day(clock[0])
folder = Path(tempfile.mkdtemp())


def fresh():
    """An empty record and the clock back at noon on the 25th."""
    (folder / "health.json").unlink(missing_ok=True)
    clock[0] = NOON


def new_log():
    return healthlog.HealthLog(folder / "health.json", clock=lambda: clock[0])


log = new_log()
log.snapshot("0.9.14-beta", "Windows 10.0.26200", [(5120, 2880, 150), (2560, 1440, None)], "screen", "ok")
script = [("read", False), ("read", True), ("tesseract", False), ("tesseract", True), ("unclear", False),
          ("not_found", False), ("covered", False), ("no_window", False), ("read", False)]
for kind, pct in script:
    log.look(kind, pct, tries=(("map", True), ("mesos", False)), ms=20.0, tracking=1.5, game=(5120, 2880, True, 28.0))
rec = log.today()
check("the categories add up to the number of looks", sum(rec["exp"][k] for k in healthlog.EXP_KINDS) == rec["looks"] == len(script))
check("percentage-only looks are counted as a part of read + tesseract", rec["exp"]["percent_only"] == 2)
check("the other readers' tries are counted", rec["map"] == {"read": 9, "unread": 0} and rec["mesos"] == {"read": 0, "unclear": 9})
log.look("nonsense")
check("an unknown kind counts nothing", rec["looks"] == len(script))
log.look("unclear", True)
check("a percentage-only look that wasn't read doesn't count as percentage-only", rec["exp"]["percent_only"] == 2)
log.errors({"TesseractError": 2, "Bad Name!": 5, "ValueError": 0})
check("only exception type names with letters are kept", rec["errors"] == {"TesseractError": 2})

# yesterday's record, finished, is what gets sent
clock[0] += 86400
tomorrow_log = log
body = tomorrow_log.body("2026-10-25", "0123456789abcdef")
check("a finished day's body passes the check", body is not None and healthlog.bad_field(body, "2026-10-26") is None)
allowed = {"id", "version", "day", "os", "screens", "game", "capture", "tesseract", "seconds_tracking", "looks", "exp",
           "level", "map", "class", "mesos", "potions", "errors", "ms", "shadow"}
check("the body has only contract keys", set(body) <= allowed)
check("the body holds the day's game size, tracking time and speed", body["game"] == {"w": 5120, "h": 2880, "fullscreen": True, "gh": 28.0}
      and body["seconds_tracking"] == 13 and body["ms"]["look_avg"] == 20.0 and 20 <= body["ms"]["look_p95"] <= 30
      and body["screens"] == [[5120, 2880, 150], [2560, 1440, None]])


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from strings(v)


allowed_text = {body["id"], body["version"], body["day"], body["os"], body["capture"], body["tesseract"]} | set(body["errors"]) | set(body)
for sub in ("exp", "level", "map", "class", "mesos", "potions", "ms", "game"):
    allowed_text |= set(body[sub])
check("the only text in the body is the id, version, day, os, capture, tesseract and exception type names",
      set(strings(body)) <= allowed_text)
private = [str(m.DATA_DIR), os.environ.get("USERNAME", "zzzz-no-user"), "Henesys", "Mage", "Rocky Road"]
check("nothing in the body is the data folder, the user name, a map or the class",
      not any(p.lower() in json.dumps(body).lower() for p in private if p))

# ---- saving and loading
log.save()
again = new_log()
check("the record survives a restart", again.days.get("2026-10-25", {}).get("looks") == rec["looks"])
(folder / "health.json").write_text('{"days": {"2026-10-25": {"looks": "lots", "exp": 5}}, "last_attempt": "x"}', encoding="utf-8")
damaged = new_log()
check("a damaged record is cleaned up, not crashed on", damaged.days["2026-10-25"]["looks"] == 0 and damaged.last_attempt == 0.0)
(folder / "health.json").write_text("{not json", encoding="utf-8")
check("a broken file is started again", new_log().days == {})

# ---- when it sends
fresh()
log = new_log()
log.snapshot("0.9.14-beta", "Windows 10.0.26200", [], "screen", "ok")
log.look("read", ms=10.0, game=(1920, 1080, False, 11.0))
check("today isn't sent (it isn't finished)", log.due("0123456789abcdef") is None)
clock[0] += 86400
got = log.due("0123456789abcdef")
check("the next day the finished one is due", got is not None and got[0] == "2026-10-25" and got[1]["looks"] == 1)
log.attempting()
check("...but not again within the hour", log.due("0123456789abcdef") is None)
restarted = new_log()
check("...even after a restart", restarted.due("0123456789abcdef") is None)
clock[0] += 3601
check("...and an hour later it is", restarted.due("0123456789abcdef") is not None)
restarted.finish("2026-10-25", "later")
clock[0] += 3601
check("a network error waits until the next day", restarted.due("0123456789abcdef") is None)
clock[0] += 86400
check("...then tries again", restarted.due("0123456789abcdef") is not None)
restarted.finish("2026-10-25", "bad")
clock[0] += 3601
check("a refused body is never sent again", restarted.due("0123456789abcdef") is None and restarted.last_sent == "")
fresh()
log = new_log()
log.snapshot("0.9.14-beta", "Windows 10.0.26200", [], "screen", "ok")
log.look("read", ms=10.0)
clock[0] += 86400 * 3
log.finish("2026-10-25", "ok")
check("an accepted day is marked sent and remembered", log.last_sent == "2026-10-25" and log.due("0123456789abcdef") is None)
fresh()
log = new_log()
log.snapshot("0.9.14-beta", "Windows 10.0.26200", [], "screen", "ok")
log.look("read")
log.days["2026-10-01"] = copy.deepcopy(log.days["2026-10-25"])
clock[0] += 86400 * 10
check("days older than 7 are dropped unsent", log.due("0123456789abcdef") is None and log.days.get("2026-10-01", {}).get("sent"))
log.save()
check("...and old days leave the file", "2026-10-01" not in json.loads((folder / "health.json").read_text(encoding="utf-8"))["days"])

# ---- never while testing
sent = []


def fake_urlopen(request, timeout=0):
    sent.append(request.full_url)
    raise AssertionError("must not be called")


real_urlopen = m.urllib.request.urlopen
m.urllib.request.urlopen = fake_urlopen
try:
    m.post_health(full)
    blocked = False
except RuntimeError:
    blocked = True
m.urllib.request.urlopen = real_urlopen
check("while testing (MAPLE_EXP_DATA is set) nothing can be sent to the real site", blocked and not sent)


class Answer:
    def __init__(self, data, code=200):
        self.data, self.code = json.dumps(data).encode(), code

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.data


def answering(data=None, code=200):
    def urlopen(request, timeout=0):
        sent.append((request.full_url, request.data))
        if code == 200:
            return Answer(data)
        raise m.urllib.error.HTTPError(request.full_url, code, "x", {}, Answer(data))
    return urlopen


os.environ["MAPLE_EXP_ALLOW_SHARE"] = "1"
try:
    for code, data, wanted in ((200, {"ok": True}, ("ok", "")), (200, {"ok": True, "dup": True}, ("ok", "")),
                               (400, {"error": "exp"}, ("bad", "exp")), (413, {}, ("big", "")),
                               (429, {"retry": True}, ("later", "")), (500, {}, ("later", "")), (404, {}, ("later", ""))):
        sent.clear()
        m.urllib.request.urlopen = answering(data, code)
        check(f"the site's answer {code} {data} is understood as {wanted}", m.post_health(full) == wanted
              and sent[0][0] == m.STATS_SITE + "/api/health" and json.loads(sent[0][1]) == full)
    m.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
    check("being offline means try later", m.post_health(full) == ("later", ""))
finally:
    m.urllib.request.urlopen = real_urlopen
    os.environ.pop("MAPLE_EXP_ALLOW_SHARE")

# ---- the settings file
for key, good, bad in (("share_health", True, "yes"), ("health_id", "0123456789abcdef", "ABC")):
    m.CONFIG_PATH.write_text(json.dumps({key: good}), encoding="utf-8")
    kept = key in m.load_config()
    m.CONFIG_PATH.write_text(json.dumps({key: bad}), encoding="utf-8")
    check(f"config: {key} is kept when valid and dropped when damaged", kept and key not in m.load_config())
m.CONFIG_PATH.write_text("{}", encoding="utf-8")
check("config: share_health missing means not asked yet", "share_health" not in m.load_config())

print("\nALL PASSED" if not failures else f"\n{failures} FAILED")
sys.exit(1 if failures else 0)
