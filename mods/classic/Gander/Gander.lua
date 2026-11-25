-- Gander: shows a mob's stats on its tooltip. It reads whatever the game
-- reveals about the mob, remembers it for when the game hides it, and shares
-- what it learns with other players running Gander.
local ADDON, ns = ...

local db              -- GanderDB
local panel, category
local debugging = false
local myName, myRealm
local refreshBestiary = function() end  -- replaced once the window exists
local updateMinimapButton = function() end  -- replaced once the button exists

local function say(fmt, ...) print("|cffc0a060Gander|r: " .. format(fmt, ...)) end
local function dbg(fmt, ...) if debugging then say("|cff999999" .. fmt .. "|r", ...) end end

-- Forever hides some values from addons ("secret values"); they error when
-- compared or joined, so everything read from the game is checked first.
local function isSecret(v) return issecretvalue ~= nil and issecretvalue(v) end

local function commas(n)
  local s = tostring(math.floor(n + 0.5)):reverse():gsub("(%d%d%d)", "%1,"):reverse()
  return (s:gsub("^,", ""))
end

local function round(n) return math.floor(n * 100 + 0.5) / 100 end

-- A number without needless decimals: 2, 2.5, 1.33.
local function compact(n)
  if n == math.floor(n) then return format("%d", n) end
  return (format("%.2f", n):gsub("0+$", ""))
end

---------------------------------------------------------------------------
-- Settings
---------------------------------------------------------------------------
-- The tooltip lines, in the order shown. Each can be switched off.
local LINE_KEYS = { "defense", "armor", "resist", "health", "power", "speed", "damage", "ap", "ranged",
                    "stats", "run", "class", "family", "casts", "id" }
local LINE_LABEL = {
  defense = "Defense", armor = "Armor", resist = "Resistances", health = "Health", power = "Mana / power",
  speed = "Attack speed", damage = "Damage", ap = "Attack power", ranged = "Ranged attack",
  stats = "Strength, agility and other stats", run = "Run speed", class = "Class", family = "Family",
  casts = "What it casts", id = "Mob ID",
}

local function loadSettings()
  GanderDB = type(GanderDB) == "table" and GanderDB or {}
  db = GanderDB
  for _, key in ipairs({ "tooltips", "remembered", "share", "channel", "signedOnly" }) do
    if type(db[key]) ~= "boolean" then db[key] = true end
  end
  if type(db.lines) ~= "table" then db.lines = {} end
  for _, key in ipairs(LINE_KEYS) do
    if type(db.lines[key]) ~= "boolean" then db.lines[key] = true end
  end
  if type(db.mobs) ~= "table" then db.mobs = {} end
  if type(db.autolog) ~= "boolean" then db.autolog = false end
  if type(db.autologWorld) ~= "boolean" then db.autologWorld = false end
  -- The order the lines are shown in: what's saved and still valid, then
  -- any line it doesn't mention, in the usual order.
  local order, placed = {}, {}
  for _, key in ipairs(type(db.order) == "table" and db.order or {}) do
    if type(key) == "string" and LINE_LABEL[key] and not placed[key] then
      order[#order + 1], placed[key] = key, true
    end
  end
  for _, key in ipairs(LINE_KEYS) do
    if not placed[key] then order[#order + 1] = key end
  end
  db.order = order
  if type(db.minimap) ~= "table" then db.minimap = {} end
  if type(db.minimap.hide) ~= "boolean" then db.minimap.hide = false end
  if type(db.minimap.angle) ~= "number" then db.minimap.angle = 225 end  -- bottom left
end

---------------------------------------------------------------------------
-- Reading a mob
--
-- Every stat is a field: a short key, what kind of value it is, and whether
-- it changes with the mob's level. A stat the game doesn't send for mobs
-- reads as zero, so zero means "not sent" and gets no line.
--
-- The last four fields aren't stats: they say which mob this is (its name,
-- creature type, rank and the zone it was first seen in), for the bestiary.
---------------------------------------------------------------------------
local FIELDS = {
  { "def", "n", true }, { "armor", "n", true },
  { "r1", "n", true }, { "r2", "n", true }, { "r3", "n", true },
  { "r4", "n", true }, { "r5", "n", true }, { "r6", "n", true },
  { "hp", "n", true }, { "pow", "n", true }, { "ptype", "token", false },
  { "spd", "n", false }, { "oh", "n", false },
  { "dmin", "n", true }, { "dmax", "n", true }, { "ap", "n", true },
  { "rspd", "n", false }, { "rmin", "n", true }, { "rmax", "n", true },
  { "s1", "n", true }, { "s2", "n", true }, { "s3", "n", true }, { "s4", "n", true }, { "s5", "n", true },
  { "run", "n", false }, { "class", "token", false }, { "fam", "name", false },
  { "n", "text", false }, { "ty", "name", false }, { "rk", "token", false }, { "z", "text", false },
}
local FIELD = {}
for _, f in ipairs(FIELDS) do FIELD[f[1]] = { kind = f[2], perLevel = f[3] } end
local INFO = { n = true, ty = true, rk = true, z = true }
local RANK = { ELITE = "Elite", RARE = "Rare", RAREELITE = "Rare elite", WORLDBOSS = "Boss" }

local MAX_NUMBER = 1000000000
local MAX_TOKEN, MAX_NAME, MAX_TEXT = 20, 24, 40

-- Do these values hold any stat, not just which mob it is?
local function hasStats(values)
  for key in pairs(values) do
    if not INFO[key] then return true end
  end
  return false
end

-- Is value a usable reading for this kind of field? Returns it cleaned up.
local function clean(kind, value)
  if kind == "n" then
    if type(value) == "number" and value > 0 and value <= MAX_NUMBER then return round(value) end
  elseif kind == "token" then
    if type(value) == "string" and #value <= MAX_TOKEN and value:find("^%u+$") then return value end
  elseif type(value) == "string" and value ~= "" and #value <= (kind == "text" and MAX_TEXT or MAX_NAME)
         and not value:find("[,=:|#%c]") then
    return value
  end
end

-- Call a game function that may not exist in this game, or may refuse.
local function results(ok, ...) if ok then return ... end end
local function call(name, ...)
  local fn = _G[name]
  if type(fn) ~= "function" then return end
  return results(pcall(fn, ...))
end

-- Read everything the game says about unit. Returns the live values by
-- field, and which fields the game hid.
local function read(unit)
  local v, hid = {}, {}
  local function take(key, value)
    if isSecret(value) then
      hid[key] = true
    else
      v[key] = clean(FIELD[key].kind, value)
    end
  end
  take("def", (call("UnitDefenseSkill", unit)))
  take("armor", (select(2, call("UnitArmor", unit))))
  for school = 1, 6 do take("r" .. school, (select(2, call("UnitResistance", unit, school)))) end
  take("hp", (call("UnitHealthMax", unit)))
  take("pow", (call("UnitPowerMax", unit)))
  if v.pow then take("ptype", (select(2, call("UnitPowerType", unit)))) end
  local speed, offhand = call("UnitAttackSpeed", unit)
  take("spd", speed); take("oh", offhand)
  local dmin, dmax = call("UnitDamage", unit)
  take("dmin", dmin); take("dmax", dmax)
  take("ap", (call("UnitAttackPower", unit)))
  local rspd, rmin, rmax = call("UnitRangedDamage", unit)
  take("rspd", rspd); take("rmin", rmin); take("rmax", rmax)
  for i = 1, 5 do take("s" .. i, (call("UnitStat", unit, i))) end
  take("run", (select(2, call("GetUnitSpeed", unit))))
  take("class", (select(2, call("UnitClass", unit))))
  take("fam", (call("UnitCreatureFamily", unit)))
  take("n", (call("UnitName", unit)))
  take("ty", (call("UnitCreatureType", unit)))
  local rank = call("UnitClassification", unit)
  if isSecret(rank) then
    hid.rk = true
  elseif type(rank) == "string" and RANK[rank:upper()] then
    v.rk = rank:upper()
  end
  take("z", (call("GetRealZoneText")))
  return v, hid
end

-- Which mob is unit? Returns its creature ID (nil for pets, players and
-- mobs the game won't identify) and its level (nil if hidden).
local function identify(unit)
  local id
  local guid = call("UnitGUID", unit)
  if not isSecret(guid) and type(guid) == "string" then
    local kind, npc = guid:match("^(%a+)%-%d+%-%d+%-%d+%-%d+%-(%d+)%-")
    if kind == "Creature" or kind == "Vehicle" then id = tonumber(npc) end
  end
  local level = call("UnitLevel", unit)
  if isSecret(level) or type(level) ~= "number" then level = nil end
  return id, level
end

---------------------------------------------------------------------------
-- Remembering
--
-- GanderDB.mobs[creatureID] = { lv = { [level] = record }, heard = { ... } }.
-- lv holds what we saw ourselves, heard what other players told us; each
-- record is { at = when it was seen, by = who (heard only), v = values by
-- field }. Kept apart so every value keeps its true source. Whichever was
-- seen most recently is shown, so a change someone else saw replaces our
-- older sighting. A defense of level x 5 isn't stored: it can always be
-- worked out.
---------------------------------------------------------------------------
local queueSend, askAbout  -- set below, in Sharing

local function ruleDefense(level)
  if level and level > 0 then return level * 5 end
end

-- Store what we just saw ourselves, and pass it on if it brought something new.
local function remember(id, level, v)
  if next(v) == nil then return end  -- nothing was visible: not a sighting
  local mob = db.mobs[id]
  local old = mob and mob.lv[level]
  local values, changed = {}, false
  for key, value in pairs(old and old.v or {}) do values[key] = value end
  for key, value in pairs(v) do
    if key == "def" and value == ruleDefense(level) then value = nil end
    if key == "z" and values.z ~= nil then value = nil end  -- the first zone it was seen in is kept
    if value ~= nil and values[key] ~= value then
      values[key] = value
      changed = true
    end
  end
  if next(values) == nil then return end
  if not mob then
    mob = { lv = {}, heard = {} }
    db.mobs[id] = mob
  end
  -- Only seeing its stats counts as a fresh sighting: a hidden mob whose
  -- name still shows mustn't make old stats look newly seen.
  local seenAt = (hasStats(v) or not old) and time() or old.at
  mob.lv[level] = { at = seenAt, v = values }
  if changed then
    dbg("learned mob %d at level %d", id, level)
    if hasStats(values) then queueSend(id, level) end
    refreshBestiary()
  end
end

-- The newest record in records that has this field.
local function newestWith(records, key)
  local best
  for _, rec in pairs(records) do
    if rec.v[key] ~= nil and (not best or rec.at > best.at) then best = rec end
  end
  return best
end

-- Of our record and a heard one, the more recently seen that has this field.
local function newer(ours, theirs, key)
  local a = ours and ours.v[key] ~= nil
  local b = theirs and theirs.v[key] ~= nil
  if a and b then return theirs.at > ours.at and theirs or ours end
  return (a and ours) or (b and theirs) or nil
end

-- What is remembered for this mob at this level: field -> { value, record }.
-- The most recently seen value wins, ours or heard. Fields that don't change
-- with level can also come from another level.
local function recall(id, level)
  local found = {}
  local mob = id and db.mobs[id]
  if not mob then return found end
  local seen, heard = mob.lv or {}, mob.heard or {}
  for key, spec in pairs(FIELD) do
    local rec = level and newer(seen[level], heard[level], key) or nil
    if not rec and not spec.perLevel then
      rec = newer(newestWith(seen, key), newestWith(heard, key), key)
    end
    if rec then found[key] = { rec.v[key], rec } end
  end
  return found
end

-- Are any stats remembered for this mob at this level, ours or heard?
local function knows(id, level)
  local mob = db.mobs[id]
  if not mob then return false end
  local seen, heard = mob.lv and mob.lv[level], mob.heard and mob.heard[level]
  return (seen and hasStats(seen.v)) or (heard and hasStats(heard.v)) or false
end

---------------------------------------------------------------------------
-- Tooltip lines
---------------------------------------------------------------------------
local RESIST = { "Holy", "Fire", "Nature", "Frost", "Shadow", "Arcane" }
local STATS = { "Str", "Agi", "Sta", "Int", "Spi" }
local POWER = { MANA = "Mana", RAGE = "Rage", ENERGY = "Energy", FOCUS = "Focus" }

local function listed(get, prefix, names)
  local parts = {}
  for i, name in ipairs(names) do
    local value = get(prefix .. i)
    if value then parts[#parts + 1] = name .. " " .. commas(value) end
  end
  return table.concat(parts, ", ")
end

local function range(lo, hi) return commas(lo) .. " - " .. commas(hi or lo) end

---------------------------------------------------------------------------
-- What mobs cast
--
-- An addon can't learn this in game on Forever: in a dungeon fight the game
-- hides which spell a mob is casting. So the list ships with the addon, in
-- Abilities.lua, built from combat log files by tools/gander_import.py.
-- Each game has its own list.
---------------------------------------------------------------------------
local GAME = (select(4, GetBuildInfo()) or 0) >= 16000 and "forever" or "classic"
local shipped = type(ns) == "table" and type(ns.abilities) == "table" and ns.abilities[GAME]
if type(shipped) ~= "table" then shipped = {} end
local CASTS_ON_TOOLTIP = 5   -- spells named on a tooltip before "and 2 more"

-- A spell's name: the game's own (in the player's language), or else the
-- English one in the list.
local function spellName(id)
  local name
  if C_Spell and C_Spell.GetSpellName then
    name = results(pcall(C_Spell.GetSpellName, id))
  else
    name = call("GetSpellInfo", id)
  end
  if isSecret(name) or type(name) ~= "string" or name == "" then
    name = type(shipped.spells) == "table" and shipped.spells[id]
  end
  if type(name) ~= "string" or name == "" then name = "Spell #" .. id end
  return name
end

-- "Sleep, Mind Blast" for a mob on the list. Ranks of one spell are named
-- once. With a limit, the rest are counted: "... and 2 more".
local function castsText(id, limit)
  local spells = id and type(shipped.mobs) == "table" and shipped.mobs[id]
  if type(spells) ~= "table" then return end
  local names, listed = {}, {}
  for _, spell in ipairs(spells) do
    local name = spellName(spell)
    if not listed[name] then
      listed[name] = true
      names[#names + 1] = name
    end
  end
  if #names == 0 then return end
  if limit and #names > limit then
    return table.concat(names, ", ", 1, limit) .. " and " .. (#names - limit) .. " more"
  end
  return table.concat(names, ", ")
end

-- Each line: its setting key, the fields that make it appear (any one is
-- enough), and how to write it from get(field).
local LINES = {
  { key = "defense", fields = { "def" }, text = function(get) return "Defense", commas(get("def")) end },
  { key = "armor", fields = { "armor" }, text = function(get) return "Armor", commas(get("armor")) end },
  { key = "resist", fields = { "r1", "r2", "r3", "r4", "r5", "r6" },
    text = function(get) return "Resistances", listed(get, "r", RESIST) end },
  { key = "health", fields = { "hp" }, text = function(get) return "Health", commas(get("hp")) end },
  { key = "power", fields = { "pow" },
    text = function(get) return POWER[get("ptype") or ""] or "Power", commas(get("pow")) end },
  { key = "speed", fields = { "spd" }, text = function(get)
      local s = format("%.2f", get("spd")):gsub("0$", "")
      if get("oh") then s = s .. " / " .. format("%.2f", get("oh")):gsub("0$", "") end
      return "Attack speed", s
    end },
  { key = "damage", fields = { "dmin" }, text = function(get) return "Damage", range(get("dmin"), get("dmax")) end },
  { key = "ap", fields = { "ap" }, text = function(get) return "Attack power", commas(get("ap")) end },
  { key = "ranged", fields = { "rspd" }, text = function(get)
      local s = "speed " .. format("%.2f", get("rspd")):gsub("0$", "")
      if get("rmin") then s = range(get("rmin"), get("rmax")) .. ", " .. s end
      return "Ranged", s
    end },
  { key = "stats", fields = { "s1", "s2", "s3", "s4", "s5" },
    text = function(get) return "Stats", listed(get, "s", STATS) end },
  { key = "run", fields = { "run" },
    text = function(get) return "Run speed", format("%d%%", math.floor(get("run") / 7 * 100 + 0.5)) end },
  { key = "class", fields = { "class" }, text = function(get)
      local token = get("class")
      local names = LOCALIZED_CLASS_NAMES_MALE
      return "Class", names and names[token] or (token:sub(1, 1) .. token:sub(2):lower())
    end },
  { key = "family", fields = { "fam" }, text = function(get) return "Family", get("fam") end },
}

local LINE = {}
for _, line in ipairs(LINES) do LINE[line.key] = line end

local LABEL, VALUE, GREY = "|cffffd100", "|cffffffff", "|cff999999"

local function source(rec)
  if rec.by then return "from " .. rec.by end
  return "seen " .. tonumber(date("%d", rec.at)) .. " " .. date("%b", rec.at)
end

local function firstOf(fields, has)
  for _, key in ipairs(fields) do
    if has(key) then return key end
  end
end

-- The lines for a mob with these live values, and what is remembered.
local function linesFor(v, id, level)
  local lines = {}
  local mem = db.remembered and recall(id, level) or {}
  local function live(key) return v[key] end
  local function kept(key) return mem[key] and mem[key][1] end
  for _, lineKey in ipairs(db.order) do
    local line = LINE[lineKey]
    if lineKey == "casts" then
      local casts = db.lines.casts and castsText(id, CASTS_ON_TOOLTIP)
      if casts then lines[#lines + 1] = LABEL .. "Casts:|r " .. VALUE .. casts .. "|r" end
    elseif lineKey == "id" then
      -- The creature ID: the number the game, this addon's lists and
      -- database sites all know the mob by.
      if db.lines.id and id then lines[#lines + 1] = LABEL .. "ID:|r " .. VALUE .. id .. "|r" end
    elseif db.lines[line.key] then
      if firstOf(line.fields, live) then
        local label, value = line.text(live)
        lines[#lines + 1] = LABEL .. label .. ":|r " .. VALUE .. value .. "|r"
      else
        local key = firstOf(line.fields, kept)
        if key then
          local label, value = line.text(kept)
          lines[#lines + 1] = GREY .. label .. ": " .. value .. " (" .. source(mem[key][2]) .. ")|r"
        elseif line.key == "defense" and ruleDefense(level) then
          lines[#lines + 1] = LABEL .. "Defense:|r " .. VALUE .. commas(ruleDefense(level)) .. "|r"
        end
      end
    end
  end
  return lines
end

local function isPlayer(unit)
  local p = call("UnitIsPlayer", unit)
  return isSecret(p) or p
end

-- Look at a mob: remember what the game shows, and return its tooltip lines.
-- A mob in a fight isn't remembered, since debuffs and enrages change its
-- stats for a while.
local function look(unit)
  local v, hid = read(unit)
  local id, level = identify(unit)
  if id and level then
    local fighting = call("UnitAffectingCombat", unit)
    if not isSecret(fighting) and not fighting then remember(id, level, v) end
    -- The game is hiding this mob's stats and nothing is known: ask around.
    if next(hid) ~= nil and not knows(id, level) then askAbout(id, level) end
  end
  return linesFor(v, id, level)
end

local doneFor = setmetatable({}, { __mode = "k" })  -- tooltips that already have our lines

local function addLines(tip, once)
  if not db or not tip.GetUnit then return end
  local _, unit = tip:GetUnit()
  if isSecret(unit) or type(unit) ~= "string" then
    if tip ~= GameTooltip or not UnitExists("mouseover") then return end
    unit = "mouseover"
  end
  if isPlayer(unit) then return end
  if once then
    if doneFor[tip] then return end
    doneFor[tip] = true
  end
  local lines = look(unit)
  if not db.tooltips then return end
  for _, line in ipairs(lines) do tip:AddLine(line) end
end

local function hookTooltips()
  local types = Enum and Enum.TooltipDataType
  if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and types and types.Unit then
    TooltipDataProcessor.AddTooltipPostCall(types.Unit, function(tip) pcall(addLines, tip) end)
    return
  end
  GameTooltip:HookScript("OnTooltipSetUnit", function(self) pcall(addLines, self, true) end)
  GameTooltip:HookScript("OnTooltipCleared", function(self) doneFor[self] = nil end)
end

---------------------------------------------------------------------------
-- Sharing with other players
--
-- Hidden addon messages, prefix "Gander", each starting with protocol "2"
-- and ending with a signature:
--   2:M:<creatureID>:<level>:<field>=<value>,...[,t=<seconds since seen>]#<signature>
--   2:Q:<creatureID>:<level>#<signature>      who has seen this mob?
-- The signature is a keyed checksum of the rest. A message without the right
-- one is ignored, so stats typed by hand with /run aren't taken. The key is
-- in this file, so it only stops the casual case: someone who copies this
-- code can still sign what they like. Versions before 0.4.0 spoke protocol
-- "1", unsigned. With the "signed only" setting off, unsigned messages of
-- either protocol are taken as well; what we send is always signed.
-- A mob is sent to guild and group a few seconds after learning something
-- new, one at a time, and never while chat is locked or a boss fight is on.
-- Only what we saw ourselves is sent, so nothing echoes back and forth.
-- "t" says how long ago it was seen (left out when under a minute), so the
-- receiver can keep whichever sighting is newest; clocks needn't agree.
-- Fields a newer version adds are ignored by this one.
--
-- The same messages also go to a custom chat channel, "Gander", which every
-- player running Gander joins: that reaches people outside guild and group.
-- The channel is joined a while after login so it doesn't take the number
-- of one of the game's own channels.
--
-- A question is asked when the game hides a mob's stats and nothing is
-- remembered for it. Whoever saw that mob answers after a short random
-- wait, the way the question came, unless someone else answers first.
---------------------------------------------------------------------------
local PREFIX = "Gander"
local CHANNEL = "Gander"
local JOIN_DELAY = 30  -- seconds after login before joining the channel
local CHANNEL_TRIES = 3  -- times a throttled channel message is tried again
local SEND_DELAY = 3   -- seconds after learning before the first send
local SEND_GAP = 2     -- seconds between mobs
local SEND_RETRY = 5   -- seconds before trying again while chat is locked
local MAX_MESSAGE = 255
local SIGN_KEY = "Gander:honk:4d7e1c9a"
local SIGN_LENGTH = 9  -- "#" and eight hex digits
local MAX_ID, MAX_LEVEL = 9999999, 255
local MAX_AGE = 10 * 365 * 86400  -- a sighting older than this is nonsense
local FRESH = 60                  -- a sighting younger than this is sent without its age
local ASK_AGAIN = 600             -- seconds before asking about the same mob again
local ANSWER_MIN, ANSWER_MAX = 1, 4  -- seconds to wait before answering a question
local ANSWER_CAP, ANSWER_WINDOW = 10, 60  -- at most this many answers in this many seconds

local ECHO_WINDOW = 15 -- seconds in which our own message can come back to us

local queue, queued, sendPending = {}, {}, false
local sentAt = {}      -- message text -> when we sent it
local channelRefused = false  -- the game won't take addon messages on channels
local asked = {}       -- "id:level" -> when we, or someone else, last asked about it
local toldAt = {}      -- "id:level" -> when someone else last told everyone about it
local answering = {}   -- "id:level" -> true while an answer of ours is waiting
local answerTimes = {} -- when we sent our recent answers

local RESULT = Enum and Enum.SendAddonMessageResult or {}
local THROTTLED = { [RESULT.AddonMessageThrottle or 3] = true, [RESULT.ChannelThrottle or 8] = true }
local NOT_JOINED = RESULT.InvalidChannel or 7

local function channelWanted() return db.share and db.channel end

-- Our number for the channel, or nil if we aren't in it.
local function channelNumber()
  local number = call("GetChannelName", CHANNEL)
  if isSecret(number) or type(number) ~= "number" or number <= 0 then return end
  return number
end

local function joinChannel()
  if not channelWanted() or channelNumber() then return end
  call("JoinTemporaryChannel", CHANNEL)
  dbg("joined the %s channel", CHANNEL)
end

local function leaveChannel()
  if channelNumber() then call("LeaveChannelByName", CHANNEL) end
end

-- Did the channel already tell us everything in values for this mob?
local function channelKnows(mob, level, values)
  local told = mob.heard and mob.heard[level]
  if not (told and told.ch) then return false end
  for key, value in pairs(values) do
    if told.v[key] ~= value then return false end
  end
  return true
end

-- Send text to the channel. Returns "sent", "retry" (throttled) or nil.
local function sendToChannel(text)
  if channelRefused or not channelWanted() then return end
  local number = channelNumber()
  if not number then return end
  local ok, result = pcall(C_ChatInfo.SendAddonMessage, PREFIX, text, "CHANNEL", number)
  if not ok then return end
  if result == nil or result == true or result == (RESULT.Success or 0) then return "sent" end
  if THROTTLED[result] then return "retry" end
  if result ~= NOT_JOINED and result ~= false then
    channelRefused = true
    dbg("the game refuses addon messages on chat channels (result %s); sharing with guild and group only", tostring(result))
  end
end

local function chatLocked()
  if C_ChatInfo and C_ChatInfo.InChatMessagingLockdown and C_ChatInfo.InChatMessagingLockdown() then return true end
  local fighting = (C_InstanceEncounter and C_InstanceEncounter.IsEncounterInProgress) or IsEncounterInProgress
  return fighting ~= nil and fighting() and true or false
end

-- A keyed checksum of payload, as eight hex digits. Plain arithmetic, so it
-- gives the same answer in both games without the bit library.
local function signature(payload)
  local h, text = 7, SIGN_KEY .. payload .. SIGN_KEY
  for i = 1, #text do h = (h * 131 + text:byte(i)) % 2147483647 end
  return format("%08x", h)
end

local function signed(payload) return payload .. "#" .. signature(payload) end

-- The payload of a properly signed message, or nil.
local function verified(text)
  local payload, sig = text:match("^(.*)#(%x+)$")
  if payload and sig == signature(payload) then return payload end
end

-- The message for a mob seen age seconds ago.
local function encode(id, level, v, age)
  local parts = {}
  for _, f in ipairs(FIELDS) do
    local value = v[f[1]]
    if value ~= nil then parts[#parts + 1] = f[1] .. "=" .. (f[2] == "n" and compact(value) or value) end
  end
  local head = format("2:M:%d:%d:", id, level)
  local tail = (age and age >= FRESH) and format(",t=%d", math.min(age, MAX_AGE)) or ""
  local text = head .. table.concat(parts, ",") .. tail
  while #text > MAX_MESSAGE - SIGN_LENGTH and #parts > 1 do
    tremove(parts)
    text = head .. table.concat(parts, ",") .. tail
  end
  return text
end

-- Remember that we sent text, so its copy coming back isn't taken as news.
local function noteSent(text)
  for old, at in pairs(sentAt) do
    if GetTime() - at > ECHO_WINDOW then sentAt[old] = nil end
  end
  sentAt[text] = GetTime()
end

local function flush()
  sendPending = false
  if #queue == 0 then return end
  if not db.share then
    queue, queued = {}, {}
    return
  end
  if chatLocked() then
    sendPending = true
    C_Timer.After(SEND_RETRY, flush)
    return
  end
  local item = tremove(queue, 1)
  queued[item.key] = nil
  local retry = false
  local mob = db.mobs[item.id]
  local rec = mob and mob.lv[item.level]
  local text
  if item.q then
    text = format("2:Q:%d:%d", item.id, item.level)
  elseif rec then
    text = encode(item.id, item.level, rec.v, time() - rec.at)
  end
  if text and C_ChatInfo and C_ChatInfo.SendAddonMessage then
    local wire = signed(text)
    noteSent(wire)
    local went, note = {}, nil  -- where it went, and why not the channel
    if not item.channelOnly then
      if IsInGuild() then
        pcall(C_ChatInfo.SendAddonMessage, PREFIX, wire, "GUILD")
        went[#went + 1] = "guild"
      end
      local group = IsInRaid() and "RAID" or (IsInGroup() and "PARTY") or nil
      if group then
        pcall(C_ChatInfo.SendAddonMessage, PREFIX, wire, group)
        went[#went + 1] = group:lower()
      end
    end
    if not channelWanted() then
      note = "the Gander channel is switched off"
    elseif channelRefused then
      note = "the game refuses channel messages"
    elseif not channelNumber() then
      note = "not in the Gander channel yet"
    elseif rec and not item.q and channelKnows(mob, item.level, rec.v) then
      note = "the Gander channel already had it"
    else
      local outcome = sendToChannel(wire)
      if outcome == "sent" then
        went[#went + 1] = "the Gander channel"
      elseif outcome == "retry" then
        -- Throttled: try the channel again later, without repeating the rest.
        item.tries = (item.tries or 0) + 1
        if item.tries <= CHANNEL_TRIES then
          item.channelOnly = true
          queued[item.key] = true
          queue[#queue + 1] = item
          retry = true
        end
        note = retry and "the Gander channel is throttled, trying again soon" or "the Gander channel is throttled, gave up"
      else
        note = "the Gander channel didn't take it"
      end
    end
    local what = item.q and format("asked about mob %d (level %d):", item.id, item.level) or "shared"
    if #went > 0 then
      dbg("%s %s with %s%s", what, text, table.concat(went, ", "), note and (" (" .. note .. ")") or "")
    else
      dbg("%s %s: shared with nobody (%s)", what, text, note or "no guild or group")
    end
  end
  if #queue > 0 then
    sendPending = true
    C_Timer.After(retry and SEND_RETRY or SEND_GAP, flush)
  end
end

-- Queue a mob we saw (or, with question, a question about one) for sending.
queueSend = function(id, level, question)
  if not db.share then return end
  local key = (question and "q:" or "") .. id .. ":" .. level
  if queued[key] then
    for _, item in ipairs(queue) do
      if item.key == key then item.channelOnly, item.tries = nil, nil end
    end
  else
    queued[key] = true
    queue[#queue + 1] = { key = key, id = id, level = level, q = question or nil }
  end
  if not sendPending then
    sendPending = true
    C_Timer.After(SEND_DELAY, flush)
  end
end

-- Ask who has seen this mob, unless it was asked about a short while ago.
askAbout = function(id, level)
  if not db.share then return end
  local key = id .. ":" .. level
  if asked[key] and GetTime() - asked[key] < ASK_AGAIN then return end
  asked[key] = GetTime()
  queueSend(id, level, true)
end

local function isMe(sender)
  local name, realm = sender:match("^([^-]+)%-?(.*)$")
  return name == myName and (realm == "" or realm == myRealm)
end

-- Answer a question about a mob we saw ourselves, the way the question came.
local function answer(key, id, level, route, questionAt)
  answering[key] = nil
  if not db.share or chatLocked() then return end
  if toldAt[key] and toldAt[key] > questionAt then  -- told after the question: that was its answer
    dbg("someone else answered about mob %d first", id)
    return
  end
  local mob = db.mobs[id]
  local rec = mob and mob.lv and mob.lv[level]
  if not (rec and hasStats(rec.v) and C_ChatInfo and C_ChatInfo.SendAddonMessage) then return end
  local wire = signed(encode(id, level, rec.v, time() - rec.at))
  noteSent(wire)
  if route == "CHANNEL" then
    sendToChannel(wire)
  else
    pcall(C_ChatInfo.SendAddonMessage, PREFIX, wire, route)
  end
  answerTimes[#answerTimes + 1] = GetTime()
  dbg("answered a question about mob %d (level %d) on %s", id, level, route:lower())
end

-- Someone asked who has seen a mob. Wait a random moment, so that of
-- everyone who could answer only the first does.
local function onQuestion(id, level, route, sender)
  local key = id .. ":" .. level
  asked[key] = GetTime()  -- no need for us to ask as well
  local mob = db.mobs[id]
  local ours = mob and mob.lv and mob.lv[level]
  if not (ours and hasStats(ours.v)) or answering[key] then return end
  if route == "GUILD" then
    if not IsInGuild() then return end
  elseif route == "PARTY" or route == "RAID" then
    if not IsInGroup() then return end
  elseif route ~= "CHANNEL" then
    return
  end
  -- Never more than a few answers a minute, however many questions arrive.
  while answerTimes[1] and GetTime() - answerTimes[1] > ANSWER_WINDOW do tremove(answerTimes, 1) end
  local waiting = 0
  for _ in pairs(answering) do waiting = waiting + 1 end
  if #answerTimes + waiting >= ANSWER_CAP then return end
  answering[key] = true
  local questionAt = GetTime()
  dbg("%s asked about mob %d (level %d)", sender, id, level)
  C_Timer.After(ANSWER_MIN + math.random() * (ANSWER_MAX - ANSWER_MIN), function()
    answer(key, id, level, route, questionAt)
  end)
end

local function onAddonMessage(prefix, text, channel, sender)
  if isSecret(prefix) or prefix ~= PREFIX or not db.share then return end
  if isSecret(text) or isSecret(sender) or type(text) ~= "string" or type(sender) ~= "string" then return end
  -- The game sends our own guild and group messages back to us. The sender
  -- name can't be relied on to spot them (Forever names can have a surname,
  -- and realms are written several ways), so the text we just sent is.
  local mine = sentAt[text]
  if (mine and GetTime() - mine <= ECHO_WINDOW) or isMe(sender) then return end
  local payload = verified(text)
  if not payload then
    if db.signedOnly then
      dbg("ignored a message from %s that isn't signed by Gander", sender)
      return
    end
    payload = text:match("^(.*)#[^#]*$") or text  -- drop a signature that didn't check out
    dbg("taking an unsigned message from %s (signed only is off)", sender)
  end
  local kind, id, level, body = payload:match("^[12]:(%u):(%d+):(%-?%d+):?(.*)$")
  id, level = tonumber(id), tonumber(level)
  if not id or id < 1 or id > MAX_ID then return end
  if not (level == -1 or (level >= 1 and level <= MAX_LEVEL)) then return end
  if kind == "Q" then
    if body == "" then onQuestion(id, level, channel, sender) end
    return
  end
  if kind ~= "M" or body == "" then return end
  local values, age = {}, 0
  for key, raw in body:gmatch("(%w+)=([^,]*)") do
    local spec = FIELD[key]
    if spec then
      if spec.kind == "n" then raw = raw:find("^%d+%.?%d*$") and tonumber(raw) or nil end
      values[key] = clean(spec.kind, raw)
    elseif key == "t" then
      age = raw:find("^%d+$") and tonumber(raw) or -1
    end
  end
  if next(values) == nil or age < 0 or age > MAX_AGE then return end
  local who = sender:match("^[^-]+")
  dbg("heard mob %d (level %d) from %s", id, level, sender)
  toldAt[id .. ":" .. level] = GetTime()
  local mob = db.mobs[id]
  if not mob then
    mob = { lv = {}, heard = {} }
    db.mobs[id] = mob
  end
  mob.heard = mob.heard or {}
  local seenAt = time() - age
  local told = mob.heard[level]
  if told and told.at > seenAt then return end  -- we already heard of a newer sighting
  mob.heard[level] = { at = seenAt, by = who, v = values, ch = (channel == "CHANNEL") or nil }
  refreshBestiary()
end

---------------------------------------------------------------------------
-- Combat logging in dungeons
--
-- The game can write its combat log to a file (Logs\WoWCombatLog...), and
-- that file is where the list of what mobs cast comes from. With the setting
-- on, Gander switches that logging on inside a dungeon or raid and off again
-- on the way out. It doesn't bother once the list has plenty from an
-- instance. A second setting keeps it on in the open world as well, where
-- the game hides mob spells from addons just the same; there's no "plenty"
-- out there, so that one logs until it's unticked. Battlegrounds and arenas
-- are never logged. Gander never touches logging the player switched on
-- themselves: GanderDB.logging is set only while logging that Gander started
-- is running.
---------------------------------------------------------------------------
local AUTOLOG_ENOUGH = 90   -- minutes of logged fighting after which an instance is covered

local function isLogging()
  local on = call("LoggingCombat")
  return not isSecret(on) and on and true or false
end

local function checkLogging()
  if not db then return end
  local inside, kind = call("IsInInstance")
  local name, _, _, _, _, _, _, instanceID = call("GetInstanceInfo")
  if isSecret(inside) or isSecret(kind) or isSecret(instanceID) then return end
  if isSecret(name) or type(name) ~= "string" then name = "this instance" end
  local dungeon = inside and (kind == "party" or kind == "raid") or false
  local wanted = false
  if db.autolog and dungeon then
    wanted = true
    if type(shipped.instances) == "table" and (shipped.instances[instanceID] or 0) >= AUTOLOG_ENOUGH then
      dbg("not logging %s: the list already has plenty from here", name)
      wanted = false
    end
  elseif db.autolog and db.autologWorld and not inside then
    wanted = true
  end
  if wanted then
    if isLogging() then return end
    call("LoggingCombat", true)
    if isLogging() then
      db.logging = true
      if dungeon then
        say("logging combat in %s to a file, to learn what its mobs cast. It stops when you leave.", name)
      else
        say("logging combat to a file, to learn what mobs cast. It stays on until you untick the setting.")
      end
    else
      say("couldn't switch combat logging on here.")
    end
  elseif db.logging then
    db.logging = nil
    if isLogging() then
      call("LoggingCombat", false)
      say("combat logging is off again.")
    end
  end
end

---------------------------------------------------------------------------
-- Settings panel (Options > AddOns > Gander)
---------------------------------------------------------------------------
local function countMobs()
  local n = 0
  for _ in pairs(db.mobs) do n = n + 1 end
  return n
end

-- The Stat order page: one row per line, in the order they're shown. A row
-- is dragged up or down to move its line, and its tick shows or hides it.
local ORDER_ROW = 26      -- height of a row
local orderPage, orderCategory
local dragging            -- the position of the row being dragged

local function drawOrder()
  if not orderPage then return end
  for i, row in ipairs(orderPage.rows) do
    local key = db.order[i]
    row.key = key
    row.number:SetText(i .. ".")
    row.label:SetText(LINE_LABEL[key])
    row.check:SetChecked(db.lines[key])
    row:SetAlpha(dragging == i and 0.4 or 1)
    panel.checks[key] = row.check
  end
end

-- The position the cursor is over, from 1 to the number of lines.
local function dropPosition()
  local _, y = GetCursorPosition()
  local scale = orderPage.list:GetEffectiveScale() or 1
  local top = orderPage.list:GetTop()
  if not (y and top) or scale == 0 then return dragging end
  local position = math.floor((top - y / scale) / ORDER_ROW) + 1
  return math.max(1, math.min(#db.order, position))
end

local function endDrag()
  dragging = nil
  orderPage:SetScript("OnUpdate", nil)
  orderPage.marker:Hide()
  drawOrder()
end

local function refreshPanel()
  for _, key in ipairs({ "tooltips", "remembered", "share", "channel", "signedOnly" }) do
    panel.checks[key]:SetChecked(db[key])
  end
  panel.checks.minimap:SetChecked(not db.minimap.hide)
  panel.checks.autolog:SetChecked(db.autolog)
  panel.checks.autologWorld:SetChecked(db.autologWorld)
  drawOrder()
  local n = countMobs()
  panel.count:SetText(format("Remembering %s %s.", commas(n), n == 1 and "mob" or "mobs"))
end

local function addCheck(key, label, x, y, onClick)
  local check = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
  check:SetPoint("TOPLEFT", x, y)
  check:SetScript("OnClick", function(self) onClick(self:GetChecked() and true or false) end)
  local text = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  text:SetPoint("LEFT", check, "RIGHT", 4, 0)
  text:SetText(label)
  panel.checks[key] = check
end

-- Open the settings window at one of our pages. The game blocks addons from
-- opening it during combat (and blames the addon), so in a fight the page
-- waits and opens when the fight ends.
local waitingPage

local function openPage(page, missing)
  if not page then
    say(missing)
  elseif InCombatLockdown() then
    waitingPage = page
    say("the settings can't be opened in a fight. They'll open when it ends.")
  else
    waitingPage = nil
    pcall(Settings.OpenToCategory, page:GetID())
  end
end

local function fightEnded()
  local page = waitingPage
  waitingPage = nil
  if page then openPage(page) end
end

local function buildOrderPage()
  orderPage = CreateFrame("Frame", "GanderOrderPanel")
  orderPage.rows, orderPage.rowHeight = {}, ORDER_ROW

  local title = orderPage:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 16, -16)
  title:SetText("Gander: stat order")
  local intro = orderPage:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  intro:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -8)
  intro:SetText("Drag a line up or down to change where it appears on the tooltip and in the bestiary. Untick a line to hide it.")

  orderPage.list = CreateFrame("Frame", nil, orderPage)
  orderPage.list:SetPoint("TOPLEFT", 16, -64)
  orderPage.list:SetSize(420, #LINE_KEYS * ORDER_ROW)
  for i = 1, #LINE_KEYS do
    local row = CreateFrame("Button", nil, orderPage.list)
    row.index = i
    row:SetSize(420, ORDER_ROW)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * ORDER_ROW)
    row:RegisterForDrag("LeftButton")
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.number = row:CreateFontString(nil, "ARTWORK", "GameFontDisable")
    row.number:SetPoint("LEFT", 4, 0)
    row.check = CreateFrame("CheckButton", nil, row, "UICheckButtonTemplate")
    row.check:SetSize(24, 24)
    row.check:SetPoint("LEFT", 32, 0)
    row.check:SetScript("OnClick", function(self) db.lines[row.key] = self:GetChecked() and true or false end)
    row.label = row:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    row.label:SetPoint("LEFT", 62, 0)
    row:SetScript("OnDragStart", function(self)
      dragging = self.index
      drawOrder()
      -- While dragging, a gold line marks where the row will land.
      orderPage:SetScript("OnUpdate", function()
        local to = dropPosition()
        local edge = (to > dragging) and to or (to - 1)
        orderPage.marker:ClearAllPoints()
        orderPage.marker:SetPoint("TOPLEFT", orderPage.list, "TOPLEFT", 0, -edge * ORDER_ROW)
        orderPage.marker:Show()
      end)
    end)
    row:SetScript("OnDragStop", function()
      if dragging then
        local to = dropPosition()
        tinsert(db.order, to, tremove(db.order, dragging))
      end
      endDrag()
    end)
    orderPage.rows[i] = row
  end
  orderPage.marker = orderPage.list:CreateTexture(nil, "OVERLAY")
  orderPage.marker:SetColorTexture(1, 0.82, 0, 0.9)
  orderPage.marker:SetSize(420, 2)
  orderPage.marker:Hide()

  orderPage.reset = CreateFrame("Button", nil, orderPage, "UIPanelButtonTemplate")
  orderPage.reset:SetSize(120, 22)
  orderPage.reset:SetPoint("TOPLEFT", 16, -64 - #LINE_KEYS * ORDER_ROW - 12)
  orderPage.reset:SetText("Reset order")
  orderPage.reset:SetScript("OnClick", function()
    db.order = {}
    for i, key in ipairs(LINE_KEYS) do db.order[i] = key end
    drawOrder()
  end)

  orderPage:SetScript("OnShow", refreshPanel)
  orderPage:SetScript("OnHide", function() if dragging then endDrag() end end)
end

local function buildPanel()
  panel = CreateFrame("Frame", "GanderPanel")
  panel.checks = {}

  local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 16, -16)
  title:SetText("Gander")
  local intro = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  intro:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -8)
  intro:SetText("Shows a mob's stats on its tooltip. A line only appears when the game reveals that stat, or someone running Gander has seen it.")

  addCheck("tooltips", "Show on mob tooltips", 16, -64, function(on) db.tooltips = on end)
  addCheck("remembered", "Show remembered values (in grey) when the live ones are hidden", 16, -92,
           function(on) db.remembered = on end)
  local function channelChanged()
    if channelWanted() then joinChannel() else leaveChannel() end
  end
  addCheck("share", "Share what I learn with my guild and group, and use what they share", 16, -120,
           function(on) db.share = on; channelChanged() end)
  addCheck("channel", "Also share on the Gander chat channel, with everyone running Gander", 40, -148,
           function(on) db.channel = on; channelChanged() end)

  addCheck("signedOnly", "Only accept signed messages (ignores ones typed by hand, or from before 0.4.0)", 40, -176,
           function(on) db.signedOnly = on end)

  addCheck("minimap", "Show a minimap button that opens the bestiary", 16, -204, function(on)
    db.minimap.hide = not on
    updateMinimapButton()
  end)

  addCheck("autolog", "Log combat to a file in dungeons and raids, to learn what their mobs cast", 16, -232,
           function(on)
             db.autolog = on
             checkLogging()
           end)

  addCheck("autologWorld", "Also in the open world (logs every fight until this is unticked)", 40, -260,
           function(on)
             db.autologWorld = on
             checkLogging()
           end)

  local note = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  note:SetPoint("TOPLEFT", 20, -304)
  note:SetText("Which lines show, and in what order, is on its own page:")
  panel.orderButton = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
  panel.orderButton:SetSize(120, 22)
  panel.orderButton:SetPoint("TOPLEFT", 20, -326)
  panel.orderButton:SetText("Stat order...")
  panel.orderButton:SetScript("OnClick", function()
    openPage(orderCategory, "the Stat order page isn't available here.")
  end)

  panel.count = panel:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  panel.count:SetPoint("TOPLEFT", 20, -366)

  buildOrderPage()
  panel:SetScript("OnShow", refreshPanel)

  if Settings and Settings.RegisterCanvasLayoutCategory then
    category = Settings.RegisterCanvasLayoutCategory(panel, "Gander")
    Settings.RegisterAddOnCategory(category)
    if Settings.RegisterCanvasLayoutSubcategory then
      orderCategory = Settings.RegisterCanvasLayoutSubcategory(category, orderPage, "Stat order")
    end
  end
end

---------------------------------------------------------------------------
-- The bestiary (/gander): every remembered mob, and all that's known of it
---------------------------------------------------------------------------
local ROWS = 10           -- mobs visible at once
local WHEEL_STEP = 3      -- rows per notch of the mouse wheel
local SHOW = { { "all", "All" }, { "seen", "Seen by me" }, { "heard", "Heard" } }
local bestiary
local showing, searching, offset, selected = "all", "", 0, nil

local function openSettings()
  openPage(category, "the settings window isn't available here.")
end

-- The newest value of one field for a mob, from any level, ours or heard.
local function info(mob, key)
  local rec = newer(newestWith(mob.lv or {}, key), newestWith(mob.heard or {}, key), key)
  return rec and rec.v[key]
end

-- "30", "30-32" or "??" for the levels a mob is known at.
local function levelText(mob)
  local lo, hi
  for _, records in ipairs({ mob.lv or {}, mob.heard or {} }) do
    for level in pairs(records) do
      if level > 0 then
        lo = math.min(lo or level, level)
        hi = math.max(hi or level, level)
      end
    end
  end
  if not lo then return "??" end
  return lo == hi and tostring(lo) or (lo .. "-" .. hi)
end

-- Every remembered mob as a list entry, named ones first by name.
local function allEntries()
  local list = {}
  for id, mob in pairs(db.mobs) do
    local name, rank = info(mob, "n"), info(mob, "rk")
    local seen = next(mob.lv or {}) ~= nil
    list[#list + 1] = {
      id = id, mob = mob, named = name ~= nil, seen = seen,
      name = (name or ("Mob #" .. id)) .. (rank and RANK[rank] and (" (" .. RANK[rank] .. ")") or ""),
      level = levelText(mob), kind = info(mob, "ty") or "", zone = info(mob, "z") or "",
    }
  end
  table.sort(list, function(a, b)
    if a.named ~= b.named then return a.named end
    if a.named and a.name:lower() ~= b.name:lower() then return a.name:lower() < b.name:lower() end
    return a.id < b.id
  end)
  return list
end

local function matches(entry)
  if showing == "seen" and not entry.seen then return false end
  if showing == "heard" and entry.seen then return false end
  if searching == "" then return true end
  local haystack = (entry.name .. "\n" .. entry.zone .. "\n" .. entry.kind .. "\n" .. entry.id):lower()
  return haystack:find(searching:lower(), 1, true) ~= nil
end

local function when(at) return tonumber(date("%d", at)) .. " " .. date("%b", at) end

-- One record's stats on a line: "Defense 150 · Attack speed 1.3".
local function statsLine(level, rec)
  local parts = {}
  local function get(key) return rec.v[key] end
  for _, lineKey in ipairs(db.order) do
    local line = LINE[lineKey]
    if line and line.key ~= "family" then
      if firstOf(line.fields, get) then
        local label, value = line.text(get)
        parts[#parts + 1] = label .. " " .. value
      elseif line.key == "defense" and ruleDefense(level) then
        parts[#parts + 1] = "Defense " .. commas(ruleDefense(level))
      end
    end
  end
  if not hasStats(rec.v) then parts[#parts + 1] = "(its stats were hidden)" end
  return table.concat(parts, "  ·  ")
end

-- Everything known about one mob, as text for the lower pane.
local function detailText(id)
  local mob = id and db.mobs[id]
  if not mob then return GREY .. "Click a mob to see everything known about it.|r" end
  local out = {}
  local rank = info(mob, "rk")
  out[#out + 1] = LABEL .. (info(mob, "n") or ("Mob #" .. id)) .. "|r" .. GREY .. "  (id " .. id .. ")|r"
  local about = {}
  local kind, family = info(mob, "ty"), info(mob, "fam")
  if kind or family then about[#about + 1] = (kind or "") .. ((kind and family) and ", " or "") .. (family or "") end
  if rank and RANK[rank] then about[#about + 1] = RANK[rank] end
  if info(mob, "z") then about[#about + 1] = info(mob, "z") end
  if #about > 0 then out[#out + 1] = table.concat(about, "  ·  ") end
  local casts = castsText(id)
  if casts then out[#out + 1] = LABEL .. "Casts:|r " .. VALUE .. casts .. "|r" end
  local levels = {}
  for _, records in ipairs({ mob.lv or {}, mob.heard or {} }) do
    for level in pairs(records) do levels[level] = true end
  end
  local sorted = {}
  for level in pairs(levels) do sorted[#sorted + 1] = level end
  table.sort(sorted)
  for _, level in ipairs(sorted) do
    local title = "Level " .. (level > 0 and level or "??")
    local seen, heard = mob.lv and mob.lv[level], mob.heard and mob.heard[level]
    if seen then
      out[#out + 1] = " "
      out[#out + 1] = LABEL .. title .. " - seen " .. when(seen.at) .. "|r"
      out[#out + 1] = statsLine(level, seen)
    end
    if heard then
      out[#out + 1] = " "
      out[#out + 1] = LABEL .. title .. " - from " .. heard.by .. ", " .. when(heard.at) .. "|r"
      out[#out + 1] = statsLine(level, heard)
    end
  end
  return table.concat(out, "\n")
end

local function drawBestiary()
  local all, shown = allEntries(), {}
  for _, entry in ipairs(all) do
    if matches(entry) then shown[#shown + 1] = entry end
  end
  offset = math.max(0, math.min(offset, #shown - ROWS))
  for i, row in ipairs(bestiary.rows) do
    local entry = shown[offset + i]
    if entry then
      row.id = entry.id
      row.name:SetText(entry.name)
      row.level:SetText(entry.level)
      row.kind:SetText(entry.kind)
      row.zone:SetText(entry.zone)
      row.picked:SetShown(entry.id == selected)
      row:Show()
    else
      row.id = nil
      row:Hide()
    end
  end
  local total = #all
  local noun = total == 1 and "mob" or "mobs"
  if #shown == total then
    bestiary.count:SetText(format("%s %s", commas(total), noun))
  else
    bestiary.count:SetText(format("%s of %s %s", commas(#shown), commas(total), noun))
  end
  for key, button in pairs(bestiary.filters) do button:SetEnabled(key ~= showing) end
  bestiary.detail:SetText(detailText(selected))
  bestiary.child:SetHeight(math.max(10, (bestiary.detail:GetStringHeight() or 0) + 10))
end

local function buildBestiary()
  bestiary = CreateFrame("Frame", "GanderBestiary", UIParent, "BasicFrameTemplateWithInset")
  bestiary:Hide()
  bestiary:SetSize(560, 540)
  bestiary:SetPoint("CENTER")
  bestiary:SetFrameStrata("HIGH")
  bestiary:SetClampedToScreen(true)
  bestiary:SetMovable(true)
  bestiary:EnableMouse(true)
  bestiary:RegisterForDrag("LeftButton")
  bestiary:SetScript("OnDragStart", bestiary.StartMoving)
  bestiary:SetScript("OnDragStop", bestiary.StopMovingOrSizing)
  if type(bestiary.TitleText) == "table" then bestiary.TitleText:SetText("Gander: Bestiary") end
  tinsert(UISpecialFrames, "GanderBestiary")  -- Escape closes it

  local label = bestiary:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  label:SetPoint("TOPLEFT", 16, -36)
  label:SetText("Search")
  bestiary.search = CreateFrame("EditBox", "GanderBestiarySearch", bestiary, "InputBoxTemplate")
  bestiary.search:SetSize(150, 22)
  bestiary.search:SetPoint("LEFT", label, "RIGHT", 12, 0)
  bestiary.search:SetAutoFocus(false)
  bestiary.search:SetMaxLetters(40)
  bestiary.search:SetScript("OnTextChanged", function(self)
    searching, offset = strtrim(self:GetText() or ""), 0
    drawBestiary()
  end)
  bestiary.search:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
  bestiary.search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)

  bestiary.filters = {}
  local x = 232
  for _, f in ipairs(SHOW) do
    local b = CreateFrame("Button", nil, bestiary, "UIPanelButtonTemplate")
    b:SetSize(f[1] == "seen" and 92 or 64, 22)
    b:SetPoint("TOPLEFT", x, -31)
    b:SetText(f[2])
    b:SetScript("OnClick", function()
      showing, offset = f[1], 0
      drawBestiary()
    end)
    bestiary.filters[f[1]] = b
    x = x + (f[1] == "seen" and 96 or 68)
  end
  bestiary.settings = CreateFrame("Button", nil, bestiary, "UIPanelButtonTemplate")
  bestiary.settings:SetSize(76, 22)
  bestiary.settings:SetPoint("TOPRIGHT", -14, -31)
  bestiary.settings:SetText("Settings")
  bestiary.settings:SetScript("OnClick", openSettings)

  local columns = { name = 20, level = 280, kind = 330, zone = 420 }
  for key, title in pairs({ name = "Name", level = "Level", kind = "Type", zone = "Zone" }) do
    local h = bestiary:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
    h:SetPoint("TOPLEFT", columns[key], -64)
    h:SetText(title)
  end
  bestiary.count = bestiary:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  bestiary.count:SetPoint("TOPRIGHT", -18, -64)

  -- The list: fixed rows, moved through with the mouse wheel.
  bestiary.list = CreateFrame("Frame", nil, bestiary)
  bestiary.list:SetPoint("TOPLEFT", 12, -80)
  bestiary.list:SetSize(536, ROWS * 20)
  bestiary.list:EnableMouseWheel(true)
  bestiary.list:SetScript("OnMouseWheel", function(_, delta)
    offset = offset - delta * WHEEL_STEP
    drawBestiary()
  end)
  bestiary.rows = {}
  for i = 1, ROWS do
    local row = CreateFrame("Button", nil, bestiary.list)
    row:SetSize(536, 20)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * 20)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.picked = row:CreateTexture(nil, "BACKGROUND")
    row.picked:SetAllPoints()
    row.picked:SetColorTexture(1, 0.82, 0, 0.18)
    row.picked:Hide()
    for key, font in pairs({ name = "GameFontHighlight", level = "GameFontHighlight",
                             kind = "GameFontHighlightSmall", zone = "GameFontHighlightSmall" }) do
      row[key] = row:CreateFontString(nil, "ARTWORK", font)
      row[key]:SetPoint("LEFT", columns[key] - 12, 0)
      row[key]:SetJustifyH("LEFT")
    end
    row.name:SetWidth(252)
    row.zone:SetWidth(126)
    row:SetScript("OnClick", function(self)
      selected = self.id
      drawBestiary()
    end)
    bestiary.rows[i] = row
  end

  -- Everything known about the mob that was clicked.
  local scroll = CreateFrame("ScrollFrame", "GanderBestiaryScroll", bestiary, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", 16, -(80 + ROWS * 20 + 12))
  scroll:SetPoint("BOTTOMRIGHT", -34, 12)
  bestiary.child = CreateFrame("Frame", nil, scroll)
  bestiary.child:SetSize(500, 10)
  scroll:SetScrollChild(bestiary.child)
  bestiary.detail = bestiary.child:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  bestiary.detail:SetPoint("TOPLEFT")
  bestiary.detail:SetWidth(500)
  bestiary.detail:SetJustifyH("LEFT")
  bestiary.detail:SetJustifyV("TOP")
  bestiary.detail:SetSpacing(3)

  bestiary:SetScript("OnShow", drawBestiary)
  refreshBestiary = function() if bestiary:IsShown() then drawBestiary() end end
end

local function toggleBestiary()
  if not bestiary then buildBestiary() end
  if bestiary:IsShown() then bestiary:Hide() else bestiary:Show() end
end

---------------------------------------------------------------------------
-- The minimap button
--
-- Left-click opens the bestiary, right-click the settings. It sits on the
-- minimap's edge at GanderDB.minimap.angle (degrees, 0 = right, 90 = top)
-- and can be dragged around it. Switched off in the settings, it's hidden.
---------------------------------------------------------------------------
local ICON = "Interface\\Icons\\INV_Misc_Spyglass_02"
local minimapButton

local function placeMinimapButton()
  local angle = math.rad(db.minimap.angle)
  local radius = (Minimap:GetWidth() or 140) / 2 + 5
  minimapButton:ClearAllPoints()
  minimapButton:SetPoint("CENTER", Minimap, "CENTER", math.cos(angle) * radius, math.sin(angle) * radius)
end

-- While dragging: keep the button on the edge, towards the cursor.
local function followCursor()
  local cx, cy = Minimap:GetCenter()
  local x, y = GetCursorPosition()
  local scale = Minimap:GetEffectiveScale() or 1
  if not (cx and cy and x and y) or scale == 0 then return end
  db.minimap.angle = math.deg(math.atan2(y / scale - cy, x / scale - cx))
  placeMinimapButton()
end

local function buildMinimapButton()
  if type(Minimap) ~= "table" then return end
  local b = CreateFrame("Button", "GanderMinimapButton", Minimap)
  minimapButton = b
  b:SetSize(31, 31)
  b:SetFrameStrata("MEDIUM")
  b:SetFrameLevel(8)
  b:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  b:RegisterForDrag("LeftButton")
  b:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")

  local back = b:CreateTexture(nil, "BACKGROUND")
  back:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  back:SetSize(20, 20)
  back:SetPoint("TOPLEFT", 7, -5)
  local icon = b:CreateTexture(nil, "ARTWORK")
  icon:SetTexture(ICON)
  icon:SetTexCoord(0.05, 0.95, 0.05, 0.95)
  icon:SetSize(17, 17)
  icon:SetPoint("TOPLEFT", 7, -6)
  local border = b:CreateTexture(nil, "OVERLAY")
  border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
  border:SetSize(53, 53)
  border:SetPoint("TOPLEFT")

  b:SetScript("OnClick", function(_, button)
    if button == "RightButton" then openSettings() else toggleBestiary() end
  end)
  b:SetScript("OnDragStart", function(self) self:SetScript("OnUpdate", followCursor) end)
  b:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
  b:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:SetText("Gander")
    GameTooltip:AddLine("Left-click: open the bestiary", 1, 1, 1)
    GameTooltip:AddLine("Right-click: settings", 1, 1, 1)
    GameTooltip:AddLine("Drag: move around the minimap", 0.6, 0.6, 0.6)
    GameTooltip:Show()
  end)
  b:SetScript("OnLeave", function() GameTooltip:Hide() end)

  placeMinimapButton()
  updateMinimapButton = function() b:SetShown(not db.minimap.hide) end
  updateMinimapButton()
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
local HELP = {
  "/gander  -  open the bestiary: every mob Gander remembers",
  "/gander settings  -  choose which lines show, and how sharing works",
  "/gander debug  -  print what the game says about your target, what Gander learns, sends and hears, and the mob casts and control effects it sees",
  "/gander help  -  this list",
}

-- What the game says about your target right now, for sending to the author.
---------------------------------------------------------------------------
-- The ability probe (part of /gander debug)
--
-- A test for a feature that doesn't exist yet: remembering what a mob can
-- do to you. While debug is on, it prints each mob cast, each new debuff on
-- you and each control effect (stun, disarm...) the game reports, so we can
-- see what each game lets an addon know, and when it's hidden.
---------------------------------------------------------------------------
local PROBE_REPEAT = 30   -- seconds before the same thing is printed again
local PROBE_EVENTS = { "UNIT_SPELLCAST_START", "UNIT_SPELLCAST_CHANNEL_START", "UNIT_SPELLCAST_SUCCEEDED",
                       "UNIT_AURA", "LOSS_OF_CONTROL_ADDED" }
local CAST_WORD = { UNIT_SPELLCAST_START = "starts casting", UNIT_SPELLCAST_CHANNEL_START = "channels",
                    UNIT_SPELLCAST_SUCCEEDED = "used" }
local LOG_EVENTS = { SPELL_CAST_START = true, SPELL_CAST_SUCCESS = true, SPELL_AURA_APPLIED = true }
local probeFrame
local probePrinted = {}   -- what was printed -> when

-- Print line, unless the same thing (key) was printed a moment ago: a mob
-- seen as both your target and a nameplate reports each cast twice.
local function probeSay(key, line)
  local t = GetTime()
  if probePrinted[key] and t - probePrinted[key] < PROBE_REPEAT then return end
  probePrinted[key] = t
  dbg("%s", line)
end

-- "Defias Pillager (id 589)" and 589 for the mob under unit. Nothing for a
-- player or a player's pet.
local function probeMob(unit)
  if isSecret(unit) or type(unit) ~= "string" then return "a hidden unit" end
  if isPlayer(unit) then return end
  local theirs = call("UnitPlayerControlled", unit)
  if not isSecret(theirs) and theirs then return end
  local name = call("UnitName", unit)
  if isSecret(name) or type(name) ~= "string" then name = "(name hidden)" end
  local id = identify(unit)
  return format("%s (id %s)", name, id and tostring(id) or "hidden"), id
end

-- "Fireball (spell 133)" and 133.
local function probeSpell(id, name)
  if isSecret(id) or type(id) ~= "number" then return "a hidden spell" end
  if isSecret(name) or type(name) ~= "string" then
    if C_Spell and C_Spell.GetSpellName then
      name = results(pcall(C_Spell.GetSpellName, id))
    else
      name = call("GetSpellInfo", id)
    end
  end
  if isSecret(name) or type(name) ~= "string" then name = "unnamed" end
  return format("%s (spell %d)", name, id), id
end

-- Who put an aura on you: a mob's name and id, "caster unknown", or nothing
-- for a player.
local function probeCaster(aura)
  local source = aura.sourceUnit
  if source == nil then return "caster unknown" end
  if isSecret(source) then return "caster hidden" end
  return (probeMob(source))
end

local function probeCast(event, unit, _, spellID)
  if not isSecret(unit) and unit == "player" then return end
  local who, id = probeMob(unit)
  if not who then return end
  local what, spell = probeSpell(spellID)
  probeSay(format("cast:%s:%s:%s", event, tostring(id), tostring(spell)),
           format("cast: %s %s %s [seen as %s]", who, CAST_WORD[event], what, isSecret(unit) and "?" or tostring(unit)))
end

local function probeDebuff(aura)
  if isSecret(aura) then
    probeSay("debuff:hidden", "debuff on you: hidden")
    return
  end
  if type(aura) ~= "table" then return end
  local harmful = aura.isHarmful
  if not isSecret(harmful) and not harmful then return end
  local from = probeCaster(aura)
  if not from then return end
  local what, spell = probeSpell(aura.spellId, aura.name)
  local kind = aura.dispelName
  if isSecret(kind) or type(kind) ~= "string" or kind == "" then kind = nil end
  probeSay(format("debuff:%s:%s", tostring(spell), from),
           format("debuff on you: %s%s, %s%s", what, kind and (", " .. kind) or "",
                  from:find("^caster ") and "" or "from ", from))
end

local function probeAuras(unit, info)
  if isSecret(unit) or unit ~= "player" or isSecret(info) or type(info) ~= "table" then return end
  local added = info.addedAuras
  if isSecret(added) or type(added) ~= "table" then return end
  for _, aura in ipairs(added) do probeDebuff(aura) end
end

local function probeControl(unit, index)
  if isSecret(unit) or type(unit) ~= "string" then unit = "player" end
  local loc, data = C_LossOfControl, nil
  if loc and loc.GetActiveLossOfControlDataByUnit then
    data = results(pcall(loc.GetActiveLossOfControlDataByUnit, unit, index))
  elseif loc and loc.GetActiveLossOfControlData and unit == "player" then
    data = results(pcall(loc.GetActiveLossOfControlData, index))
  end
  if isSecret(data) then
    probeSay("control:hidden:" .. unit, format("control effect on %s: hidden", unit))
    return
  end
  if type(data) ~= "table" then
    probeSay("control:none:" .. unit, format("control effect on %s: the game gave no details", unit))
    return
  end
  local kind, text = data.locType, data.displayText
  if isSecret(kind) or type(kind) ~= "string" then kind = "kind hidden" end
  if isSecret(text) or type(text) ~= "string" then text = "?" end
  local what, spell = probeSpell(data.spellID)
  local from = "caster unknown"
  local instance = data.auraInstanceID
  if isSecret(instance) then
    from = "caster hidden"
  elseif instance ~= nil and C_UnitAuras and C_UnitAuras.GetAuraDataByAuraInstanceID then
    local aura = results(pcall(C_UnitAuras.GetAuraDataByAuraInstanceID, unit, instance))
    if isSecret(aura) then
      from = "caster hidden"
    elseif type(aura) == "table" then
      from = probeCaster(aura) or "a player"
    end
  end
  probeSay(format("control:%s:%s:%s:%s", unit, kind, tostring(spell), from),
           format('control effect on %s: %s ("%s") from %s, %s', unit, kind, text, what, from))
end

-- Classic Era only: the combat log names the mob and spell for everything nearby.
local function probeLog()
  local _, sub, _, sourceGUID, sourceName, _, _, _, destName, _, _, spellID, spellName = CombatLogGetCurrentEventInfo()
  if not LOG_EVENTS[sub] or type(sourceGUID) ~= "string" then return end
  local kind, npc = sourceGUID:match("^(%a+)%-%d+%-%d+%-%d+%-%d+%-(%d+)%-")
  if kind ~= "Creature" and kind ~= "Vehicle" then return end
  local what
  if type(spellID) == "number" and spellID > 0 then
    what = probeSpell(spellID, spellName)
  else
    what = format("%s (no spell id)", tostring(spellName))
  end
  probeSay(format("log:%s:%s:%s", sub, npc, tostring(spellName)),
           format("combat log: %s (id %s) %s %s%s", tostring(sourceName), npc, sub, what,
                  type(destName) == "string" and (" on " .. destName) or ""))
end

local function probeEvent(event, ...)
  if CAST_WORD[event] then
    probeCast(event, ...)
  elseif event == "UNIT_AURA" then
    probeAuras(...)
  elseif event == "LOSS_OF_CONTROL_ADDED" then
    probeControl(...)
  elseif event == "COMBAT_LOG_EVENT_UNFILTERED" then
    probeLog()
  end
end

-- Start or stop the probe. It only listens while debug is on: these events
-- fire constantly in a fight.
local function setProbe(on)
  if not probeFrame then
    probeFrame = CreateFrame("Frame")
    probeFrame:SetScript("OnEvent", function(_, event, ...)
      local ok, err = pcall(probeEvent, event, ...)
      if not ok then probeSay("error:" .. event, format("probe error on %s: %s", event, tostring(err))) end
    end)
  end
  local hasLog = type(CombatLogGetCurrentEventInfo) == "function"
  local wanted, missing = {}, {}
  for _, e in ipairs(PROBE_EVENTS) do wanted[#wanted + 1] = e end
  if hasLog then wanted[#wanted + 1] = "COMBAT_LOG_EVENT_UNFILTERED" end
  for _, e in ipairs(wanted) do
    if not on then
      pcall(probeFrame.UnregisterEvent, probeFrame, e)
    elseif not pcall(probeFrame.RegisterEvent, probeFrame, e) then
      missing[#missing + 1] = e
    end
  end
  if not on then return end
  probePrinted = {}
  say("watching for mob casts, new debuffs on you and control effects%s. Each is printed once every %d seconds.",
      hasLog and ", and reading the combat log" or "", PROBE_REPEAT)
  if #missing > 0 then say("this game has no event called %s.", table.concat(missing, ", ")) end
end

local function describeTarget()
  if not UnitExists("target") then
    say("no target. Target a mob to see what the game says about it.")
    return
  end
  if isPlayer("target") then
    say("your target is a player; Gander only looks at mobs.")
    return
  end
  local v, hid = read("target")
  local id, level = identify("target")
  local name = call("UnitName", "target")
  if isSecret(name) or type(name) ~= "string" then name = "(name hidden)" end
  say("%s: id %s, level %s.", name, id and tostring(id) or "hidden or not a creature", level and tostring(level) or "hidden")
  local sent, zero, hidden = {}, {}, {}
  for _, f in ipairs(FIELDS) do
    local key = f[1]
    if v[key] ~= nil then
      sent[#sent + 1] = key .. "=" .. (f[2] == "n" and compact(v[key]) or v[key])
    elseif hid[key] then
      hidden[#hidden + 1] = key
    else
      zero[#zero + 1] = key
    end
  end
  if #sent > 0 then say("the game sends: %s", table.concat(sent, " ")) end
  if #zero > 0 then say("not sent (zero): %s", table.concat(zero, " ")) end
  if #hidden > 0 then say("hidden right now: %s", table.concat(hidden, " ")) end
end

local function describeChannel()
  if not channelWanted() then
    say("the Gander channel is switched off.")
  elseif channelRefused then
    say("the game refuses addon messages on chat channels here.")
  elseif channelNumber() then
    say("in the Gander channel, as channel %d.", channelNumber())
  else
    say("not in the Gander channel yet (it's joined %d seconds after login).", JOIN_DELAY)
  end
end

SLASH_GANDER1 = "/gander"
SlashCmdList.GANDER = function(msg)
  if not (db and panel) then
    say("didn't finish loading. Try /reload, and check for errors.")
    return
  end
  local word = strtrim(msg or ""):match("^(%S*)"):lower()
  if word == "" then
    toggleBestiary()
  elseif word == "settings" then
    openSettings()
  elseif word == "debug" then
    debugging = not debugging
    say("debug %s.", debugging and "on" or "off")
    if debugging then
      describeTarget()
      describeChannel()
    end
    setProbe(debugging)
  elseif word == "help" then
    for _, line in ipairs(HELP) do say(line) end
  else
    say("no command called %s. Type /gander help for commands.", word)
  end
end

---------------------------------------------------------------------------
-- Startup
---------------------------------------------------------------------------
local events = CreateFrame("Frame")
for _, e in ipairs({ "ADDON_LOADED", "PLAYER_LOGIN", "PLAYER_TARGET_CHANGED", "CHAT_MSG_ADDON",
                     "PLAYER_REGEN_ENABLED", "PLAYER_ENTERING_WORLD" }) do
  pcall(events.RegisterEvent, events, e)
end
events:SetScript("OnEvent", function(_, event, arg1, ...)
  if event == "ADDON_LOADED" then
    if arg1 == ADDON then loadSettings() end
  elseif event == "PLAYER_LOGIN" then
    if not db then return end
    local name = UnitName("player")
    if not isSecret(name) and type(name) == "string" then myName = name end
    myRealm = (GetNormalizedRealmName and GetNormalizedRealmName()) or GetRealmName():gsub("%s", "")
    hookTooltips()
    buildPanel()
    pcall(buildMinimapButton)
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
      pcall(C_ChatInfo.RegisterAddonMessagePrefix, PREFIX)
      C_Timer.After(JOIN_DELAY, joinChannel)
    end
  elseif not (db and panel) then
    return
  elseif event == "PLAYER_TARGET_CHANGED" then
    if UnitExists("target") and not isPlayer("target") then pcall(look, "target") end
  elseif event == "CHAT_MSG_ADDON" then
    pcall(onAddonMessage, arg1, ...)
  elseif event == "PLAYER_REGEN_ENABLED" then
    fightEnded()
  elseif event == "PLAYER_ENTERING_WORLD" then
    pcall(checkLogging)
  end
end)
