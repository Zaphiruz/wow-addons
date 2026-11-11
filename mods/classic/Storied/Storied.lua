-- Storied: remembers the history of your gear and the people you play with.
-- Who enchanted an item, where it came from and how many kills each weapon
-- has; who you've grouped with and who resurrected or summoned you. Shown
-- in tooltips. The game keeps none of this, so it's recorded as it happens.
local ADDON = ...

local db              -- StoriedDB: settings, shared by the account
local char            -- StoriedCharDB: this character's item histories
local category, panel -- our page in the game's settings window
local debugging = false

local function say(fmt, ...) print("|cffc9a66bStoried|r: " .. format(fmt, ...)) end
local function dbg(fmt, ...) if debugging then say("|cff999999" .. fmt .. "|r", ...) end end

-- Forever hides some values from addons at restricted moments ("secret
-- values"). They can't be compared or used as keys, so anything that might
-- be one is checked first. Classic Era has no issecretvalue.
local function isSecret(v) return issecretvalue ~= nil and issecretvalue(v) end
local function text(v) if not isSecret(v) and type(v) == "string" and v ~= "" then return v end end
local function number(v) if not isSecret(v) and type(v) == "number" then return v end end

local function commas(n)
  local s = tostring(math.floor(n)):reverse():gsub("(%d%d%d)", "%1,"):reverse()
  return (s:gsub("^,", ""))
end

local function day(t) return (date("%d %b %Y", t):gsub("^0", "")) end
local function shortDay(t) return (date("%d %b", t):gsub("^0", "")) end

---------------------------------------------------------------------------
-- Settings and saved history
---------------------------------------------------------------------------
local OPTIONS = {
  { key = "enchants", label = "Enchants", note = "Who put each enchant on your gear, and when" },
  { key = "origin", label = "Where it came from",
    note = "Drops, chests, lockboxes, quests, vendors, trades and mail, for green and better gear" },
  { key = "kills", label = "Weapon kills", note = "Your killing blows, counted on the weapon you had equipped" },
  { key = "grouped", label = "Grouped with", note = "Where you first and last grouped with each player" },
  { key = "help", label = "Help", note = "Who resurrected, summoned or soulstoned you" },
  { key = "thanks", label = "Say thanks", default = false,
    note = "Whisper them when you accept a resurrect or summon. {name} is their name." },
  { key = "tooltips", label = "Show on tooltips", note = "Turn off to keep recording without the extra lines" },
}
local TEXTS = { thanksRes = "Thanks for the res, {name}!", thanksSummon = "Thanks for the summon, {name}!" }

local function loadSaved()
  if type(StoriedDB) ~= "table" then StoriedDB = {} end
  db = StoriedDB
  for _, o in ipairs(OPTIONS) do
    if db[o.key] == nil then db[o.key] = o.default ~= false end
  end
  for k, v in pairs(TEXTS) do
    if type(db[k]) ~= "string" then db[k] = v end
  end
  if type(StoriedCharDB) ~= "table" then StoriedCharDB = {} end
  char = StoriedCharDB
  if type(char.items) ~= "table" then char.items = {} end      -- item ID -> its history
  if type(char.openers) ~= "table" then char.openers = {} end  -- lockbox ID -> who picked it
  if type(char.people) ~= "table" then char.people = {} end    -- "Name-Realm" -> your history with them
  if type(char.group) ~= "table" then char.group = {} end      -- who's in your group now, kept over a reload
end

---------------------------------------------------------------------------
-- Items
--
-- Classic items have no ID of their own, so history is kept per kind of
-- item, per character. Two copies of the same item share one history.
---------------------------------------------------------------------------
local MIN_QUALITY = 2  -- green: origins are kept for green and better gear
local NOT_GEAR = { [""] = true, INVTYPE_BAG = true, INVTYPE_AMMO = true, INVTYPE_QUIVER = true,
                   INVTYPE_NON_EQUIP_IGNORE = true }
local CONSUMABLE = 0   -- item class of potions, food and the like

local function itemID(item)
  if number(item) then return item end
  local s = text(item)
  return s and tonumber(s:match("item:(%d+)"))
end

-- The enchant ID inside an item link, 0 if none.
local function enchantOf(link)
  local s = text(link)
  return s and tonumber(s:match("item:%d+:(%d*)") or "") or 0
end

local function info(item)
  local f = (C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
  if f then
    local ok, id, _, _, loc, _, class = pcall(f, item)
    if ok and id then return loc, class end
  end
end

local function isGear(item)
  local loc = info(item)
  return type(loc) == "string" and not NOT_GEAR[loc]
end

local function quality(item)
  local f = C_Item and C_Item.GetItemQualityByID
  if f then
    local ok, q = pcall(f, item)
    if ok then return number(q) end
  end
end

local function history(id)
  local e = char.items[id]
  if not e then
    e = {}
    char.items[id] = e
  end
  return e
end

---------------------------------------------------------------------------
-- Where it came from
---------------------------------------------------------------------------
local function article(name) return (name:match("^[AEIOUaeiou]") and "an " or "a ") .. name end

-- One or two tooltip lines for an origin.
local function originLines(o)
  local when = day(o.at)
  if o.how == "loot" then
    local first = o.from and ("Looted from " .. o.from .. (o.zone and (", " .. o.zone) or ""))
                  or ("Looted" .. (o.zone and (" in " .. o.zone) or ""))
    if o.others and o.others > 0 then
      when = format("%s, with %d other%s", when, o.others, o.others == 1 and "" or "s")
    end
    return first, when
  elseif o.how == "chest" then
    return "Found in " .. o.from .. (o.zone and (", " .. o.zone) or ""), when
  elseif o.how == "box" then
    return "From " .. article(o.from) .. (o.by and (" opened by " .. o.by) or ""), when
  elseif o.how == "quest" then
    return format("Reward from %s, %s", o.from, when)
  elseif o.how == "vendor" then
    return format("Bought from %s, %s", o.from, when)
  elseif o.how == "trade" then
    return format("Traded to you by %s, %s", o.from, when)
  elseif o.how == "mail" then
    return format("Mailed to you by %s, %s", o.from, when)
  elseif o.how == "auction" then
    return "Won at auction, " .. when
  end
end

local function setOrigin(item, o)
  if not (db.origin and o) then return end
  local id = itemID(item)
  if not id or not isGear(id) then return end
  local q = quality(id)
  if q and q < MIN_QUALITY then return end
  local e = history(id)
  if e.origin then return end  -- the first time you got it is its story
  local copy = { at = time() }
  for k, v in pairs(o) do copy[k] = v end
  e.origin = copy
  local a, b = originLines(copy)
  dbg("item %d: %s%s", id, a, b and (" / " .. b) or "")
end

-- Names of creatures seen as target or under the mouse, so a corpse's loot
-- can say what it was.
local MAX_NAMES = 500
local names, nameCount = {}, 0

local function rememberName(unit)
  local guid, name = text(UnitGUID(unit)), text(UnitName(unit))
  if not (guid and name) then return end
  if not names[guid] then
    if nameCount >= MAX_NAMES then names, nameCount = {}, 0 end
    nameCount = nameCount + 1
  end
  names[guid] = name
end

local function zone() return text(GetRealZoneText and GetRealZoneText()) end

local function others()
  local n = number(GetNumGroupMembers and GetNumGroupMembers())
  return (n and n > 1) and (n - 1) or 0
end

local RECENT = 5        -- seconds an action stays linked to what arrives after it
local ROLL_WAIT = 300   -- seconds an item seen in a loot window waits for its roll

local lastSent          -- { target, at }: what your last spell was cast at
local lastBox           -- { id, name, at }: the last item you opened from your bags
local boxLooted         -- the lockbox ID whose loot window is open
local seen = {}         -- item ID -> { origin, at }: items seen in a loot window

local function sourceOf(guid)
  local now = GetTime()
  local g = text(guid)
  local creature = g and (g:find("^Creature") or g:find("^Vehicle"))
  local object = g and g:find("^GameObject")
  if lastBox and now - lastBox.at < RECENT and not creature and not object then
    local opener = char.openers[lastBox.id]
    return { how = "box", from = lastBox.name, by = opener and opener.by }, lastBox.id
  end
  if object and lastSent and now - lastSent.at < RECENT and lastSent.target then
    return { how = "chest", from = lastSent.target, zone = zone() }
  end
  return { how = "loot", from = g and names[g], zone = zone(), others = others() }
end

local function onLootOpened()
  boxLooted = nil
  local now = GetTime()
  for i = 1, (number(GetNumLootItems and GetNumLootItems()) or 0) do
    local id = itemID(GetLootSlotLink(i))
    if id then
      local guid = GetLootSourceInfo and GetLootSourceInfo(i)
      local o, box = sourceOf(guid)
      seen[id] = { origin = o, at = now }
      boxLooted = box or boxLooted
    end
  end
end

local function onLootClosed()
  -- A lockbox someone picked for you is theirs once; the next is yours.
  if boxLooted then char.openers[boxLooted] = nil end
  boxLooted, lastBox = nil, nil
end

-- The game's loot lines turned into patterns: "You receive loot: %s." etc.
local function pattern(fmt)
  if type(fmt) ~= "string" then return end
  local p = fmt:gsub("([%^%$%(%)%.%[%]%*%+%-%?])", "%%%1")
  p = p:gsub("%%s", "(.+)"):gsub("%%d", "(%%d+)")
  return "^" .. p .. "$"
end

local lootPatterns
local function buildPatterns()
  lootPatterns = {}
  for _, p in ipairs({ { LOOT_ITEM_SELF_MULTIPLE, "loot" }, { LOOT_ITEM_SELF, "loot" },
                       { LOOT_ITEM_PUSHED_SELF_MULTIPLE, "pushed" }, { LOOT_ITEM_PUSHED_SELF, "pushed" } }) do
    local pat = pattern(p[1])
    if pat then lootPatterns[#lootPatterns + 1] = { pat, p[2] } end
  end
end

local open = {}  -- "quest" / "vendor" -> { name, closed }

local function openNow(kind)
  local c = open[kind]
  if c and c.name and (not c.closed or GetTime() - c.closed < RECENT) then return c.name end
end

local function onLootMessage(msg)
  msg = text(msg)
  if not msg then return end
  local kind
  for _, p in ipairs(lootPatterns) do
    if msg:match(p[1]) then kind = p[2] break end
  end
  local id = kind and itemID(msg)
  if not id then return end
  if kind == "loot" then
    local s = seen[id]
    if s and GetTime() - s.at < ROLL_WAIT then
      setOrigin(id, s.origin)
    else
      setOrigin(id, { how = "loot", zone = zone(), others = others() })
    end
  else
    local quest, vendor = openNow("quest"), openNow("vendor")
    if quest then
      setOrigin(id, { how = "quest", from = quest })
    elseif vendor then
      setOrigin(id, { how = "vendor", from = vendor })
    end
  end
end

local function onUseItem(bag, slot)
  local get = (C_Container and C_Container.GetContainerItemLink) or GetContainerItemLink
  local link = get and text(get(bag, slot))
  local id = itemID(link)
  if not id or isGear(id) then return end
  local _, class = info(id)
  if class == CONSUMABLE then return end
  lastBox = { id = id, name = link:match("%[(.-)%]") or "a box", at = GetTime() }
end

local function fromMail(index, attachment)
  local _, _, sender = GetInboxHeaderInfo(index)
  local invoice = GetInboxInvoiceInfo and GetInboxInvoiceInfo(index)
  local o
  if text(invoice) == "buyer" then
    o = { how = "auction" }
  elseif text(sender) then
    o = { how = "mail", from = sender }
  end
  if not o then return end
  for a = attachment or 1, attachment or (ATTACHMENTS_MAX_RECEIVE or 16) do
    local id = itemID(GetInboxItemLink(index, a))
    if id then setOrigin(id, o) end
  end
end

---------------------------------------------------------------------------
-- Trades: enchants, lockpicking, and items handed to you
--
-- The trade window shows the enchant someone casts on your item in the
-- "Will not be traded" slot, and their name. It's read as the trade goes
-- and recorded once the game says the trade completed.
---------------------------------------------------------------------------
local ENCHANT_SLOT = TRADE_ENCHANT_SLOT or 7
local trade  -- { partner, mine = { id, enchant }, got = { item IDs }, closed }

-- "Enchant 2H Weapon - Crusader" -> "Crusader"
local function enchantName(s) return s:match(" %- (.+)$") or s end

local function readTrade()
  if not trade then return end
  trade.partner = text(UnitName("NPC")) or trade.partner
  local id = itemID(GetTradePlayerItemLink(ENCHANT_SLOT))
  if id then
    local enchant = select(5, GetTradePlayerItemInfo(ENCHANT_SLOT))
    trade.mine = { id = id, enchant = text(enchant) }
  else
    trade.mine = nil
  end
  trade.got = {}
  for i = 1, ENCHANT_SLOT - 1 do
    local got = itemID(GetTradeTargetItemLink(i))
    if got then trade.got[#trade.got + 1] = got end
  end
end

local function finishTrade()
  local t = trade
  trade = nil
  if not (t and t.partner) then return end
  if t.closed and GetTime() - t.closed > RECENT then return end
  local mine = t.mine
  if mine then
    dbg("trade with %s: your item %d in the \"Will not be traded\" slot got %s", t.partner, mine.id,
      mine.enchant or "nothing")
    if isGear(mine.id) then
      if mine.enchant and db.enchants then
        history(mine.id).enchant = { name = enchantName(mine.enchant), by = t.partner, at = time() }
      end
    else
      char.openers[mine.id] = { by = t.partner, at = time() }
    end
  end
  for _, id in ipairs(t.got) do setOrigin(id, { how = "trade", from = t.partner }) end
end

---------------------------------------------------------------------------
-- Weapon kills
--
-- PARTY_KILL names who got each killing blow. A kill just after one of your
-- ranged shots counts on your ranged weapon, any other on your main hand.
---------------------------------------------------------------------------
local MAIN_HAND, RANGED_SLOT = 16, 18
local RANGED_FOR = 3  -- seconds after a ranged shot that a kill is its
-- Auto Shot, Shoot (wand), Shoot, Shoot Bow, Shoot Gun, Shoot Crossbow, Throw
local RANGED = { [75] = true, [5019] = true, [3018] = true, [2480] = true, [7918] = true, [7919] = true,
                 [2764] = true }
local lastRanged

local function onCast(unit, _, spellID)
  if unit == "player" and number(spellID) and RANGED[spellID] then lastRanged = GetTime() end
end

local function onKill(attacker)
  if not db.kills then return end
  local me = text(UnitGUID("player"))
  if not me or text(attacker) ~= me then return end
  local ranged = lastRanged and GetTime() - lastRanged < RANGED_FOR
  local id = number(GetInventoryItemID("player", ranged and RANGED_SLOT or MAIN_HAND))
  if not id then return end
  local e = history(id)
  e.kills = (e.kills or 0) + 1
  dbg("killing blow with item %d (%s): %d kills", id, ranged and "ranged" or "main hand", e.kills)
end

---------------------------------------------------------------------------
-- People: who you've grouped with
--
-- Each time someone joins your group counts once. Where it happened is the
-- zone you were in, or the dungeon the group goes into next. Going into a
-- different dungeon with the same group counts as a new time; running back
-- into the same one after a wipe doesn't.
---------------------------------------------------------------------------
local myRealm

-- "Name-Realm" for a name that may lack its realm.
local function withRealm(name)
  name = text(name)
  if name and not name:find("-", 1, true) and myRealm then name = name .. "-" .. myRealm end
  return name
end

-- "Name-Realm" for the player under unit, or nil.
local function fullName(unit)
  local name, realm = UnitName(unit)
  name = text(name)
  if not name then return end
  return name .. "-" .. (text(realm) or myRealm)
end

local function person(full)
  local p = char.people[full]
  if not p then
    p = {}
    char.people[full] = p
  end
  return p
end

-- Where you are: the dungeon's name inside one, otherwise the zone.
local function place()
  if IsInInstance and IsInInstance() then
    return text((GetInstanceInfo())) or zone(), true
  end
  return zone(), false
end

local function newTime(full, where)
  local p = person(full)
  p.times = (p.times or 0) + 1
  local at = time()
  p.first = p.first or { place = where, at = at }
  p.last = { place = where, at = at }
end

local function groupUnits()
  local list = {}
  if IsInRaid() then
    for i = 1, 40 do list[#list + 1] = "raid" .. i end
  else
    for i = 1, 4 do list[#list + 1] = "party" .. i end
  end
  return list
end

local function onRoster()
  if not db.grouped then
    char.group = {}
    return
  end
  local where, inside = place()
  local now = {}
  for _, unit in ipairs(groupUnits()) do
    if UnitIsPlayer(unit) and not UnitIsUnit(unit, "player") then
      local full = fullName(unit)
      if full then
        local dungeon = char.group[full]
        if dungeon == nil then
          newTime(full, where)
          dungeon = inside and where or false
        end
        now[full] = dungeon
      end
    end
  end
  char.group = now
end

local function onZone()
  local where, inside = place()
  if not (inside and where) then return end
  for full, dungeon in pairs(char.group) do
    local p = char.people[full]
    if p and p.last and dungeon ~= where then
      if dungeon then
        newTime(full, where)  -- a different dungeon with the same group
      else
        p.last.place = where  -- the group formed outside; this is where it went
        if p.times == 1 then p.first.place = where end
      end
      char.group[full] = where
    end
  end
end

---------------------------------------------------------------------------
-- People: who helped you
--
-- A resurrect or summon offer names who it's from. It counts once you
-- accept it. A soulstone is credited to whoever cast the buff on you, which
-- the game only says while they're in your group.
---------------------------------------------------------------------------
local OFFER_WAIT = { res = 60, summon = 120 }  -- seconds an offer stays open
local THANKS = { res = "thanksRes", summon = "thanksSummon" }
local THANKS_DELAY = 2   -- seconds after accepting before the whisper
local MAX_CHAT = 255     -- the game's limit for one chat line
local SOULSTONE = { [20707] = true, [20762] = true, [20763] = true, [20764] = true, [20765] = true,
                    [27239] = true }
local HELP_WORDS = { { "res", "Resurrected" }, { "summon", "Summoned" }, { "soulstone", "Soulstoned" } }

local offers = {}  -- "res" / "summon" -> { name, at }
local stoneBy      -- "Name-Realm" of who cast your soulstone, when known

local function chatLocked()
  return C_ChatInfo ~= nil and C_ChatInfo.InChatMessagingLockdown ~= nil and C_ChatInfo.InChatMessagingLockdown()
end

local function thank(kind, name)
  local key = THANKS[kind]
  if not (db.thanks and key) then return end
  local short = (Ambiguate and Ambiguate(name, "short")) or name
  local msg = db[key]:gsub("{name}", function() return short end)
  if strtrim(msg) == "" or #msg > MAX_CHAT then return end
  C_Timer.After(THANKS_DELAY, function()
    if chatLocked() then
      dbg("chat is locked right now, no thanks sent to %s", short)
      return
    end
    local send = (C_ChatInfo and C_ChatInfo.SendChatMessage) or SendChatMessage
    if send then pcall(send, msg, "WHISPER", nil, name) end
  end)
end

local function helped(kind, name)
  local full = withRealm(name)
  if not full then return end
  if db.help then
    local p = person(full)
    local h = p[kind] or { n = 0 }
    h.n, h.at = h.n + 1, time()
    p[kind] = h
    dbg("%s: %s (%d)", kind, full, h.n)
  end
  thank(kind, name)
end

local function offered(kind, name)
  offers[kind] = { name = text(name), at = GetTime() }
end

local function accepted(kind)
  local o = offers[kind]
  offers[kind] = nil
  if o and o.name and GetTime() - o.at < OFFER_WAIT[kind] then helped(kind, o.name) end
end

local function auraAt(i)
  if C_UnitAuras and C_UnitAuras.GetAuraDataByIndex then
    return C_UnitAuras.GetAuraDataByIndex("player", i, "HELPFUL")
  end
  if UnitAura then
    local name, _, _, _, _, _, source, _, _, spellId = UnitAura("player", i, "HELPFUL")
    if name then return { name = name, sourceUnit = source, spellId = spellId } end
  end
end

local function readAuras()
  -- The buff goes when you die, but its caster is still who to thank.
  if UnitIsDeadOrGhost("player") then return end
  stoneBy = nil
  for i = 1, 40 do
    local a = auraAt(i)
    if not a then break end
    if SOULSTONE[number(a.spellId) or 0] then
      local unit = text(a.sourceUnit)
      stoneBy = unit and fullName(unit) or nil
    end
  end
end

local function usedSelfRes()
  local by = stoneBy
  stoneBy = nil
  if by then helped("soulstone", by) end
end

---------------------------------------------------------------------------
-- Tooltips
---------------------------------------------------------------------------
local GOLD = "|cffffd100"

local function linesFor(id, link)
  local e = char.items[id]
  local lines = {}
  if not e then return lines end
  local ench = e.enchant
  if ench then
    -- The item's own link says which enchant is on it now. The first one
    -- seen after the trade is learnt; a different one later means it was
    -- replaced, and the old story no longer applies.
    local now = link and enchantOf(link)
    if now and not ench.id and now > 0 then ench.id = now end
    if not now or now == ench.id then
      lines[#lines + 1] = format("%s by %s, %s", ench.name, ench.by, day(ench.at))
    end
  end
  if e.origin then
    local a, b = originLines(e.origin)
    lines[#lines + 1] = a
    lines[#lines + 1] = b
  end
  if e.kills and e.kills > 0 then
    lines[#lines + 1] = format("%s kill%s", commas(e.kills), e.kills == 1 and "" or "s")
  end
  return lines
end

local function personLines(full)
  local p = char.people[full]
  local lines = {}
  if not p then return lines end
  local function at(stamp) return (stamp.place and (stamp.place .. ", ") or "") .. day(stamp.at) end
  if p.times and p.first and p.last then
    if p.times == 1 then
      lines[#lines + 1] = "Grouped once: " .. at(p.first)
    else
      lines[#lines + 1] = "First grouped: " .. at(p.first)
      lines[#lines + 1] = format("Last: %s (%d times)", at(p.last), p.times)
    end
  end
  for _, w in ipairs(HELP_WORDS) do
    local h = p[w[1]]
    if h and h.n and h.n > 0 then
      if h.n == 1 then
        lines[#lines + 1] = format("%s you once, %s", w[2], shortDay(h.at))
      else
        lines[#lines + 1] = format("%s you %d times, last %s", w[2], h.n, shortDay(h.at))
      end
    end
  end
  return lines
end

local doneFor = setmetatable({}, { __mode = "k" })  -- tooltip -> what was already added

local function addTo(tip, key, lines, once)
  if once then
    if doneFor[tip] == key then return end
    doneFor[tip] = key
  end
  for _, line in ipairs(lines) do tip:AddLine(GOLD .. line .. "|r") end
end

local function addItemLines(tip, id, once)
  if not (db and char and db.tooltips) or not number(id) then return end
  local link = text(tip.GetItem and select(2, tip:GetItem()))
  addTo(tip, link or id, linesFor(id, link), once)
end

local function addUnitLines(tip, once)
  if not (db and char and db.tooltips and tip.GetUnit) then return end
  local _, unit = tip:GetUnit()
  unit = text(unit)
  if not unit or not UnitIsPlayer(unit) or UnitIsUnit(unit, "player") then return end
  local full = fullName(unit)
  if full then addTo(tip, "unit:" .. full, personLines(full), once) end
end

local function hookTooltips()
  local types = Enum and Enum.TooltipDataType
  if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and types and types.Item then
    TooltipDataProcessor.AddTooltipPostCall(types.Item, function(tip, data)
      pcall(addItemLines, tip, data and data.id)
    end)
    if types.Unit then
      TooltipDataProcessor.AddTooltipPostCall(types.Unit, function(tip) pcall(addUnitLines, tip) end)
    end
    return
  end
  for _, tip in ipairs({ GameTooltip, ItemRefTooltip }) do
    if tip then
      tip:HookScript("OnTooltipSetItem", function(self)
        pcall(function() addItemLines(self, itemID(select(2, self:GetItem())), true) end)
      end)
      tip:HookScript("OnTooltipCleared", function(self) doneFor[self] = nil end)
    end
  end
  GameTooltip:HookScript("OnTooltipSetUnit", function(self) pcall(addUnitLines, self, true) end)
end

---------------------------------------------------------------------------
-- Settings panel (Options > AddOns > Storied)
---------------------------------------------------------------------------
local MAX_MESSAGE = 200  -- letters, leaving room for a long name

local function buildPanel()
  panel = CreateFrame("Frame", "StoriedPanel")
  panel.checks = {}

  local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 16, -16)
  title:SetText("Storied")
  local intro = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  intro:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -8)
  intro:SetText("Starts recording from the day you install it. Nothing earlier can be recovered.")

  local function textBox(key, y)
    local box = CreateFrame("EditBox", nil, panel, "InputBoxTemplate")
    box:SetPoint("TOPLEFT", 54, y)
    box:SetSize(300, 22)
    box:SetAutoFocus(false)
    box:SetMaxLetters(MAX_MESSAGE)
    box:SetScript("OnTextChanged", function(self, userInput)
      if userInput then db[key] = self:GetText() end
    end)
    box:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
    box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return box
  end

  local y = -70
  for _, o in ipairs(OPTIONS) do
    local check = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
    check:SetPoint("TOPLEFT", 16, y)
    check:SetScript("OnClick", function(self) db[o.key] = self:GetChecked() and true or false end)
    local label = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    label:SetPoint("TOPLEFT", 48, y - 4)
    label:SetText(o.label)
    local note = panel:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
    note:SetPoint("TOPLEFT", 48, y - 22)
    note:SetText(o.note)
    panel.checks[o.key] = check
    y = y - 44
    if o.key == "thanks" then
      panel.thanksRes = textBox("thanksRes", y + 4)
      panel.thanksSummon = textBox("thanksSummon", y - 22)
      y = y - 56
    end
  end

  panel:SetScript("OnShow", function()
    for _, o in ipairs(OPTIONS) do panel.checks[o.key]:SetChecked(db[o.key]) end
    panel.thanksRes:SetText(db.thanksRes)
    panel.thanksSummon:SetText(db.thanksSummon)
  end)

  if Settings and Settings.RegisterCanvasLayoutCategory then
    category = Settings.RegisterCanvasLayoutCategory(panel, "Storied")
    Settings.RegisterAddOnCategory(category)
  end
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
local HELP = {
  "/storied  -  open the settings",
  "/storied debug  -  print each trade, origin, kill and helping hand as it's recorded",
  "Hover over an item, or a player you've grouped with, to see their history in the tooltip.",
}

SLASH_STORIED1 = "/storied"
SlashCmdList.STORIED = function(msg)
  if not (db and char and panel) then
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
  elseif word == "help" then
    for _, line in ipairs(HELP) do say(line) end
  else
    say("no command called %s. Type /storied help for commands.", word)
  end
end

---------------------------------------------------------------------------
-- Startup
---------------------------------------------------------------------------
local function hookFunctions()
  local function hook(t, name, fn)
    if t and type(t[name]) == "function" then hooksecurefunc(t, name, fn) end
  end
  local function safe(fn) return function(...) pcall(fn, ...) end end
  hook(C_Container, "UseContainerItem", safe(onUseItem))
  if not (C_Container and C_Container.UseContainerItem) then hook(_G, "UseContainerItem", safe(onUseItem)) end
  hook(_G, "TakeInboxItem", safe(fromMail))
  hook(_G, "AutoLootMailItem", safe(function(index) fromMail(index) end))
  hook(_G, "AcceptResurrect", safe(function() accepted("res") end))
  hook(C_SummonInfo, "ConfirmSummon", safe(function() accepted("summon") end))
  hook(C_DeathInfo, "UseSelfResurrectOption", safe(usedSelfRes))
end

local HANDLERS = {
  TRADE_SHOW = function() trade = {} readTrade() end,
  TRADE_PLAYER_ITEM_CHANGED = readTrade,
  TRADE_TARGET_ITEM_CHANGED = readTrade,
  TRADE_ACCEPT_UPDATE = readTrade,
  TRADE_CLOSED = function() if trade then trade.closed = GetTime() end end,
  UI_INFO_MESSAGE = function(_, msg)
    if trade and ERR_TRADE_COMPLETE and text(msg) == ERR_TRADE_COMPLETE then finishTrade() end
  end,
  LOOT_OPENED = onLootOpened,
  LOOT_CLOSED = onLootClosed,
  CHAT_MSG_LOOT = onLootMessage,
  UNIT_SPELLCAST_SENT = function(unit, target)
    if unit == "player" then lastSent = { target = text(target), at = GetTime() } end
  end,
  UNIT_SPELLCAST_SUCCEEDED = onCast,
  PARTY_KILL = onKill,
  PLAYER_TARGET_CHANGED = function() rememberName("target") end,
  UPDATE_MOUSEOVER_UNIT = function() rememberName("mouseover") end,
  QUEST_COMPLETE = function() open.quest = { name = text(GetTitleText()) } end,
  QUEST_FINISHED = function() if open.quest then open.quest.closed = GetTime() end end,
  MERCHANT_SHOW = function() open.vendor = { name = text(UnitName("npc")) } end,
  MERCHANT_CLOSED = function() if open.vendor then open.vendor.closed = GetTime() end end,
  GROUP_ROSTER_UPDATE = onRoster,
  PLAYER_ENTERING_WORLD = onZone,
  ZONE_CHANGED_NEW_AREA = onZone,
  RESURRECT_REQUEST = function(inviter) offered("res", inviter) end,
  CONFIRM_SUMMON = function()
    offered("summon", C_SummonInfo and C_SummonInfo.GetSummonConfirmSummoner())
  end,
  UNIT_AURA = function(unit) if unit == "player" then readAuras() end end,
}

local events = CreateFrame("Frame")
pcall(events.RegisterEvent, events, "ADDON_LOADED")
pcall(events.RegisterEvent, events, "PLAYER_LOGIN")
for e in pairs(HANDLERS) do pcall(events.RegisterEvent, events, e) end

events:SetScript("OnEvent", function(_, event, ...)
  if event == "ADDON_LOADED" then
    if ... == ADDON then loadSaved() end
  elseif event == "PLAYER_LOGIN" then
    if not db then return end
    myRealm = text(GetNormalizedRealmName and GetNormalizedRealmName()) or (GetRealmName():gsub("%s", ""))
    buildPatterns()
    buildPanel()
    hookTooltips()
    hookFunctions()
  elseif db and char and lootPatterns then
    -- Unit checks can return hidden values on Forever, which error when
    -- tested, so each handler runs under pcall: a hidden value is skipped.
    local ok, err = pcall(HANDLERS[event], ...)
    if not ok then dbg("%s: %s", event, tostring(err)) end
  end
end)
