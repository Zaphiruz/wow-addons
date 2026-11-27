-- Hitched: marry another player. Target them and type /hitched propose: you
-- kneel, they get a question, and a yes marries your two characters. Married
-- players show "Married to ..." on their tooltip for everyone with Hitched.
-- Either of you can end it with /hitched divorce.
--
-- The two games talk in addon messages nobody sees. Each game only ever says
-- who its own character is married to, so nobody can marry someone else off.
local ADDON = ...

local db              -- HitchedDB: settings, shared by the account
local char            -- HitchedCharDB: this character's marriage and story
local category, panel -- our page in the game's settings window
local debugging = false

local PINK = "|cffff8fb4"
local function say(fmt, ...) print(PINK .. "Hitched|r: " .. format(fmt, ...)) end
local function dbg(fmt, ...) if debugging then say("|cff999999" .. fmt .. "|r", ...) end end

-- Forever hides some values from addons at restricted moments ("secret
-- values"). They can't be compared or used as keys, so anything that might
-- be one is checked first. Classic Era has no issecretvalue.
local function isSecret(v) return issecretvalue ~= nil and issecretvalue(v) end
local function str(v) if not isSecret(v) and type(v) == "string" and v ~= "" then return v end end
local function day(t) return (date("%d %b %Y", t):gsub("^0", "")) end

---------------------------------------------------------------------------
-- Settings and saved data
---------------------------------------------------------------------------
local OPTIONS = {
  { key = "tooltips", label = "Show on tooltips",
    note = "Who a player is married to, on their tooltip. Your game quietly asks theirs when you point at them." },
  { key = "cheer", label = "Cheer for weddings", note = "Cheer when someone in your guild or group gets married" },
  { key = "proposals", label = "Proposals", note = "Let other players propose to you" },
}
local NOTICE_KEPT = 90 * 86400  -- how long a divorce waits to be delivered
local NAME_MAX = 48

-- Everything that arrives from another game is checked before it is kept or
-- shown: a character ID looks like "Player-1-0000000A", and a name has no
-- colour codes or links in it.
local function goodGUID(v) return type(v) == "string" and #v <= 40 and v:find("^Player%-[%w%-]+$") ~= nil end
local function goodName(v) return type(v) == "string" and #v >= 1 and #v <= NAME_MAX and not v:find("[|;%c]") end

local function loadSaved()
  if type(HitchedDB) ~= "table" then HitchedDB = {} end
  db = HitchedDB
  for _, o in ipairs(OPTIONS) do
    if type(db[o.key]) ~= "boolean" then db[o.key] = true end
  end
  if type(HitchedCharDB) ~= "table" then HitchedCharDB = {} end
  char = HitchedCharDB
  if type(char.story) ~= "table" then char.story = {} end      -- proposals, weddings and divorces, oldest first
  if type(char.notices) ~= "table" then char.notices = {} end  -- character ID -> a divorce they haven't heard of
  local s = char.spouse                                        -- { guid, name, full, since, place }
  if type(s) ~= "table" or not goodGUID(s.guid) or not goodName(s.name) then
    char.spouse = nil
  elseif type(s.since) ~= "number" then
    s.since = time()
  end
  local p = char.proposed                                      -- who you proposed to, until they answer
  if type(p) ~= "table" or not goodGUID(p.guid) or not goodName(p.name) or type(p.at) ~= "number" then
    char.proposed = nil
  end
  for guid, n in pairs(char.notices) do
    if type(n) ~= "table" or not goodName(n.name) or type(n.at) ~= "number" or time() - n.at > NOTICE_KEPT then
      char.notices[guid] = nil
    end
  end
end

---------------------------------------------------------------------------
-- Who is who
--
-- Players are told apart by character ID, never by name: a Forever name can
-- have a surname, and the same player is written differently in different
-- places. A name is only compared to check that a message about a character
-- came from that character.
---------------------------------------------------------------------------
local myGUID, myName, myRealm

local function rememberMe()
  local name = str((UnitName("player")))
  if name then myName = name end
  local guid = str(UnitGUID and UnitGUID("player"))
  if guid then myGUID = guid end
end

-- "Name-Realm" for the player under unit, or nil.
local function fullName(unit)
  local name, realm = UnitName(unit)
  name = str(name)
  if not name then return end
  return name .. "-" .. (str(realm) or myRealm)
end

local function whisperName(full) return Ambiguate(full, "none") end
local function short(full) return Ambiguate(full, "short") end

-- Are these two spellings of one player's name? The realm is left off, and
-- a first name alone matches the same name with a surname.
local function bare(name) return (name:lower():gsub("%-[^%-]*$", "")) end
local function sameName(a, b)
  a, b = bare(a), bare(b)
  return a == b or a:match("^%S+") == b:match("^%S+")
end

local function zone() return str(GetRealZoneText and GetRealZoneText()) end

local function targetGUID()
  local ok, guid = pcall(UnitGUID, "target")
  if ok then return str(guid) end
end

local function hasTarget()
  local ok, exists = pcall(UnitExists, "target")
  return not ok or isSecret(exists) or exists == true
end

-- Is your target one of these players?
local function aimedAt(a, b)
  local t = targetGUID()
  return t ~= nil and (t == a or t == b)
end

---------------------------------------------------------------------------
-- Your story: what Storied shows in its timeline
---------------------------------------------------------------------------
local STORY_MAX = 200
local WHAT = {
  proposed = "Proposed to %s", proposal = "%s proposed to you", declined = "%s said no",
  refused = "You turned %s down", married = "Married %s", divorced = "Divorced %s",
  left = "%s divorced you", ended = "Your marriage to %s ended",
}
local watchers = {}

local function changed()
  for _, fn in ipairs(watchers) do pcall(fn) end
end

local function record(kind, name)
  local s = char.story
  s[#s + 1] = { kind = kind, name = name, at = time(), place = zone() }
  while #s > STORY_MAX do tremove(s, 1) end
end

---------------------------------------------------------------------------
-- Chat and emotes
--
-- The game aims a real emote only at your target, so one is only used when
-- the right player is targeted, or nobody is. Emote lines ("says yes to
-- Bob!") name the player whoever is targeted, but Forever only lets an addon
-- send one from a click or key press.
---------------------------------------------------------------------------
local onForever = (select(4, GetBuildInfo()) or 0) >= 16000

local function chatLocked()
  local ok, locked = pcall(function()
    if C_ChatInfo and C_ChatInfo.InChatMessagingLockdown and C_ChatInfo.InChatMessagingLockdown() then return true end
    local fighting = (C_InstanceEncounter and C_InstanceEncounter.IsEncounterInProgress) or IsEncounterInProgress
    return fighting ~= nil and fighting() and true or false
  end)
  return not ok or locked
end

local function canLine(fromClick) return (fromClick or not onForever) and not chatLocked() end

local function emoteLine(line)
  local send = (C_ChatInfo and C_ChatInfo.SendChatMessage) or SendChatMessage
  if send then pcall(send, line, "EMOTE") end
  dbg("emote line: %s", line)
end

local function perform(token)
  local emote = (C_ChatInfo and C_ChatInfo.PerformEmote) or DoEmote
  if emote then pcall(emote, token) end
  dbg("emote: /%s", token:lower())
end

---------------------------------------------------------------------------
-- Talking to other games
--
-- Every message is "1;<what>;<the sender's character ID>;...". Questions and
-- answers between two players go by whisper; news for everyone goes to guild
-- and group.
---------------------------------------------------------------------------
local PREFIX, VERSION = "Hitched", "1"

-- A whisper to a player who has logged out makes the game print "No player
-- named '...' is currently playing.", even for a whisper nobody sees. An
-- addon can only tell who is online while the game shows them, so for a few
-- seconds after a quiet whisper that line is held back for that player. A
-- proposal isn't quiet: there the line says why nothing came back.
local QUIET_FOR = 5
local quiet = {}    -- { name, till, told } for each quiet whisper
local notFound      -- the game's line as a pattern that finds the name

local function hush(name)
  local t = GetTime()
  for i = #quiet, 1, -1 do
    if quiet[i].till < t then tremove(quiet, i) end
  end
  quiet[#quiet + 1] = { name = name, till = t + QUIET_FOR }
end

-- The game runs this for every chat window the line would go to, so an
-- entry is kept until its time is up, not used up by the first window.
local function hideLine(_, _, text)
  if not notFound or isSecret(text) or type(text) ~= "string" then return end
  local name = text:match(notFound)
  if not name then return end
  local t = GetTime()
  for _, q in ipairs(quiet) do
    if q.till >= t and sameName(q.name, name) then
      if not q.told then
        q.told = true
        dbg("hid the game's line: %s", text)
      end
      return true
    end
  end
end

local function watchChat()
  local line = str(ERR_CHAT_PLAYER_NOT_FOUND_S)
  local add = (ChatFrameUtil and ChatFrameUtil.AddMessageEventFilter) or ChatFrame_AddMessageEventFilter
  if not (line and add) then return end
  -- "No player named '%s' is currently playing." with the name as (.+);
  -- some languages write the name as %1$s.
  local pattern = line:gsub("%%%d+%$s", "%%s"):gsub("%p", "%%%0"):gsub("%%%%s", "(.+)")
  notFound = "^" .. pattern .. "$"
  add("CHAT_MSG_SYSTEM", hideLine)
end

local function send(route, target, ...)
  local fn = C_ChatInfo and C_ChatInfo.SendAddonMessage
  if not (fn and myGUID) then return false end
  local what = ...
  local msg = table.concat({ VERSION, what, myGUID, select(2, ...) }, ";")
  if chatLocked() then
    dbg("not sent, the game is blocking addon messages: %s", msg)
    return false
  end
  if route == "WHISPER" and what ~= "propose" then hush(target) end
  local ok, result = pcall(fn, PREFIX, msg, route, target)
  local shown = not ok and "error" or isSecret(result) and "hidden" or tostring(result)
  dbg("sent %s%s: %s (%s)", route, target and (" to " .. target) or "", msg, shown)
  if not ok then return false end
  if isSecret(result) or result == nil or result == true then return true end
  return result == 0 or (Enum and Enum.SendAddonMessageResult and result == Enum.SendAddonMessageResult.Success) or false
end

local function groupRoute()
  if IsInRaid() then return "RAID" elseif IsInGroup() then return "PARTY" end
end

local function announce(...)
  if IsInGuild() then send("GUILD", nil, ...) end
  local group = groupRoute()
  if group then send(group, nil, ...) end
end

local function wedFields()
  local s = char.spouse
  return "wed", s.guid, s.name, format("%d", s.since)
end

-- Tell someone that you aren't (or are no longer) married to them. Their
-- game answers "divorced" when it has heard.
local TELL_EVERY = 60
local toldAt = {}

local function tellDivorce(guid, to)
  local at = toldAt[guid]
  if at and GetTime() - at < TELL_EVERY then return end
  if send("WHISPER", to, "divorce") then toldAt[guid] = GetTime() end
end

---------------------------------------------------------------------------
-- The question on screen: a proposal to answer, or "really divorce?"
---------------------------------------------------------------------------
local dialog, asking

local function finish(which)
  local q = asking
  if not q then return end
  asking = nil
  dialog:Hide()
  if q[which] then q[which]() end
end

local function buildDialog()
  dialog = CreateFrame("Frame", "HitchedDialog", UIParent, "BasicFrameTemplateWithInset")
  dialog:Hide()
  dialog:SetSize(340, 150)
  dialog:SetPoint("CENTER", 0, 140)
  dialog:SetFrameStrata("DIALOG")
  dialog:SetClampedToScreen(true)
  dialog:SetMovable(true)
  dialog:EnableMouse(true)
  dialog:RegisterForDrag("LeftButton")
  dialog:SetScript("OnDragStart", dialog.StartMoving)
  dialog:SetScript("OnDragStop", dialog.StopMovingOrSizing)
  if type(dialog.TitleText) == "table" then dialog.TitleText:SetText("Hitched") end

  dialog.text = dialog:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  dialog.text:SetPoint("TOP", 0, -42)
  dialog.text:SetWidth(300)
  dialog.text:SetSpacing(4)

  dialog.yes = CreateFrame("Button", nil, dialog, "UIPanelButtonTemplate")
  dialog.yes:SetSize(120, 24)
  dialog.yes:SetPoint("BOTTOMLEFT", 36, 18)
  dialog.yes:SetScript("OnClick", function() finish("onYes") end)
  dialog.no = CreateFrame("Button", nil, dialog, "UIPanelButtonTemplate")
  dialog.no:SetSize(120, 24)
  dialog.no:SetPoint("BOTTOMRIGHT", -36, 18)
  dialog.no:SetScript("OnClick", function() finish("onNo") end)
  -- Closed with the X in the corner: the question goes unanswered.
  dialog:SetScript("OnHide", function() finish("onGone") end)
end

-- q: text, yes and no (button labels), onYes, onNo, onGone (left alone or
-- closed), timeout (seconds).
local function ask(q)
  if not dialog then buildDialog() end
  asking = q
  dialog.text:SetText(q.text)
  dialog.yes:SetText(q.yes)
  dialog.no:SetText(q.no)
  dialog:Show()
  if q.timeout then
    C_Timer.After(q.timeout, function()
      if asking == q then finish("onGone") end
    end)
  end
end

---------------------------------------------------------------------------
-- Tooltips
---------------------------------------------------------------------------
local CLAIM_KEPT = 3600  -- seconds something heard from another game is shown for

-- What other games said about their own characters, this session only:
-- character ID -> { name (of the spouse), from (who said it), at }, or
-- { single = true, from, at }.
local claims = {}
local doneFor = setmetatable({}, { __mode = "k" })  -- tooltip -> the character it already has a line for

local function lineFor(guid, name)
  if guid == myGUID then return char.spouse and ("Married to " .. char.spouse.name) end
  if char.spouse and guid == char.spouse.guid then return "Your spouse since " .. day(char.spouse.since) end
  local c = claims[guid]
  -- Only believed when it came from the player the tooltip is for.
  if c and not c.single and name and GetTime() - c.at < CLAIM_KEPT and sameName(c.from, name) then
    return "Married to " .. c.name
  end
end

local function addUnitLine(tip, once)
  if not (db and char and db.tooltips and tip.GetUnit) then return end
  local _, unit = tip:GetUnit()
  unit = str(unit)
  if not unit or not UnitIsPlayer(unit) then return end
  local guid = str(UnitGUID(unit))
  if not guid or (once and doneFor[tip] == guid) then return end
  local line = lineFor(guid, str((UnitName(unit))))
  if line then
    doneFor[tip] = guid
    tip:AddLine(PINK .. line .. "|r")
  end
end

-- An answer came in while the tooltip for that player is up: add the line now.
local function refreshTooltip(guid)
  pcall(function()
    local tip = GameTooltip
    if not (tip and tip.GetUnit and tip:IsShown()) then return end
    local _, unit = tip:GetUnit()
    unit = str(unit)
    if unit and str(UnitGUID(unit)) == guid then
      addUnitLine(tip, true)
      tip:Show()  -- fits the tooltip to its new line
    end
  end)
end

local function hookTooltips()
  local types = Enum and Enum.TooltipDataType
  if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and types and types.Unit then
    TooltipDataProcessor.AddTooltipPostCall(types.Unit, function(tip) pcall(addUnitLine, tip) end)
  elseif GameTooltip and GameTooltip.HookScript then
    GameTooltip:HookScript("OnTooltipSetUnit", function(self) pcall(addUnitLine, self, true) end)
  end
  if GameTooltip and GameTooltip.HookScript then
    pcall(GameTooltip.HookScript, GameTooltip, "OnTooltipCleared", function(self) doneFor[self] = nil end)
  end
end

---------------------------------------------------------------------------
-- Asking the players you point at
--
-- Pointing at or targeting a player sends their game one quiet question, at
-- most every ten minutes per player, and never faster than one every second
-- and a half. A player without Hitched never notices.
--
-- A player can log out while they wait their turn. If the game still shows
-- them and says they're offline, they're skipped. If it no longer shows
-- them there is no telling, so they're asked, and the game's "No player
-- named" line is held back (see hush).
---------------------------------------------------------------------------
local ASK_EVERY, ASK_GAP, QUEUE_MAX = 600, 1.5, 8
local askedAt = {}   -- character ID -> when we last asked
local queue = {}     -- { guid, name } waiting to be asked
local lastAsk, pumping = -100, false

-- The unit the game shows this player as, if it still shows them.
local function unitOf(guid)
  if UnitTokenFromGUID then
    local ok, unit = pcall(UnitTokenFromGUID, guid)
    if ok and str(unit) then return unit end
  end
  for _, unit in ipairs({ "mouseover", "target" }) do
    local ok, theirs = pcall(UnitGUID, unit)
    if ok and str(theirs) == guid then return unit end
  end
end

local function wentOffline(guid)
  local unit = unitOf(guid)
  if not unit then return false end
  local ok, connected = pcall(UnitIsConnected, unit)
  return ok and not isSecret(connected) and connected == false
end

local function pump()
  pumping = false
  if #queue == 0 then return end
  local wait = lastAsk + ASK_GAP - GetTime()
  if wait <= 0 then
    if not chatLocked() then
      while #queue > 0 do
        local q = tremove(queue, 1)
        if wentOffline(q.guid) then
          askedAt[q.guid] = nil   -- ask when they're back
          dbg("not asked, they went offline: %s", q.name)
        else
          lastAsk = GetTime()
          send("WHISPER", q.name, "ask")
          break
        end
      end
    end
    wait = ASK_GAP
  end
  if #queue > 0 then
    pumping = true
    C_Timer.After(wait, pump)
  end
end

-- A player the game shows you: under the mouse or targeted.
local function notice(unit)
  if not (db and char and myGUID) or not UnitIsPlayer(unit) then return end
  local guid, full = str(UnitGUID(unit)), fullName(unit)
  if not (guid and full) or guid == myGUID then return end
  local connected = UnitIsConnected(unit)
  if not isSecret(connected) and connected == false then return end
  local mine, theirs = str(UnitFactionGroup("player")), str(UnitFactionGroup(unit))
  if mine and theirs and mine ~= theirs then return end  -- the two sides can't whisper
  if char.notices[guid] then
    tellDivorce(guid, whisperName(full))
    return
  end
  if not db.tooltips then return end
  local at = askedAt[guid]
  if (at and GetTime() - at < ASK_EVERY) or #queue >= QUEUE_MAX then return end
  askedAt[guid] = GetTime()
  queue[#queue + 1] = { guid = guid, name = whisperName(full) }
  if not pumping then pump() end
end

---------------------------------------------------------------------------
-- Marrying and divorcing
---------------------------------------------------------------------------
local ACK_WAIT = 5            -- seconds their game has to say the proposal arrived
local ANSWER_WAIT = 60        -- seconds the question stays on their screen
local GIVE_UP = 80            -- seconds until you stop waiting for an answer
local REFUSE_BLOCK = 600      -- seconds before someone you turned down can ask again
local PROPOSED_KEPT = 86400   -- seconds a proposal can still be answered with a late yes

local outgoing          -- your proposal while you wait: { guid, name, got }
local refusedAt = {}    -- character ID -> when you turned them down

local function openProposal()
  local p = char.proposed
  if p and time() - p.at < PROPOSED_KEPT then return p end
  char.proposed = nil
end

local function marry(guid, name, full, since)
  char.spouse = { guid = guid, name = name, full = full, since = since, place = zone() }
  char.proposed, outgoing = nil, nil
  char.notices[guid] = nil
  claims[guid] = nil
  record("married", name)
  say("you and %s are now married!", name)
  announce("just", guid, name)
  changed()
end

local function endMarriage(kind, fmt)
  local s = char.spouse
  if not s then return end
  char.spouse = nil
  record(kind, s.name)
  say(fmt, s.name)
  announce("single")
  changed()
end

local function propose()
  if char.spouse then return say("you're already married to %s.", char.spouse.name) end
  if outgoing then return say("you're still waiting for %s's answer.", outgoing.name) end
  if asking then return say("answer the question on screen first.") end
  local ok, isPlayer = pcall(function() return UnitExists("target") and UnitIsPlayer("target") end)
  if not ok or isSecret(isPlayer) or not isPlayer then
    return say("target the player you want to propose to first.")
  end
  rememberMe()
  local guid, full = targetGUID(), fullName("target")
  if not (guid and full and myGUID) then
    return say("the game is hiding who that is right now. Try again in a moment.")
  end
  if guid == myGUID then return say("you can't marry yourself.") end
  local name = short(full)
  local mine, theirs = str(UnitFactionGroup("player")), str(UnitFactionGroup("target"))
  if mine and theirs and mine ~= theirs then
    return say("%s is on the other side: your games can't talk to each other.", name)
  end
  local connected = UnitIsConnected("target")
  if not isSecret(connected) and connected == false then return say("%s is offline.", name) end
  if chatLocked() then
    return say("the game is blocking addon messages right now. Try again after the fight.")
  end
  if not send("WHISPER", whisperName(full), "propose") then
    return say("the proposal couldn't be sent. Try again in a moment.")
  end
  perform("KNEEL")  -- they are your target, so you kneel before them

  local o = { guid = guid, name = name }
  outgoing = o
  char.proposed = { guid = guid, name = name, full = full, at = time() }
  say("you proposed to %s. Waiting for an answer...", name)
  C_Timer.After(ACK_WAIT, function()
    if outgoing == o and not o.got then
      outgoing, char.proposed = nil, nil
      say("%s doesn't seem to have Hitched, so they can't answer.", name)
    end
  end)
  C_Timer.After(GIVE_UP, function()
    if outgoing == o then
      outgoing = nil
      say("%s didn't answer.", name)
    end
  end)
end

local function divorce()
  local s = char.spouse
  if not s then return say("you aren't married.") end
  if asking then return say("answer the question on screen first.") end
  ask({
    text = format("Really divorce %s?", s.name), yes = "Divorce", no = "Stay married",
    onYes = function()
      if char.spouse ~= s then return end
      -- Kept until their game says it has heard, however long that takes.
      char.notices[s.guid] = { name = s.name, at = time() }
      tellDivorce(s.guid, whisperName(s.full or s.name))
      endMarriage("divorced", "you have divorced %s. They're told now if they're online, or the next time you meet.")
    end,
  })
end

-- Something a player's game said about their marriage: does it fit yours?
local function consistent(guid, sender, theirs, since)
  local s = char.spouse
  if s and s.guid == guid then
    -- Your spouse says they're single, or married to someone else.
    if theirs ~= myGUID and sameName(sender, s.name) then
      endMarriage("ended", "%s is no longer married to you.")
    end
    return
  end
  if theirs ~= myGUID then return end
  -- They say they're married to you, and you aren't married to them.
  local p = openProposal()
  if not s and p and p.guid == guid and sameName(sender, p.name) then
    marry(guid, p.name, p.full, since)  -- you proposed, and their yes never reached you
  else
    tellDivorce(guid, sender)
  end
end

---------------------------------------------------------------------------
-- Messages from other games
---------------------------------------------------------------------------
local ANSWER_EVERY = 5   -- seconds between answers to the same player
local CHEER_ONCE = 120   -- seconds: both newlyweds announce the same wedding
local answeredAt, cheered = {}, {}
local handlers = {}

function handlers.ask(guid, sender, route)
  if route ~= "WHISPER" then return end
  local at = answeredAt[guid]
  if at and GetTime() - at < ANSWER_EVERY then return end
  answeredAt[guid] = GetTime()
  if char.spouse then send("WHISPER", sender, wedFields()) else send("WHISPER", sender, "single") end
end

function handlers.wed(guid, sender, route, f)
  local theirs, name, since = f[4], f[5], tonumber(f[6])
  if not (goodGUID(theirs) and goodName(name) and since and since > 0) then return end
  claims[guid] = { name = name, from = sender, at = GetTime() }
  consistent(guid, sender, theirs, since)
  refreshTooltip(guid)
end

function handlers.single(guid, sender)
  claims[guid] = { single = true, from = sender, at = GetTime() }
  consistent(guid, sender, nil)
end

function handlers.propose(guid, sender, route)
  local name = short(sender)
  if route ~= "WHISPER" or not goodName(name) then return end
  local function refuse(why) send("WHISPER", sender, "no", why) end
  if char.spouse then return refuse("married") end
  local at = refusedAt[guid]
  if not db.proposals or (at and GetTime() - at < REFUSE_BLOCK) then return refuse("closed") end
  if asking or outgoing then return refuse("busy") end

  send("WHISPER", sender, "got")
  record("proposal", name)
  changed()
  ask({
    text = format("%s is on one knee.\nWill you marry %s?", name, name), yes = "I do", no = "No",
    timeout = ANSWER_WAIT,
    onYes = function()
      if char.spouse then return end
      local since = time()
      send("WHISPER", sender, "yes", format("%d", since))
      if canLine(true) then emoteLine(format("says yes to %s!", name)) end
      if aimedAt(guid) or not hasTarget() then perform("CHEER") end
      marry(guid, name, sender, since)
    end,
    onNo = function()
      refusedAt[guid] = GetTime()
      send("WHISPER", sender, "no", "no")
      if canLine(true) then emoteLine(format("gently turns %s down.", name)) end
      record("refused", name)
      changed()
    end,
    onGone = function()
      send("WHISPER", sender, "no", "timeout")
      say("you didn't answer %s's proposal.", name)
    end,
  })
end

function handlers.got(guid, _, route)
  local o = outgoing
  if route ~= "WHISPER" or not (o and o.guid == guid) or o.got then return end
  o.got = true
  record("proposed", o.name)
  changed()
end

function handlers.yes(guid, sender, route, f)
  if route ~= "WHISPER" or char.spouse then return end
  local p = openProposal()
  if not (p and p.guid == guid) then return end
  local since = tonumber(f[4])
  if not since or since <= 0 then since = time() end
  if aimedAt(guid) or not hasTarget() then perform("CHEER") end
  marry(guid, p.name, p.full, since)
end

function handlers.no(guid, _, route, f)
  local p = char.proposed
  if route ~= "WHISPER" or not (p and p.guid == guid) then return end
  local name, why = p.name, f[4]
  char.proposed = nil
  if outgoing and outgoing.guid == guid then outgoing = nil end
  if why == "married" then
    say("%s is already married.", name)
  elseif why == "busy" then
    say("%s is busy with another proposal. Try again in a minute.", name)
  elseif why == "closed" then
    say("%s isn't taking proposals right now.", name)
  elseif why == "timeout" then
    say("%s didn't answer.", name)
  else
    say("%s said no.", name)
    if aimedAt(guid) or not hasTarget() then perform("CRY") end
    record("declined", name)
    changed()
  end
end

function handlers.divorce(guid, sender, route)
  if route ~= "WHISPER" then return end
  send("WHISPER", sender, "divorced")
  local s = char.spouse
  if s and s.guid == guid and sameName(sender, s.name) then endMarriage("left", "%s has divorced you.") end
  local p = char.proposed
  if p and p.guid == guid then char.proposed = nil end
end

function handlers.divorced(guid, sender, route)
  local n = char.notices[guid]
  if route ~= "WHISPER" or not (n and sameName(sender, n.name)) then return end
  char.notices[guid] = nil
  say("%s has been told.", n.name)
end

-- A wedding, told to guild and group by each of the two.
function handlers.just(guid, sender, _, f)
  local theirs, name, first = f[4], f[5], short(sender)
  if not (goodGUID(theirs) and goodName(name) and goodName(first)) then return end
  claims[guid] = { name = name, from = sender, at = GetTime() }
  consistent(guid, sender, theirs, time())
  if theirs == myGUID then return end  -- your own wedding
  local key = guid < theirs and (guid .. theirs) or (theirs .. guid)
  if cheered[key] and GetTime() - cheered[key] < CHEER_ONCE then return end
  cheered[key] = GetTime()
  say("%s and %s just got married!", first, name)
  if not db.cheer then return end
  C_Timer.After(1 + math.random() * 2, function()
    if aimedAt(guid, theirs) then
      perform("CHEER")
    elseif canLine(false) then
      emoteLine(format("cheers for %s and %s!", first, name))
    elseif not hasTarget() and not chatLocked() then
      perform("CHEER")
    end
  end)
end

local function onMessage(prefix, msg, route, sender)
  if isSecret(prefix) or prefix ~= PREFIX then return end
  msg, route, sender = str(msg), str(route), str(sender)
  if not (db and char and msg and route and sender) then return end
  rememberMe()
  if not myGUID then return end
  local f = {}
  for field in (msg .. ";"):gmatch("([^;]*);") do f[#f + 1] = field end
  local what, guid = f[2], f[3]
  -- Guild and group messages come back to their sender too.
  if f[1] ~= VERSION or not goodGUID(guid) or guid == myGUID or not handlers[what] then return end
  dbg("heard %s from %s: %s", route, sender, msg)
  handlers[what](guid, sender, route, f)
  -- Someone who hasn't heard that you divorced them is around: tell them.
  local n = char.notices[guid]
  if n and what ~= "divorced" and sameName(sender, n.name) then tellDivorce(guid, sender) end
end

-- A married player tells their guild at login and their group when it
-- changes, so the tooltips there work without asking.
local LOGIN_WAIT, GROUP_WAIT, GROUP_EVERY = 8, 2, 60
local groupAt, groupDue = -1000, false

local function onRoster()
  if not (char and char.spouse and groupRoute()) or groupDue or GetTime() - groupAt < GROUP_EVERY then return end
  groupDue = true
  C_Timer.After(GROUP_WAIT, function()
    groupDue = false
    local route = groupRoute()
    if char.spouse and route then
      groupAt = GetTime()
      send(route, nil, wedFields())
    end
  end)
end

---------------------------------------------------------------------------
-- For other addons (Storied puts your story in its timeline)
---------------------------------------------------------------------------
Hitched = {}

-- Each entry: what ("Married Bob"), at (the time), place. Oldest first.
function Hitched.story()
  local list = {}
  if not char then return list end
  for _, e in ipairs(char.story) do
    local fmt = WHAT[e.kind]
    if fmt and goodName(e.name) and type(e.at) == "number" then
      list[#list + 1] = { what = format(fmt, e.name), at = e.at, place = str(e.place) }
    end
  end
  return list
end

-- Your spouse's name and the time you married, or nothing.
function Hitched.spouse()
  if char and char.spouse then return char.spouse.name, char.spouse.since end
end

-- fn is called whenever your story or marriage changes.
function Hitched.watch(fn)
  if type(fn) == "function" then watchers[#watchers + 1] = fn end
end

---------------------------------------------------------------------------
-- Settings panel (Options > AddOns > Hitched)
---------------------------------------------------------------------------
local function buildPanel()
  panel = CreateFrame("Frame", "HitchedPanel")
  panel.checks = {}

  local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 16, -16)
  title:SetText("Hitched")
  local intro = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  intro:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -8)
  intro:SetText("Target a player and type /hitched propose. Both of you need Hitched. /hitched divorce ends a marriage.")

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
  end

  panel:SetScript("OnShow", function()
    for _, o in ipairs(OPTIONS) do panel.checks[o.key]:SetChecked(db[o.key]) end
  end)

  if Settings and Settings.RegisterCanvasLayoutCategory then
    category = Settings.RegisterCanvasLayoutCategory(panel, "Hitched")
    Settings.RegisterAddOnCategory(category)
  end
end

-- Open the settings window at our page. The game blocks addons from opening
-- it during combat (and blames the addon), so in a fight it waits and opens
-- when the fight ends.
local settingsWaiting = false

local function openSettings()
  if not category then
    say("the settings window isn't available here.")
  elseif InCombatLockdown() then
    settingsWaiting = true
    say("the settings can't be opened in a fight. They'll open when it ends.")
  else
    settingsWaiting = false
    pcall(Settings.OpenToCategory, category:GetID())
  end
end

local function fightEnded()
  if settingsWaiting then openSettings() end
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
local HELP = {
  "/hitched  -  who you're married to",
  "/hitched propose  -  propose to the player you have targeted (they need Hitched too)",
  "/hitched divorce  -  end your marriage",
  "/hitched settings  -  open the settings",
  "/hitched debug  -  print what Hitched sends to and hears from other games",
}

local function status()
  local s = char.spouse
  if s then
    say("you're married to %s since %s%s.", s.name, day(s.since), s.place and (" (" .. s.place .. ")") or "")
  else
    say("you aren't married. Target a player and type /hitched propose.")
  end
end

SLASH_HITCHED1 = "/hitched"
SlashCmdList.HITCHED = function(msg)
  if not (db and char and panel) then
    say("didn't finish loading. Try /reload, and check for errors.")
    return
  end
  local word = strtrim(msg or ""):match("^(%S*)"):lower()
  if word == "" then
    status()
  elseif word == "propose" then
    propose()
  elseif word == "divorce" then
    divorce()
  elseif word == "settings" then
    openSettings()
  elseif word == "debug" then
    debugging = not debugging
    say("debug %s.", debugging and "on" or "off")
    if debugging then
      rememberMe()
      say("You are %s (%s) on %s.", myName or "hidden", myGUID or "hidden", onForever and "Forever" or "Classic Era")
      status()
    end
  elseif word == "help" then
    for _, line in ipairs(HELP) do say("%s", line) end
  else
    say("no command called %s. Type /hitched help for commands.", word)
  end
end

---------------------------------------------------------------------------
-- Startup
---------------------------------------------------------------------------
local events = CreateFrame("Frame")
for _, e in ipairs({ "ADDON_LOADED", "PLAYER_LOGIN", "CHAT_MSG_ADDON", "UPDATE_MOUSEOVER_UNIT",
                     "PLAYER_TARGET_CHANGED", "GROUP_ROSTER_UPDATE", "PLAYER_REGEN_ENABLED" }) do
  pcall(events.RegisterEvent, events, e)
end
events:SetScript("OnEvent", function(_, event, ...)
  if event == "ADDON_LOADED" then
    if ... == ADDON then loadSaved() end
    return
  end
  if not (db and char) then return end
  if event == "PLAYER_LOGIN" then
    myRealm = (GetNormalizedRealmName and GetNormalizedRealmName()) or GetRealmName():gsub("%s", "")
    rememberMe()
    if C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix then
      pcall(C_ChatInfo.RegisterAddonMessagePrefix, PREFIX)
    end
    buildPanel()
    hookTooltips()
    pcall(watchChat)
    C_Timer.After(LOGIN_WAIT, function()
      rememberMe()
      if char.spouse and IsInGuild() then send("GUILD", nil, wedFields()) end
    end)
  elseif not myRealm then
    return
  elseif event == "CHAT_MSG_ADDON" then
    onMessage(...)
  -- Unit checks can return hidden values on Forever, which error when
  -- tested, so unit work runs under pcall: a hidden player is just skipped.
  elseif event == "UPDATE_MOUSEOVER_UNIT" then
    pcall(notice, "mouseover")
  elseif event == "PLAYER_TARGET_CHANGED" then
    pcall(notice, "target")
  elseif event == "GROUP_ROSTER_UPDATE" then
    onRoster()
  elseif event == "PLAYER_REGEN_ENABLED" then
    fightEnded()
  end
end)
