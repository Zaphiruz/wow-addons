-- Huzzah: emotes and sends a message when someone levels up. Group members,
-- guildmates, strangers nearby and your own level-ups each have their own
-- settings, in Options > AddOns > Huzzah.
local ADDON = ...

local db              -- HuzzahDB: settings for each kind of level-up
local category        -- our page in the game's settings window
local debugging = false

local function say(fmt, ...) print("|cffffd100Huzzah|r: " .. format(fmt, ...)) end
local function dbg(fmt, ...) if debugging then say("|cff999999" .. fmt .. "|r", ...) end end

-- Forever hides some values from addons at restricted moments ("secret
-- values"). They can't be compared or used as keys, so anything that might
-- be one is checked first. Classic Era has no issecretvalue.
local function isSecret(v) return issecretvalue ~= nil and issecretvalue(v) end

---------------------------------------------------------------------------
-- Settings
---------------------------------------------------------------------------
local KINDS = { "group", "guild", "stranger", "self" }
local DEFAULTS = {
  group    = { on = true,  emote = "CHEER",        message = "Gz {name}, {level}!" },
  guild    = { on = true,  emote = "CONGRATULATE", message = "Grats on {level}, {name}!" },
  stranger = { on = false, emote = "APPLAUD",      message = "Gz on {level}!" },
  self     = { on = false, emote = "FLEX",         message = "Ding {level}!" },
}
local HEADING = { group = "Group", guild = "Guild", stranger = "Strangers", self = "You" }
local ROW_LABEL = { group = "Group member", guild = "Guildmate", stranger = "Stranger", self = "You" }
local SENT_TO = { group = "Party / raid", guild = "Guild", stranger = "Whisper", self = "Guild" }

-- Emotes to pick from, in order: token, label, and the custom emote line
-- used when the player isn't your target. "" is no emote.
local EMOTES = {
  { "", "None" },
  { "APPLAUD", "Applaud", "applauds %s." },
  { "BOW", "Bow", "bows to %s." },
  { "CHEER", "Cheer", "cheers for %s!" },
  { "CLAP", "Clap", "claps for %s." },
  { "CONGRATULATE", "Congratulate", "congratulates %s!" },
  { "DANCE", "Dance", "dances for %s!" },
  { "FLEX", "Flex", "flexes at %s." },
  { "GRIN", "Grin", "grins at %s." },
  { "HUG", "Hug", "hugs %s." },
  { "ROAR", "Roar", "roars for %s!" },
  { "SALUTE", "Salute", "salutes %s." },
  { "WAVE", "Wave", "waves at %s." },
}

local function loadSettings()
  HuzzahDB = HuzzahDB or {}
  db = HuzzahDB
  for _, kind in ipairs(KINDS) do
    if type(db[kind]) ~= "table" then db[kind] = {} end
    for k, v in pairs(DEFAULTS[kind]) do
      if db[kind][k] == nil then db[kind][k] = v end
    end
  end
end

---------------------------------------------------------------------------
-- Reacting
--
-- Each level-up gets one reaction, a moment later so it doesn't look
-- instant. A player seen dinging through several units (party1 and target,
-- or the guild list) is still congratulated once per level.
---------------------------------------------------------------------------
local DELAY_MIN, DELAY_MAX = 1, 3  -- seconds before reacting
local MAX_CHAT = 255               -- the game's limit for one chat line

local myRealm
local reacted = {}                 -- "Name-Realm:level" -> true

-- "Name-Realm" for the player under unit, or nil.
local function fullName(unit)
  local name, realm = UnitName(unit)
  if isSecret(name) or isSecret(realm) or type(name) ~= "string" or name == "" then return end
  if type(realm) ~= "string" or realm == "" then realm = myRealm end
  return name .. "-" .. realm
end

local function fill(message, name, level)
  local text = message:gsub("{name}", function() return name end)
  text = text:gsub("{level}", function() return tostring(level) end)
  return text
end

local function channelFor(kind, target)
  if kind == "group" then
    if IsInRaid() then return "RAID" elseif IsInGroup() then return "PARTY" end
  elseif kind == "guild" or kind == "self" then
    if IsInGuild() then return "GUILD" end
  elseif kind == "stranger" then
    return "WHISPER", target
  end
end

local function chatLocked()
  return C_ChatInfo ~= nil and C_ChatInfo.InChatMessagingLockdown ~= nil and C_ChatInfo.InChatMessagingLockdown()
end

local function sendChat(text, channel, to)
  local send = (C_ChatInfo and C_ChatInfo.SendChatMessage) or SendChatMessage
  return send ~= nil and (pcall(send, text, channel, nil, to))
end

-- The custom emote line for token, naming the player: "cheers for Bob!".
local function emoteLine(token, name)
  for _, e in ipairs(EMOTES) do
    if e[1] == token and e[3] then return format(e[3], name) end
  end
  return format("%ss at %s.", token:lower(), name)
end

-- Is full the player you have targeted?
local function isTarget(full)
  local ok, name = pcall(fullName, "target")
  return ok and name == full
end

-- Forever blocks emote lines that aren't sent from a key press, and ours come
-- from a timer. A blocked call does nothing and raises no error, so it can't
-- be caught: on Forever the line isn't tried at all.
local emoteLinesBlocked = (select(4, GetBuildInfo()) or 0) >= 16000

-- The game aims an emote only at your current target; a name given with it
-- is ignored. So the player who dinged gets the real emote if they're your
-- target, and otherwise a custom emote line naming them. A plain emote never
-- plays while someone else (or nobody) is targeted: it would cheer at them.
local function emoteAt(kind, token, full, short)
  local emote = (C_ChatInfo and C_ChatInfo.PerformEmote) or DoEmote
  if kind ~= "self" and not isTarget(full) then
    if emoteLinesBlocked then
      dbg("no emote: %s is not your target (Forever blocks emote lines)", short)
      return
    end
    local line = emoteLine(token, short)
    if not chatLocked() and sendChat(line, "EMOTE") then
      dbg("custom emote: %s", line)
    else
      dbg("couldn't send the custom emote, and %s is not your target: no emote", short)
    end
    return
  end
  if emoteLinesBlocked then dbg("plain emote /%s at your target", token:lower()) end
  if emote then pcall(emote, token) end
end

local function perform(kind, full, level)
  local cfg = db[kind]
  if not cfg.on then return end
  local short, target = Ambiguate(full, "short"), Ambiguate(full, "none")

  if cfg.emote ~= "" then emoteAt(kind, cfg.emote, full, short) end

  local text = fill(cfg.message, short, level)
  if strtrim(text) == "" then return end
  if #text > MAX_CHAT then
    dbg("message for %s is too long for chat, not sent", short)
    return
  end
  local channel, to = channelFor(kind, target)
  if not channel then return end
  if chatLocked() then
    dbg("chat is locked right now, message for %s not sent", short)
    return
  end
  sendChat(text, channel, to)
end

local myName, myGUID  -- your name and character ID, remembered while the game shows them
local SELF_WINDOW = 30   -- seconds after your own ding when nobody is cheered for that level
local ownDing            -- { level, at } of your last level-up

-- Is full ("Name-Realm") you? Only the name part is compared, ignoring case:
-- the guild list can write the realm differently, and Forever can hide your
-- name at restricted moments, when the one remembered is used.
local function rememberMe()
  local name = UnitName("player")
  if not isSecret(name) and type(name) == "string" and name ~= "" then myName = name end
  local guid = UnitGUID and UnitGUID("player")
  if not isSecret(guid) and type(guid) == "string" and guid ~= "" then myGUID = guid end
end

local function isMe(full)
  rememberMe()
  return myName ~= nil and full:match("^[^-]+"):lower() == myName:lower()
end

-- Is this guild list entry you? Its character ID says so for certain; the
-- name is the fallback when the list doesn't give one.
local function isMeEntry(m)
  rememberMe()
  if m.guid and myGUID then return m.guid == myGUID end
  return isMe(m.name)
end

-- Did you reach this level yourself a moment ago? Then a guild list or unit
-- change to that level is most likely you under a name Huzzah didn't match.
local function justReached(level)
  return ownDing ~= nil and ownDing.level == level and GetTime() - ownDing.at <= SELF_WINDOW
end

-- source says where the ding was seen, for /huzzah debug.
local function react(kind, full, level, source)
  if kind ~= "self" and isMe(full) then return end  -- your own ding is "self" only
  local key = full .. ":" .. level
  if reacted[key] then return end
  reacted[key] = true
  dbg("%s reached level %d (%s, from %s)", full, level, kind, source)
  if not db[kind].on then return end
  -- Checked when the reaction is due: your own PLAYER_LEVEL_UP can come
  -- just after the guild list shows your new level.
  local function skip()
    if kind ~= "self" and justReached(level) then
      dbg("not cheering %s: you just reached level %d yourself, so it may be you", full, level)
      return true
    end
  end
  if skip() then return end
  C_Timer.After(DELAY_MIN + math.random() * (DELAY_MAX - DELAY_MIN), function()
    if not skip() then perform(kind, full, level) end
  end)
end

---------------------------------------------------------------------------
-- Seeing level-ups
--
-- The game only reports another player's level change (UNIT_LEVEL) for units
-- it tracks: group members, target, mouseover, focus and nameplates. Levels
-- are remembered when those units appear, so a change can be told from a
-- first look. Guildmates elsewhere are found by comparing the guild list
-- each time it refreshes.
---------------------------------------------------------------------------
local ROSTER_EVERY = 30  -- seconds between guild list refreshes

local levels = {}        -- "Name-Realm" -> last level seen

-- Name and level of another player under unit, or nil.
local function playerAt(unit)
  if not UnitIsPlayer(unit) then return end
  local me = UnitIsUnit(unit, "player")
  if isSecret(me) or me then return end  -- hidden: it might be you
  local level = UnitLevel(unit)
  if isSecret(level) or type(level) ~= "number" or level <= 0 then return end
  local full = fullName(unit)
  if full then return full, level end
end

local function remember(unit)
  local full, level = playerAt(unit)
  if full then levels[full] = level end
end

local function rememberGroup()
  for i = 1, 4 do remember("party" .. i) end
  for i = 1, 40 do remember("raid" .. i) end
end

local function kindOf(unit)
  if UnitInParty(unit) or UnitInRaid(unit) then return "group" end
  if UnitIsInMyGuild and UnitIsInMyGuild(unit) then return "guild" end
  return "stranger"
end

local function onUnitLevel(unit)
  if type(unit) ~= "string" or unit == "player" then return end
  local full, level = playerAt(unit)
  if not full then return end
  local old = levels[full]
  levels[full] = level
  if old and level > old then react(kindOf(unit), full, level, unit) end
end

-- Each readable guild list entry: name ("Name-Realm"), level, online and
-- guid (character ID, when the list gives one). Also returns how many
-- entries there were, and how many of those the game hid.
local function guildList()
  local list, total, hidden = {}, GetNumGuildMembers() or 0, 0
  if isSecret(total) or type(total) ~= "number" then return list, 0, 0 end
  for i = 1, total do
    local name, _, _, level, _, _, _, _, online, _, _, _, _, _, _, _, guid = GetGuildRosterInfo(i)
    if not isSecret(name) and type(name) == "string" and not isSecret(level) and type(level) == "number" then
      if not name:find("-", 1, true) then name = name .. "-" .. myRealm end
      if isSecret(guid) or type(guid) ~= "string" or guid == "" then guid = nil end
      list[#list + 1] = { name = name, level = level, online = online, guid = guid }
    else
      hidden = hidden + 1
    end
  end
  return list, total, hidden
end

local function scanGuild()
  if not IsInGuild() then return end
  for _, m in ipairs(guildList()) do
    if not isMeEntry(m) then  -- you're on the list too; your own ding is "self"
      local old = levels[m.name]
      levels[m.name] = m.level
      if old and m.level > old and m.online then react("guild", m.name, m.level, "the guild list") end
    end
  end
end

local function askForRoster()
  if IsInGuild() then
    local ask = (C_GuildInfo and C_GuildInfo.GuildRoster) or GuildRoster
    if ask then ask() end
  end
end

local function rosterLoop()
  askForRoster()
  C_Timer.After(ROSTER_EVERY, rosterLoop)
end

---------------------------------------------------------------------------
-- Settings panel (Options > AddOns > Huzzah)
---------------------------------------------------------------------------
local MAX_MESSAGE = 200  -- letters, leaving room for a name and level
local panel

local function emoteIndex(token)
  for i, e in ipairs(EMOTES) do if e[1] == token then return i end end
end

local function emoteLabel(token)
  local i = emoteIndex(token)
  if i then return EMOTES[i][2] end
  return token:sub(1, 1) .. token:sub(2):lower()
end

local function refreshPanel()
  for _, kind in ipairs(KINDS) do
    local row, cfg = panel.rows[kind], db[kind]
    row.check:SetChecked(cfg.on)
    row.emote:SetText(emoteLabel(cfg.emote))
    row.message:SetText(cfg.message)
  end
end

local function stepEmote(kind, step)
  local i = emoteIndex(db[kind].emote) or 1
  i = (i - 1 + step) % #EMOTES + 1
  db[kind].emote = EMOTES[i][1]
  panel.rows[kind].emote:SetText(EMOTES[i][2])
end

local function buildPanel()
  panel = CreateFrame("Frame", "HuzzahPanel")
  panel.rows = {}

  local title = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 16, -16)
  title:SetText("Huzzah")
  local intro = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  intro:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -8)
  intro:SetText("What to do when someone levels up. Leave the emote as None or the message empty to skip it. Messages can use {name} and {level}.")

  local x = { check = 16, label = 46, emote = 160, message = 290, sent = 530 }
  for col, text in pairs({ label = "When", emote = "Emote (click)", message = "Message", sent = "Sent to" }) do
    local h = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
    h:SetPoint("TOPLEFT", x[col], -76)
    h:SetText(text)
  end

  for i, kind in ipairs(KINDS) do
    local y = -96 - (i - 1) * 34
    local row = {}

    row.check = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
    row.check:SetPoint("TOPLEFT", x.check, y + 4)
    row.check:SetScript("OnClick", function(self) db[kind].on = self:GetChecked() and true or false end)

    local label = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    label:SetPoint("TOPLEFT", x.label, y - 2)
    label:SetText(ROW_LABEL[kind])

    row.emote = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    row.emote:SetPoint("TOPLEFT", x.emote, y)
    row.emote:SetSize(116, 22)
    row.emote:RegisterForClicks("LeftButtonUp", "RightButtonUp")
    row.emote:SetScript("OnClick", function(_, button) stepEmote(kind, button == "RightButton" and -1 or 1) end)

    row.message = CreateFrame("EditBox", nil, panel, "InputBoxTemplate")
    row.message:SetPoint("TOPLEFT", x.message + 6, y)
    row.message:SetSize(226, 22)
    row.message:SetAutoFocus(false)
    row.message:SetMaxLetters(MAX_MESSAGE)
    row.message:SetScript("OnTextChanged", function(self, userInput)
      if userInput then db[kind].message = self:GetText() end
    end)
    row.message:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
    row.message:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)

    local sent = panel:CreateFontString(nil, "ARTWORK", "GameFontDisable")
    sent:SetPoint("TOPLEFT", x.sent, y - 2)
    sent:SetText(SENT_TO[kind])

    panel.rows[kind] = row
  end

  local note = panel:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  note:SetPoint("TOPLEFT", 16, -96 - #KINDS * 34 - 8)
  note:SetText("Right-click an emote to go back. The game only aims emotes at your target, so anyone else gets a custom emote line naming them, such as \"cheers for Bob!\". Guildmates who aren't nearby are noticed when the guild list refreshes, so that reaction can come a minute or so late.")

  panel:SetScript("OnShow", refreshPanel)

  if Settings and Settings.RegisterCanvasLayoutCategory then
    category = Settings.RegisterCanvasLayoutCategory(panel, "Huzzah")
    Settings.RegisterAddOnCategory(category)
  end
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
local HELP = {
  "/huzzah  -  open the settings",
  "/huzzah test  -  show what each kind of level-up would do, without sending anything",
  "/huzzah debug  -  print each level-up as it's noticed",
}

local function describe(kind, name, level)
  local cfg = db[kind]
  if not cfg.on then return HEADING[kind] .. ": off" end
  local parts = {}
  if cfg.emote ~= "" then
    if kind == "self" then
      parts[#parts + 1] = "/" .. cfg.emote:lower()
    elseif emoteLinesBlocked then
      parts[#parts + 1] = format("/%s if %s is your target, otherwise no emote", cfg.emote:lower(), name)
    else
      parts[#parts + 1] = format("/%s if %s is your target, otherwise the emote \"%s %s\"",
        cfg.emote:lower(), name, UnitName("player"), emoteLine(cfg.emote, name))
    end
  end
  local text = fill(cfg.message, name, level)
  if strtrim(text) ~= "" then parts[#parts + 1] = "to " .. SENT_TO[kind]:lower() .. ": " .. text end
  if #parts == 0 then return HEADING[kind] .. ": on, but nothing to do" end
  return HEADING[kind] .. ": " .. table.concat(parts, ", then ")
end

local function test()
  for _, kind in ipairs(KINDS) do
    if kind == "self" then
      local level = UnitLevel("player")
      say(describe(kind, UnitName("player"), (type(level) == "number" and not isSecret(level) and level or 0) + 1))
    else
      say(describe(kind, "Bob", 20))
    end
  end
end

SLASH_HUZZAH1 = "/huzzah"
SlashCmdList.HUZZAH = function(msg)
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
  elseif word == "test" then
    test()
  elseif word == "debug" then
    debugging = not debugging
    say("debug %s.", debugging and "on" or "off")
    if debugging then
      local you, listed = fullName("player") or (myName and myName .. " (name hidden right now)") or "hidden", nil
      if IsInGuild() then
        local members, total, hidden = guildList()
        for _, m in ipairs(members) do
          if isMeEntry(m) then listed = m.name .. (m.guid and " (matched by character ID)" or "") end
        end
        if listed then
          say("You are %s; the guild list has you as %s.", you, listed)
        else
          say("You are %s; not on the guild list (it has %d members, %d hidden).", you, total, hidden)
        end
      else
        say("You are %s; not in a guild.", you)
      end
    end
  elseif word == "help" then
    for _, line in ipairs(HELP) do say(line) end
  else
    say("no command called %s. Type /huzzah help for commands.", word)
  end
end

---------------------------------------------------------------------------
-- Startup
---------------------------------------------------------------------------
local events = CreateFrame("Frame")
for _, e in ipairs({ "ADDON_LOADED", "PLAYER_LOGIN", "PLAYER_LEVEL_UP", "UNIT_LEVEL",
                     "GROUP_ROSTER_UPDATE", "PLAYER_TARGET_CHANGED", "UPDATE_MOUSEOVER_UNIT",
                     "PLAYER_FOCUS_CHANGED", "NAME_PLATE_UNIT_ADDED", "GUILD_ROSTER_UPDATE" }) do
  pcall(events.RegisterEvent, events, e)
end
events:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 == ADDON then loadSettings() end
    return
  end
  if not (db and myRealm) and event ~= "PLAYER_LOGIN" then return end
  -- Unit checks can return hidden values on Forever, which error when
  -- tested, so unit work runs under pcall: a hidden player is just skipped.
  if event == "UNIT_LEVEL" then
    pcall(onUnitLevel, arg1)
  elseif event == "PLAYER_LEVEL_UP" then
    local full = fullName("player")
    if type(arg1) == "number" then ownDing = { level = arg1, at = GetTime() } end
    if full and type(arg1) == "number" then react("self", full, arg1, "your level-up") end
  elseif event == "GROUP_ROSTER_UPDATE" then
    pcall(rememberGroup)
  elseif event == "PLAYER_TARGET_CHANGED" then
    pcall(remember, "target")
  elseif event == "UPDATE_MOUSEOVER_UNIT" then
    pcall(remember, "mouseover")
  elseif event == "PLAYER_FOCUS_CHANGED" then
    pcall(remember, "focus")
  elseif event == "NAME_PLATE_UNIT_ADDED" then
    if type(arg1) == "string" then pcall(remember, arg1) end
  elseif event == "GUILD_ROSTER_UPDATE" then
    pcall(scanGuild)
  elseif event == "PLAYER_LOGIN" then
    if not db then return end
    myRealm = (GetNormalizedRealmName and GetNormalizedRealmName()) or GetRealmName():gsub("%s", "")
    rememberMe()
    buildPanel()
    rememberGroup()
    remember("target")
    rosterLoop()
  end
end)
