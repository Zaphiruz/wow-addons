"""Turns combat log files into Gander's list of what each mob casts.

Usage: python gander_import.py              import every new log, then delete the logs
       python gander_import.py --keep       import, but leave the log files alone
       python gander_import.py --dry-run    show what an import would do; change nothing
       python gander_import.py --logs DIR   read logs from DIR (repeatable) instead of the game folders

The game writes Logs/WoWCombatLog-<date>.txt while combat logging is on
(/combatlog, or Gander's "log combat in dungeons" setting). Addons can't read
that file, so this script does. From each log it keeps one kind of fact:
"this hostile mob cast or applied this spell". Players, their pets and their
totems are skipped, and no player name is written anywhere.

What it writes:
  mods/classic/data/gander_abilities.json      everything imported so far (kept in git)
  mods/classic/Gander/Abilities.lua            the same list for the addon to load
  mods/classic/data/gander_import_state.json   how far into each kept log it has read
                                               (this PC only, not in git)

A log is deleted once it has been read to the end, unless --keep is given or
the file changed in the last ten minutes (the game may still be writing it).
"""
import argparse
import csv
import datetime
import json
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent  # mods/classic
DATA = ROOT / "data" / "gander_abilities.json"
STATE = ROOT / "data" / "gander_import_state.json"
LUA = ROOT / "Gander" / "Abilities.lua"
GAME_DIR = pathlib.Path(r"D:\Battle.net\Games\World of Warcraft")
DEFAULT_LOGS = [GAME_DIR / "_forever_" / "Logs", GAME_DIR / "_classic_era_" / "Logs"]

# PROJECT_ID in the log's header line -> the name Gander uses for that game.
GAMES = {"18": "forever", "2": "classic"}
EVENTS = {"SPELL_CAST_START", "SPELL_CAST_SUCCESS", "SPELL_AURA_APPLIED"}
# Effects every mob can cause, which say nothing about the mob.
IGNORED_SPELLS = {1604: "Dazed"}
# Unit flags (COMBATLOG_OBJECT_*): who controls the unit and how it reacts to you.
FRIENDLY, HOSTILE, PLAYER_CONTROL, NPC_CONTROL = 0x10, 0x40, 0x100, 0x200
GAP = 30       # seconds: a longer pause between log lines isn't counted as fighting
IN_USE = 600   # seconds: a log changed more recently than this may still be open in the game

LINE = re.compile(r"^(\d+)/(\d+)(?:/(\d+))? (\d+):(\d+):(\d+)\.(\d+)\S*  (.*)$")


def empty_data():
    return {"version": 1, "games": {}}


def game_data(data, game):
    return data["games"].setdefault(game, {"instances": {}, "spells": {}, "mobs": {}})


def creature_id(guid):
    """The creature ID in a mob's GUID, or None for players, pets and anything else."""
    parts = guid.split("-")
    if len(parts) >= 7 and parts[0] in ("Creature", "Vehicle") and parts[5].isdigit():
        return int(parts[5])


def flags_of(text):
    try:
        return int(text, 16)
    except ValueError:
        return 0


def player_owned(guid, flags):
    return guid.startswith(("Player-", "Pet-")) or bool(flags & PLAYER_CONTROL)


class Reader:
    """Reads log lines into data. ctx carries what the earlier part of a log
    said (which game, build and instance), so a log can be read in pieces."""

    def __init__(self, data, ctx=None, year=None):
        self.data = data
        self.ctx = ctx or {}
        self.year = year or datetime.date.today().year
        self.last = None          # time of the previous line
        self.summoned = set()     # GUIDs of things players summoned: totems, pets
        self.spawns = {}          # (game, mob, spell) -> GUIDs seen using it
        self.lines = 0
        self.new_mobs = 0
        self.new_spells = 0

    def feed(self, lines):
        for line in lines:
            m = LINE.match(line.rstrip("\r\n"))
            if m:
                self.lines += 1
                self.read(m)
        for (game, mob, spell), guids in self.spawns.items():
            game_data(self.data, game)["mobs"][mob]["spells"][spell]["spawns"] += len(guids)
        self.spawns = {}

    def read(self, m):
        month, day, year, hour, minute, second, _, rest = m.groups()
        when = datetime.datetime(int(year or self.year), int(month), int(day), int(hour), int(minute), int(second))
        event = rest.split(",", 1)[0]
        if event == "COMBAT_LOG_VERSION":
            f = rest.split(",")
            pairs = dict(zip(f[0::2], f[1::2]))  # NAME,value,NAME,value...
            project = pairs.get("PROJECT_ID")
            self.ctx["game"] = GAMES.get(project, project)
            self.ctx["build"] = pairs.get("BUILD_VERSION")
        elif event == "ZONE_CHANGE":
            f = next(csv.reader([rest]))
            if len(f) >= 3:
                # The last field is the difficulty: 0 is the open world, where
                # the "instance" is a whole continent and the name just a zone.
                inside = len(f) < 4 or f[3] != "0"
                self.ctx["instance"] = f[1] if inside else None
                self.ctx["instance_name"] = f[2] if inside else None
                self.last = None  # the gap before this was travel, not fighting
        game = self.ctx.get("game")
        if not game:
            return
        self.count_time(game, when)
        if event == "SPELL_SUMMON":
            f = next(csv.reader([rest]))
            if len(f) >= 6 and player_owned(f[1], flags_of(f[3])):
                self.summoned.add(f[5])
        elif event in EVENTS:
            self.read_spell(game, event, next(csv.reader([rest])), when)

    def count_time(self, game, when):
        instance = self.ctx.get("instance")
        if instance and self.last:
            gap = (when - self.last).total_seconds()
            if 0 < gap <= GAP:
                entry = game_data(self.data, game)["instances"].setdefault(
                    instance, {"name": self.ctx.get("instance_name", ""), "minutes": 0})
                entry["minutes"] = round(entry["minutes"] + gap / 60, 3)
        if self.last is None or when > self.last:
            self.last = when

    def read_spell(self, game, event, f, when):
        if len(f) < 11:
            return
        guid, name, flags = f[1], f[2], flags_of(f[3])
        mob = creature_id(guid)
        if mob is None or guid in self.summoned:
            return
        if not (flags & HOSTILE and flags & NPC_CONTROL) or flags & (PLAYER_CONTROL | FRIENDLY):
            return
        if not f[9].isdigit() or int(f[9]) <= 0 or int(f[9]) in IGNORED_SPELLS:
            return
        g = game_data(self.data, game)
        mob, spell = str(mob), f[9]
        g["spells"][spell] = f[10]
        if mob not in g["mobs"]:
            g["mobs"][mob] = {"name": name, "spells": {}}
            self.new_mobs += 1
        entry = g["mobs"][mob]
        entry["name"] = name
        if spell not in entry["spells"]:
            entry["spells"][spell] = {"n": 0, "spawns": 0}
            self.new_spells += 1
        seen = entry["spells"][spell]
        seen["n"] += 1
        seen["at"] = when.date().isoformat()
        if self.ctx.get("build"):
            seen["build"] = self.ctx["build"]
        self.spawns.setdefault((game, mob, spell), set()).add(guid)


def lua_string(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def to_lua(data):
    """The addon's copy: per game, minutes logged in each instance, spell
    names, and each mob's spells with the most often seen first."""
    out = ["-- What each mob casts, gathered from combat log files.",
           "-- Generated by mods/classic/tools/gander_import.py. Don't edit by hand.",
           "local _, ns = ...",
           "ns.abilities = {"]
    for game in sorted(data["games"]):
        g = data["games"][game]
        mobs = {}
        for mob, entry in g["mobs"].items():
            spells = [s for s in entry["spells"] if int(s) not in IGNORED_SPELLS]
            spells.sort(key=lambda s: (-entry["spells"][s]["n"], int(s)))
            if spells:
                mobs[mob] = spells
        used = sorted({int(s) for spells in mobs.values() for s in spells})
        out.append(f"  {game} = {{")
        out.append("    instances = {  -- minutes of fighting logged in each")
        for instance in sorted(g["instances"], key=int):
            entry = g["instances"][instance]
            out.append(f"      [{int(instance)}] = {int(entry['minutes'])},  -- {lua_comment(entry['name'])}")
        out.append("    },")
        out.append("    spells = {")
        for spell in used:
            out.append(f"      [{spell}] = {lua_string(g['spells'].get(str(spell), ''))},")
        out.append("    },")
        out.append("    mobs = {")
        for mob in sorted(mobs, key=int):
            out.append(f"      [{int(mob)}] = {{ {', '.join(mobs[mob])} }},  -- {lua_comment(g['mobs'][mob]['name'])}")
        out.append("    },")
        out.append("  },")
    out.append("}")
    return "\n".join(out) + "\n"


def lua_comment(text):
    return str(text).replace("\n", " ").replace("\r", " ")


def load_json(path, default):
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def size(n):
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{n / 1024:.0f} KB"


def run(log_dirs, data_path=DATA, state_path=STATE, lua_path=LUA, keep=False, dry_run=False, now=None, out=print):
    now = time.time() if now is None else now
    data = load_json(data_path, empty_data())
    state = load_json(state_path, {})
    left_on_disk = 0
    found = set()
    for folder in log_dirs:
        folder = pathlib.Path(folder)
        for log in sorted(folder.glob("WoWCombatLog*.txt")):
            key = f"{folder.parent.name}/{log.name}"
            found.add(key)
            seen = state.get(key, {})
            offset = seen.get("offset", 0)
            raw = log.read_bytes()
            if offset > len(raw):
                offset, seen = 0, {}  # a different file under an old name
            fresh = raw[offset:]
            fresh = fresh[:fresh.rfind(b"\n") + 1]  # whole lines only
            mtime = log.stat().st_mtime
            reader = Reader(data, dict(seen.get("ctx", {})), datetime.date.fromtimestamp(mtime).year)
            reader.feed(fresh.decode("utf-8", errors="replace").splitlines())
            note = f"{reader.lines} lines, {reader.new_mobs} new mobs, {reader.new_spells} new abilities"
            in_use = now - mtime < IN_USE
            if keep or in_use or dry_run:
                state[key] = {"offset": offset + len(fresh), "ctx": reader.ctx}
                left_on_disk += len(raw)
                why = "kept (--keep)" if keep else "kept: changed in the last ten minutes" if in_use else "would delete"
                out(f"{key}: {note}; {why}, {size(len(raw))}")
            else:
                try:
                    log.unlink()
                    state.pop(key, None)
                    out(f"{key}: {note}; deleted, freed {size(len(raw))}")
                except OSError as e:
                    state[key] = {"offset": offset + len(fresh), "ctx": reader.ctx}
                    left_on_disk += len(raw)
                    out(f"{key}: {note}; couldn't delete it ({e.strerror}), {size(len(raw))}")
    for key in [k for k in state if k not in found]:
        del state[key]  # a log that has gone
    if not found:
        out("no combat logs found. Switch logging on in game with /combatlog or Gander's setting.")
    totals = ", ".join(f"{game}: {len(g['mobs'])} mobs" for game, g in sorted(data["games"].items()))
    out(f"the list now has {totals or 'nothing'}; {size(left_on_disk)} of logs left on disk.")
    if dry_run:
        out("dry run: nothing was written or deleted.")
        return data
    save_json(data_path, data)
    save_json(state_path, state)
    lua_path.parent.mkdir(parents=True, exist_ok=True)
    lua_path.write_text(to_lua(data), encoding="utf-8", newline="\n")
    return data


def main(argv=None):
    p = argparse.ArgumentParser(description="Import combat logs into Gander's abilities list.")
    p.add_argument("--logs", action="append", help="a Logs folder to read (repeatable)")
    p.add_argument("--keep", action="store_true", help="don't delete logs after importing them")
    p.add_argument("--dry-run", action="store_true", help="change nothing; just report")
    args = p.parse_args(argv)
    run(args.logs or DEFAULT_LOGS, keep=args.keep, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
