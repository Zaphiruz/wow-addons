-- Hopscotch: counts every hop off the ground, per character and for the account.
local ADDON = ...

local db, me          -- HopscotchDB, and this character's entry in it
local counter, window
local refreshWindow = function() end  -- replaced once the window exists
local debugging = false

local function say(fmt, ...) print("|cff66ccffHopscotch|r: " .. format(fmt, ...)) end
local function dbg(fmt, ...) if debugging then say("|cff999999" .. fmt .. "|r", ...) end end

local function commas(n)
  local s = tostring(math.floor(n)):reverse():gsub("(%d%d%d)", "%1,"):reverse()
  return (s:gsub("^,", ""))
end

local function charKey(name, realm) return name .. "-" .. realm end

---------------------------------------------------------------------------
-- Counting
--
-- The jump key calls JumpOrAscendStart on press and AscendStop on release.
-- A press only counts if the player then leaves the ground soon after, so
-- presses in mid-air, presses while rooted and swimming upward don't count.
-- Holding the key bunny-hops, and each new take-off while held counts too.
---------------------------------------------------------------------------
local TAKEOFF_WINDOW = 0.3  -- seconds after a press in which leaving the ground counts
local HELD_TIMEOUT = 0.6    -- on the ground this long means the key isn't held any more

local held, pressedAt, falling, groundedFor = false, -math.huge, false, 0

---------------------------------------------------------------------------
-- Zones and dungeon runs
--
-- Every jump also counts toward the zone it happened in (dungeons are zones).
-- A run starts on entering a dungeon or raid and ends on leaving, but coming
-- back to the same one within RUN_GRACE (a corpse run, a repair trip)
-- continues it. The run in progress is saved on the character, so a reload
-- inside a dungeon doesn't lose it.
---------------------------------------------------------------------------
local RUN_GRACE = 15 * 60
local ZONE_CHECK_EVERY = 30
local KEEP_RUNS = 20
local RUN_TYPES = { party = true, raid = true }

local zone              -- the zone we're in now
local sessionZones = {} -- jumps per zone since login
local visitJumps = 0    -- jumps since entering this zone

---------------------------------------------------------------------------
-- Jumps per hour
--
-- Hopscotch keeps its own time online per character and per zone. A rate
-- only uses jumps counted while that time was kept (timedJumps), so jumps
-- from before tracking began don't inflate it. Rates hide until there's
-- enough time behind them to mean something.
---------------------------------------------------------------------------
local MIN_RATE_SECONDS = 5 * 60
local MAX_TICK = 120   -- never credit more than this between two ticks
local sessionStart, sessionJumps, lastTick = nil, 0, nil

local function perHour(jumps, seconds, minSeconds)
  if not jumps or not seconds or seconds < (minSeconds or MIN_RATE_SECONDS) then return nil end
  return math.floor(jumps * 3600 / seconds + 0.5)
end

local function rateText(jumps, seconds, minSeconds)
  local r = perHour(jumps, seconds, minSeconds)
  return r and (commas(r) .. "/h") or ""
end

local function sessionText()
  local text = format("This session: %s jumps", commas(sessionJumps))
  local r = sessionStart and perHour(sessionJumps, GetTime() - sessionStart)
  if r then text = text .. format(", %s per hour", commas(r)) end
  return text
end

-- Credit the time since the last tick to this character and zone.
local function addTime()
  local now = GetTime()
  if lastTick and me then
    local dt = math.min(now - lastTick, MAX_TICK)
    if dt > 0 then
      me.seconds = (me.seconds or 0) + dt
      if zone and zone ~= "" then me.zoneSeconds[zone] = (me.zoneSeconds[zone] or 0) + dt end
    end
  end
  lastTick = now
end

local function currentDungeon()
  local inside, kind = IsInInstance()
  if inside and RUN_TYPES[kind] then return GetRealZoneText() end
end

local function finishRun()
  local run = me.run
  if not run then return end
  me.run = nil
  local ended = run.lastInside or run.started
  local seconds = math.max(0, ended - run.started)
  table.insert(db.runs, 1, { dungeon = run.dungeon, char = me.name, ended = ended,
                             jumps = run.jumps, seconds = seconds })
  while #db.runs > KEEP_RUNS do table.remove(db.runs) end
  local d = db.dungeons[run.dungeon] or { runs = 0 }
  d.runs = (d.runs or 0) + 1
  d.fewest = math.min(d.fewest or run.jumps, run.jumps)
  d.most = math.max(d.most or run.jumps, run.jumps)
  db.dungeons[run.dungeon] = d
  say("%s run: %s jumps in %d min.", run.dungeon, commas(run.jumps), math.floor(seconds / 60 + 0.5))
end

-- Start, continue or finish the dungeon run to match where we are.
local function checkRun()
  local now, dungeon = time(), currentDungeon()
  local run = me.run
  if run then
    local expired = now - (run.lastInside or run.started) > RUN_GRACE
    if (dungeon and dungeon ~= run.dungeon) or expired then finishRun() end
  end
  if dungeon then
    me.run = me.run or { dungeon = dungeon, started = now, jumps = 0 }
    me.run.lastInside = now
  end
end

local function inRun()
  return me.run and zone == me.run.dungeon and currentDungeon() == me.run.dungeon
end

local function locationText()
  local mode = db.counter.location or "login"
  if mode == "off" or not zone or zone == "" then return nil end
  if inRun() then return format("%s run  %s", zone, commas(me.run.jumps)) end
  local n = mode == "visit" and visitJumps or (sessionZones[zone] or 0)
  return format("%s  %s", zone, commas(n))
end

local function updateCounter()
  if not counter then return end
  counter.text:SetText("|cffffd200Jumps|r  " .. commas(me.jumps))
  local where = locationText()
  local width = counter.text:GetStringWidth()
  if where then
    counter.where:SetText(where)
    counter.where:Show()
    width = math.max(width, counter.where:GetStringWidth())
    counter.text:ClearAllPoints()
    counter.text:SetPoint("TOP", 0, -6)
    counter:SetHeight(40)
  else
    counter.where:Hide()
    counter.text:ClearAllPoints()
    counter.text:SetPoint("CENTER")
    counter:SetHeight(24)
  end
  counter:SetWidth(width + 24)
end

local function onZoneChanged()
  local newZone = GetRealZoneText()
  if not newZone or newZone == "" then return end
  -- We were inside the run's dungeon until just now.
  if me.run and zone == me.run.dungeon then me.run.lastInside = time() end
  addTime()  -- the time so far belongs to the zone we're leaving
  if newZone ~= zone then
    zone = newZone
    visitJumps = 0
  end
  checkRun()
  updateCounter()
  refreshWindow()
end

local function zoneLoop()
  addTime()
  checkRun()
  updateCounter()
  refreshWindow()
  C_Timer.After(ZONE_CHECK_EVERY, zoneLoop)
end

local function countJump()
  me.jumps = me.jumps + 1
  me.timedJumps = (me.timedJumps or 0) + 1
  sessionJumps = sessionJumps + 1
  if zone and zone ~= "" then
    me.zones[zone] = (me.zones[zone] or 0) + 1
    sessionZones[zone] = (sessionZones[zone] or 0) + 1
  end
  visitJumps = visitJumps + 1
  if inRun() then
    me.run.jumps = me.run.jumps + 1
    me.run.lastInside = time()
  end
  updateCounter()
  refreshWindow()
end

---------------------------------------------------------------------------
-- Perfect hops and streaks
--
-- A perfect hop is a fresh press that leaves the ground within PERFECT_GAP of
-- landing: one frame at 60 FPS, measured in time so higher frame rates aren't
-- punished. Holding the key makes the game re-jump on the landing frame by
-- itself, so held hops neither count as perfect nor break a streak.
---------------------------------------------------------------------------
local PERFECT_GAP = 0.020
local SHOW_STREAK = 3     -- streaks this long or longer get the pop-up
local POPUP_FADE = 1.5    -- seconds the pop-up stays after a streak ends

local landedAt
local streak, streakStartBest, bestSounded = 0, 0, false
local popup, popupToken = nil, 0

local function hidePopupSoon()
  popupToken = popupToken + 1
  local token = popupToken
  C_Timer.After(POPUP_FADE, function()
    if token == popupToken and popup then popup:Hide() end
  end)
end

local function showStreak()
  if not popup or streak < SHOW_STREAK then return end
  popupToken = popupToken + 1  -- cancels a pending fade
  local newBest = streak > streakStartBest
  popup.text:SetText(format("Perfect x%d!", streak))
  popup.sub:SetText("New best!")
  popup.sub:SetShown(newBest)
  popup:Show()
  if newBest and not bestSounded then
    bestSounded = true
    if PlaySound and SOUNDKIT and SOUNDKIT.IG_QUEST_LIST_COMPLETE then
      pcall(PlaySound, SOUNDKIT.IG_QUEST_LIST_COMPLETE)
    end
  end
end

local function endStreak()
  if streak >= SHOW_STREAK then hidePopupSoon() end
  streak = 0
end

local function perfectHop()
  if streak == 0 then streakStartBest, bestSounded = me.bestStreak or 0, false end
  streak = streak + 1
  me.perfectHops = (me.perfectHops or 0) + 1
  if streak > (me.bestStreak or 0) then me.bestStreak = streak end
  if zone and zone ~= "" and streak > (me.zoneBest[zone] or 0) then me.zoneBest[zone] = streak end
  showStreak()
end

-- Judge a counted hop that left the ground at time t.
local function judgeHop(t)
  if not landedAt then
    endStreak()
    return
  end
  if held and pressedAt < landedAt then
    dbg("held hop: streak unchanged")
    return
  end
  local gap = t - landedAt
  if gap <= PERFECT_GAP then
    perfectHop()
    dbg("perfect hop, %d ms after landing (streak %d)", gap * 1000, streak)
  else
    dbg("hop %d ms after landing", gap * 1000)
    endStreak()
  end
end

local function canCount()
  return not IsSwimming() and not UnitIsDeadOrGhost("player") and not UnitOnTaxi("player")
end

local function onPress()
  held, pressedAt, groundedFor = true, GetTime(), 0
  dbg("jump pressed (in the air: %s)", tostring(falling))
end

local function onRelease() held = false end

local function onUpdate(_, elapsed)
  local nowFalling = IsFalling() and true or false
  if nowFalling and not falling then
    local recent = GetTime() - pressedAt <= TAKEOFF_WINDOW
    if (held or recent) and canCount() then
      countJump()
      dbg("hop %d", me.jumps)
      judgeHop(GetTime())
    else
      dbg("left the ground without a jump")
    end
  elseif falling and not nowFalling then
    landedAt = GetTime()
  end
  if nowFalling then
    groundedFor = 0
  else
    groundedFor = groundedFor + elapsed
    if held and groundedFor > HELD_TIMEOUT then held = false end
  end
  falling = nowFalling
end

---------------------------------------------------------------------------
-- Sharing with other players
--
-- Hidden addon messages, prefix "Hopscotch", each starting with protocol "1":
--   1:S:<characterJumps>:<accountTotal>[:<bestStreak>]    my numbers
--   1:SQ:<characterJumps>:<accountTotal>[:<bestStreak>]   my numbers, and please send yours
--   1:Q                                    please send yours
-- Answers to a request go back by whisper, so the guild isn't flooded.
-- Only the character you're on and the account total are shared, never alt names.
---------------------------------------------------------------------------
local PREFIX = "Hopscotch"
local ANNOUNCE_GAP = 10           -- seconds between announcements on one channel
local UPDATE_EVERY = 60           -- seconds between sending changed numbers
local REPLY_GAP = 10              -- seconds between answers to the same player
local COMPARE_WAIT = 5            -- seconds to wait for a /hop compare answer
local FORGET_AFTER = 30 * 86400   -- drop players not heard from in this long
local MAX_JUMPS = 1000000000

local SOURCES = { GUILD = "guild", PARTY = "group", RAID = "group", INSTANCE_CHAT = "group", WHISPER = "whisper" }

local myKey
local lastSent, lastReply, comparing = {}, {}, {}
local sentTotal, groupSize = nil, 0

local function accountTotal()
  local total = 0
  for _, e in pairs(db.chars) do total = total + e.jumps end
  return total
end

local function sharing() return db.share ~= false end

local function send(text, channel, target)
  if not (C_ChatInfo and C_ChatInfo.SendAddonMessage) then return end
  C_ChatInfo.SendAddonMessage(PREFIX, text, channel, target)
  dbg("sent %s to %s%s", text, channel, target and (" " .. target) or "")
end

local function groupChannel()
  if IsInRaid() then return "RAID" elseif IsInGroup() then return "PARTY" end
end

-- Tell a channel my numbers, and with ask, ask for theirs.
local function announce(channel, ask, force)
  if not channel or not sharing() then return end
  local now = GetTime()
  if not force and lastSent[channel] and now - lastSent[channel] < ANNOUNCE_GAP then return end
  lastSent[channel] = now
  sentTotal = accountTotal()
  send(format("1:%s:%d:%d:%d", ask and "SQ" or "S", me.jumps, sentTotal, me.bestStreak or 0), channel)
end

local function sendUpdates()
  if sharing() and accountTotal() ~= sentTotal then
    if IsInGuild() then announce("GUILD", false, true) end
    announce(groupChannel(), false, true)
  end
  C_Timer.After(UPDATE_EVERY, sendUpdates)
end

local function reply(sender)
  if not sharing() then return end
  local now = GetTime()
  if lastReply[sender] and now - lastReply[sender] < REPLY_GAP then return end
  lastReply[sender] = now
  send(format("1:S:%d:%d:%d", me.jumps, accountTotal(), me.bestStreak or 0), "WHISPER", sender)
end

local function shortName(sender)
  if Ambiguate then return Ambiguate(sender, "none") end
  return (sender:gsub("%-.*$", ""))
end

local function fullName(sender)
  if sender:find("-", 1, true) then return sender end
  return sender .. "-" .. GetRealmName()
end

local function remember(key, name, charJumps, total, channel, best)
  local p = db.players[key] or {}
  local source = SOURCES[channel] or "whisper"
  p.name, p.charJumps, p.total, p.seen = name, charJumps, total, time()
  p.best = best
  p[source], p.source = p.seen, source
  db.players[key] = p

  local asked = comparing[name:lower()]
  if asked then
    comparing[name:lower()] = nil
    say("%s: %s on this character, %s on the account.", name, commas(charJumps), commas(total))
  end
  refreshWindow()
end

local function onAddonMessage(prefix, text, channel, sender)
  if prefix ~= PREFIX or type(text) ~= "string" or type(sender) ~= "string" then return end
  local key = fullName(sender)
  if key == myKey then return end
  local kind, rest = text:match("^1:(%u+):?(.*)$")
  if not kind then return end
  dbg("heard %s from %s on %s", text, sender, tostring(channel))
  if kind == "S" or kind == "SQ" then
    -- Fields: character jumps, account total, then (0.3.0+) best streak.
    -- Newer versions may add more after these; ignore them.
    local charJumps, total, best = rest:match("^(%d+):(%d+):?(%d*)")
    charJumps, total, best = tonumber(charJumps), tonumber(total), tonumber(best)
    if charJumps and total and charJumps <= total and total <= MAX_JUMPS then
      if best and best > charJumps then best = nil end
      remember(key, shortName(sender), charJumps, total, channel, best)
    end
  end
  if kind == "Q" or kind == "SQ" then reply(sender) end
end

local function onGroupChanged()
  local size = GetNumGroupMembers()
  if size > groupSize and size > 1 then announce(groupChannel(), true) end
  groupSize = size
  refreshWindow()
end

local function startSharing()
  if IsInGuild() then announce("GUILD", true) end
  groupSize = GetNumGroupMembers()
  if groupSize > 1 then announce(groupChannel(), true) end
  C_Timer.After(UPDATE_EVERY, sendUpdates)
end

local function compare(name)
  name = strtrim(name or "")
  if name == "" then
    say("type a name: /hop compare <name>")
    return
  end
  local key = shortName(name):lower()
  comparing[key] = true
  send("1:Q", "WHISPER", name)
  C_Timer.After(COMPARE_WAIT, function()
    if comparing[key] then
      comparing[key] = nil
      say("no answer from %s. They may be offline, or not running Hopscotch.", name)
    end
  end)
end

local function forgetOldPlayers()
  local cutoff = time() - FORGET_AFTER
  for key, p in pairs(db.players) do
    if type(p) ~= "table" or (p.seen or 0) < cutoff then db.players[key] = nil end
  end
end

local function ago(seconds)
  if seconds < 300 then return "just now" end
  if seconds < 3600 then return format("%d min ago", seconds / 60) end
  if seconds < 86400 then
    local h = math.floor(seconds / 3600)
    return h == 1 and "1 hour ago" or format("%d hours ago", h)
  end
  local d = math.floor(seconds / 86400)
  return d == 1 and "1 day ago" or format("%d days ago", d)
end

---------------------------------------------------------------------------
-- On-screen counter
---------------------------------------------------------------------------
local function savePosition()
  local point, _, relPoint, x, y = counter:GetPoint(1)
  if not point then return end
  db.counter.point, db.counter.relPoint = point, relPoint
  db.counter.x, db.counter.y = math.floor(x + 0.5), math.floor(y + 0.5)
end

local function placeCounter()
  local c = db.counter
  counter:ClearAllPoints()
  counter:SetPoint(c.point or "TOP", UIParent, c.relPoint or c.point or "TOP", c.x or 0, c.y or -120)
end

local function setCounterShown(shown)
  db.counter.hidden = not shown or nil
  counter:SetShown(shown)
  refreshWindow()
end

local function setLocked(locked)
  db.counter.locked = locked or nil
  refreshWindow()
end

local toggleWindow

local function buildCounter()
  counter = CreateFrame("Button", "HopscotchCounter", UIParent, "BackdropTemplate")
  counter:SetSize(90, 24)
  counter:SetFrameStrata("MEDIUM")
  counter:SetClampedToScreen(true)
  counter:SetMovable(true)
  counter:EnableMouse(true)
  counter:RegisterForDrag("LeftButton")
  counter:RegisterForClicks("LeftButtonUp")
  if counter.SetBackdrop then
    counter:SetBackdrop({
      bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
      edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
      tile = true, tileSize = 16, edgeSize = 12,
      insets = { left = 3, right = 3, top = 3, bottom = 3 },
    })
    counter:SetBackdropColor(0, 0, 0, 0.6)
    counter:SetBackdropBorderColor(0.6, 0.6, 0.6, 0.8)
  end
  counter.text = counter:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  counter.text:SetPoint("CENTER")
  counter.where = counter:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  counter.where:SetPoint("BOTTOM", 0, 7)
  counter.where:SetTextColor(0.75, 0.75, 0.75)

  counter:SetScript("OnDragStart", function(self)
    if not db.counter.locked then self:StartMoving() end
  end)
  counter:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    savePosition()
  end)
  counter:SetScript("OnClick", function() toggleWindow() end)
  counter:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_BOTTOM")
    GameTooltip:SetText("Hopscotch")
    GameTooltip:AddLine("Click to see every character's jumps.", 1, 1, 1)
    GameTooltip:AddLine(sessionText(), 1, 0.82, 0)
    if not db.counter.locked then GameTooltip:AddLine("Drag to move.", 1, 1, 1) end
    GameTooltip:Show()
  end)
  counter:SetScript("OnLeave", function() GameTooltip:Hide() end)

  placeCounter()
  updateCounter()
  counter:SetShown(not db.counter.hidden)

  popup = CreateFrame("Frame", "HopscotchPopup", UIParent)
  popup:SetSize(220, 44)
  popup:SetPoint("BOTTOM", counter, "TOP", 0, 4)
  popup:SetFrameStrata("HIGH")
  popup:EnableMouse(false)
  popup.text = popup:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
  popup.text:SetPoint("TOP", 0, -4)
  popup.text:SetTextColor(1, 0.82, 0)
  popup.sub = popup:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  popup.sub:SetPoint("TOP", popup.text, "BOTTOM", 0, -2)
  popup.sub:SetTextColor(0.4, 1, 0.4)
  popup:Hide()
end

---------------------------------------------------------------------------
-- Window
---------------------------------------------------------------------------
local ROW_HEIGHT = 22

StaticPopupDialogs.HOPSCOTCH_REMOVE = {
  text = "Remove %s from Hopscotch?\nTheir %s jumps come off the account total.",
  button1 = REMOVE or "Remove",
  button2 = CANCEL or "Cancel",
  OnAccept = function(_, key)
    if db and key and db.chars[key] ~= me then
      db.chars[key] = nil
      refreshWindow()
    end
  end,
  timeout = 0,
  whileDead = true,
  hideOnEscape = true,
  preferredIndex = 3,
}

local function displayName(e) return e.name .. " - " .. e.realm end

local LOCATION_LABELS = { login = "Since login", visit = "This visit", off = "Off" }
local NEXT_LOCATION = { login = "visit", visit = "off", off = "login" }

local function cycleLocation()
  local nextMode = NEXT_LOCATION[db.counter.location or "login"]
  db.counter.location = nextMode ~= "login" and nextMode or nil
  updateCounter()
  refreshWindow()
end

-- A row with text on the left (name) and on the right (right).
local function makeTextRow(parent, i)
  local row = CreateFrame("Frame", nil, parent)
  row:SetHeight(ROW_HEIGHT)
  row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_HEIGHT)
  row:SetPoint("RIGHT", parent, "RIGHT", 0, 0)
  row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  row.name:SetPoint("LEFT", 4, 0)
  row.name:SetJustifyH("LEFT")
  row.right = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.right:SetPoint("RIGHT", -4, 0)
  row.right:SetJustifyH("RIGHT")
  row.rate = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.rate:SetPoint("RIGHT", -70, 0)
  row.rate:SetJustifyH("RIGHT")
  return row
end

local function sortedChars()
  local list = {}
  for key, e in pairs(db.chars) do list[#list + 1] = { key = key, entry = e } end
  table.sort(list, function(a, b)
    if a.entry.jumps ~= b.entry.jumps then return a.entry.jumps > b.entry.jumps end
    return a.key < b.key
  end)
  return list
end

local function makeRow(parent, i)
  local row = CreateFrame("Frame", nil, parent)
  row:SetHeight(ROW_HEIGHT)
  row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_HEIGHT)
  row:SetPoint("RIGHT", parent, "RIGHT", 0, 0)

  row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.name:SetPoint("LEFT", 4, 0)
  row.name:SetJustifyH("LEFT")

  row.remove = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
  row.remove:SetSize(22, 18)
  row.remove:SetPoint("RIGHT", -2, 0)
  row.remove:SetText("X")
  row.remove:SetScript("OnClick", function(self)
    local r = self:GetParent()
    if r.key then StaticPopup_Show("HOPSCOTCH_REMOVE", displayName(r.entry), commas(r.entry.jumps), r.key) end
  end)

  row.jumps = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.jumps:SetPoint("RIGHT", row.remove, "LEFT", -8, 0)
  row.jumps:SetJustifyH("RIGHT")

  row.rate = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.rate:SetPoint("RIGHT", row.remove, "LEFT", -72, 0)
  row.rate:SetJustifyH("RIGHT")

  row.best = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.best:SetPoint("RIGHT", row.remove, "LEFT", -128, 0)
  row.best:SetJustifyH("RIGHT")
  return row
end

local function makePlayerRow(parent, i)
  local row = CreateFrame("Frame", nil, parent)
  row:SetHeight(ROW_HEIGHT)
  row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_HEIGHT)
  row:SetPoint("RIGHT", parent, "RIGHT", 0, 0)

  row.bg = row:CreateTexture(nil, "BACKGROUND")
  row.bg:SetAllPoints()
  row.bg:SetColorTexture(0.25, 0.5, 1, 0.15)

  row.rank = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.rank:SetPoint("LEFT", 2, 0)
  row.rank:SetWidth(20)
  row.rank:SetJustifyH("RIGHT")

  row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  row.name:SetPoint("LEFT", 28, 0)
  row.name:SetJustifyH("LEFT")

  row.total = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.total:SetPoint("RIGHT", -4, 0)
  row.total:SetJustifyH("RIGHT")

  row.charJumps = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  row.charJumps:SetPoint("RIGHT", -76, 0)
  row.charJumps:SetJustifyH("RIGHT")
  return row
end

local function checkbox(parent, name, label, x, onClick)
  local box = CreateFrame("CheckButton", name, parent, "UICheckButtonTemplate")
  box:SetSize(24, 24)
  box:SetPoint("BOTTOMLEFT", parent, "BOTTOMLEFT", x, 10)
  local text = box:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  text:SetPoint("LEFT", box, "RIGHT", 2, 1)
  text:SetText(label)
  box:SetScript("OnClick", function(self) onClick(self:GetChecked() and true or false) end)
  return box
end

local function smallButton(parent, name, label, width, onClick)
  local b = CreateFrame("Button", name, parent, "UIPanelButtonTemplate")
  b:SetSize(width, 22)
  b:SetText(label)
  b:SetScript("OnClick", onClick)
  return b
end

local function scrollList(parent, name, top, bottom)
  local scroll = CreateFrame("ScrollFrame", name, parent, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", 12, top)
  scroll:SetPoint("BOTTOMRIGHT", -32, bottom)
  local content = CreateFrame("Frame", nil, scroll)
  content:SetSize(330, 1)
  scroll:SetScrollChild(content)
  return content
end

local function setShare(on)
  if on then
    db.share = nil
    sentTotal = nil  -- send our numbers with the next update
  else
    db.share = false
  end
  refreshWindow()
end

local function buildMineView()
  local view = CreateFrame("Frame", nil, window)
  view:SetPoint("TOPLEFT", 0, -58)
  view:SetPoint("BOTTOMRIGHT", 0, 0)
  window.mineView = view

  window.content = scrollList(view, "HopscotchWindowScroll", 0, 146)
  window.session = view:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  window.session:SetPoint("BOTTOMLEFT", 16, 108)
  window.perfect = view:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  window.perfect:SetPoint("BOTTOMLEFT", 16, 126)
  window.rows = {}

  local totalLabel = view:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  totalLabel:SetPoint("BOTTOMLEFT", 16, 48)
  totalLabel:SetText("Account total")
  window.total = view:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  window.total:SetPoint("BOTTOMRIGHT", -40, 48)
  window.totalRate = view:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  window.totalRate:SetPoint("BOTTOMRIGHT", -110, 49)

  window.lockBox = checkbox(view, "HopscotchWindowLock", "Lock counter", 12, setLocked)
  window.showBox = checkbox(view, "HopscotchWindowShow", "Show counter", 170, setCounterShown)

  local locLabel = view:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  locLabel:SetPoint("BOTTOMLEFT", 16, 82)
  locLabel:SetText("Location line on the counter:")
  window.locationButton = smallButton(view, "HopscotchWindowLocation", "", 110, cycleLocation)
  window.locationButton:SetPoint("BOTTOMRIGHT", -36, 76)
end

local function buildPlacesView()
  local view = CreateFrame("Frame", nil, window)
  view:SetPoint("TOPLEFT", 0, -58)
  view:SetPoint("BOTTOMRIGHT", 0, 0)
  window.placesView = view

  window.placesScope = "char"
  window.scopeButtons = {
    char = smallButton(view, "HopscotchWindowScopeChar", "This character", 110, function()
      window.placesScope = "char"
      refreshWindow()
    end),
    account = smallButton(view, "HopscotchWindowScopeAccount", "Account", 110, function()
      window.placesScope = "account"
      refreshWindow()
    end),
  }
  window.scopeButtons.char:SetPoint("TOPLEFT", 12, 0)
  window.scopeButtons.account:SetPoint("LEFT", window.scopeButtons.char, "RIGHT", 4, 0)

  window.zoneContent = scrollList(view, "HopscotchWindowZonesScroll", -30, 200)
  window.zoneRows = {}

  local runsLabel = view:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  runsLabel:SetPoint("BOTTOMLEFT", 16, 180)
  runsLabel:SetText("Recent dungeon runs")
  window.runContent = scrollList(view, "HopscotchWindowRunsScroll", -(382 - 172), 12)
  window.runRows = {}
  window.noRuns = view:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  window.noRuns:SetPoint("TOPLEFT", window.runContent, "TOPLEFT", 4, -4)
  window.noRuns:SetText("No dungeon runs yet. Runs start when you enter a dungeon or raid.")
end

local function buildPlayersView()
  local view = CreateFrame("Frame", nil, window)
  view:SetPoint("TOPLEFT", 0, -58)
  view:SetPoint("BOTTOMRIGHT", 0, 0)
  window.playersView = view

  window.filter = "all"
  window.filters = {}
  local x = 12
  for _, f in ipairs({ { "all", "All" }, { "guild", "Guild" }, { "group", "Group" } }) do
    local key = f[1]
    local b = smallButton(view, "HopscotchWindowFilter" .. f[2], f[2], 64, function()
      window.filter = key
      refreshWindow()
    end)
    b:SetPoint("TOPLEFT", x, 0)
    window.filters[key] = b
    x = x + 68
  end

  local function header(text, point, xOff)
    local h = view:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    h:SetPoint(point, view, "TOP" .. point, xOff, -30)
    h:SetText(text)
  end
  header("Player", "LEFT", 40)
  header("Character", "RIGHT", -112)
  header("Account", "RIGHT", -40)

  window.playerContent = scrollList(view, "HopscotchWindowPlayersScroll", -46, 44)
  window.playerRows = {}

  window.shareBox = checkbox(view, "HopscotchWindowShare", "Share my jumps", 12, setShare)
  local hint = view:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  hint:SetPoint("BOTTOMRIGHT", -16, 16)
  hint:SetText("/hop compare <name>")
end

local function showView(name)
  window.view = name
  refreshWindow()
end

local function buildWindow()
  window = CreateFrame("Frame", "HopscotchWindow", UIParent, "BasicFrameTemplateWithInset")
  window:SetSize(400, 440)
  window:SetPoint("CENTER")
  window:SetFrameStrata("DIALOG")
  window:SetClampedToScreen(true)
  window:SetMovable(true)
  window:EnableMouse(true)
  window:RegisterForDrag("LeftButton")
  window:SetScript("OnDragStart", window.StartMoving)
  window:SetScript("OnDragStop", window.StopMovingOrSizing)
  window.TitleText:SetText("Hopscotch")
  tinsert(UISpecialFrames, "HopscotchWindow")

  window.tabs = {
    mine = smallButton(window, "HopscotchWindowTabMine", "My characters", 120, function() showView("mine") end),
    players = smallButton(window, "HopscotchWindowTabPlayers", "Players", 110, function() showView("players") end),
    places = smallButton(window, "HopscotchWindowTabPlaces", "Places", 110, function() showView("places") end),
  }
  window.tabs.mine:SetPoint("TOPLEFT", 12, -28)
  window.tabs.players:SetPoint("LEFT", window.tabs.mine, "RIGHT", 4, 0)
  window.tabs.places:SetPoint("LEFT", window.tabs.players, "RIGHT", 4, 0)

  buildMineView()
  buildPlayersView()
  buildPlacesView()
  window.view = "mine"

  window:SetScript("OnShow", function() refreshWindow() end)
  window:Hide()
end

local function refreshMine()
  local list, total = sortedChars(), 0
  for i, item in ipairs(list) do
    local e = item.entry
    total = total + e.jumps
    local row = window.rows[i] or makeRow(window.content, i)
    window.rows[i] = row
    row.key, row.entry = item.key, e
    local label = e.name .. " |cff808080- " .. e.realm .. "|r"
    if e == me then label = label .. " |cff66ccff(you)|r" end
    row.name:SetText(label)
    local color = RAID_CLASS_COLORS and RAID_CLASS_COLORS[e.class or ""]
    if color then row.name:SetTextColor(color.r, color.g, color.b) else row.name:SetTextColor(1, 1, 1) end
    row.jumps:SetText(commas(e.jumps))
    row.rate:SetText(rateText(e.timedJumps, e.seconds))
    row.best:SetText((e.bestStreak or 0) > 0 and format("best %d", e.bestStreak) or "")
    row.remove:SetShown(e ~= me)
    row:Show()
  end
  for i = #list + 1, #window.rows do window.rows[i]:Hide() end
  window.content:SetHeight(math.max(1, #list * ROW_HEIGHT))
  window.total:SetText(commas(total))
  window.lockBox:SetChecked(db.counter.locked and true or false)
  window.showBox:SetChecked(not db.counter.hidden)
  window.locationButton:SetText(LOCATION_LABELS[db.counter.location or "login"])
  local timedJumps, seconds = 0, 0
  for _, e in pairs(db.chars) do
    if e.seconds then
      timedJumps, seconds = timedJumps + (e.timedJumps or 0), seconds + e.seconds
    end
  end
  window.totalRate:SetText(rateText(timedJumps, seconds))
  window.session:SetText(sessionText())
  window.perfect:SetText(format("Perfect hops: %s, best streak %d", commas(me.perfectHops or 0), me.bestStreak or 0))
end

local function zoneList()
  local totals, seconds, bests = {}, {}, {}
  local chars = window.placesScope == "account" and db.chars or { me }
  for _, e in pairs(chars) do
    for z, n in pairs(e.zones or {}) do totals[z] = (totals[z] or 0) + n end
    for z, t in pairs(e.zoneSeconds or {}) do seconds[z] = (seconds[z] or 0) + t end
    for z, b in pairs(e.zoneBest or {}) do bests[z] = math.max(bests[z] or 0, b) end
  end
  local list = {}
  for z, n in pairs(totals) do
    list[#list + 1] = { zone = z, jumps = n, seconds = seconds[z], best = bests[z] }
  end
  table.sort(list, function(a, b)
    if a.jumps ~= b.jumps then return a.jumps > b.jumps end
    return a.zone < b.zone
  end)
  return list
end

local function fillRows(rows, content, items, fill)
  for i, item in ipairs(items) do
    local row = rows[i] or makeTextRow(content, i)
    rows[i] = row
    fill(row, item)
    row:Show()
  end
  for i = #items + 1, #rows do rows[i]:Hide() end
  content:SetHeight(math.max(1, #items * ROW_HEIGHT))
end

local function refreshPlaces()
  fillRows(window.zoneRows, window.zoneContent, zoneList(), function(row, item)
    local label = item.zone
    if db.dungeons[item.zone] then label = label .. "  |cff808080dungeon|r" end
    if item.best then label = label .. format("  |cff808080best streak %d|r", item.best) end
    row.name:SetText(label)
    row.right:SetText(commas(item.jumps))
    row.rate:SetText(rateText(item.jumps, item.seconds))
    row.jumps = row.right
  end)

  local now = time()
  fillRows(window.runRows, window.runContent, db.runs, function(row, run)
    local d = db.dungeons[run.dungeon]
    local record = d and format("  (fewest %s, most %s)", commas(d.fewest), commas(d.most)) or ""
    row.name:SetText(format("%s  |cff808080%s, %s%s|r", run.dungeon, run.char or "?", ago(now - (run.ended or now)), record))
    local info = format("%s jumps, %d min", commas(run.jumps), math.floor((run.seconds or 0) / 60 + 0.5))
    local r = perHour(run.jumps, run.seconds, 60)
    if r then info = info .. format(", %s/h", commas(r)) end
    row.right:SetText(info)
    row.rate:SetText("")
    row.info = row.right
  end)
  window.noRuns:SetShown(#db.runs == 0)

  window.scopeButtons.char:SetEnabled(window.placesScope ~= "char")
  window.scopeButtons.account:SetEnabled(window.placesScope ~= "account")
end

local function inMyGroup(name)
  local inParty = UnitInParty and UnitInParty(name)
  local inRaid = UnitInRaid and UnitInRaid(name)
  return (inParty or inRaid) and true or false
end

local function playerList()
  local list, filter, now = {}, window.filter, time()
  for _, p in pairs(db.players) do
    local keep = filter == "all"
      or (filter == "guild" and p.guild ~= nil)
      or (filter == "group" and inMyGroup(p.name))
    if keep then
      local note = (p.source or "whisper") .. ", " .. ago(now - (p.seen or now))
      if p.best and p.best > 0 then note = note .. format(", best streak %d", p.best) end
      list[#list + 1] = { name = p.name, charJumps = p.charJumps, total = p.total, note = note }
    end
  end
  list[#list + 1] = { name = me.name, charJumps = me.jumps, total = accountTotal(), you = true }
  table.sort(list, function(a, b)
    if a.total ~= b.total then return a.total > b.total end
    return a.name < b.name
  end)
  return list
end

local function refreshPlayers()
  local list = playerList()
  for i, item in ipairs(list) do
    local row = window.playerRows[i] or makePlayerRow(window.playerContent, i)
    window.playerRows[i] = row
    row.rank:SetText(i)
    if item.you then
      row.name:SetText(item.name .. " |cff66ccff(you)|r")
    else
      row.name:SetText(item.name .. "  |cff808080" .. item.note .. "|r")
    end
    row.bg:SetShown(item.you or false)
    row.charJumps:SetText(commas(item.charJumps))
    row.total:SetText(commas(item.total))
    row:Show()
  end
  for i = #list + 1, #window.playerRows do window.playerRows[i]:Hide() end
  window.playerContent:SetHeight(math.max(1, #list * ROW_HEIGHT))
  for key, b in pairs(window.filters) do b:SetEnabled(key ~= window.filter) end
  window.shareBox:SetChecked(sharing())
end

refreshWindow = function()
  if not (window and window:IsShown()) then return end
  local view = window.view
  window.mineView:SetShown(view == "mine")
  window.playersView:SetShown(view == "players")
  window.placesView:SetShown(view == "places")
  for name, tab in pairs(window.tabs) do tab:SetEnabled(name ~= view) end
  if view == "players" then
    refreshPlayers()
  elseif view == "places" then
    refreshPlaces()
  else
    refreshMine()
  end
end

toggleWindow = function()
  if not window then buildWindow() end
  if window:IsShown() then window:Hide() else window:Show() end
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
local HELP = {
  "/hop  -  open or close the window with every character's jumps",
  "/hop show  /  /hop hide  -  show or hide the on-screen counter",
  "/hop lock  /  /hop unlock  -  stop or allow dragging the counter",
  "/hop compare <name>  -  ask another Hopscotch player for their jumps",
  "/hop debug  -  print each jump press and shared message, to check what counts",
}

SLASH_HOPSCOTCH1 = "/hop"
SLASH_HOPSCOTCH2 = "/hopscotch"
SlashCmdList.HOPSCOTCH = function(msg)
  if not (db and me and counter) then
    say("didn't finish loading. Try /reload, and check for errors.")
    return
  end
  local word, rest = strtrim(msg or ""):match("^(%S*)%s*(.-)$")
  word = word:lower()
  if word == "compare" then
    compare(rest)
  elseif word == "" then
    toggleWindow()
  elseif word == "show" or word == "hide" then
    setCounterShown(word == "show")
  elseif word == "lock" or word == "unlock" then
    setLocked(word == "lock")
    say(word == "lock" and "counter locked." or "counter unlocked. Drag it anywhere.")
  elseif word == "debug" then
    debugging = not debugging
    say("debug %s.", debugging and "on" or "off")
  elseif word == "help" then
    for _, line in ipairs(HELP) do say(line) end
  else
    say("no command called %s. Type /hop help for commands.", word)
  end
end

---------------------------------------------------------------------------
-- Startup
---------------------------------------------------------------------------
local SHARE_DELAY = 10  -- seconds after login before telling guild and group

local events = CreateFrame("Frame")
for _, e in ipairs({ "ADDON_LOADED", "PLAYER_LOGIN", "CHAT_MSG_ADDON", "GROUP_ROSTER_UPDATE",
                     "ZONE_CHANGED_NEW_AREA", "PLAYER_ENTERING_WORLD", "PLAYER_LOGOUT" }) do
  pcall(events.RegisterEvent, events, e)
end
events:SetScript("OnEvent", function(self, event, arg1, ...)
  if event == "CHAT_MSG_ADDON" then
    if db and me then onAddonMessage(arg1, ...) end
  elseif event == "GROUP_ROSTER_UPDATE" then
    if db and me then onGroupChanged() end
  elseif event == "PLAYER_LOGOUT" then
    if db and me then addTime() end
  elseif event == "ZONE_CHANGED_NEW_AREA" or event == "PLAYER_ENTERING_WORLD" then
    if db and me then onZoneChanged() end
  elseif event == "ADDON_LOADED" and arg1 == ADDON then
    HopscotchDB = HopscotchDB or {}
    db = HopscotchDB
    db.chars = db.chars or {}
    db.counter = db.counter or {}
    db.players = db.players or {}
    db.runs = db.runs or {}
    db.dungeons = db.dungeons or {}
    forgetOldPlayers()
  elseif event == "PLAYER_LOGIN" then
    local name, realm = UnitName("player"), GetRealmName()
    local key = charKey(name, realm)
    myKey = key
    me = db.chars[key] or { jumps = 0 }
    me.name, me.realm = name, realm
    me.class = select(2, UnitClass("player"))
    me.jumps = me.jumps or 0
    me.zones = me.zones or {}
    me.zoneSeconds = me.zoneSeconds or {}
    me.zoneBest = me.zoneBest or {}
    db.chars[key] = me
    sessionStart, lastTick = GetTime(), GetTime()

    -- Where we are, and whether a saved dungeon run continues or is over.
    zone = GetRealZoneText()
    checkRun()
    C_Timer.After(ZONE_CHECK_EVERY, zoneLoop)

    buildCounter()
    local hooked = pcall(hooksecurefunc, "JumpOrAscendStart", onPress)
    pcall(hooksecurefunc, "AscendStop", onRelease)
    if hooked then
      self:SetScript("OnUpdate", onUpdate)
    else
      say("can't see jumps in this game version, so nothing will be counted.")
    end

    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
      C_ChatInfo.RegisterAddonMessagePrefix(PREFIX)
      C_Timer.After(SHARE_DELAY, startSharing)
    end
  end
end)
