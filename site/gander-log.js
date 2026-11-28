// Reads World of Warcraft combat logs for the GanderData database: which
// spells hostile mobs cast, and how long was spent fighting in each dungeon.
// Nothing else is taken from a log. No player's name, GUID or spell is kept.
//
// This is the same reading mods/classic/tools/gander_import.py does, written
// again so it can run in a browser. The two must agree: the tests in
// mods/classic/tests/tools/test_gander_site.py read the same logs with both
// and compare, so change them together.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.GanderLog = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // PROJECT_ID in a log's header line -> game.
  var GAMES = { "18": "forever", "2": "classic" };
  var EVENTS = { SPELL_CAST_START: true, SPELL_CAST_SUCCESS: true, SPELL_AURA_APPLIED: true };
  // Effects every mob can cause, which say nothing about the mob.
  var IGNORED_SPELLS = { 1604: "Dazed" };
  // Unit flags (COMBATLOG_OBJECT_*): who controls the unit and how it reacts to you.
  var FRIENDLY = 0x10, HOSTILE = 0x40, PLAYER_CONTROL = 0x100, NPC_CONTROL = 0x200;
  var GAP = 30;            // seconds: a longer pause between log lines isn't counted as fighting
  var FORMAT = 1;          // the submission format, as in gander_submit.py
  var BLOCK_SIZE = 30000;  // characters in one submission, as in Gander's /gander send
  var MAX_PLACES = 20;     // dungeons one mob may be listed in

  var LINE = /^(\d+)\/(\d+)(?:\/(\d+))? (\d+):(\d+):(\d+)\.(\d+)\S*  (.*)$/;
  var DIGITS = /^\d+$/;
  var HEX = /^(0x)?[0-9a-f]+$/i;

  function newData() {
    return { games: {} };
  }

  // ---- the record of logs ----
  // The database keeps a record of how many bytes of each combat log it has
  // had (data/gander_logs.json), so that no part of a log is counted twice.
  // A log is known there by a scramble of its first line, which holds a time
  // and the game's version and nothing about the player. This is
  // gander_import.py's log_id: bytes is the start of the file. The answer
  // comes later (a Promise): the name, or null if the first line isn't whole.
  function logId(bytes) {
    var end = bytes.indexOf(10);
    if (end < 0) return Promise.resolve(null);
    while (end > 0 && (bytes[end - 1] === 13 || bytes[end - 1] === 10)) end -= 1;
    var subtle = (typeof crypto !== "undefined" && crypto.subtle) || require("crypto").webcrypto.subtle;
    return subtle.digest("SHA-256", bytes.slice(0, end)).then(function (hash) {
      var out = "";
      new Uint8Array(hash).slice(0, 8).forEach(function (byte) { out += (byte < 16 ? "0" : "") + byte.toString(16); });
      return out;
    });
  }

  function gameData(data, game) {
    if (!Object.prototype.hasOwnProperty.call(data.games, game)) {
      data.games[game] = { instances: {}, spells: {}, mobs: {} };
    }
    return data.games[game];
  }

  function mobEntry(g, mob, name) {
    if (!Object.prototype.hasOwnProperty.call(g.mobs, mob)) {
      g.mobs[mob] = { name: name || "", spells: {}, levels: {} };
    }
    var entry = g.mobs[mob];
    if (name) entry.name = name;
    return entry;
  }

  // Note the dungeons (instance IDs) a mob was logged in: each once, in
  // number order, and never more than a mob could really be found in.
  function addPlaces(entry, instances) {
    var have = (entry["in"] || []).slice();
    for (var i = 0; i < instances.length; i++) {
      var instance = instances[i];
      if (typeof instance === "string" && DIGITS.test(instance) && have.indexOf(instance) === -1 &&
          have.length < MAX_PLACES) {
        have.push(instance);
      }
    }
    if (have.length) entry["in"] = have.sort(function (a, b) { return Number(a) - Number(b); });
  }

  // One line's fields. A field in quotes can hold commas, and a doubled
  // quote inside it stands for one quote.
  function fields(text) {
    var out = [], field = "", i = 0, n = text.length;
    while (i <= n) {
      field = "";
      if (text.charAt(i) === '"') {
        i += 1;
        while (i < n) {
          var c = text.charAt(i);
          if (c === '"') {
            if (text.charAt(i + 1) === '"') { field += '"'; i += 2; continue; }
            i += 1;
            break;
          }
          field += c;
          i += 1;
        }
      }
      var comma = text.indexOf(",", i);
      if (comma === -1) comma = n;
      field += text.slice(i, comma);
      out.push(field);
      i = comma + 1;
    }
    return out;
  }

  // The creature ID in a mob's GUID, or null for players, pets and anything else.
  function creatureId(guid) {
    var parts = guid.split("-");
    if (parts.length >= 7 && (parts[0] === "Creature" || parts[0] === "Vehicle") && DIGITS.test(parts[5])) {
      return parseInt(parts[5], 10);
    }
    return null;
  }

  function flagsOf(text) {
    return HEX.test(text) ? parseInt(text, 16) : 0;
  }

  function playerOwned(guid, flags) {
    return guid.indexOf("Player-") === 0 || guid.indexOf("Pet-") === 0 || (flags & PLAYER_CONTROL) !== 0;
  }

  function pad(number, width) {
    var text = String(number);
    while (text.length < width) text = "0" + text;
    return text;
  }

  function round3(value) {
    return Math.round(value * 1000) / 1000;
  }

  // Reads log lines into data. ctx carries what the earlier part of a log
  // said (which game, build and instance), so a log can be read in pieces.
  // year is for Classic Era, whose lines don't say which year it is.
  function Reader(data, ctx, year) {
    this.data = data;
    this.ctx = {};
    for (var key in ctx || {}) this.ctx[key] = ctx[key];
    this.year = year || new Date().getFullYear();
    this.last = null;      // time of the previous line, in seconds
    this.summoned = {};    // GUIDs of things players summoned: totems, pets
    this.spawns = {};      // game, mob and spell -> the GUIDs seen using it
    this.lines = 0;
    this.partial = "";     // the start of a line whose end hasn't arrived yet
  }

  // Read whole lines. Call it once for each piece of a log: at the end it
  // counts how many different mobs used each spell in that piece.
  Reader.prototype.feed = function (lines) {
    for (var i = 0; i < lines.length; i++) this.line(lines[i]);
    this.finish();
  };

  // Read text as it arrives, in any size of chunk. Call finish() at the end.
  // A last line with no line ending is left unread: the game may still be
  // writing it.
  Reader.prototype.feedText = function (text) {
    var lines = (this.partial + text).split("\n");
    this.partial = lines.pop();
    for (var i = 0; i < lines.length; i++) this.line(lines[i]);
  };

  Reader.prototype.finish = function () {
    for (var key in this.spawns) {
      var where = key.split("\n");
      this.data.games[where[0]].mobs[where[1]].spells[where[2]].spawns += Object.keys(this.spawns[key]).length;
    }
    this.spawns = {};
  };

  Reader.prototype.line = function (text) {
    var m = LINE.exec(text.replace(/[\r\n]+$/, ""));
    if (!m) return;
    var year = parseInt(m[3] || this.year, 10), month = parseInt(m[1], 10), day = parseInt(m[2], 10);
    var when = Date.UTC(year, month - 1, day, parseInt(m[4], 10), parseInt(m[5], 10), parseInt(m[6], 10)) / 1000;
    if (isNaN(when) || month < 1 || month > 12 || day < 1 || day > 31) return;
    this.lines += 1;
    var rest = m[8];
    var comma = rest.indexOf(",");
    var event = comma === -1 ? rest : rest.slice(0, comma);
    var f;
    if (event === "COMBAT_LOG_VERSION") {
      f = rest.split(",");
      var pairs = {};
      for (var i = 0; i + 1 < f.length; i += 2) pairs[f[i]] = f[i + 1];  // NAME,value,NAME,value...
      var project = pairs.PROJECT_ID === undefined ? null : pairs.PROJECT_ID;
      this.ctx.game = GAMES.hasOwnProperty(project) ? GAMES[project] : project;
      this.ctx.build = pairs.BUILD_VERSION === undefined ? null : pairs.BUILD_VERSION;
    } else if (event === "ZONE_CHANGE") {
      f = fields(rest);
      if (f.length >= 3) {
        // The last field is the difficulty: 0 is the open world, where the
        // "instance" is a whole continent and the name just a zone.
        var inside = f.length < 4 || f[3] !== "0";
        this.ctx.instance = inside ? f[1] : null;
        this.ctx.instance_name = inside ? f[2] : null;
        this.last = null;  // the gap before this was travel, not fighting
      }
    }
    var game = this.ctx.game;
    if (!game) return;
    this.countTime(game, when);
    if (event === "SPELL_SUMMON") {
      f = fields(rest);
      if (f.length >= 6 && playerOwned(f[1], flagsOf(f[3]))) this.summoned[f[5]] = true;
    } else if (EVENTS.hasOwnProperty(event)) {
      this.readSpell(game, fields(rest), pad(year, 4) + "-" + pad(month, 2) + "-" + pad(day, 2));
    }
  };

  Reader.prototype.countTime = function (game, when) {
    var instance = this.ctx.instance;
    if (instance && this.last !== null) {
      var gap = when - this.last;
      if (gap > 0 && gap <= GAP) {
        var instances = gameData(this.data, game).instances;
        if (!Object.prototype.hasOwnProperty.call(instances, instance)) {
          var name = this.ctx.instance_name;
          instances[instance] = { name: name === undefined ? "" : name, minutes: 0 };
        }
        instances[instance].minutes = round3(instances[instance].minutes + gap / 60);
      }
    }
    if (this.last === null || when > this.last) this.last = when;
  };

  Reader.prototype.readSpell = function (game, f, day) {
    if (f.length < 11) return;
    var guid = f[1], name = f[2], flags = flagsOf(f[3]);
    var mob = creatureId(guid);
    if (mob === null || this.summoned[guid] === true) return;
    if (!((flags & HOSTILE) && (flags & NPC_CONTROL)) || (flags & (PLAYER_CONTROL | FRIENDLY))) return;
    if (!DIGITS.test(f[9]) || parseInt(f[9], 10) <= 0 || IGNORED_SPELLS.hasOwnProperty(parseInt(f[9], 10))) return;
    var g = gameData(this.data, game);
    var spell = f[9];
    mob = String(mob);
    g.spells[spell] = f[10];
    var entry = mobEntry(g, mob, name);
    if (this.ctx.instance) addPlaces(entry, [this.ctx.instance]);
    if (!Object.prototype.hasOwnProperty.call(entry.spells, spell)) entry.spells[spell] = { n: 0, spawns: 0 };
    var seen = entry.spells[spell];
    seen.n += 1;
    seen.at = day;
    if (this.ctx.build) seen.build = this.ctx.build;
    var key = game + "\n" + mob + "\n" + spell;
    if (!this.spawns[key]) this.spawns[key] = {};
    this.spawns[key][guid] = true;
  };

  // Add what one log held to what the logs before it held.
  function merge(into, from) {
    for (var game in from.games) {
      var g = gameData(into, game), other = from.games[game], key;
      for (key in other.spells) g.spells[key] = other.spells[key];
      for (key in other.instances) {
        if (!Object.prototype.hasOwnProperty.call(g.instances, key)) {
          g.instances[key] = { name: other.instances[key].name, minutes: 0 };
        }
        g.instances[key].minutes = round3(g.instances[key].minutes + other.instances[key].minutes);
      }
      for (key in other.mobs) {
        var entry = mobEntry(g, key, other.mobs[key].name);
        addPlaces(entry, other.mobs[key]["in"] || []);
        for (var spell in other.mobs[key].spells) {
          var seen = other.mobs[key].spells[spell];
          if (!Object.prototype.hasOwnProperty.call(entry.spells, spell)) entry.spells[spell] = { n: 0, spawns: 0 };
          var mine = entry.spells[spell];
          mine.n += seen.n;
          mine.spawns += seen.spawns;
          mine.at = seen.at;
          if (seen.build) mine.build = seen.build;
        }
      }
    }
    return into;
  }

  function known(game) {
    return game === "forever" || game === "classic";
  }

  function numbered(keys) {
    return keys.sort(function (a, b) { return Number(a) - Number(b) || (a < b ? -1 : a > b ? 1 : 0); });
  }

  function casters(g) {
    return numbered(Object.keys(g.mobs).filter(function (mob) { return Object.keys(g.mobs[mob].spells).length > 0; }));
  }

  // What was found, for telling the player: one entry for each game.
  function summary(data) {
    var out = [];
    numbered(Object.keys(data.games)).forEach(function (game) {
      if (!known(game)) return;
      var g = data.games[game], spells = {};
      var mobs = casters(g);
      mobs.forEach(function (mob) { for (var spell in g.mobs[mob].spells) spells[spell] = true; });
      var instances = numbered(Object.keys(g.instances)).map(function (key) {
        return { id: key, name: g.instances[key].name || "", minutes: g.instances[key].minutes };
      });
      if (mobs.length || instances.length) {
        out.push({ game: game, mobs: mobs.length, spells: Object.keys(spells).length, instances: instances });
      }
    });
    return out;
  }

  // The submissions to send: JSON texts in the format gander_submit.py
  // checks, each no longer than options.size characters. Names are left out
  // when the game isn't in English (options.english === false), because the
  // database keeps English names only.
  //
  // options.logs says which logs the data came from, for each game:
  // { forever: { "<log id>": [first byte, byte after the last] } }. Every
  // block of a game carries its record, and when there are several they are
  // numbered ("part" of "parts"): together they are one read of those logs.
  function blocks(data, options) {
    options = options || {};
    var size = options.size || BLOCK_SIZE, english = options.english !== false;
    var out = [];
    ["classic", "forever"].forEach(function (game) {
      if (!Object.prototype.hasOwnProperty.call(data.games, game)) return;
      var g = data.games[game];
      var block = null, length = 0;
      var made = [];
      var record = options.logs && options.logs[game];
      if (record && !Object.keys(record).length) record = null;
      // Room for the record and the numbering, which go in at the end.
      var spare = record ? JSON.stringify(record).length + 40 : 0;

      function start() {
        block = { format: FORMAT, game: game, mobs: {}, spells: {}, instances: {} };
        if (!english) block.locale = "other";
        length = JSON.stringify(block).length + spare;
      }
      function close() {
        if (block && (Object.keys(block.mobs).length || Object.keys(block.instances).length)) made.push(block);
        block = null;
      }

      start();
      numbered(Object.keys(g.instances)).forEach(function (key) {
        block.instances[key] = { minutes: g.instances[key].minutes };
        if (english && g.instances[key].name) block.instances[key].name = g.instances[key].name;
      });
      length = JSON.stringify(block).length + spare;

      casters(g).forEach(function (mob) {
        var entry = { spells: {} }, names = {}, extra = 0;
        if (english && g.mobs[mob].name) entry.name = g.mobs[mob].name;
        if (g.mobs[mob]["in"]) entry["in"] = g.mobs[mob]["in"].slice();
        numbered(Object.keys(g.mobs[mob].spells)).forEach(function (spell) {
          var seen = g.mobs[mob].spells[spell];
          entry.spells[spell] = { n: seen.n, spawns: seen.spawns, at: seen.at };
          if (seen.build) entry.spells[spell].build = seen.build;
          if (english && typeof g.spells[spell] === "string") names[spell] = g.spells[spell];
        });
        function cost() {
          extra = JSON.stringify(mob).length + 1 + JSON.stringify(entry).length + 1;
          for (var spell in names) {
            if (!Object.prototype.hasOwnProperty.call(block.spells, spell)) {
              extra += JSON.stringify(spell).length + 1 + JSON.stringify(names[spell]).length + 1;
            }
          }
          return extra;
        }
        if (length + cost() > size && (Object.keys(block.mobs).length || Object.keys(block.instances).length)) {
          close();
          start();
          cost();
        }
        block.mobs[mob] = entry;
        for (var spell in names) block.spells[spell] = names[spell];
        length += extra;
      });
      close();
      made.forEach(function (one, i) {
        if (record) {
          one.logs = record;
          if (made.length > 1) {
            one.part = i + 1;
            one.parts = made.length;
          }
        }
        out.push(JSON.stringify(one));
      });
    });
    return out;
  }

  return {
    GAMES: GAMES,
    BLOCK_SIZE: BLOCK_SIZE,
    Reader: Reader,
    newData: newData,
    merge: merge,
    summary: summary,
    blocks: blocks,
    fields: fields,
    logId: logId,
  };
});
