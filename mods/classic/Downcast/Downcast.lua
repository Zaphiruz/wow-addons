-- Downcast
--
-- Casting a spell from an action slot makes the game drop to the best rank
-- the target can take. Casting by name (/cast) does not: it fails with
-- "Target is too low level". Downcast keeps each chosen spell's top rank in a
-- hidden action slot and gives it a button your macros can /click:
--
--   /click DowncastRenew
--
-- At the moment of the click, a secure snippet picks the unit
-- (mouseover, then friendly target, then you), so it works in combat.

local ADDON = ...
local PREFIX = "|cff66ccffDowncast:|r "
local UNIT_RULE = "[@mouseover,help,nodead] mouseover; [help,nodead] target; player"
local BOOK = BOOKTYPE_SPELL or "spell"
local MAX_SLOT = 120
local MAX_KEY_LEN = 24

local PRIEST_DEFAULTS = {
  { key = "Renew",      spell = "Renew" },
  { key = "Fort",       spell = "Power Word: Fortitude" },
  { key = "Shield",     spell = "Power Word: Shield" },
  { key = "Spirit",     spell = "Divine Spirit" },
  { key = "ShadowProt", spell = "Shadow Protection" },
}

local db                 -- DowncastCharDB once loaded
local buttons = {}       -- frame name -> secure button
local status = {}        -- entry -> text for /downcast
local worldReady = false
local syncQueued = false
local pendingCombat = false
local debugOn = false

local function say(fmt, ...)
  print(PREFIX .. format(fmt, ...))
end

---------------------------------------------------------------------------
-- Secure buttons
---------------------------------------------------------------------------

local header = CreateFrame("Frame", "DowncastHeader", UIParent, "SecureHandlerBaseTemplate")

-- Runs in the restricted environment on every click, in or out of combat.
-- useOnKeyDown is matched to the click we got, so a plain "/click X" (a
-- release) and "/click X LeftButton 1" (a press) both cast exactly once.
local CLICK_SNIPPET = [=[
  local unit = SecureCmdOptionParse(self:GetAttribute("downcast-unitrule"))
  self:SetAttribute("unit", unit or "player")
  self:SetAttribute("useOnKeyDown", down and true or false)
]=]

local function buttonName(e)
  return "Downcast" .. e.key
end

local function getButton(e)
  local name = buttonName(e)
  local b = buttons[name]
  if not b then
    if InCombatLockdown() then return nil end
    b = CreateFrame("Button", name, UIParent, "SecureActionButtonTemplate")
    b:RegisterForClicks("AnyUp", "AnyDown")
    b:SetAttribute("downcast-unitrule", UNIT_RULE)
    SecureHandlerWrapScript(b, "OnClick", header, CLICK_SNIPPET)
    -- Read-only report after each click, only when /downcast debug is on.
    b:HookScript("OnClick", function(self, _, down)
      if not debugOn then return end
      local slot = self:GetAttribute("action")
      local holds = ""
      if slot then
        local kind, id = GetActionInfo(slot)
        if kind == "spell" then
          local sub = GetSpellSubtext and GetSpellSubtext(id)
          holds = format(" holds %s (%s)", GetSpellInfo(id) or "?", (sub and sub ~= "") and sub or "?")
        else
          holds = " holds " .. tostring(kind)
        end
      end
      say("%s click: down=%s unit=%s type=%s slot=%s%s useOnKeyDown=%s",
        self:GetName(), tostring(down), tostring(self:GetAttribute("unit")),
        tostring(self:GetAttribute("type")), tostring(slot), holds,
        tostring(self:GetAttribute("useOnKeyDown")))
    end)
    buttons[name] = b
  end
  return b
end

-- With no "action" attribute Blizzard's button falls back to slot 1, so a
-- button that isn't ready must have no type at all.
local function disable(b)
  b:SetAttribute("type", nil)
  b:SetAttribute("action", nil)
end

---------------------------------------------------------------------------
-- Spellbook and action slots
---------------------------------------------------------------------------

-- Highest known rank: spellbook index, proper name, rank number, spell ID.
local function topRank(spellName)
  local want = spellName:lower()
  local bestIndex, bestName, bestRank
  for tab = 1, GetNumSpellTabs() do
    local _, _, offset, numSpells = GetSpellTabInfo(tab)
    for i = offset + 1, offset + numSpells do
      local name, subtext = GetSpellBookItemName(i, BOOK)
      if name and name:lower() == want then
        local rank = tonumber(subtext and subtext:match("%d+")) or 0
        if not bestRank or rank >= bestRank then
          bestIndex, bestName, bestRank = i, name, rank
        end
      end
    end
  end
  if not bestIndex then return nil end
  local _, spellID = GetSpellBookItemInfo(bestIndex, BOOK)
  return bestIndex, bestName, bestRank, spellID
end

-- True if the slot holds any rank of this spell.
local function slotHolds(slot, spellName)
  local kind, id = GetActionInfo(slot)
  if kind ~= "spell" or not id then return false end
  local name = GetSpellInfo(id)
  return name ~= nil and name:lower() == spellName:lower()
end

local function slotClaimed(slot, except)
  for _, e in ipairs(db.spells) do
    if e ~= except and e.slot == slot then return true end
  end
  return false
end

local function freeSlot(except)
  for slot = MAX_SLOT, 1, -1 do
    if not HasAction(slot) and not slotClaimed(slot, except) then return slot end
  end
end

local function ownsSlot(slot)
  if slot == 0 then return true end
  for _, e in ipairs(db.spells) do
    if e.slot == slot then return true end
  end
  return false
end

---------------------------------------------------------------------------
-- Keeping slots and buttons up to date (out of combat only)
---------------------------------------------------------------------------

local function syncEntry(e)
  local b = getButton(e)
  if not b then return end

  local index, name, rank, spellID = topRank(e.spell)
  if not index then
    disable(b)
    status[e] = "not in your spellbook"
    return
  end
  e.spell = name

  local slot = e.slot
  if not (slot and slotHolds(slot, name)) then
    -- Our old slot is gone or something else is in it now. Never overwrite it.
    slot = freeSlot(e)
    if not slot then
      disable(b)
      e.slot = nil
      status[e] = "no empty action slot to use"
      return
    end
  end

  local kind, current = GetActionInfo(slot)
  if not (kind == "spell" and current == spellID) then
    ClearCursor()
    PickupSpellBookItem(index, BOOK)
    PlaceAction(slot)
    ClearCursor()
    kind, current = GetActionInfo(slot)
  end
  if not (kind == "spell" and current == spellID) then
    disable(b)
    status[e] = "could not place it in an action slot"
    return
  end

  e.slot = slot
  b:SetAttribute("type", "action")
  b:SetAttribute("action", slot)
  status[e] = rank > 0 and format("ready, top rank %d", rank) or "ready"
end

local queueSync

local function sync()
  syncQueued = false
  if not (db and worldReady) then return end
  if InCombatLockdown() then
    pendingCombat = true
    return
  end
  if GetCursorInfo() then
    -- Don't drop whatever the player is dragging. Try again shortly.
    queueSync(1)
    return
  end
  pendingCombat = false
  for _, e in ipairs(db.spells) do syncEntry(e) end
end

queueSync = function(delay)
  if syncQueued then return end
  syncQueued = true
  C_Timer.After(delay or 0.1, sync)
end

---------------------------------------------------------------------------
-- Slash command
---------------------------------------------------------------------------

local function findEntry(key)
  key = strtrim(key or ""):lower()
  if key == "" then return nil end
  local bare = key:match("^downcast(.+)$")
  for i, e in ipairs(db.spells) do
    local k = e.key:lower()
    if k == key or k == bare then return e, i end
  end
end

local function help()
  say("commands:")
  print("  /downcast  - list your buttons and the /click line for each")
  print("  /downcast spells  - list spells in your spellbook worth adding")
  print("  /downcast add <spell name>  - add a spell, e.g. /downcast add Abolish Disease")
  print("  /downcast add <spell name> as <ButtonName>  - pick a shorter button name")
  print("  /downcast remove <ButtonName>  - remove a button")
  print("  /downcast debug  - print what each click does, for troubleshooting")
end

local function list()
  if #db.spells == 0 then
    say("no spells yet. Add one with /downcast add <spell name>")
    return
  end
  say("put these lines in your macros:")
  for _, e in ipairs(db.spells) do
    print(format("  /click %s  -  %s (%s)", buttonName(e), e.spell, status[e] or "waiting"))
  end
  if pendingCombat then say("changes will apply when combat ends.") end
end

-- Spells worth a button: castable on others, with more than one rank.
local function spells()
  local best, names = {}, {}
  for tab = 1, GetNumSpellTabs() do
    local _, _, offset, numSpells = GetSpellTabInfo(tab)
    for i = offset + 1, offset + numSpells do
      local name, subtext = GetSpellBookItemName(i, BOOK)
      local rank = tonumber(subtext and subtext:match("%d+"))
      local helpful = (not IsHelpfulSpell) or IsHelpfulSpell(i, BOOK)
      local passive = IsPassiveSpell and IsPassiveSpell(i, BOOK)
      if name and rank and helpful and not passive then
        if not best[name] then names[#names + 1] = name end
        best[name] = math.max(best[name] or 0, rank)
      end
    end
  end
  table.sort(names)

  local shown = 0
  for _, name in ipairs(names) do
    if best[name] >= 2 then
      if shown == 0 then say("spells you can cast on others that have more than one rank:") end
      shown = shown + 1
      local added
      for _, e in ipairs(db.spells) do
        if e.spell:lower() == name:lower() then added = e end
      end
      print(format("  %s (rank %d)%s", name, best[name],
        added and (", added as " .. buttonName(added)) or ""))
    end
  end
  if shown == 0 then
    say("no spells in your spellbook that you cast on others have more than one rank yet.")
  else
    say("add one with /downcast add <spell name>")
  end
end

local function add(args)
  local spell, key = args:match("^(.-)%s+[Aa][Ss]%s+(%S+)$")
  spell = strtrim(spell or args)
  if spell == "" then
    say("usage: /downcast add <spell name> [as <ButtonName>]")
    return
  end
  key = key or (spell:gsub("[^%w]", ""))
  if not key:match("^%a%w*$") or #key > MAX_KEY_LEN then
    say("button names must start with a letter, use only letters and numbers, and be at most %d long.", MAX_KEY_LEN)
    return
  end
  if InCombatLockdown() then say("can't add spells in combat.") return end
  if GetCursorInfo() then say("drop what's on your cursor first.") return end
  if findEntry(key) then say("you already have a button called %s.", "Downcast" .. key) return end
  for _, e in ipairs(db.spells) do
    if e.spell:lower() == spell:lower() then
      say("%s is already covered by %s.", e.spell, buttonName(e))
      return
    end
  end

  local index, name = topRank(spell)
  local e = { key = key, spell = name or spell }
  tinsert(db.spells, e)
  syncEntry(e)
  say("added. Use this line in your macro: /click %s", buttonName(e))
  if not index then
    say("%s isn't in your spellbook. Check the spelling. It will start working once you learn it.", spell)
  end
end

local function remove(args)
  local e, i = findEntry(args)
  if not e then say("no button called %s. Type /downcast to see your buttons.", strtrim(args)) return end
  if InCombatLockdown() then say("can't remove spells in combat.") return end
  if GetCursorInfo() then say("drop what's on your cursor first.") return end
  if e.slot and slotHolds(e.slot, e.spell) then
    ClearCursor()
    PickupAction(e.slot)
    ClearCursor()
  end
  local b = buttons[buttonName(e)]
  if b then disable(b) end
  tremove(db.spells, i)
  status[e] = nil
  say("removed %s. Macros that click it will do nothing now.", buttonName(e))
end

SLASH_DOWNCAST1 = "/downcast"
SlashCmdList.DOWNCAST = function(msg)
  if not db then
    say("didn't finish loading, so it can't run. Check BugSack or /console scriptErrors 1 for the error.")
    return
  end
  local cmd, rest = strtrim(msg or ""):match("^(%S*)%s*(.-)$")
  cmd = cmd:lower()
  if cmd == "" or cmd == "list" then list()
  elseif cmd == "spells" then spells()
  elseif cmd == "debug" then
    debugOn = not debugOn
    say("debug %s.%s", debugOn and "on" or "off", debugOn
      and format(" Cast-on-key-press setting is %s. Each click will print a line.", tostring(GetCVarBool("ActionButtonUseKeyDown")))
      or "")
  elseif cmd == "add" then add(rest)
  elseif cmd == "remove" then remove(rest)
  else help() end
end

---------------------------------------------------------------------------
-- Events
---------------------------------------------------------------------------

local events = CreateFrame("Frame")
-- SPELLS_CHANGED also covers learning a new rank. Each registration is
-- guarded: the game throws on event names it doesn't have, and one bad name
-- must never stop the rest of the addon from loading.
for _, event in ipairs({ "ADDON_LOADED", "PLAYER_ENTERING_WORLD", "SPELLS_CHANGED",
                         "ACTIONBAR_SLOT_CHANGED", "PLAYER_REGEN_ENABLED" }) do
  if not pcall(events.RegisterEvent, events, event) then
    say("this game version has no %s event. Please report it.", event)
  end
end
events:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 ~= ADDON then return end
    DowncastCharDB = DowncastCharDB or {}
    db = DowncastCharDB
    db.spells = db.spells or {}
    if not db.seeded then
      db.seeded = true
      local _, class = UnitClass("player")
      if class == "PRIEST" then
        for _, d in ipairs(PRIEST_DEFAULTS) do
          tinsert(db.spells, { key = d.key, spell = d.spell })
        end
      end
    end
  elseif not db then
    return
  elseif event == "PLAYER_ENTERING_WORLD" then
    -- Action bar contents are only reliable from here on.
    worldReady = true
    queueSync()
  elseif event == "PLAYER_REGEN_ENABLED" then
    if pendingCombat then queueSync() end
  elseif event == "ACTIONBAR_SLOT_CHANGED" then
    if ownsSlot(arg1) then queueSync() end
  else
    queueSync()
  end
end)
