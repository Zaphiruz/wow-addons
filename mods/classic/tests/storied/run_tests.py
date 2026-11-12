"""Runs Storied.lua against a small fake WoW API. Usage: python run_tests.py path/to/Storied.lua"""
import pathlib
import sys
from lupa import lua51

ADDON = open(sys.argv[1], encoding="utf-8").read()
GUARD = (pathlib.Path(__file__).parent.parent / "guard_globals.lua").read_text(encoding="utf-8")

MOCK = r'''
out, events = {}, {}
function print(...) local t = {} for i = 1, select("#", ...) do t[#t+1] = tostring(select(i, ...)) end out[#out+1] = table.concat(t, " ") end
format, tinsert, tremove = string.format, table.insert, table.remove
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
SlashCmdList = {}
UISpecialFrames = {}
StaticPopupDialogs = {}

-- Clocks: GetTime counts seconds since the client started, time() is the date.
now = 100
function GetTime() return now end
clock = os.time({ year = 2026, month = 11, day = 11, hour = 12 })
function time() return clock end
date = os.date
timers = {}
C_Timer = { After = function(d, fn) table.insert(timers, { at = now + d, fn = fn }) end }
function advance(seconds)
  local stop = now + seconds
  while true do
    local nextIdx
    for i, t in ipairs(timers) do
      if t.at <= stop and (not nextIdx or t.at < timers[nextIdx].at) then nextIdx = i end
    end
    if not nextIdx then break end
    local t = table.remove(timers, nextIdx)
    if t.at > now then clock = clock + (t.at - now); now = t.at end
    t.fn()
  end
  clock = clock + (stop - now)
  now = stop
end
function days(n) clock = clock + n * 86400 end

-- Units.
units = {
  player = { name = "Zaphiruz", guid = "Player-1-0001", isPlayer = true },
}
function UnitName(u) local x = units[u]; if x then return x.name, x.realm end end
function UnitGUID(u) local x = units[u]; if x then return x.guid end end
function UnitIsPlayer(u) local x = units[u]; return x ~= nil and x.isPlayer == true end
function UnitIsUnit(a, b) return units[a] ~= nil and units[a] == units[b] end
function UnitIsDeadOrGhost(u) local x = units[u]; return x ~= nil and x.dead == true end
function GetRealmName() return "Whitemane" end
function GetNormalizedRealmName() return "Whitemane" end
function Ambiguate(full, how)
  local name, realm = full:match("^(.-)%-(.+)$")
  if name and (how == "short" or realm == "Whitemane") then return name end
  return full
end
function GetRealZoneText() return zoneName end
zoneName = "Elwynn Forest"
groupSize = 0
function GetNumGroupMembers() return groupSize end

-- Groups: join(...) puts players in your party (or raid), leave() empties it.
raid = false
instance = nil   -- the dungeon or raid you're in, or nil outside
function IsInRaid() return raid end
function IsInInstance() return instance ~= nil, instance and "party" or "none" end
function GetInstanceInfo() return instance or zoneName end
function join(...)
  local prefix = raid and "raid" or "party"
  for i = 1, 40 do units["party" .. i], units["raid" .. i] = nil, nil end
  local list = { ... }
  for i, p in ipairs(list) do
    local name, realm = p:match("^(.-)%-(.+)$")
    units[prefix .. i] = { name = name or p, realm = realm, guid = "Player-1-" .. p, isPlayer = true }
  end
  if raid then units["raid" .. (#list + 1)] = units.player end
  groupSize = #list > 0 and (#list + 1) or 0
  fire("GROUP_ROSTER_UPDATE")
end
function leave() join() end
function enter(place) instance = place; zoneName = place or "Elwynn Forest"; fire("PLAYER_ENTERING_WORLD") end

-- Resurrects, summons and soulstones.
function AcceptResurrect() end
C_SummonInfo = { GetSummonConfirmSummoner = function() return summoner end, ConfirmSummon = function() end }
C_DeathInfo = { UseSelfResurrectOption = function(kind, id) end }
playerAuras = {}
C_UnitAuras = { GetAuraDataByIndex = function(unit, i, filter) if unit == "player" then return playerAuras[i] end end }
function soulstone(by) playerAuras = { { name = "Soulstone Resurrection", spellId = 20765, sourceUnit = by } }
                       fire("UNIT_AURA", "player") end
function die() playerAuras = {}; units.player.dead = true; fire("UNIT_AURA", "player"); fire("PLAYER_DEAD") end
function alive() units.player.dead = false; fire("PLAYER_ALIVE") end

-- Your level, and asking the server for /played.
units.player.level = 39
function UnitLevel(u) local x = units[u]; return x and x.level end
function UnitExists(u) return units[u] ~= nil end
function UnitCanAttack(a, b) local x = units[b]; return x ~= nil and x.hostile == true end
function UnitIsFeignDeath(u) local x = units[u]; return x ~= nil and x.feign == true end
playedRequests = 0
function RequestTimePlayed() playedRequests = playedRequests + 1 end
function played(total, thisLevel) fire("TIME_PLAYED_MSG", total, thisLevel) end
function ding(level) units.player.level = level; fire("PLAYER_LEVEL_UP", level, 10, 10, 1, 0, 1, 1, 1, 1, 1) end

-- Chat windows, which show the /played reply when they're registered for it.
NUM_CHAT_WINDOWS = 2
local function chatFrame(registered)
  local f = { registered = registered }
  function f:IsEventRegistered(e) return self.registered[e] == true end
  function f:RegisterEvent(e) self.registered[e] = true end
  function f:UnregisterEvent(e) self.registered[e] = nil end
  return f
end
ChatFrame1 = chatFrame({ TIME_PLAYED_MSG = true, CHAT_MSG_SYSTEM = true })
ChatFrame2 = chatFrame({})

-- The combat log (Classic Era only): something hits you.
cleu = {}
C_CombatLog = { GetCurrentEventInfo = function() return unpack(cleu, 1, 20) end }
function hit(source, spell)
  local sub = spell and "SPELL_DAMAGE" or "SWING_DAMAGE"
  cleu = { 1, sub, false, creature(1), source, 0, 0, "Player-1-0001", "Zaphiruz", 0, 0 }
  if spell then cleu[12], cleu[13], cleu[14], cleu[15] = 1, spell, 1, 120 else cleu[12] = 120 end
  fire("COMBAT_LOG_EVENT_UNFILTERED")
end
function env(kind)
  cleu = { 1, "ENVIRONMENTAL_DAMAGE", false, "", nil, 0, 0, "Player-1-0001", "Zaphiruz", 0, 0, kind, 500 }
  fire("COMBAT_LOG_EVENT_UNFILTERED")
end

-- Chat.
whispers, lockdown = {}, false
C_ChatInfo = {
  SendChatMessage = function(msg, chatType, lang, target)
    assert(#msg <= 255, "message too long")
    table.insert(whispers, chatType .. ":" .. tostring(target) .. ": " .. msg)
  end,
  InChatMessagingLockdown = function() return lockdown end,
}

-- Items, as the client describes them.
ITEMS = {
  [12784] = { name = "Arcanite Reaper",     quality = 4, loc = "INVTYPE_2HWEAPON", class = 2 },
  [19137] = { name = "Onslaught Girdle",    quality = 4, loc = "INVTYPE_WAIST",    class = 4 },
  [4634]  = { name = "Heavy Lockbox",        quality = 1, loc = "",                 class = 15 },
  [14136] = { name = "Silver-thread Cloak", quality = 3, loc = "INVTYPE_CLOAK",    class = 4 },
  [2589]  = { name = "Linen Cloth",         quality = 1, loc = "",                 class = 7 },
  [1000]  = { name = "Tattered Cloak",      quality = 0, loc = "INVTYPE_CLOAK",    class = 4 },
  [2504]  = { name = "Worn Shortbow",       quality = 1, loc = "INVTYPE_RANGED",   class = 2 },
  [858]   = { name = "Lesser Healing Potion", quality = 1, loc = "",               class = 0 },
  [6125]  = { name = "Brawler's Harness",   quality = 2, loc = "INVTYPE_CHEST",    class = 4 },
  [15564] = { name = "Rugged Armor Kit",    quality = 1, loc = "",                 class = 0, spell = 19057 },
}

local function idOf(item)
  if type(item) == "number" then return item end
  return tonumber(tostring(item):match("item:(%d+)"))
end
function link(id, enchant)
  return format("|cffa335ee|Hitem:%d:%d:0:0:0:0:0:0|h[%s]|h|r", id, enchant or 0, ITEMS[id].name)
end
C_Item = {
  GetItemInfoInstant = function(item)
    local id = idOf(item); local i = ITEMS[id]
    if i then return id, "Type", "Sub", i.loc, 134400, i.class, 0 end
  end,
  GetItemQualityByID = function(item) local i = ITEMS[idOf(item)]; return i and i.quality end,
  GetItemSpell = function(item) local i = ITEMS[idOf(item)]; if i and i.spell then return SPELLS[i.spell], i.spell end end,
}

-- Hooks on the game's own functions.
function hooksecurefunc(a, b, c)
  local t, name, fn = a, b, c
  if type(a) == "string" then t, name, fn = _G, a, b end
  local orig = t[name]
  assert(orig, "hooked a missing function " .. tostring(name))
  t[name] = function(...) local r = { orig(...) }; fn(...); return unpack(r) end
end

-- Bags: what's in each bag slot, and using one.
bags = {}
NUM_BAG_SLOTS = 4
C_Container = {
  GetContainerNumSlots = function(bag) return 16 end,
  GetContainerItemLink = function(bag, slot) return bags[bag .. ":" .. slot] end,
  UseContainerItem = function(bag, slot) end,
}

-- Equipped gear: item ID in each slot, and its enchant.
equipped, wornEnchant = {}, {}
function GetInventoryItemID(unit, slot) if unit == "player" then return equipped[slot] end end
function GetInventoryItemLink(unit, slot)
  if unit == "player" and equipped[slot] then return link(equipped[slot], wornEnchant[slot]) end
end

-- An enchant lands on an item in your bags, or on one you wear.
function enchantBag(where, enchant)
  bags[where] = link(idOf(bags[where]), enchant)
  fire("BAG_UPDATE", tonumber(where:match("^(%d+)")))
  fire("BAG_UPDATE_DELAYED")
end
function enchantWorn(slot, enchant)
  wornEnchant[slot] = enchant
  fire("UNIT_INVENTORY_CHANGED", "player")
  fire("PLAYER_EQUIPMENT_CHANGED", slot, false)
end

-- Trade window.
TRADE_ENCHANT_SLOT = 7
ERR_TRADE_COMPLETE = "Trade complete."
tradeMine, tradeTheirs, tradeEnchant = {}, {}, nil
function GetTradePlayerItemLink(i) return tradeMine[i] end
function GetTradePlayerItemInfo(i)
  if tradeMine[i] then return "name", 1, 1, 4, i == 7 and tradeEnchant or nil end
end
function GetTradeTargetItemLink(i) return tradeTheirs[i] end
-- Trade with someone: opts.mine = my item in the "Will not be traded" slot,
-- opts.enchant = what they cast on it, opts.give = items they hand over.
function trade(partner, opts)
  opts = opts or {}
  units.NPC = { name = partner }
  tradeMine, tradeTheirs, tradeEnchant = {}, {}, nil
  fire("TRADE_SHOW")
  if opts.mine then tradeMine[7] = opts.mine; fire("TRADE_PLAYER_ITEM_CHANGED", 7) end
  for i, l in ipairs(opts.give or {}) do tradeTheirs[i] = l; fire("TRADE_TARGET_ITEM_CHANGED", i) end
  if opts.enchant then tradeEnchant = opts.enchant; fire("TRADE_PLAYER_ITEM_CHANGED", 7) end
  fire("TRADE_ACCEPT_UPDATE", 1, 1)
  fire("TRADE_CLOSED")
  tradeMine, tradeTheirs, tradeEnchant = {}, {}, nil
  units.NPC = nil
  if not opts.cancel then fire("UI_INFO_MESSAGE", 226, ERR_TRADE_COMPLETE) end
end

-- Loot.
LOOT_ITEM_SELF = "You receive loot: %s."
LOOT_ITEM_SELF_MULTIPLE = "You receive loot: %sx%d."
LOOT_ITEM_PUSHED_SELF = "You receive item: %s."
LOOT_ITEM_PUSHED_SELF_MULTIPLE = "You receive item: %sx%d."
LOOT_ITEM = "%s receives loot: %s."
lootSlots = {}   -- { link, source GUID }
function GetNumLootItems() return #lootSlots end
function GetLootSlotLink(i) return lootSlots[i] and lootSlots[i][1] end
function GetLootSourceInfo(i) if lootSlots[i] then return lootSlots[i][2], 1 end end
-- Open a loot window from source and take everything in it.
function loot(source, links, opts)
  opts = opts or {}
  lootSlots = {}
  for _, l in ipairs(links) do table.insert(lootSlots, { l, source }) end
  fire("LOOT_OPENED", true)
  if not opts.roll then
    for _, l in ipairs(links) do fire("CHAT_MSG_LOOT", format(LOOT_ITEM_SELF, l), "Zaphiruz") end
  end
  fire("LOOT_CLOSED")
  lootSlots = {}
end
function received(l) fire("CHAT_MSG_LOOT", format(LOOT_ITEM_PUSHED_SELF, l), "Zaphiruz") end
function looted(l) fire("CHAT_MSG_LOOT", format(LOOT_ITEM_SELF, l), "Zaphiruz") end
function creature(n) return "Creature-0-1-0-0-" .. n .. "-0001" end

-- Spells.
function cast(spellID, target)
  fire("UNIT_SPELLCAST_SENT", "player", target or "", "Cast-1", spellID)
  fire("UNIT_SPELLCAST_SUCCEEDED", "player", "Cast-1", spellID)
end
SPELLS = { [75] = "Auto Shot", [5019] = "Shoot", [3365] = "Opening", [585] = "Smite", [133] = "Fireball",
           [13882] = "Enchant Cloak - Lesser Agility", [20030] = "Enchant 2H Weapon - Superior Impact",
           [19057] = "Rugged Armor Kit", [458] = "Brown Horse" }
function GetSpellInfo(id) return SPELLS[id] end

-- Quests and vendors.
questTitle = nil
function GetTitleText() return questTitle end

-- Mail.
mail = {}   -- index -> { sender, invoice, items = { links } }
function GetInboxHeaderInfo(i) local m = mail[i]; if m then return nil, nil, m.sender, "subject", 0, 0, 30, #m.items end end
function GetInboxInvoiceInfo(i) local m = mail[i]; return m and m.invoice end
function GetInboxItemLink(i, a) local m = mail[i]; return m and m.items[a] end
function TakeInboxItem(i, a) end
function AutoLootMailItem(i) end
ATTACHMENTS_MAX_RECEIVE = 16

-- Forever hides some values from addons ("secret values").
SECRET = setmetatable({}, { __index = function() error("read a secret value") end })
function issecretvalue(v) return rawequal(v, SECRET) end

-- Frames.
local noop = function() end
local widgetMT = { __index = function() return noop end }
function widget(kind, name, parent, template)
  local w = setmetatable({ kind = kind, name = name, parent = parent, template = template, scripts = {}, hooks = {},
                           shown = false, text = "", checked = false }, widgetMT)
  function w:SetScript(s, fn) self.scripts[s] = fn end
  function w:GetScript(s) return self.scripts[s] end
  function w:HookScript(s, fn) self.hooks[s] = self.hooks[s] or {}; table.insert(self.hooks[s], fn) end
  function w:RunHooks(s, ...) for _, fn in ipairs(self.hooks[s] or {}) do fn(self, ...) end end
  function w:RegisterEvent(e) events[e] = self end
  function w:GetName() return self.name end
  function w:SetText(t) self.text = t == nil and "" or tostring(t) end
  function w:GetText() return self.text end
  function w:SetChecked(v) self.checked = not not v end
  function w:GetChecked() return self.checked end
  function w:SetMaxLetters(n) self.maxLetters = n end
  -- The player types into an edit box.
  function w:Type(t)
    if self.maxLetters and #t > self.maxLetters then t = t:sub(1, self.maxLetters) end
    self.text = t
    if self.scripts.OnTextChanged then self.scripts.OnTextChanged(self, true) end
  end
  function w:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
  function w:Hide() self.shown = false; if self.scripts.OnHide then self.scripts.OnHide(self) end end
  function w:IsShown() return self.shown end
  function w:GetStringHeight() return 0 end
  function w:CreateFontString(n) return widget("FontString", n, self) end
  function w:Click(button)
    if self.kind == "CheckButton" then self.checked = not self.checked end
    if self.scripts.OnClick then self.scripts.OnClick(self, button or "LeftButton") end
  end
  return w
end
function CreateFrame(kind, name, parent, template)
  local w = widget(kind, name, parent, template)
  if name then _G[name] = w end
  return w
end
UIParent = widget("Frame", "UIParent")

-- The game's settings window.
categories, opened = {}, nil
Settings = {
  RegisterCanvasLayoutCategory = function(frame, name)
    local c = { frame = frame, name = name, id = 88 }
    function c:GetID() return self.id end
    return c
  end,
  RegisterAddOnCategory = function(c) table.insert(categories, c) end,
  OpenToCategory = function(id) opened = id end,
}

-- The game tooltip, with the item data hook the client offers.
GameTooltip = widget("GameTooltip", "GameTooltip")
GameTooltip.lines, GameTooltip.item = {}, false
function GameTooltip:AddLine(t) table.insert(self.lines, t) end
function GameTooltip:ClearLines() self.lines = {}; self.item = false; self:RunHooks("OnTooltipCleared") end
function GameTooltip:GetItem() if self.item then return ITEMS[idOf(self.item)].name, self.item end end
function GameTooltip:GetUnit() if self.unit then return UnitName(self.unit), self.unit end end
Enum = { TooltipDataType = { Item = 0, Unit = 2 } }
postCalls = {}
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn)
  postCalls[kind] = postCalls[kind] or {}; table.insert(postCalls[kind], fn) end }
function plain(s) return (tostring(s):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")) end
-- Hover an item: the client fills the tooltip and runs the item hooks.
function hover(l)
  GameTooltip:ClearLines()
  GameTooltip:AddLine(ITEMS[idOf(l)].name)
  GameTooltip.item = l
  if TooltipDataProcessor then
    for _, fn in ipairs(postCalls[Enum.TooltipDataType.Item] or {}) do fn(GameTooltip, { type = 0, id = idOf(l) }) end
  else
    GameTooltip:RunHooks("OnTooltipSetItem")
  end
  GameTooltip:Show()
  local t = {}
  for i = 2, #GameTooltip.lines do t[#t+1] = plain(GameTooltip.lines[i]) end
  return table.concat(t, "\n")
end
-- Hover a player: their name and level line, then the unit hooks.
function hoverUnit(u)
  GameTooltip:ClearLines()
  GameTooltip.unit = u
  GameTooltip:AddLine(tostring(UnitName(u)))
  GameTooltip:AddLine("Level 60 Human Priest (Player)")
  if TooltipDataProcessor then
    for _, fn in ipairs(postCalls[Enum.TooltipDataType.Unit] or {}) do fn(GameTooltip, { type = 2 }) end
  else
    GameTooltip:RunHooks("OnTooltipSetUnit")
  end
  GameTooltip:Show()
  GameTooltip.unit = nil
  local t = {}
  for i = 3, #GameTooltip.lines do t[#t+1] = plain(GameTooltip.lines[i]) end
  return table.concat(t, "\n")
end

function fire(e, ...) local f = events[e]; if f then f.scripts.OnEvent(f, e, ...) end end
function login(saved, charSaved)
  StoriedDB, StoriedCharDB = saved, charSaved
  events, timers, categories, postCalls = {}, {}, {}, {}
  GameTooltip.hooks = {}
  assert(loadstring(ADDON_SRC, "Storied.lua"))("Storied")
  fire("ADDON_LOADED", "Storied")
  fire("PLAYER_LOGIN")
end
function cmd(s) out = {}; SlashCmdList.STORIED(s); return table.concat(out, "\n") end
function ok(c, m) if not c then error("FAIL: " .. tostring(m), 2) end end
function panel() return categories[1].frame end
function kill(attacker) fire("PARTY_KILL", attacker or "Player-1-0001", creature(299)) end
-- The story window's text, without colours.
function story() return plain(StoriedStory.list:GetText()) end
function summary() return plain(StoriedStory.summary:GetText()) end
'''

SCENARIOS = {
# ---- settings ----
"first login turns everything on and adds a settings page": r'''
  login(nil, nil)
  ok(StoriedDB.enchants and StoriedDB.origin and StoriedDB.kills and StoriedDB.tooltips, "all on")
  ok(StoriedDB.grouped and StoriedDB.help and StoriedDB.thanks == false, "people on, thanks off")
  ok(type(StoriedCharDB.items) == "table" and type(StoriedCharDB.people) == "table", "histories")
  ok(categories[1] and categories[1].name == "Storied", "settings page")
  cmd("settings")
  ok(opened == 88, "/storied settings opens the settings")
''',
"each switch is saved, and older saves get new switches": r'''
  login({ kills = false }, { items = { [12784] = { kills = 5 } } })
  ok(StoriedDB.kills == false and StoriedDB.origin == true, "kept the old choice, added the rest")
  ok(StoriedCharDB.items[12784].kills == 5, "kept the history")
  panel():Show()
  local box = panel().checks.kills
  ok(box:GetChecked() == false, "box shows the saved choice")
  box:Click()
  ok(StoriedDB.kills == true, "clicking saves it")
''',

# ---- enchants ----
"an enchant done through a trade is remembered with who and when": r'''
  login(nil, nil)
  trade("Bob", { mine = link(12784), enchant = "Enchant 2H Weapon - Crusader" })
  local t = hover(link(12784, 1900))
  ok(t == "Crusader by Bob, 11 Nov 2026", t)
''',
"a cancelled trade records nothing": r'''
  login(nil, nil)
  trade("Bob", { mine = link(12784), enchant = "Crusader", cancel = true })
  ok(hover(link(12784, 1900)) == "", "recorded a cancelled trade")
''',
"once the enchant is replaced, the old one isn't shown": r'''
  login(nil, nil)
  trade("Bob", { mine = link(12784), enchant = "Enchant 2H Weapon - Crusader" })
  ok(hover(link(12784, 1900)) == "Crusader by Bob, 11 Nov 2026", "learns the enchant from the item")
  ok(hover(link(12784, 1898)) == "", "a different enchant now: " .. hover(link(12784, 1898)))
  ok(hover(link(12784)) == "", "no enchant at all")
  trade("Cid", { mine = link(12784, 1900), enchant = "Lifestealing" })
  ok(hover(link(12784, 1898)) == "Lifestealing by Cid, 11 Nov 2026", hover(link(12784, 1898)))
''',
"with enchants switched off, none are recorded": r'''
  login({ enchants = false }, nil)
  trade("Bob", { mine = link(12784), enchant = "Crusader" })
  ok(hover(link(12784, 1900)) == "", "recorded while off")
  bags["0:1"] = link(14136); fire("BAG_UPDATE_DELAYED")
  cast(13882); enchantBag("0:1", 849)
  ok(hover(link(14136, 849)) == "", "recorded your own while off")
''',
"an enchant you put on your own gear is remembered as yours": r'''
  bags["0:1"] = link(14136)
  equipped[16] = 12784
  login(nil, nil)
  cast(13882); enchantBag("0:1", 849)
  local t = hover(link(14136, 849))
  ok(t == "Lesser Agility by you, 11 Nov 2026", "in your bags: " .. t)
  -- The item can change before the game says the cast succeeded.
  advance(60)
  fire("UNIT_SPELLCAST_SENT", "player", "", "Cast-2", 20030)
  enchantWorn(16, 1896)
  fire("UNIT_SPELLCAST_SUCCEEDED", "player", "Cast-2", 20030)
  t = hover(link(12784, 1896))
  ok(t == "Superior Impact by you, 11 Nov 2026", "worn: " .. t)
''',
"an item you use on your gear is remembered by its name": r'''
  bags["0:2"] = link(15564)
  equipped[5] = 6125
  login(nil, nil)
  C_Container.UseContainerItem(0, 2)
  advance(20)  -- picking the item to use it on can take a while
  cast(19057); enchantWorn(5, 1843)
  local t = hover(link(6125, 1843))
  ok(t:find("^Rugged Armor Kit by you, 11 Nov 2026"), t)
''',
"an enchant that appears without a cast of yours isn't credited to you": r'''
  bags["0:1"] = link(14136)
  login(nil, nil)
  enchantBag("0:1", 849)
  ok(hover(link(14136, 849)) == "", "with no cast: " .. hover(link(14136, 849)))
  cast(13882); advance(30); enchantBag("0:1", 850)
  ok(hover(link(14136, 850)) == "", "a cast long before: " .. hover(link(14136, 850)))
  -- Gear that arrives already enchanted (from the auction house) isn't yours.
  cast(458); bags["0:3"] = link(19137, 2523); fire("BAG_UPDATE_DELAYED")
  ok(hover(link(19137, 2523)) == "", "arrived enchanted: " .. hover(link(19137, 2523)))
''',
"a trade enchant stays credited to the enchanter": r'''
  bags["0:1"] = link(12784)
  login(nil, nil)
  trade("Bob", { mine = link(12784), enchant = "Enchant 2H Weapon - Crusader" })
  enchantBag("0:1", 1900)
  ok(hover(link(12784, 1900)) == "Crusader by Bob, 11 Nov 2026", hover(link(12784, 1900)))
''',
"replacing an enchant yourself shows yours instead": r'''
  equipped[16] = 12784; wornEnchant[16] = 1900
  login(nil, nil)
  trade("Bob", { mine = link(12784, 1900), enchant = "Enchant 2H Weapon - Crusader" })
  ok(hover(link(12784, 1900)) == "Crusader by Bob, 11 Nov 2026", "Bob's first")
  advance(60)
  cast(20030); enchantWorn(16, 1896)
  ok(hover(link(12784, 1896)) == "Superior Impact by you, 11 Nov 2026", hover(link(12784, 1896)))
''',
"/storied debug says when you enchant your gear": r'''
  bags["0:1"] = link(14136)
  login(nil, nil)
  cmd("debug"); out = {}
  cast(13882); enchantBag("0:1", 849)
  local o = plain(table.concat(out, "\n"))
  ok(o:find("you enchanted Silver%-thread Cloak: Lesser Agility"), o)
  out = {}
  advance(30)
  enchantBag("0:1", 850)
  o = plain(table.concat(out, "\n"))
  ok(o:find("Silver%-thread Cloak got a new enchant, not from a cast of yours"), o)
''',

# ---- where it came from ----
"a drop remembers the creature, zone, date and group": r'''
  login(nil, nil)
  zoneName, groupSize = "Molten Core", 40
  units.target = { name = "Ragnaros", guid = creature(11502) }
  fire("PLAYER_TARGET_CHANGED")
  loot(creature(11502), { link(19137) })
  local t = hover(link(19137))
  ok(t == "Looted from Ragnaros, Molten Core\n11 Nov 2026, with 39 others", t)
''',
"solo, from a creature never targeted": r'''
  login(nil, nil)
  loot(creature(500), { link(6125) })
  ok(hover(link(6125)) == "Looted in Elwynn Forest\n11 Nov 2026", hover(link(6125)))
''',
"a creature seen under the mouse is named": r'''
  login(nil, nil)
  units.mouseover = { name = "Hogger", guid = creature(448) }
  fire("UPDATE_MOUSEOVER_UNIT")
  loot(creature(448), { link(6125) })
  ok(hover(link(6125)) == "Looted from Hogger, Elwynn Forest\n11 Nov 2026", hover(link(6125)))
''',
"only green and better gear gets a history": r'''
  login(nil, nil)
  loot(creature(500), { link(1000), link(2589), link(2504) })
  ok(StoriedCharDB.items[1000] == nil and StoriedCharDB.items[2589] == nil and StoriedCharDB.items[2504] == nil,
     "recorded grey, white or non-gear items")
''',
"the first time you got an item is kept": r'''
  login(nil, nil)
  loot(creature(500), { link(6125) })
  days(3)
  zoneName = "Westfall"
  loot(creature(600), { link(6125) })
  ok(hover(link(6125)) == "Looted in Elwynn Forest\n11 Nov 2026", hover(link(6125)))
''',
"an item won by a roll after the window closed still knows its source": r'''
  login(nil, nil)
  groupSize = 5
  units.target = { name = "Edwin VanCleef", guid = creature(639) }
  fire("PLAYER_TARGET_CHANGED")
  zoneName = "The Deadmines"
  loot(creature(639), { link(6125) }, { roll = true })
  advance(40)
  zoneName = "Westfall"
  looted(link(6125))
  ok(hover(link(6125)) == "Looted from Edwin VanCleef, The Deadmines\n11 Nov 2026, with 4 others", hover(link(6125)))
''',
"other players' loot isn't yours": r'''
  login(nil, nil)
  fire("CHAT_MSG_LOOT", format(LOOT_ITEM, "Bob", link(6125)), "Bob")
  ok(StoriedCharDB.items[6125] == nil, "recorded someone else's loot")
''',
"a chest is named from the Opening cast": r'''
  login(nil, nil)
  cast(3365, "Battered Chest")
  loot("GameObject-0-1-0-0-2843-0001", { link(6125) })
  ok(hover(link(6125)) == "Found in Battered Chest, Elwynn Forest\n11 Nov 2026", hover(link(6125)))
''',
"a lockbox picked by someone else names them on what was inside": r'''
  login(nil, nil)
  trade("Bob", { mine = link(4634) })
  bags["0:3"] = link(4634)
  C_Container.UseContainerItem(0, 3)
  loot("Item-1-0-0001", { link(14136) })
  ok(hover(link(14136)) == "From a Heavy Lockbox opened by Bob\n11 Nov 2026", hover(link(14136)))
  -- the next box of that kind you open yourself isn't Bob's
  advance(60)
  C_Container.UseContainerItem(0, 3)
  loot("Item-1-0-0002", { link(6125) })
  ok(hover(link(6125)) == "From a Heavy Lockbox\n11 Nov 2026", hover(link(6125)))
''',
"a potion drunk just before looting isn't the source": r'''
  login(nil, nil)
  bags["0:1"] = link(858)
  C_Container.UseContainerItem(0, 1)
  loot(nil, { link(6125) })
  ok(hover(link(6125)) == "Looted in Elwynn Forest\n11 Nov 2026", hover(link(6125)))
''',
"quest rewards, vendors, trades and mail": r'''
  login(nil, nil)
  questTitle = "The Defias Brotherhood"
  fire("QUEST_COMPLETE")
  fire("QUEST_FINISHED")
  received(link(6125))
  ok(hover(link(6125)) == "Reward from The Defias Brotherhood, 11 Nov 2026", hover(link(6125)))

  advance(30)
  units.npc = { name = "Gina MacGregor" }
  fire("MERCHANT_SHOW")
  received(link(14136))
  fire("MERCHANT_CLOSED")
  ok(hover(link(14136)) == "Bought from Gina MacGregor, 11 Nov 2026", hover(link(14136)))

  trade("Ann", { give = { link(19137) } })
  ok(hover(link(19137)) == "Traded to you by Ann, 11 Nov 2026", hover(link(19137)))

  mail[1] = { sender = "Cid", items = { link(12784) } }
  TakeInboxItem(1, 1)
  ok(hover(link(12784)) == "Mailed to you by Cid, 11 Nov 2026", hover(link(12784)))
''',
"an auction you won says so": r'''
  login(nil, nil)
  mail[2] = { sender = "Stormwind Auction House", invoice = "buyer", items = { link(6125) } }
  AutoLootMailItem(2)
  ok(hover(link(6125)) == "Won at auction, 11 Nov 2026", hover(link(6125)))
''',
"a pushed item with no quest or vendor open isn't given a source": r'''
  login(nil, nil)
  questTitle = "Old Quest"
  fire("QUEST_COMPLETE"); fire("QUEST_FINISHED")
  advance(60)
  received(link(6125))
  ok(StoriedCharDB.items[6125] == nil, "guessed a source")
''',
"with origins switched off, none are recorded": r'''
  login({ origin = false }, nil)
  loot(creature(500), { link(6125) })
  ok(StoriedCharDB.items[6125] == nil, "recorded while off")
''',

# ---- weapon kills ----
"your killing blows count on the weapon in your hand": r'''
  login(nil, nil)
  equipped[16] = 12784
  kill()
  ok(hover(link(12784)) == "1 kill", hover(link(12784)))
  kill(); kill("Player-1-0002")
  ok(hover(link(12784)) == "2 kills", "someone else's kill counted: " .. hover(link(12784)))
  for i = 1, 1200 do kill() end
  ok(hover(link(12784)) == "1,202 kills", hover(link(12784)))
''',
"a kill just after a ranged shot counts on the ranged weapon": r'''
  login(nil, nil)
  equipped[16], equipped[18] = 12784, 2504
  cast(75)
  kill()
  ok(hover(link(2504)) == "1 kill" and hover(link(12784)) == "", "ranged")
  advance(10)
  kill()
  ok(hover(link(12784)) == "1 kill", "melee again after a while")
  cast(133)   -- a spell isn't a ranged shot
  kill()
  ok(hover(link(12784)) == "2 kills", hover(link(12784)))
''',
"no weapon, nothing counted; switched off, nothing counted": r'''
  login(nil, nil)
  kill()
  ok(next(StoriedCharDB.items) == nil, "counted without a weapon")
  StoriedDB.kills = false
  equipped[16] = 12784
  kill()
  ok(next(StoriedCharDB.items) == nil, "counted while off")
''',
"all lines together, in order": r'''
  login(nil, nil)
  trade("Ann", { give = { link(12784) } })
  trade("Bob", { mine = link(12784), enchant = "Enchant 2H Weapon - Crusader" })
  equipped[16] = 12784
  for i = 1, 3 do kill() end
  local t = hover(link(12784, 1900))
  ok(t == "Crusader by Bob, 11 Nov 2026\nTraded to you by Ann, 11 Nov 2026\n3 kills", t)
''',

# ---- tooltips ----
"with tooltips off, history is kept but not shown": r'''
  login({ tooltips = false }, nil)
  equipped[16] = 12784
  kill()
  ok(hover(link(12784)) == "", "shown while off")
  StoriedDB.tooltips = true
  ok(hover(link(12784)) == "1 kill", "kept")
''',
"tooltips without the data hook still get the lines": r'''
  TooltipDataProcessor = nil
  login(nil, nil)
  equipped[16] = 12784
  kill()
  ok(hover(link(12784)) == "1 kill", hover(link(12784)))
  GameTooltip:RunHooks("OnTooltipSetItem")   -- some items set twice
  ok(#GameTooltip.lines == 2, "added twice")
  join("Bob")
  ok(hoverUnit("party1") == "Grouped once: Elwynn Forest, 11 Nov 2026", hoverUnit("party1"))
''',
"with tooltips off, players get no lines either": r'''
  login({ tooltips = false }, nil)
  join("Bob")
  ok(hoverUnit("party1") == "", hoverUnit("party1"))
''',
"items with no history get no lines": r'''
  login(nil, nil)
  ok(hover(link(6125)) == "", hover(link(6125)))
''',

# ---- grouped with ----
"grouping with someone once": r'''
  login(nil, nil)
  join("Bob")
  ok(hoverUnit("party1") == "Grouped once: Elwynn Forest, 11 Nov 2026", hoverUnit("party1"))
''',
"first and last time grouped, and how many times": r'''
  login(nil, nil)
  join("Bob")                     -- formed in the open world...
  enter("Scholomance")            -- ...the dungeon is where it happened
  enter("Scholomance")            -- running back in after a wipe isn't a new time
  enter(nil); leave()
  days(3)
  join("Bob"); enter("Stratholme")
  enter("Blackrock Spire")        -- a different dungeon with the same group is
  enter(nil)
  local t = hoverUnit("party1")
  ok(t == "First grouped: Scholomance, 11 Nov 2026\nLast: Blackrock Spire, 14 Nov 2026 (3 times)", t)
''',
"someone joining a group you're already in counts once": r'''
  login(nil, nil)
  join("Bob")
  join("Bob", "Ann")
  join("Bob", "Ann", "Cid")
  ok(StoriedCharDB.people["Bob-Whitemane"].times == 1, "Bob counted again when others joined")
  ok(StoriedCharDB.people["Cid-Whitemane"].times == 1, "Cid")
''',
"a /reload while grouped doesn't count again": r'''
  login(nil, nil)
  join("Bob")
  login(StoriedDB, StoriedCharDB)
  join("Bob")
  ok(StoriedCharDB.people["Bob-Whitemane"].times == 1, "counted again after a reload")
''',
"raids count, and you're not in your own history": r'''
  login(nil, nil)
  raid = true
  join("Bob", "Ann-Mograine")
  ok(StoriedCharDB.people["Bob-Whitemane"] and StoriedCharDB.people["Ann-Mograine"], "both recorded")
  ok(StoriedCharDB.people["Zaphiruz-Whitemane"] == nil, "recorded yourself")
  units.target = units.player
  ok(hoverUnit("target") == "", "lines on your own tooltip")
''',
"strangers and monsters get no lines": r'''
  login(nil, nil)
  units.target = { name = "Dee", guid = "Player-1-Dee", isPlayer = true }
  ok(hoverUnit("target") == "", hoverUnit("target"))
  units.target = { name = "Hogger", guid = creature(448) }
  ok(hoverUnit("target") == "", hoverUnit("target"))
''',
"with grouped-with switched off, nothing is recorded": r'''
  login({ grouped = false }, nil)
  join("Bob")
  ok(StoriedCharDB.people["Bob-Whitemane"] == nil, "recorded while off")
''',

# ---- help ----
"an accepted resurrect is remembered": r'''
  login(nil, nil)
  join("Bob")
  fire("RESURRECT_REQUEST", "Bob")
  AcceptResurrect()
  ok(hoverUnit("party1") == "Grouped once: Elwynn Forest, 11 Nov 2026\nResurrected you once, 11 Nov", hoverUnit("party1"))
  days(2)
  fire("RESURRECT_REQUEST", "Bob")
  AcceptResurrect()
  ok(StoriedCharDB.people["Bob-Whitemane"].res.n == 2, "second res")
  ok(hoverUnit("party1"):find("Resurrected you 2 times, last 13 Nov"), hoverUnit("party1"))
''',
"a declined resurrect isn't": r'''
  login(nil, nil)
  fire("RESURRECT_REQUEST", "Bob")
  advance(70)
  AcceptResurrect()   -- a much later accept belongs to someone else's offer
  ok(StoriedCharDB.people["Bob-Whitemane"] == nil, "counted a declined res")
''',
"a summon you accept is remembered": r'''
  login(nil, nil)
  summoner = "Dee-Mograine"
  fire("CONFIRM_SUMMON")
  C_SummonInfo.ConfirmSummon()
  ok(StoriedCharDB.people["Dee-Mograine"].summon.n == 1, "summon")
  units.target = { name = "Dee", realm = "Mograine", guid = "Player-1-Dee", isPlayer = true }
  ok(hoverUnit("target") == "Summoned you once, 11 Nov", hoverUnit("target"))
''',
"a soulstone is credited to whoever cast it": r'''
  login(nil, nil)
  join("Dee")
  soulstone("party1")
  die()
  C_DeathInfo.UseSelfResurrectOption(1, 20765)
  ok(hoverUnit("party1"):find("Soulstoned you once, 11 Nov"), hoverUnit("party1"))
''',
"a soulstone that ran out, or from someone unknown, isn't credited": r'''
  login(nil, nil)
  join("Dee")
  soulstone("party1")
  playerAuras = {}; fire("UNIT_AURA", "player")   -- it wore off while alive
  die()
  C_DeathInfo.UseSelfResurrectOption(1, 20765)
  alive()
  soulstone(nil)                                  -- cast by someone out of the group
  die()
  C_DeathInfo.UseSelfResurrectOption(1, 20765)
  ok(StoriedCharDB.people["Dee-Whitemane"].soulstone == nil, "credited a soulstone")
''',
"with help switched off, nothing is recorded": r'''
  login({ help = false }, nil)
  fire("RESURRECT_REQUEST", "Bob"); AcceptResurrect()
  ok(StoriedCharDB.people["Bob-Whitemane"] == nil, "recorded while off")
''',

# ---- say thanks ----
"thanks are off until you turn them on": r'''
  login(nil, nil)
  fire("RESURRECT_REQUEST", "Bob"); AcceptResurrect()
  advance(5)
  ok(#whispers == 0, "whispered while off")
  StoriedDB.thanks = true
  fire("RESURRECT_REQUEST", "Bob-Mograine"); AcceptResurrect()
  ok(#whispers == 0, "waits a moment")
  advance(5)
  ok(whispers[1] == "WHISPER:Bob-Mograine: Thanks for the res, Bob!", tostring(whispers[1]))
  summoner = "Dee"
  fire("CONFIRM_SUMMON"); C_SummonInfo.ConfirmSummon()
  advance(5)
  ok(whispers[2] == "WHISPER:Dee: Thanks for the summon, Dee!", tostring(whispers[2]))
''',
"thanks are skipped when empty or while chat is locked": r'''
  login({ thanks = true, thanksRes = "  " }, nil)
  fire("RESURRECT_REQUEST", "Bob"); AcceptResurrect()
  advance(5)
  ok(#whispers == 0, "sent an empty thanks")
  lockdown = true
  summoner = "Dee"
  fire("CONFIRM_SUMMON"); C_SummonInfo.ConfirmSummon()
  advance(5)
  ok(#whispers == 0, "whispered while chat was locked")
''',
"the thanks messages are edited in settings": r'''
  login(nil, nil)
  panel():Show()
  ok(panel().thanksRes:GetText() == "Thanks for the res, {name}!", panel().thanksRes:GetText())
  panel().thanksRes:Type("Ty {name} <3")
  panel().checks.thanks:Click()
  ok(StoriedDB.thanksRes == "Ty {name} <3" and StoriedDB.thanks == true, "saved")
  ok(panel().thanksRes.maxLetters and panel().thanksRes.maxLetters <= 200, "long messages are refused")
''',

# ---- your story ----
"your story starts at the level you were when Storied was installed": r'''
  login(nil, nil)
  local s = StoriedCharDB.story
  ok(#s == 1 and s[1].kind == "start" and s[1].level == 39, "start entry")
  login(StoriedDB, StoriedCharDB)
  ok(#StoriedCharDB.story == 1, "started again after a reload")
  cmd("")
  ok(StoriedStory.shown, "/storied opens the story")
  ok(story() == "Storied started keeping your story at level 39\n11 Nov 2026, Elwynn Forest", story())
  ok(summary() == "Level 39", summary())
  cmd("")
  ok(not StoriedStory.shown, "/storied again closes it")
  local escapes = false
  for _, n in ipairs(UISpecialFrames) do if n == "StoriedStory" then escapes = true end end
  ok(escapes, "Escape closes the window")
''',
"a level-up records the date, zone and played time": r'''
  login(nil, nil)
  advance(5)
  ok(playedRequests == 1, "asks for /played once at login: " .. playedRequests)
  played(300000, 1000)
  zoneName = "Stranglethorn Vale"
  ding(40)
  ok(playedRequests == 2, "asks again on a level-up")
  played(360060, 60)                 -- a minute after the ding
  days(1)
  instance = "Zul'Gurub"
  ding(41)
  played(393120, 0)
  instance = nil
  cmd("")
  local t = story()
  ok(t == "Level 41 in Zul'Gurub\n12 Nov 2026, 4d 13h played, 9h 12m since 40\n"
       .. "Level 40 in Stranglethorn Vale\n11 Nov 2026, 4d 4h played\n"
       .. "Storied started keeping your story at level 39\n11 Nov 2026, Elwynn Forest", t)
  ok(summary() == "Level 41, 4d 13h played", summary())
''',
"asking for played time doesn't print it in chat": r'''
  login(nil, nil)
  advance(5)
  ok(not ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "chat would show the reply")
  ok(ChatFrame1:IsEventRegistered("CHAT_MSG_SYSTEM"), "other chat left alone")
  played(300000, 1000)
  advance(1)
  ok(ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "chat gets /played back after the reply")
  ok(not ChatFrame2:IsEventRegistered("TIME_PLAYED_MSG"), "registered a window that never had it")
  ding(40)
  ok(not ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "hidden for the level-up request")
  advance(30)                        -- no reply came
  ok(ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "chat gets /played back even without a reply")
''',
"a level whose played reply comes after a reload still gets it": r'''
  login(nil, nil)
  ding(40)
  login(StoriedDB, StoriedCharDB)
  advance(5)
  played(360100, 100)
  ok(StoriedCharDB.story[2].played == 360000, tostring(StoriedCharDB.story[2].played))
''',
"a death names what killed you, where and at what level": r'''
  login(nil, nil)
  zoneName, groupSize = "Stranglethorn Vale", 3
  units.player.level = 41
  hit("Bloodscalp Headhunter", "Throw")
  die()
  alive()
  groupSize = 0
  hit("Hogger")
  die()
  alive()
  env("Falling")
  die()
  cmd("")
  local t = story()
  ok(t:find("^Died to falling\n11 Nov 2026, level 41, Stranglethorn Vale\n"
          .. "Died to Hogger\n11 Nov 2026, level 41, Stranglethorn Vale\n"
          .. "Died to Bloodscalp Headhunter %(Throw%)\n11 Nov 2026, level 41, Stranglethorn Vale, in a group of 3\n"), t)
  ok(summary() == "Level 41, 3 deaths", summary())
''',
"an old hit isn't blamed for a death, and feigning death isn't one": r'''
  login(nil, nil)
  hit("Hogger")
  advance(30)
  die()
  ok(StoriedCharDB.story[2].by == nil, "blamed an old hit")
  alive()
  units.player.feign = true
  die()
  ok(#StoriedCharDB.story == 2, "counted feign death")
''',
"without a combat log, a death names your hostile target": r'''
  C_CombatLog = nil
  login(nil, nil)
  units.target = { name = "Bloodscalp Headhunter", guid = creature(597), hostile = true }
  die()
  alive()
  units.target = { name = "Bob", guid = "Player-1-Bob", isPlayer = true }
  die()
  cmd("")
  ok(story():find("^Died\n11 Nov 2026, level 39, Elwynn Forest\nDied while fighting Bloodscalp Headhunter\n"), story())
''',
"the window shows only levels or only deaths, and opens the settings": r'''
  login(nil, nil)
  ding(40)
  hit("Hogger"); die()
  cmd("")
  StoriedStory.filters.death:Click()
  ok(story() == "Died to Hogger\n11 Nov 2026, level 40, Elwynn Forest", story())
  StoriedStory.filters.level:Click()
  ok(story() == "Level 40 in Elwynn Forest\n11 Nov 2026\n"
       .. "Storied started keeping your story at level 39\n11 Nov 2026, Elwynn Forest", story())
  StoriedStory.filters.all:Click()
  ok(select(2, story():gsub("\n", "")) == 5, story())
  ok(summary() == "Level 40, 1 death", summary())
  StoriedStory.settings:Click()
  ok(opened == 88, "settings button")
  hit("Hogger"); die()
  ok(summary() == "Level 40, 2 deaths", "an open window updates: " .. summary())
''',
"with levels and deaths switched off, nothing is recorded": r'''
  login({ levels = false, deaths = false }, nil)
  advance(5)
  ok(playedRequests == 0, "asked for /played while off")
  ding(40)
  hit("Hogger"); die()
  ok(#StoriedCharDB.story == 1, "recorded while off")
  ok(ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "chat left alone")
  panel():Show()
  ok(panel().checks.levels and panel().checks.deaths, "settings rows")
''',

# ---- Forever ----
"hidden (secret) values are skipped without errors": r'''
  login(nil, nil)
  equipped[16] = 12784
  fire("PARTY_KILL", SECRET, SECRET)
  fire("CHAT_MSG_LOOT", SECRET, SECRET)
  units.NPC = { name = SECRET }
  fire("TRADE_SHOW"); tradeMine[7] = link(12784); tradeEnchant = "Crusader"
  fire("TRADE_PLAYER_ITEM_CHANGED", 7); fire("TRADE_CLOSED"); fire("UI_INFO_MESSAGE", 226, ERR_TRADE_COMPLETE)
  units.target = { name = SECRET, guid = SECRET, isPlayer = true }
  fire("PLAYER_TARGET_CHANGED")
  ok(hoverUnit("target") == "", "a hidden player's tooltip")
  units.party1 = { name = SECRET, isPlayer = true }; groupSize = 2
  fire("GROUP_ROSTER_UPDATE")
  fire("RESURRECT_REQUEST", SECRET); AcceptResurrect()
  summoner = SECRET; fire("CONFIRM_SUMMON"); C_SummonInfo.ConfirmSummon()
  ok(next(StoriedCharDB.items) == nil and next(StoriedCharDB.people) == nil, "recorded something hidden")
  fire("PLAYER_LEVEL_UP", SECRET)
  played(SECRET, SECRET)
  cleu = { SECRET, SECRET, SECRET, SECRET, SECRET, SECRET, SECRET, SECRET }
  fire("COMBAT_LOG_EVENT_UNFILTERED")
  units.target = { name = SECRET, hostile = true }
  die()
  ok(#StoriedCharDB.story == 2 and StoriedCharDB.story[2].kind == "death" and StoriedCharDB.story[2].by == nil,
     "a hidden death is recorded without a name")
  kill()
  ok(hover(link(12784)) == "1 kill", "still works after")
''',

# ---- commands ----
"/storied help, debug and unknown words": r'''
  login(nil, nil)
  local o = cmd("help")
  ok(o:find("/storied debug") and o:find("/storied "), o)
  o = cmd("banana")
  ok(o:find("banana") and o:find("/storied help"), o)
  cmd("debug")
  out = {}
  trade("Bob", { mine = link(12784), enchant = "Enchant 2H Weapon - Crusader" })
  local said = table.concat(out, "\n")
  ok(said:find("Bob") and said:find("Enchant 2H Weapon %- Crusader"), "debug shows the trade: " .. said)
''',
"/storied says so if loading failed": r'''
  login(nil, nil)
  events = {}
  assert(loadstring(ADDON_SRC, "Storied.lua"))("Storied")
  ok(cmd("help"):find("didn't finish loading"), cmd("help"))
''',
}

failed = 0
for name, body in SCENARIOS.items():
    L = lua51.LuaRuntime()
    L.globals().ADDON_SRC = ADDON
    try:
        L.execute(MOCK)
        L.execute(GUARD)
        L.execute(body)
        print("PASS", name)
    except Exception as e:
        failed += 1
        print("FAIL", name, "->", str(e).splitlines()[0])
print("failed:", failed)
sys.exit(1 if failed else 0)
