-- Bushel: counts the herbs you gather, ore you mine and creatures you skin,
-- by type, per character and for the account. The counts show in tooltips.
local ADDON = ...

local db, me          -- BushelDB, and this character's entry in it
local debugging = false

local function say(fmt, ...) print("|cff9acd32Bushel|r: " .. format(fmt, ...)) end
local function dbg(fmt, ...) if debugging then say("|cff999999" .. fmt .. "|r", ...) end end

local function commas(n)
  local s = tostring(math.floor(n)):reverse():gsub("(%d%d%d)", "%1,"):reverse()
  return (s:gsub("^,", ""))
end

local function charKey(name, realm) return name .. "-" .. realm end

-- Forever hides some values from addons at restricted moments ("secret
-- values"). They can't be compared or used as keys, so anything that might
-- be one is checked first. Classic Era has no issecretvalue.
local function isSecret(v) return issecretvalue ~= nil and issecretvalue(v) end

---------------------------------------------------------------------------
-- What counts
--
-- Each kind is found by its gather spell. The IDs cover Classic Era's ranks;
-- any other ID is matched by the spell's name in the player's language, so
-- other game versions and ranks work too.
---------------------------------------------------------------------------
local KINDS = {
  { key = "mining",    label = "Mining",    verb = "Mined",    spell = 2575, ids = { 2575, 2576, 3564, 10248 } },
  { key = "herbalism", label = "Herbalism", verb = "Gathered", spell = 2366, ids = { 2366, 2368, 3570, 11993 } },
  { key = "skinning",  label = "Skinning",  verb = "Skinned",  spell = 8613, ids = { 8613, 8617, 8618, 10768 } },
}
local kindById = {}
for _, k in ipairs(KINDS) do for _, id in ipairs(k.ids) do kindById[id] = k end end

local function spellName(id)
  if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) end
  if GetSpellInfo then return (GetSpellInfo(id)) end
end

local function kindOf(spellID)
  if type(spellID) ~= "number" or isSecret(spellID) then return end
  if kindById[spellID] then return kindById[spellID] end
  local name = spellName(spellID)
  if not name or isSecret(name) then return end
  for _, k in ipairs(KINDS) do
    if name == spellName(k.spell) then return k end
  end
end

---------------------------------------------------------------------------
-- Counting
--
-- UNIT_SPELLCAST_SENT names the node or corpse; UNIT_SPELLCAST_SUCCEEDED
-- says the gather finished. The loot window that follows says which node it
-- was, so a vein mined several times counts once. If no loot window shows,
-- the gather still counts after LOOT_WAIT.
---------------------------------------------------------------------------
local LOOT_WAIT = 3          -- seconds to wait for the loot window
local SAME_NODE_FOR = 600    -- seconds a node is remembered as already counted

local sent       -- { cast, kind, name }: the gather cast just started
local gathering  -- { kind, name }: a finished gather waiting for its loot
local gatherToken = 0
local seenNodes = {}         -- node GUID -> when it was counted

local function totals(kindKey, name)
  local here = me.counts[kindKey][name] or 0
  local all = 0
  for _, c in pairs(db.chars) do
    local t = c.counts and c.counts[kindKey]
    all = all + (t and t[name] or 0)
  end
  return here, all
end

local function count(kind, name)
  local t = me.counts[kind.key]
  t[name] = (t[name] or 0) + 1
  local here, all = totals(kind.key, name)
  dbg("%s %s: %d here, %d on the account", kind.verb:lower(), name, here, all)
end

local function finishGather(guid)
  local g = gathering
  gathering = nil
  if not g then return end
  if guid then
    local now = GetTime()
    for k, t in pairs(seenNodes) do
      if now - t > SAME_NODE_FOR then seenNodes[k] = nil end
    end
    if seenNodes[guid] then
      dbg("same %s as before, not counted again", g.name)
      return
    end
    seenNodes[guid] = now
  end
  count(g.kind, g.name)
end

local function onSent(unit, target, cast, spellID)
  if unit ~= "player" or isSecret(target) or isSecret(cast) then return end
  local kind = kindOf(spellID)
  if not kind or type(target) ~= "string" or target == "" then return end
  sent = { cast = cast, kind = kind, name = target }
end

local function onSucceeded(unit, cast)
  if unit ~= "player" or not sent or isSecret(cast) or cast ~= sent.cast then return end
  if gathering then finishGather(nil) end  -- the last one never showed loot
  gathering, sent = { kind = sent.kind, name = sent.name }, nil
  gatherToken = gatherToken + 1
  local token = gatherToken
  C_Timer.After(LOOT_WAIT, function()
    if token == gatherToken then finishGather(nil) end
  end)
end

local function onLootOpened()
  if not gathering then return end
  local guid = GetLootSourceInfo and GetLootSourceInfo(1)
  if isSecret(guid) or type(guid) ~= "string" then guid = nil end
  if guid then dbg("loot from %s", guid) end
  finishGather(guid)
end

---------------------------------------------------------------------------
-- Tooltips
--
-- Units and world objects get a line per kind gathered under that name,
-- through the client's tooltip data hook, with a plain OnShow hook as a
-- fallback. Each tooltip gets the lines once until it's cleared.
---------------------------------------------------------------------------
local doneFor = setmetatable({}, { __mode = "k" })  -- tooltip -> name already added

local function addCounts(tip, name, resize)
  if not (db and me) or isSecret(name) or type(name) ~= "string" or name == "" then return end
  if doneFor[tip] == name then return end
  doneFor[tip] = name
  local added = false
  for _, k in ipairs(KINDS) do
    local here, all = totals(k.key, name)
    if all > 0 then
      tip:AddLine(format("|cffffd100%s: %s|r |cffb0b0b0(account %s)|r", k.verb, commas(here), commas(all)))
      added = true
    end
  end
  if added and resize then tip:Show() end
end

local function onTooltipData(tip, data)
  local line = data and data.lines and data.lines[1]
  addCounts(tip, line and line.leftText)
end

local function onTooltipShow(tip)
  if tip.GetItem and tip:GetItem() then return end  -- an item named like a herb
  local first = _G[tip:GetName() .. "TextLeft1"]
  addCounts(tip, first and first:GetText(), true)
end

local function hookTooltips()
  if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
    for _, kind in ipairs({ "Unit", "Object" }) do
      local id = Enum.TooltipDataType[kind]
      if id then
        TooltipDataProcessor.AddTooltipPostCall(id, function(tip, data) pcall(onTooltipData, tip, data) end)
      end
    end
  end
  GameTooltip:HookScript("OnShow", function(tip) pcall(onTooltipShow, tip) end)
  GameTooltip:HookScript("OnTooltipCleared", function(tip) doneFor[tip] = nil end)
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
local LIST_TOP = 10  -- types shown per kind in /bushel list

local HELP = {
  "/bushel list  -  this character's counts for each kind, most first",
  "/bushel debug  -  print each gather as it's counted",
  "Hover over a node or creature to see its counts in the tooltip.",
}

local function list()
  local any = false
  for _, k in ipairs(KINDS) do
    local rows, sum = {}, 0
    for name, n in pairs(me.counts[k.key]) do
      rows[#rows + 1] = { name = name, n = n }
      sum = sum + n
    end
    if #rows > 0 then
      any = true
      table.sort(rows, function(a, b) if a.n ~= b.n then return a.n > b.n end return a.name < b.name end)
      say("%s: %s", k.label, commas(sum))
      for i = 1, math.min(LIST_TOP, #rows) do
        local _, all = totals(k.key, rows[i].name)
        say("   %s: %s (account %s)", rows[i].name, commas(rows[i].n), commas(all))
      end
      if #rows > LIST_TOP then say("   and %d more types", #rows - LIST_TOP) end
    end
  end
  if not any then say("nothing gathered on this character yet.") end
end

SLASH_BUSHEL1 = "/bushel"
SlashCmdList.BUSHEL = function(msg)
  if not (db and me) then
    say("didn't finish loading. Try /reload, and check for errors.")
    return
  end
  local word = strtrim(msg or ""):match("^(%S*)"):lower()
  if word == "list" or word == "" then
    list()
  elseif word == "debug" then
    debugging = not debugging
    say("debug %s.", debugging and "on" or "off")
  elseif word == "help" then
    for _, line in ipairs(HELP) do say(line) end
  else
    say("no command called %s. Type /bushel help for commands.", word)
  end
end

---------------------------------------------------------------------------
-- Startup
---------------------------------------------------------------------------
local events = CreateFrame("Frame")
for _, e in ipairs({ "ADDON_LOADED", "PLAYER_LOGIN", "UNIT_SPELLCAST_SENT",
                     "UNIT_SPELLCAST_SUCCEEDED", "LOOT_OPENED" }) do
  pcall(events.RegisterEvent, events, e)
end
events:SetScript("OnEvent", function(self, event, arg1, ...)
  if event == "UNIT_SPELLCAST_SENT" then
    if me then onSent(arg1, ...) end
  elseif event == "UNIT_SPELLCAST_SUCCEEDED" then
    if me then onSucceeded(arg1, ...) end
  elseif event == "LOOT_OPENED" then
    if me then onLootOpened() end
  elseif event == "ADDON_LOADED" and arg1 == ADDON then
    BushelDB = BushelDB or {}
    db = BushelDB
    db.chars = db.chars or {}
  elseif event == "PLAYER_LOGIN" then
    local name, realm = UnitName("player"), GetRealmName()
    local key = charKey(name, realm)
    me = db.chars[key] or {}
    me.name, me.realm = name, realm
    me.class = select(2, UnitClass("player"))
    me.counts = me.counts or {}
    for _, k in ipairs(KINDS) do me.counts[k.key] = me.counts[k.key] or {} end
    db.chars[key] = me
    hookTooltips()
  end
end)
