"""Checks Gander data sent in by players, and merges what can be trusted.

Usage: python gander_submit.py run --issues FILE --comments FILE --owner LOGIN --out DIR
                                   [--approve-hash HASH]
       python gander_submit.py held --out DIR

A submission is a GitHub issue with one block of data in it. The
"Gander data" workflow hands the open ones to "run", which sorts every fact
in them three ways:

  goes in    it passes the checks and nothing in the database says otherwise
  waits      a machine can't judge it: a name the database doesn't have (the
             only free text a stranger can send), or a value that disagrees
             with the database. It goes in once a second sender reports the
             same, or when the repository owner approves it
  left out   broken, or outside what a real mob could have

"run" changes mods/classic/data/gander_data.json, GanderData.lua and
mods/classic/data/gander_held.json (what is waiting), and writes into DIR what
the workflow should say and do: result.json, pr_body.md, a reply per issue
(issue-<number>.md) and per owner comment (command-<id>.md).

"held" writes the list of what is waiting (held.md, held.json), then changes
the files as if the owner had approved all of it. The workflow keeps that as
one pull request: approving it, as the owner, adds everything on the list.
The owner can also comment on it: "approve all", "approve m3273 s5401 i48",
"approve zones", "approve words", and "drop" the same way.

Nothing says who sent what. A sender is kept as a scrambled marker, only to
tell whether two submissions came from different people, and what waits
longer than 90 days is forgotten.

A merge here is not a release: the version stays as it is. The
"GanderData release" workflow gives the day's changes one new version.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sys
import time

import gander_import as gi
from gander_import import IGNORED_SPELLS, MAX_PLACES, NUMBERS, TEXTS

HELD = gi.ROOT / "data" / "gander_held.json"
FORMAT = 1
GAMES = ("forever", "classic")
ENGLISH = (None, "enUS", "enGB")   # names in another language would end up in everyone's game
MAX_ID = 10000000
MAX_MOBS = 5000
MAX_CASTS = 1000           # times one submission may say a mob used a spell
MAX_MINUTES = 600          # of fighting in one instance, from one submission
MAX_ISSUES = 20            # submissions handled in one run
MAX_LOGS = 300             # combat logs one block may be from
MAX_PARTS = 50             # blocks one send may be split into
MAX_BYTES = 2 ** 40        # no combat log is a terabyte
LOG_ID = re.compile(r"^[0-9a-f]{16}$")
FIRST_DAY = datetime.date(2026, 1, 1)   # Gander didn't exist before this
HELD_DAYS = 90
REMEMBERED = 500           # submissions remembered, to spot the same one sent twice
LIST_LINES = 300           # lines of the held list shown in the pull request
SPELL_NAME = 60

WORDS = ("ptype", "class", "rk", "fam", "ty", "z")   # stats that are text, not numbers
RANGES = {"def": (1, 400), "armor": (1, 30000), "hp": (1, 10000000), "pow": (1, 10000000),
          "spd": (0.1, 20), "oh": (0.1, 20), "rspd": (0.1, 20), "ap": (1, 50000), "run": (0.1, 50),
          "dmin": (0.01, 50000), "dmax": (0.01, 50000), "rmin": (0.01, 50000), "rmax": (0.01, 50000)}
RANGES.update({f"r{i}": (1, 1000) for i in range(1, 7)})
RANGES.update({f"s{i}": (1, 5000) for i in range(1, 6)})
assert set(RANGES) == NUMBERS, "every number Gander stores needs a range"

LABELS = {"def": "defense", "armor": "armor", "r1": "holy resistance", "r2": "fire resistance",
          "r3": "nature resistance", "r4": "frost resistance", "r5": "shadow resistance", "r6": "arcane resistance",
          "hp": "health", "pow": "power", "ptype": "power type", "spd": "attack speed", "oh": "off-hand speed",
          "dmin": "lowest hit", "dmax": "highest hit", "ap": "attack power", "rspd": "ranged speed",
          "rmin": "lowest ranged hit", "rmax": "highest ranged hit", "s1": "strength", "s2": "agility",
          "s3": "stamina", "s4": "intellect", "s5": "spirit", "run": "run speed", "class": "class",
          "fam": "family", "ty": "creature type", "rk": "rank", "z": "zone"}
TITLES = {"forever": "Forever", "classic": "Classic Era"}

BUILD = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
STAMP = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
COMMAND = re.compile(r"^(approve|drop)\b(.*)$", re.I)
TOKEN = re.compile(r"^(all|zones|words|[msi][1-9]\d{0,7})$")
HELP = ("Comment `approve all`, or name what you mean: `approve m3273 s5401 i48`, `approve zones`, "
        "`approve words`. `drop` works the same way and throws the data away.")


class Rejected(Exception):
    """A submission that can't be used at all. The message finishes the
    sentence "it couldn't be used: ..."."""


# ------------------------------------------------------------------ checking
def parse_body(body):
    """The data block in an issue's text, as a dict."""
    text = body if isinstance(body, str) else ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise Rejected("there is no data block in it")

    def no_constants(name):
        raise ValueError(name)
    try:
        sub = json.loads(text[start:end + 1], parse_constant=no_constants)
    except (ValueError, RecursionError):
        raise Rejected("the data block is damaged, so it can't be read") from None
    if not isinstance(sub, dict):
        raise Rejected("the data block is damaged, so it can't be read")
    return sub


def good_name(text, limit):
    """Plain words only: letters, digits, spaces and a little punctuation.
    Nothing that could be a link, a mention or formatting."""
    return (isinstance(text, str) and 0 < len(text) <= limit and text == text.strip() and "  " not in text
            and any(c.isalpha() for c in text)
            and all(c.isalnum() or c in " '-.,\":()!" for c in text))


def as_id(key):
    if isinstance(key, str) and key.isascii() and key.isdigit() and len(key) <= 8 and 0 < int(key) <= MAX_ID:
        return str(int(key))


def as_level(key):
    if key == "-1":   # a skull: too far above the player to say
        return key
    if isinstance(key, str) and key.isascii() and key.isdigit() and len(key) <= 2 and 1 <= int(key) <= 63:
        return str(int(key))


def as_number(value, low, high):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
        return int(value) if float(value).is_integer() else round(float(value), 2)


def as_date(text, last):
    try:
        day = datetime.date.fromisoformat(text) if isinstance(text, str) and len(text) == 10 else None
    except ValueError:
        day = None
    return text if day and FIRST_DAY <= day <= last else None


def as_dict(value, what):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise Rejected(f"its list of {what} is damaged")
    return value


def clean_sighting(game, level, values, english):
    """One sighting's stats, checked. Returns (values kept, how many were left out)."""
    kept, dropped = {}, 0
    for key, value in values.items():
        if key == "n":   # the mob's name is taken from the mob, never from a sighting
            continue
        if key in NUMBERS:
            number = as_number(value, *RANGES[key])
            if number is None:
                dropped += 1
            else:
                kept[key] = number
        elif key in WORDS:
            if english and good_name(value, TEXTS[key]):
                kept[key] = value
            elif english:
                dropped += 1
        else:
            dropped += 1
    # Forever sends a mob's defense as its level x 5, so anything else is made up.
    if game == "forever" and "def" in kept and (int(level) < 1 or kept["def"] != int(level) * 5):
        del kept["def"]
        dropped += 1
    for low, high in (("dmin", "dmax"), ("rmin", "rmax")):
        if low in kept and high in kept and kept[low] > kept[high]:
            del kept[low], kept[high]
            dropped += 2
    return kept, dropped


def validate(sub, now):
    """Check a submission. Returns (what can be used, how many facts were left
    out, whether its names are in English). Raises Rejected if none of it can
    be used."""
    if sub.get("format") != FORMAT:
        raise Rejected("it isn't in a format this version understands")
    game = sub.get("game")
    if game not in GAMES:
        raise Rejected("it doesn't say which game it is from")
    locale = sub.get("locale")
    english = locale in ENGLISH
    mobs_in = as_dict(sub.get("mobs"), "mobs")
    if len(mobs_in) > MAX_MOBS:
        raise Rejected(f"it has more than {MAX_MOBS} mobs in it. Send it in smaller pieces")
    last_day = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date() + datetime.timedelta(days=1)
    first_time = datetime.datetime(FIRST_DAY.year, FIRST_DAY.month, FIRST_DAY.day,
                                   tzinfo=datetime.timezone.utc).timestamp()
    dropped = 0
    mobs = {}
    for mob_key, mob_in in mobs_in.items():
        mob = as_id(mob_key)
        if not mob or not isinstance(mob_in, dict):
            dropped += 1
            continue
        out = {"levels": {}, "spells": {}}
        if english and mob_in.get("name") is not None:
            if good_name(mob_in["name"], TEXTS["n"]):
                out["name"] = mob_in["name"]
            else:
                dropped += 1
        levels = mob_in.get("levels")
        for level_key, seen in (levels.items() if isinstance(levels, dict) else ()):
            level = as_level(level_key)
            seen = seen if isinstance(seen, dict) else {}
            at = seen.get("at")
            if (level is None or not isinstance(seen.get("v"), dict)
                    or as_number(at, first_time, now + 86400) is None):
                dropped += 1
                continue
            values, bad = clean_sighting(game, level, seen["v"], english)
            dropped += bad
            if values:
                out["levels"][level] = {"at": int(at), "v": values}
        spells = mob_in.get("spells")
        for spell_key, cast_in in (spells.items() if isinstance(spells, dict) else ()):
            spell = as_id(spell_key)
            cast = cast_in if isinstance(cast_in, dict) else {}
            n = as_number(cast.get("n"), 1, 10 ** 9)
            at = as_date(cast.get("at"), last_day)
            if not spell or int(spell) in IGNORED_SPELLS or not isinstance(n, int) or not at:
                dropped += 1
                continue
            n = min(n, MAX_CASTS)
            spawns = as_number(cast.get("spawns", 1), 1, 10 ** 9)
            kept = {"n": n, "spawns": min(spawns, n) if isinstance(spawns, int) else 1, "at": at}
            if isinstance(cast.get("build"), str) and BUILD.match(cast["build"]):
                kept["build"] = cast["build"]
            out["spells"][spell] = kept
        # The dungeons it was logged in: instance IDs, never names.
        places = mob_in.get("in")
        places = {as_id(place) for place in places} if isinstance(places, list) else set()
        places = sorted(places - {None}, key=int)[:MAX_PLACES]
        if places:
            out["in"] = places
        if out["levels"] or out["spells"]:
            mobs[mob] = out
    cast_spells = {spell for mob in mobs.values() for spell in mob["spells"]}
    spell_names = {}
    for spell_key, name in as_dict(sub.get("spells"), "spell names").items():
        spell = as_id(spell_key)
        if spell in cast_spells and english:
            if good_name(name, SPELL_NAME):
                spell_names[spell] = name
            else:
                dropped += 1
    instances = {}
    for key, entry in as_dict(sub.get("instances"), "instances").items():
        instance = as_id(key)
        minutes = as_number(entry.get("minutes"), 0.001, 10 ** 9) if isinstance(entry, dict) else None
        if not instance or minutes is None:
            dropped += 1
            continue
        instances[instance] = {"minutes": min(minutes, MAX_MINUTES)}
        if english and good_name(entry.get("name"), TEXTS["z"]):
            instances[instance]["name"] = entry["name"]
    clean = {"game": game, "mobs": mobs, "spells": spell_names, "instances": instances}
    if not facts(clean):
        raise Rejected("nothing in it could be used")
    if "logs" in sub:
        clean.update(clean_logs(sub))
    return clean, dropped, english


def whole(value, low, high):
    """value if it is a whole number in range (and not true or false), else None."""
    return value if type(value) is int and low <= value <= high else None


def clean_logs(sub):
    """The combat logs a block says it came from: which bytes of each, and
    which block of the send this is. A record that can't be trusted refuses
    the whole block: without it the same casts could be counted twice."""
    damaged = Rejected("its record of which combat logs it came from is damaged. Reload the page and send it again")
    logs = sub["logs"]
    if not isinstance(logs, dict) or not logs or len(logs) > MAX_LOGS:
        raise damaged
    out = {}
    for ident, span in logs.items():
        if (not LOG_ID.match(ident) or not isinstance(span, list) or len(span) != 2
                or whole(span[0], 0, MAX_BYTES) is None or whole(span[1], 1, MAX_BYTES) is None
                or span[0] >= span[1]):
            raise damaged
        out[ident] = [span[0], span[1]]
    parts = whole(sub.get("parts", 1), 1, MAX_PARTS)
    part = whole(sub.get("part", 1), 1, MAX_PARTS)
    if parts is None or part is None or part > parts:
        raise damaged
    return {"logs": out, "part": part, "parts": parts}


def take_logs(record, clean, day):
    """Whether a block's casts are new to the database, going by the record
    of combat logs. If they are, the record moves on. A send in several
    blocks is one read of its logs: each block of it is taken once."""
    spans = clean.get("logs")
    if not spans:
        return True
    batch = scramble(json.dumps(spans, sort_keys=True) + f"/{clean['parts']}", 16)
    known = record["batches"].get(batch)
    if known:
        if clean["part"] in known["parts"]:
            return False
        known["parts"] = sorted(known["parts"] + [clean["part"]])
        return True
    if any(start < gi.log_read_to(record, ident) for ident, (start, _) in spans.items()):
        return False
    for ident, (_, end) in spans.items():
        gi.note_log(record, ident, end, day)
    if clean["parts"] > 1:
        record["batches"][batch] = {"parts": [clean["part"]], "at": day}
    return True


def forget_batches(record, today):
    cutoff = (today - datetime.timedelta(days=gi.BATCH_DAYS)).isoformat()
    record["batches"] = {key: batch for key, batch in record["batches"].items() if batch["at"] >= cutoff}


def facts(payload):
    """How many separate facts a submission holds: each stat, each mob's use of a spell, each instance."""
    return (sum(len(seen["v"]) for mob in payload["mobs"].values() for seen in mob["levels"].values())
            + sum(len(mob["spells"]) for mob in payload["mobs"].values())
            + len(payload["instances"]))


# -------------------------------------------------------------- what's known
def new_held():
    return {"version": 1, "seen": [], "pending": []}


def scramble(text, length):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def held_hash(held):
    """Stands for exactly what is waiting, so an approval can be matched to the list it was given for."""
    return scramble(json.dumps(held["pending"], sort_keys=True), 16)


def known_words(data):
    """Every text value the database already uses, per stat. Instance names count as zones."""
    words = {key: set() for key in WORDS}
    for g in data["games"].values():
        for entry in g["instances"].values():
            words["z"].add(entry.get("name"))
        for mob in g["mobs"].values():
            for seen in mob.get("levels", {}).values():
                for key in WORDS:
                    if key in seen["v"]:
                        words[key].add(seen["v"][key])
    return words


def listed_name(data, game, kind, key, offered=None):
    """The database's name for a mob, spell or instance. The same ID with the
    offered name in the other game counts too."""
    def name_in(g):
        entry = g[kind].get(key)
        return entry if isinstance(entry, str) else (entry or {}).get("name")
    here = data["games"].get(game)
    if here and name_in(here):
        return name_in(here)
    if offered and any(name_in(g) == offered for other, g in data["games"].items() if other != game):
        return offered


def waiting_name(data, game, mob, sub):
    """Does this waiting mob offer a name the database doesn't have for it yet?"""
    return bool(sub.get("name")) and not listed_name(data, game, "mobs", mob, sub["name"])


def same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 0.005
    return a == b


def open_claims(data, payload, words):
    """(key, text) for everything in a waiting submission that nobody has confirmed."""
    game = payload["game"]
    listed = data["games"].get(game, {"mobs": {}, "spells": {}, "instances": {}})
    for mob, sub in payload["mobs"].items():
        if waiting_name(data, game, mob, sub):
            yield "m" + mob, sub["name"]
        elif mob not in listed["mobs"] and not listed_name(data, game, "mobs", mob):
            yield "m" + mob, ""   # a new mob sent without a name
        have = listed["mobs"].get(mob, {}).get("levels", {})
        for level, seen in sub["levels"].items():
            for key, value in seen["v"].items():
                if key in WORDS and value not in words[key]:
                    yield f"t:{key}:{value}", value
                old = have.get(level, {}).get("v", {}).get(key)
                if key != "z" and old is not None and not same(old, value):
                    yield f"v{mob}:{level}:{key}", json.dumps(value)
        for spell in sub["spells"]:
            name = payload["spells"].get(spell)
            if not listed_name(data, game, "spells", spell, name) and name:
                yield "s" + spell, name
    for instance, entry in payload["instances"].items():
        if not listed_name(data, game, "instances", instance, entry.get("name")) and entry.get("name"):
            yield "i" + instance, entry["name"]


def claims(data, held):
    """What is waiting: {game: {key: {text: {"senders": set, "first": day}}}}."""
    words = known_words(data)
    table = {}
    for payload in held["pending"]:
        for key, text in open_claims(data, payload, words):
            claim = table.setdefault(payload["game"], {}).setdefault(key, {}).setdefault(
                text, {"senders": set(), "first": payload["received"]})
            claim["senders"].add(payload["sender"])
            claim["first"] = min(claim["first"], payload["received"])
    return table


def best(options):
    """The claim most senders agree on; the earliest breaks a tie."""
    return min(options.items(), key=lambda item: (-len(item[1]["senders"]), item[1]["first"], item[0]))


def approved(key, approve):
    if not approve:
        return False
    if approve == "all":
        return True
    if key.startswith("t:z:"):
        return "zones" in approve
    if key.startswith("t:"):
        return "words" in approve
    if key.startswith("v"):
        return "m" + key[1:].split(":")[0] in approve
    return key in approve


def confirmed(table, game, key, approve):
    """The text for a claim that two senders agree on or the owner approved, or None."""
    options = table.get(game, {}).get(key)
    if options:
        text, claim = best(options)
        if len(claim["senders"]) >= 2 or approved(key, approve):
            return text


# ------------------------------------------------------------------- merging
def apply_payload(data, payload, table, approve, words):
    """Move every fact that can go in from a waiting submission to the database. Returns how many moved."""
    game = payload["game"]
    g = gi.game_data(data, game)
    moved = 0
    for mob in list(payload["mobs"]):
        sub = payload["mobs"][mob]
        name = listed_name(data, game, "mobs", mob, sub.get("name"))
        if not name:
            # None: nobody has confirmed a name. "": approved without one.
            name = confirmed(table, game, "m" + mob, approve)
            if name is None and mob not in g["mobs"]:
                continue
        entry = gi.mob_entry(g, mob)
        entry["name"] = entry["name"] or name or ""
        gi.add_places(entry, sub.pop("in", []))
        for level in list(sub["levels"]):
            seen = sub["levels"][level]
            for key in list(seen["v"]):
                value = seen["v"][key]
                if (key in WORDS and value not in words[key]
                        and confirmed(table, game, f"t:{key}:{value}", approve) != value):
                    continue
                old = entry["levels"].get(level, {}).get("v", {}).get(key)
                differs = old is not None and not same(old, value)
                if differs and key != "z" and confirmed(table, game, f"v{mob}:{level}:{key}", approve) != json.dumps(value):
                    continue
                del seen["v"][key]
                moved += 1
                if differs and key == "z":
                    continue   # mobs wander: keep the zone the database has
                slot = entry["levels"].setdefault(
                    level, {"at": seen["at"], "v": {"n": entry["name"]} if entry["name"] else {}})
                slot["v"][key] = value
                slot["at"] = max(slot["at"], seen["at"])
                if key in WORDS:
                    words[key].add(value)
            if not seen["v"]:
                del sub["levels"][level]
        for spell in list(sub["spells"]):
            spell_name = (listed_name(data, game, "spells", spell, payload["spells"].get(spell))
                          or confirmed(table, game, "s" + spell, approve))
            if not spell_name:
                continue
            g["spells"].setdefault(spell, spell_name)
            cast = sub["spells"].pop(spell)
            moved += 1
            have = entry["spells"].setdefault(spell, {"n": 0, "spawns": 0, "at": cast["at"]})
            have["n"] += cast["n"]
            have["spawns"] += cast["spawns"]
            if cast["at"] >= have["at"]:
                have["at"] = cast["at"]
                if "build" in cast:
                    have["build"] = cast["build"]
        # A name still waiting to be confirmed keeps the mob here after its stats have gone in.
        if not sub["levels"] and not sub["spells"] and not waiting_name(data, game, mob, sub):
            del payload["mobs"][mob]
    for instance in list(payload["instances"]):
        entry = payload["instances"][instance]
        name = (listed_name(data, game, "instances", instance, entry.get("name"))
                or confirmed(table, game, "i" + instance, approve))
        if not name:
            continue
        have = g["instances"].setdefault(instance, {"name": name, "minutes": 0})
        have["name"] = have.get("name") or name
        have["minutes"] = round(have["minutes"] + entry["minutes"], 3)
        words["z"].add(name)
        del payload["instances"][instance]
        moved += 1
    used = {spell for sub in payload["mobs"].values() for spell in sub["spells"]}
    payload["spells"] = {spell: name for spell, name in payload["spells"].items() if spell in used}
    return moved


def settle(data, held, approve=None):
    """Move everything that can go into the database, until nothing more moves."""
    for _ in range(20):
        table, words = claims(data, held), known_words(data)
        if not sum(apply_payload(data, payload, table, approve, words) for payload in held["pending"]):
            break
    held["pending"] = [payload for payload in held["pending"] if payload["mobs"] or payload["instances"]]


def drop(data, held, tokens):
    """Throw waiting data away: all of it, or the mobs, spells, instances, zones or words named."""
    if "all" in tokens:
        held["pending"] = []
        return
    words = known_words(data)
    for payload in held["pending"]:
        for mob in list(payload["mobs"]):
            sub = payload["mobs"][mob]
            if "m" + mob in tokens:
                del payload["mobs"][mob]
                continue
            for level in list(sub["levels"]):
                values = sub["levels"][level]["v"]
                for key in [k for k in values if k in WORDS and values[k] not in words[k]]:
                    if ("zones" if key == "z" else "words") in tokens:
                        del values[key]
                if not values:
                    del sub["levels"][level]
            for spell in [s for s in sub["spells"] if "s" + s in tokens]:
                del sub["spells"][spell]
            if not sub["levels"] and not sub["spells"] and not waiting_name(data, payload["game"], mob, sub):
                del payload["mobs"][mob]
        payload["spells"] = {s: name for s, name in payload["spells"].items() if "s" + s not in tokens}
        payload["instances"] = {i: e for i, e in payload["instances"].items() if "i" + i not in tokens}
    held["pending"] = [payload for payload in held["pending"] if payload["mobs"] or payload["instances"]]


def expire(held, today):
    oldest = (today - datetime.timedelta(days=HELD_DAYS)).isoformat()
    held["pending"] = [payload for payload in held["pending"] if payload["received"] >= oldest]


# ------------------------------------------------------------------- wording
def count(n, one, many):
    return f"{n} {one if n == 1 else many}"


def render_held(data, held):
    """The list the owner reads, and how many things are on it."""
    table = claims(data, held)
    total = sum(len(keys) for keys in table.values())
    if not total:
        return "Nothing is waiting.\n", 0
    out = ["Data sent in by players that a machine can't judge. Each line goes into the database by itself "
           "when a second player reports the same thing.",
           "",
           "**Approving this pull request adds all of it.** \"Files changed\" shows exactly what that would add.",
           ""]
    lines = []

    def who(claim):
        return f"({count(len(claim['senders']), 'sender', 'senders')}, since {claim['first']})"

    def section(title, rows):
        if rows:
            lines.extend(["", f"**{title}**", ""] + rows)

    for game in sorted(table):
        lines.append(f"### {TITLES.get(game, game)}")
        keys = table[game]
        named = {"m": [], "s": [], "i": []}
        zones, words, differs = [], [], []
        for key in sorted(keys, key=lambda k: (k[0], [int(n) for n in re.findall(r"\d+", k)[:2]], k)):
            text, claim = best(keys[key])
            others = sorted(t or "no name" for t in keys[key] if t != text)
            also = f" (also sent as: {', '.join(others)})" if others else ""
            if key.startswith("t:z:"):
                zones.append(f"- {text} {who(claim)}")
            elif key.startswith("t:"):
                words.append(f"- {LABELS[key.split(':')[1]]}: {text} {who(claim)}")
            elif key.startswith("v"):
                mob, level, stat = key[1:].split(":")
                entry = data["games"][game]["mobs"][mob]
                old = entry["levels"][level]["v"][stat]
                differs.append(f"- `m{mob}` {entry['name'] or 'Mob ' + mob}, level {level}: {LABELS[stat]} {old} → "
                               f"{json.loads(text)}{also} {who(claim)}")
            else:
                named[key[0]].append(f"- `{key}` {text or '(no name sent)'}{also} {who(claim)}")
        section("New mobs", named["m"])
        section("New spells", named["s"])
        section("New instances", named["i"])
        section("New zones (`approve zones`)", zones)
        section("New words (`approve words`)", words)
        section("Different from the database", differs)
        lines.append("")
    if len(lines) > LIST_LINES:
        lines = lines[:LIST_LINES] + ["", f"...and {len(lines) - LIST_LINES} more lines."]
    out += lines
    out += ["---", "",
            "To approve only some of it, comment `approve m3273 s5401 i48`, `approve zones` or `approve words`. "
            "To throw data away, comment `drop` the same way, or `drop all`. "
            "Only the repository owner's approval and comments count.", ""]
    return "\n".join(out), total


def parse_command(body):
    """(verb, tokens, words it didn't understand) for an owner's comment, or None if it isn't a command."""
    first = next((line.strip() for line in (body or "").splitlines() if line.strip()), "")
    m = COMMAND.match(first)
    if not m:
        return None
    tokens = [t for t in re.split(r"[\s,]+", m.group(2).lower()) if t]
    return m.group(1).lower(), [t for t in tokens if TOKEN.match(t)], [t for t in tokens if not TOKEN.match(t)]


def reply_to(added, waiting, dropped, english):
    out = [f"Thanks! {count(added, 'fact', 'facts')} went into the database"
           + (" and will be in the next GanderData release." if added else " this time.")]
    if waiting:
        out.append(f"{waiting} {'is' if waiting == 1 else 'are'} waiting: a name the database doesn't have yet, or a "
                   "value that differs from what it has. That goes in once a second player reports the same thing, "
                   "or when the maintainer approves it.")
    if dropped:
        out.append(f"{dropped} {'was' if dropped == 1 else 'were'} left out, for being outside what a mob in the "
                   "game can have.")
    if not english:
        out.append("Names were left out because the game wasn't in English; the numbers still count.")
    return " ".join(out) + "\n"


def sender_of(issue, sub):
    """A scrambled marker for who sent an issue. A stamp inside the data is
    only believed on issues the owner's own account opened: that is how the
    submission page sends them, and it stamps each with its sender."""
    stamp = sub.get("sender")
    if issue.get("author_association") == "OWNER" and isinstance(stamp, str) and STAMP.match(stamp):
        return scramble("gander-sender:w:" + stamp, 12)
    return scramble(f"gander-sender:gh:{(issue.get('user') or {}).get('id')}", 12)


def process(data, held, issues, comments, owner, now, approve_hash=None, logs=None):
    """Handle an approval of the held pull request, the owner's comments on
    it, and the open submissions. Changes data, held and the record of combat
    logs; returns what to say."""
    today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
    logs = gi.new_logs() if logs is None else logs
    forget_batches(logs, today)
    before = gi.counts(data)
    result = {"issues": [], "commands": [], "approved": False, "stale": False}
    did = []
    if approve_hash is not None:
        if approve_hash == held_hash(held):
            settle(data, held, "all")
            result["approved"] = True
            did.append("approved held data")
        else:
            result["stale"] = True
    expire(held, today)
    settle(data, held)   # the database may have learned a name since the last run

    for note in sorted(comments, key=lambda c: c.get("id", 0)):
        if (note.get("user") or {}).get("login") != owner or (note.get("reactions") or {}).get("+1"):
            continue
        command = parse_command(note.get("body"))
        if not command:
            continue
        verb, tokens, unknown = command
        waiting = sum(facts(p) for p in held["pending"])
        if unknown or not tokens:
            reply = f"I didn't understand {', '.join(f'`{t}`' for t in unknown) or 'that'}, so nothing changed. {HELP}"
        elif verb == "approve":
            settle(data, held, "all" if "all" in tokens else set(tokens))
            left = sum(facts(p) for p in held["pending"])
            reply = (f"Approved: {count(waiting - left, 'fact', 'facts')} went into the database, "
                     f"{left} still waiting.")
            did.append("approved held data")
            if left == 0 and waiting > 0:
                # The whole list went in, as with an approving review: the
                # workflow merges through the held pull request itself.
                result["approved"] = True
        else:
            drop(data, held, set(tokens))
            left = sum(facts(p) for p in held["pending"])
            reply = f"Dropped {count(waiting - left, 'fact', 'facts')}; {left} still waiting."
            did.append("dropped held data")
        result["commands"].append({"id": note["id"], "reply": reply + "\n"})

    taken = []
    for issue in sorted(issues, key=lambda i: i.get("number", 0))[:MAX_ISSUES]:
        labels = {label.get("name") for label in issue.get("labels") or []}
        if issue.get("pull_request") or "gander-stuck" in labels:
            continue
        try:
            sub = parse_body(issue.get("body"))
            clean, dropped, english = validate(sub, now)
        except Exception as error:   # whatever a stranger sends, the run carries on
            why = error if isinstance(error, Rejected) else "the data block is damaged, so it can't be read"
            result["issues"].append({"number": issue["number"], "reason": "not planned", "comment": (
                f"Thanks for sending this, but it couldn't be used: {why}.\n\n"
                "Data for GanderData has to be the block Gander makes, pasted whole.\n")})
            continue
        sender = sender_of(issue, sub)
        mark = scramble(sender + json.dumps(clean, sort_keys=True), 16)
        if mark in held["seen"]:
            result["issues"].append({"number": issue["number"], "reason": "completed", "comment": (
                "Thanks! This exact data was already sent in, so there was nothing new to add.\n")})
            continue
        held["seen"] = (held["seen"] + [mark])[-REMEMBERED:]
        if not take_logs(logs, clean, today.isoformat()):
            result["issues"].append({"number": issue["number"], "reason": "completed", "comment": (
                "Thanks! The database already has this part of these combat logs, so nothing was added. "
                "That happens when the same log is sent from two places, or twice within a few minutes.\n")})
            continue
        for key in ("logs", "part", "parts"):
            clean.pop(key, None)
        payload = {**clean, "sender": sender, "received": today.isoformat()}
        taken.append((issue["number"], payload, facts(payload), dropped, english))
        held["pending"].append(payload)
        settle(data, held)
    # Count what each submission got in only now: a later one may have confirmed an earlier one.
    for number, payload, total, dropped, english in taken:
        waiting = facts(payload)
        result["issues"].append({"number": number, "reason": "completed",
                                 "comment": reply_to(total - waiting, waiting, dropped, english)})
    result["issues"].sort(key=lambda i: i["number"])
    if taken:
        did.insert(0, count(len(taken), "submission", "submissions"))
    note = gi.changelog_line(before, gi.counts(data))
    result["title"] = "Gander data: " + (", ".join(dict.fromkeys(did)) or "tidying up")
    body = [note or "Nothing new for players in this one: it records what is waiting to be confirmed."]
    if taken:
        body.append("Submissions: " + ", ".join(f"#{number}" for number, *_ in taken))
    why = []
    if taken:
        why.append("What came from submissions passed the checks or was confirmed by a second sender.")
    if "approved held data" in did:
        why.append("The held data in it was approved by the repository owner.")
    body.append(" ".join(why + ["Tests ran before the merge."]))
    result["body"] = "\n\n".join(body) + "\n"
    return result


# -------------------------------------------------------------- command line
def write_tree(data, held, data_path, held_path, addon, before, logs=None, logs_path=None):
    """Save whichever of the database, the held list and the record of combat
    logs changed. Returns whether anything did."""
    data_before, held_before, logs_before = before
    data_changed = json.dumps(data, sort_keys=True) != data_before
    held_changed = json.dumps(held, sort_keys=True) != held_before
    if logs is not None and json.dumps(logs, sort_keys=True) != logs_before:
        gi.save_json(logs_path, logs)
        held_changed = True
    if data_changed:
        gi.save_json(data_path, data)
        lua = addon / f"{addon.name}.lua"
        lua.write_text(gi.to_lua(data, gi.current_version(addon)), encoding="utf-8", newline="\n")
    if held_changed:
        gi.save_json(held_path, held)
    return data_changed or held_changed


def write(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv=None):
    p = argparse.ArgumentParser(description="Check Gander data sent in by players and merge what can be trusted.")
    p.add_argument("command", choices=("run", "held"))
    p.add_argument("--issues", type=pathlib.Path, help="the open submissions, as GitHub's API lists them")
    p.add_argument("--comments", type=pathlib.Path, help="comments on the held pull request, as the API lists them")
    p.add_argument("--owner", default="", help="the only login whose comments count")
    p.add_argument("--approve-hash", help="the owner approved the held list that had this hash")
    p.add_argument("--out", type=pathlib.Path, required=True, help="folder for what the workflow should say")
    p.add_argument("--now", type=float, help="the time, for tests")
    p.add_argument("--data", type=pathlib.Path, default=gi.DATA)
    p.add_argument("--held-file", type=pathlib.Path, default=HELD)
    p.add_argument("--logs-file", type=pathlib.Path, default=gi.LOGS)
    p.add_argument("--addon", type=pathlib.Path, default=gi.ADDON)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    data = gi.load_json(args.data, gi.empty_data())
    held = gi.load_json(args.held_file, new_held())
    logs = gi.load_json(args.logs_file, gi.new_logs())
    before = (json.dumps(data, sort_keys=True), json.dumps(held, sort_keys=True), json.dumps(logs, sort_keys=True))

    if args.command == "held":
        text, total = render_held(data, held)
        info = {"count": total, "hash": held_hash(held), "title": f"Held Gander data: {total} waiting"}
        settle(data, held, "all")
        info["changed"] = write_tree(data, held, args.data, args.held_file, args.addon, before)
        write(args.out / "held.md", text)
        write(args.out / "held.json", json.dumps(info) + "\n")
        print(f"{total} waiting")
        return 0

    issues = json.loads(args.issues.read_text(encoding="utf-8")) if args.issues else []
    comments = json.loads(args.comments.read_text(encoding="utf-8")) if args.comments else []
    result = process(data, held, issues, comments, args.owner, args.now or time.time(), args.approve_hash, logs)
    for issue in result["issues"]:
        write(args.out / f"issue-{issue['number']}.md", issue.pop("comment"))
    for command in result["commands"]:
        write(args.out / f"command-{command['id']}.md", command.pop("reply"))
    result["commands"] = [command["id"] for command in result["commands"]]
    write(args.out / "pr_body.md", result.pop("body"))
    result["changed"] = write_tree(data, held, args.data, args.held_file, args.addon, before, logs, args.logs_file)
    write(args.out / "result.json", json.dumps(result) + "\n")
    print(f"{result['title']}: {len(result['issues'])} issues answered, "
          f"{'files changed' if result['changed'] else 'nothing to merge'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
