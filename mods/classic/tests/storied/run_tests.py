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
  now = now + seconds
  clock = clock + seconds
end
function days(n) clock = clock + n * 86400 end

-- Units.
units = {
  player = { name = "Zaphiruz", guid = "Player-1-0001" },
}
function UnitName(u) local x = units[u]; if x then return x.name end end
function UnitGUID(u) local x = units[u]; if x then return x.guid end end
function GetRealmName() return "Whitemane" end
function GetRealZoneText() return zoneName end
zoneName = "Elwynn Forest"
groupSize = 0
function GetNumGroupMembers() return groupSize end

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
C_Container = {
  GetContainerItemLink = function(bag, slot) return bags[bag .. ":" .. slot] end,
  UseContainerItem = function(bag, slot) end,
}

-- Equipped weapons.
equipped = {}
function GetInventoryItemID(unit, slot) if unit == "player" then return equipped[slot] end end

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
SPELLS = { [75] = "Auto Shot", [5019] = "Shoot", [3365] = "Opening", [585] = "Smite", [133] = "Fireball" }
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
  function w:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
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
Enum = { TooltipDataType = { Item = 0, Unit = 2 } }
postCalls = {}
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn)
  postCalls[kind] = postCalls[kind] or {}; table.insert(postCalls[kind], fn) end }
local function plain(s) return (tostring(s):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")) end
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
'''

SCENARIOS = {
# ---- settings ----
"first login turns everything on and adds a settings page": r'''
  login(nil, nil)
  ok(StoriedDB.enchants and StoriedDB.origin and StoriedDB.kills and StoriedDB.tooltips, "all on")
  ok(type(StoriedCharDB.items) == "table", "item history")
  ok(categories[1] and categories[1].name == "Storied", "settings page")
  cmd("")
  ok(opened == 88, "/storied opens the settings")
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
''',
"items with no history get no lines": r'''
  login(nil, nil)
  ok(hover(link(6125)) == "", hover(link(6125)))
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
  units.target = { name = SECRET, guid = SECRET }
  fire("PLAYER_TARGET_CHANGED")
  ok(next(StoriedCharDB.items) == nil, "recorded something hidden")
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
