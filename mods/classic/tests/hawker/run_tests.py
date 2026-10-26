"""Runs Hawker.lua against a tiny fake WoW API. Usage: python run_tests.py path/to/Hawker.lua"""
import sys
from lupa import lua51

ADDON = open(sys.argv[1], encoding="utf-8").read()

MOCK = r'''
out, said, events = {}, {}, {}
function print(...) local t = {} for i = 1, select("#", ...) do t[#t+1] = tostring(select(i, ...)) end out[#out+1] = table.concat(t, " ") end
format, tinsert, tremove, wipe = string.format, table.insert, table.remove, function(t) for k in pairs(t) do t[k] = nil end return t end
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
SlashCmdList = {}
rolls = {}
function random(n) local r = table.remove(rolls, 1) or 1; assert(r >= 1 and r <= n, "roll out of range"); return r end
function SendChatMessage(msg, chan, lang, target)
  said[#said+1] = chan .. (target and ("(" .. target .. ")") or "") .. ": " .. msg
end
joined = { [1] = "General - Elwynn Forest", [2] = "Trade - City" }
function GetChannelName(id) if joined[id] then return id, joined[id] end return 0, nil end
function CreateFrame()
  local f = { scripts = {} }
  function f:RegisterEvent(e) events[e] = self end
  function f:SetScript(s, fn) self.scripts[s] = fn end
  return f
end
function load(saved)
  HawkerDB = saved
  assert(loadstring(ADDON_SRC, "Hawker.lua"))("Hawker")
  local f = events.ADDON_LOADED
  f.scripts.OnEvent(f, "ADDON_LOADED", "Hawker")
end
function cmd(s) out = {}; SlashCmdList.HAWKER(s); return table.concat(out, "\n") end
function ok(c, m) if not c then error("FAIL: " .. m, 2) end end
'''

SCENARIOS = {
"add, list, and say a random line": r'''
  load(nil)
  local o = cmd("add free bracer enchants to make your water taste better")
  ok(o:find("added line 1"), o)
  cmd("add struggling to kill your foes? free bracer enchants to help you out")
  cmd("add   a free buff with every free enchant  ")
  o = cmd("list")
  ok(o:find("1%. free bracer enchants to make your water taste better"), o)
  ok(o:find("3%. a free buff with every free enchant\n?") and not o:find("enchant  "), "trimmed: " .. o)
  rolls = {2}
  cmd("")
  ok(said[1] == "SAY: struggling to kill your foes? free bracer enchants to help you out", tostring(said[1]))
''',
"Hawk() works from /run": r'''
  load(nil); cmd("add hello there")
  Hawk()
  ok(said[1] == "SAY: hello there", tostring(said[1]))
''',
"never repeats the same line twice in a row": r'''
  load(nil); cmd("add one"); cmd("add two"); cmd("add three")
  rolls = {1, 1, 2}   -- second press rolls line 1 again, must skip to another
  Hawk(); Hawk()
  ok(said[1] == "SAY: one" and said[2] ~= "SAY: one", table.concat(said, " | "))
''',
"one line can repeat": r'''
  load(nil); cmd("add only")
  Hawk(); Hawk()
  ok(said[1] == "SAY: only" and said[2] == "SAY: only", table.concat(said, " | "))
''',
"clear removes everything": r'''
  load(nil); cmd("add one"); cmd("add two")
  local o = cmd("clear"); ok(o:find("cleared 2 lines"), o)
  o = cmd("list"); ok(o:find("no lines yet"), o)
  o = cmd(""); ok(o:find("no lines yet") and #said == 0, o)
''',
"remove one line": r'''
  load(nil); cmd("add one"); cmd("add two"); cmd("add three")
  local o = cmd("remove 2"); ok(o:find('removed line 2: two'), o)
  o = cmd("list"); ok(o:find("1%. one") and o:find("2%. three") and not o:find("two"), o)
  o = cmd("remove 9"); ok(o:find("no line 9"), o)
''',
"lines survive a reload": r'''
  load(nil); cmd("add keep me")
  local saved = HawkerDB
  events = {}
  load(saved)
  local o = cmd("list"); ok(o:find("1%. keep me"), o)
''',
"rejects empty and too-long lines": r'''
  load(nil)
  local o = cmd("add"); ok(o:find("usage"), o)
  o = cmd("add " .. string.rep("x", 256)); ok(o:find("too long"), o)
  o = cmd("list"); ok(o:find("no lines yet"), o)
''',
"unknown command shows help": r'''
  load(nil)
  local o = cmd("frobnicate"); ok(o:find("/hawk add"), o)
  ok(o:find("/hawk yell"), "help mentions channels: " .. o)
''',
"channel words and short forms": r'''
  load(nil); cmd("add hi")
  cmd("yell"); cmd("GUILD"); cmd("g"); cmd("p"); cmd("raid"); cmd("e"); cmd("o"); cmd("s")
  local want = { "YELL: hi", "GUILD: hi", "GUILD: hi", "PARTY: hi", "RAID: hi", "EMOTE: hi", "OFFICER: hi", "SAY: hi" }
  for i, w in ipairs(want) do ok(said[i] == w, i .. ": " .. tostring(said[i])) end
''',
"numbered channel": r'''
  load(nil); cmd("add wts enchants")
  cmd("2")
  ok(said[1] == "CHANNEL(2): wts enchants", tostring(said[1]))
  local o = cmd("5")
  ok(#said == 1 and o:find("not in channel 5"), o)
''',
"Hawk() takes a channel too": r'''
  load(nil); cmd("add hi")
  Hawk("guild"); Hawk(2); Hawk()
  ok(said[1] == "GUILD: hi" and said[2] == "CHANNEL(2): hi" and said[3] == "SAY: hi", table.concat(said, " | "))
''',
"bad channel from /run says so": r'''
  load(nil); cmd("add hi")
  out = {}; Hawk("whisper")
  ok(#said == 0 and table.concat(out):find("unknown channel"), table.concat(out))
''',
}

failed = 0
for name, body in SCENARIOS.items():
    L = lua51.LuaRuntime()
    L.globals().ADDON_SRC = ADDON
    try:
        L.execute(MOCK)
        L.execute(body)
        print("PASS", name)
    except Exception as e:
        failed += 1
        print("FAIL", name, "->", str(e).splitlines()[0])
print("failed:", failed)
sys.exit(1 if failed else 0)
