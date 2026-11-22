-- Gander: shows a mob's stats on its tooltip. It reads whatever the game
-- reveals about the mob, remembers it for when the game hides it, and shares
-- what it learns with other players running Gander.
local ADDON = ...

local db              -- GanderDB
local panel, category
local debugging = false
local myName, myRealm

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
                    "stats", "run", "class", "family" }
local LINE_LABEL = {
  defense = "Defense", armor = "Armor", resist = "Resistances", health = "Health", power = "Mana / power",
  speed = "Attack speed", damage = "Damage", ap = "Attack power", ranged = "Ranged attack",
  stats = "Strength, agility and other stats", run = "Run speed", class = "Class", family = "Family",
}

local function loadSettings()
  GanderDB = type(GanderDB) == "table" and GanderDB or {}
  db = GanderDB
  for _, key in ipairs({ "tooltips", "remembered", "share" }) do
    if type(db[key]) ~= "boolean" then db[key] = true end
  end
  if type(db.lines) ~= "table" then db.lines = {} end
  for _, key in ipairs(LINE_KEYS) do
    if type(db.lines[key]) ~= "boolean" then db.lines[key] = true end
  end
  if type(db.mobs) ~= "table" then db.mobs = {} end
end

---------------------------------------------------------------------------
-- Reading a mob
--
-- Every stat is a field: a short key, what kind of value it is, and whether
-- it changes with the mob's level. A stat the game doesn't send for mobs
-- reads as zero, so zero means "not sent" and gets no line.
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
}
local FIELD = {}
for _, f in ipairs(FIELDS) do FIELD[f[1]] = { kind = f[2], perLevel = f[3] } end

local MAX_NUMBER = 1000000000
local MAX_TOKEN, MAX_NAME = 20, 24

-- Is value a usable reading for this kind of field? Returns it cleaned up.
local function clean(kind, value)
  if kind == "n" then
    if type(value) == "number" and value > 0 and value <= MAX_NUMBER then return round(value) end
  elseif kind == "token" then
    if type(value) == "string" and #value <= MAX_TOKEN and value:find("^%u+$") then return value end
  elseif type(value) == "string" and value ~= "" and #value <= MAX_NAME and not value:find("[,=:|%c]") then
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
-- record is { at = when, by = who (heard only), v = values by field }. Kept
-- apart so every value keeps its true source, and ours always wins. A
-- defense of level x 5 isn't stored: it can always be worked out.
---------------------------------------------------------------------------
local queueSend  -- set below, in Sharing

local function ruleDefense(level)
  if level and level > 0 then return level * 5 end
end

-- Store what we just saw ourselves, and pass it on if it brought something new.
local function remember(id, level, v)
  local mob = db.mobs[id]
  local old = mob and mob.lv[level]
  local values, changed = {}, false
  for key, value in pairs(old and old.v or {}) do values[key] = value end
  for key, value in pairs(v) do
    if key == "def" and value == ruleDefense(level) then value = nil end
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
  mob.lv[level] = { at = time(), v = values }
  if changed then
    dbg("learned mob %d at level %d", id, level)
    queueSend(id, level)
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

-- What is remembered for this mob at this level: field -> { value, record }.
-- Our own record for that level comes first, then what we heard for it.
-- Fields that don't change with level can also come from another level.
local function recall(id, level)
  local found = {}
  local mob = id and db.mobs[id]
  if not mob then return found end
  local seen, heard = mob.lv or {}, mob.heard or {}
  for key, spec in pairs(FIELD) do
    local rec = level and seen[level]
    if not (rec and rec.v[key] ~= nil) then rec = level and heard[level] end
    if not (rec and rec.v[key] ~= nil) and not spec.perLevel then
      rec = newestWith(seen, key) or newestWith(heard, key)
    end
    if rec and rec.v[key] ~= nil then found[key] = { rec.v[key], rec } end
  end
  return found
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
  for _, line in ipairs(LINES) do
    if db.lines[line.key] then
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
  local v = read(unit)
  local id, level = identify(unit)
  if id and level then
    local fighting = call("UnitAffectingCombat", unit)
    if not isSecret(fighting) and not fighting then remember(id, level, v) end
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
-- Hidden addon messages, prefix "Gander", each starting with protocol "1":
--   1:M:<creatureID>:<level>:<field>=<value>,<field>=<value>,...
-- Sent to guild and group a few seconds after learning something new, one
-- mob at a time, and never while chat is locked or a boss fight is on.
-- Only what we saw ourselves is sent, so nothing echoes back and forth, and
-- what we saw ourselves is always shown ahead of what we heard.
-- Fields a newer version adds are ignored by this one.
---------------------------------------------------------------------------
local PREFIX = "Gander"
local SEND_DELAY = 3   -- seconds after learning before the first send
local SEND_GAP = 2     -- seconds between mobs
local SEND_RETRY = 5   -- seconds before trying again while chat is locked
local MAX_MESSAGE = 255
local MAX_ID, MAX_LEVEL = 9999999, 255

local ECHO_WINDOW = 15 -- seconds in which our own message can come back to us

local queue, queued, sendPending = {}, {}, false
local sentAt = {}      -- message text -> when we sent it

local function chatLocked()
  if C_ChatInfo and C_ChatInfo.InChatMessagingLockdown and C_ChatInfo.InChatMessagingLockdown() then return true end
  local fighting = (C_InstanceEncounter and C_InstanceEncounter.IsEncounterInProgress) or IsEncounterInProgress
  return fighting ~= nil and fighting() and true or false
end

local function encode(id, level, v)
  local parts = {}
  for _, f in ipairs(FIELDS) do
    local value = v[f[1]]
    if value ~= nil then parts[#parts + 1] = f[1] .. "=" .. (f[2] == "n" and compact(value) or value) end
  end
  local head = format("1:M:%d:%d:", id, level)
  local text = head .. table.concat(parts, ",")
  while #text > MAX_MESSAGE and #parts > 1 do
    tremove(parts)
    text = head .. table.concat(parts, ",")
  end
  return text
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
  queued[item.id .. ":" .. item.level] = nil
  local mob = db.mobs[item.id]
  local rec = mob and mob.lv[item.level]
  if rec and C_ChatInfo and C_ChatInfo.SendAddonMessage then
    local text = encode(item.id, item.level, rec.v)
    for old, at in pairs(sentAt) do
      if GetTime() - at > ECHO_WINDOW then sentAt[old] = nil end
    end
    sentAt[text] = GetTime()
    if IsInGuild() then pcall(C_ChatInfo.SendAddonMessage, PREFIX, text, "GUILD") end
    local group = IsInRaid() and "RAID" or (IsInGroup() and "PARTY") or nil
    if group then pcall(C_ChatInfo.SendAddonMessage, PREFIX, text, group) end
    dbg("shared %s", text)
  end
  if #queue > 0 then
    sendPending = true
    C_Timer.After(SEND_GAP, flush)
  end
end

queueSend = function(id, level)
  if not db.share then return end
  local key = id .. ":" .. level
  if not queued[key] then
    queued[key] = true
    queue[#queue + 1] = { id = id, level = level }
  end
  if not sendPending then
    sendPending = true
    C_Timer.After(SEND_DELAY, flush)
  end
end

local function isMe(sender)
  local name, realm = sender:match("^([^-]+)%-?(.*)$")
  return name == myName and (realm == "" or realm == myRealm)
end

local function onAddonMessage(prefix, text, channel, sender)
  if isSecret(prefix) or prefix ~= PREFIX or not db.share then return end
  if isSecret(text) or isSecret(sender) or type(text) ~= "string" or type(sender) ~= "string" then return end
  -- The game sends our own guild and group messages back to us. The sender
  -- name can't be relied on to spot them (Forever names can have a surname,
  -- and realms are written several ways), so the text we just sent is.
  local mine = sentAt[text]
  if (mine and GetTime() - mine <= ECHO_WINDOW) or isMe(sender) then return end
  local id, level, body = text:match("^1:M:(%d+):(%-?%d+):(.+)$")
  id, level = tonumber(id), tonumber(level)
  if not id or id < 1 or id > MAX_ID then return end
  if not (level == -1 or (level >= 1 and level <= MAX_LEVEL)) then return end
  local values = {}
  for key, raw in body:gmatch("(%w+)=([^,]*)") do
    local spec = FIELD[key]
    if spec then
      if spec.kind == "n" then raw = raw:find("^%d+%.?%d*$") and tonumber(raw) or nil end
      values[key] = clean(spec.kind, raw)
    end
  end
  if next(values) == nil then return end
  local who = sender:match("^[^-]+")
  dbg("heard mob %d (level %d) from %s", id, level, sender)
  local mob = db.mobs[id]
  if not mob then
    mob = { lv = {}, heard = {} }
    db.mobs[id] = mob
  end
  mob.heard = mob.heard or {}
  mob.heard[level] = { at = time(), by = who, v = values }  -- the newest telling wins
end

---------------------------------------------------------------------------
-- Settings panel (Options > AddOns > Gander)
---------------------------------------------------------------------------
local function countMobs()
  local n = 0
  for _ in pairs(db.mobs) do n = n + 1 end
  return n
end

local function refreshPanel()
  for _, key in ipairs({ "tooltips", "remembered", "share" }) do panel.checks[key]:SetChecked(db[key]) end
  for _, key in ipairs(LINE_KEYS) do panel.checks[key]:SetChecked(db.lines[key]) end
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
  addCheck("share", "Share what I learn with my guild and group, and use what they share", 16, -120,
           function(on) db.share = on end)

  local header = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
  header:SetPoint("TOPLEFT", 16, -160)
  header:SetText("Lines to show")
  local perColumn = math.ceil(#LINE_KEYS / 2)
  for i, key in ipairs(LINE_KEYS) do
    local column, rowIndex = math.floor((i - 1) / perColumn), (i - 1) % perColumn
    addCheck(key, LINE_LABEL[key], 16 + column * 280, -180 - rowIndex * 28, function(on) db.lines[key] = on end)
  end

  panel.count = panel:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  panel.count:SetPoint("TOPLEFT", 16, -180 - perColumn * 28 - 12)

  panel:SetScript("OnShow", refreshPanel)

  if Settings and Settings.RegisterCanvasLayoutCategory then
    category = Settings.RegisterCanvasLayoutCategory(panel, "Gander")
    Settings.RegisterAddOnCategory(category)
  end
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
local HELP = {
  "/gander  -  open the settings",
  "/gander debug  -  print what the game says about your target, and what Gander learns, sends and hears",
  "/gander help  -  this list",
}

-- What the game says about your target right now, for sending to the author.
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

SLASH_GANDER1 = "/gander"
SlashCmdList.GANDER = function(msg)
  if not (db and panel) then
    say("didn't finish loading. Try /reload, and check for errors.")
    return
  end
  local word = strtrim(msg or ""):match("^(%S*)"):lower()
  if word == "" then
    if category then
      pcall(Settings.OpenToCategory, category:GetID())
    else
      say("the settings window isn't available here.")
    end
  elseif word == "debug" then
    debugging = not debugging
    say("debug %s.", debugging and "on" or "off")
    if debugging then describeTarget() end
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
for _, e in ipairs({ "ADDON_LOADED", "PLAYER_LOGIN", "PLAYER_TARGET_CHANGED", "CHAT_MSG_ADDON" }) do
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
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
      pcall(C_ChatInfo.RegisterAddonMessagePrefix, PREFIX)
    end
  elseif not (db and panel) then
    return
  elseif event == "PLAYER_TARGET_CHANGED" then
    if UnitExists("target") and not isPlayer("target") then pcall(look, "target") end
  elseif event == "CHAT_MSG_ADDON" then
    pcall(onAddonMessage, arg1, ...)
  end
end)
