-- Hawker: keep a list of advert lines and /say a random one.
--
--   /hawk add <text>   add a line
--   /hawk list         show your lines
--   /hawk remove <n>   remove line n
--   /hawk clear        remove all lines
--   /hawk              say a random line (put this in a macro)
--   /hawk yell         same, in another channel: say yell emote guild officer
--                      party raid, short forms s y e g o p ra
--   /hawk 2            same, in numbered channel 2 (Trade in cities)
--
-- /run Hawk() does the same as /hawk, and Hawk("guild") or Hawk(2) pick a channel.

local ADDON = ...
local PREFIX = "|cffffcc00Hawker:|r "
local MAX_LEN = 255 -- longest chat message the game allows

local CHANNELS = {
  say = "SAY", s = "SAY",
  yell = "YELL", y = "YELL",
  emote = "EMOTE", e = "EMOTE",
  guild = "GUILD", g = "GUILD",
  officer = "OFFICER", o = "OFFICER",
  party = "PARTY", p = "PARTY",
  raid = "RAID", ra = "RAID",
}

local db
local lastIndex

local function say(fmt, ...)
  print(PREFIX .. format(fmt, ...))
end

local function noLines()
  say("no lines yet. Add one with /hawk add <text>")
end

-- Returns chat type and channel number, or nil and a message for the player.
local function resolveChannel(arg)
  if arg == nil or arg == "" then return "SAY" end
  local number = tonumber(arg)
  if number then
    if GetChannelName(number) == 0 then
      return nil, format("you're not in channel %d.", number)
    end
    return "CHANNEL", number
  end
  local chatType = CHANNELS[tostring(arg):lower()]
  if not chatType then
    return nil, format("unknown channel %s. Type /hawk help to see the channels.", tostring(arg))
  end
  return chatType
end

function Hawk(channel)
  if not db then return end
  local chatType, target = resolveChannel(channel)
  if not chatType then say("%s", target) return end
  local n = #db.lines
  if n == 0 then noLines() return end
  local i = random(n)
  -- Don't say the same line twice in a row when there's a choice.
  if n > 1 and i == lastIndex then
    i = i % n + 1
  end
  lastIndex = i
  SendChatMessage(db.lines[i], chatType, nil, target)
end

local function add(text)
  text = strtrim(text or "")
  if text == "" then say("usage: /hawk add <text>") return end
  if #text > MAX_LEN then
    say("that line is too long: %d characters, the limit is %d.", #text, MAX_LEN)
    return
  end
  tinsert(db.lines, text)
  say("added line %d.", #db.lines)
end

local function list()
  if #db.lines == 0 then noLines() return end
  say("your lines:")
  for i, line in ipairs(db.lines) do
    print(format("  %d. %s", i, line))
  end
end

local function remove(arg)
  local i = tonumber(arg)
  if not i or not db.lines[i] then
    say("no line %s. Type /hawk list to see the numbers.", strtrim(arg or ""))
    return
  end
  local line = tremove(db.lines, i)
  lastIndex = nil
  say("removed line %d: %s", i, line)
end

local function clear()
  local n = #db.lines
  wipe(db.lines)
  lastIndex = nil
  say("cleared %d lines.", n)
end

local function help()
  say("commands:")
  print("  /hawk  - say a random line")
  print("  /hawk yell  - same, in another channel: say yell emote guild officer party raid")
  print("      short forms: s y e g o p ra")
  print("  /hawk 2  - same, in numbered channel 2 (Trade in cities)")
  print("  /hawk add <text>  - add a line")
  print("  /hawk list  - show your lines")
  print("  /hawk remove <number>  - remove one line")
  print("  /hawk clear  - remove all lines")
end

SLASH_HAWKER1 = "/hawk"
SlashCmdList.HAWKER = function(msg)
  if not db then
    say("didn't finish loading. Check BugSack for the error.")
    return
  end
  local cmd, rest = strtrim(msg or ""):match("^(%S*)%s*(.-)$")
  cmd = cmd:lower()
  if cmd == "" then Hawk()
  elseif cmd == "add" then add(rest)
  elseif cmd == "list" then list()
  elseif cmd == "remove" then remove(rest)
  elseif cmd == "clear" then clear()
  elseif CHANNELS[cmd] or tonumber(cmd) then Hawk(cmd)
  else help() end
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function(_, _, name)
  if name ~= ADDON then return end
  HawkerDB = HawkerDB or {}
  db = HawkerDB
  db.lines = db.lines or {}
end)
