import sys, pathlib
from lupa import lua51

HERE = pathlib.Path(__file__).parent
MOCK = (HERE / "wowmock.lua").read_text(encoding="utf-8")
ADDON = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")

PRELUDE = r'''
function ok(cond, msg) if not cond then error("FAIL: " .. msg, 2) end end
function entry(key) for _, e in ipairs(DowncastCharDB.spells) do if e.key == key then return e end end end
function login(db)
  DowncastCharDB = db
  local chunk = assert(loadstring(ADDON_SRC, "Downcast.lua"))
  chunk("Downcast")
  M.fire("ADDON_LOADED", "Downcast")
  M.fire("PLAYER_ENTERING_WORLD")
  M.fire("SPELLS_CHANGED")
  M.runTimers()
end
function cmd(s) M.out = {}; SlashCmdList.DOWNCAST(s); M.runTimers(); return table.concat(M.out, "\n") end
function priestBook()
  for r = 1, 5 do M.learn("Renew", r, 100 + r) end
  for r = 1, 3 do M.learn("Power Word: Fortitude", r, 200 + r) end
  for r = 1, 4 do M.learn("Power Word: Shield", r, 300 + r) end
  M.learn("Inner Fire", 1, 400)
  M.learn("Abolish Disease", nil, 500)
  M.learn("Flash Heal", 1, 600)
  -- user's own bars: slots 1-12 plus a leftover in 120
  for s = 1, 12 do M.actions[s] = { kind = "spell", id = 601 } end
  M.spellNames[601] = "Flash Heal"
  M.actions[120] = { kind = "spell", id = 105 }  -- old test addon's Renew
end
'''

SCENARIOS = {
"priest login seeds defaults and places top ranks": r'''
  priestBook(); login(nil)
  ok(#DowncastCharDB.spells == 5, "5 defaults")
  local r = entry("Renew"); ok(r.slot == 119, "Renew in 119, got " .. tostring(r.slot))
  ok(M.actions[119].id == 105, "Renew top rank")
  ok(M.actions[120].id == 105 and M.actions[1].id == 601, "user slots untouched")
  ok(DowncastRenew.attrs.type == "action" and DowncastRenew.attrs.action == 119, "Renew button ready")
  ok(entry("Fort").slot == 118 and M.actions[118].id == 203, "Fort rank 3 in 118")
  ok(entry("Shield").slot == 117 and M.actions[117].id == 304, "Shield rank 4")
  ok(DowncastSpirit.attrs.type == nil and DowncastSpirit.attrs.action == nil, "Spirit disabled")
  ok(DowncastShadowProt.attrs.type == nil, "ShadowProt disabled")
  ok(M.cursor == nil, "cursor clean")
  local out = cmd("")
  ok(out:find("/click DowncastRenew  %-  Renew %(ready, top rank 5%)"), "list Renew: " .. out)
  ok(out:find("DowncastSpirit  %-  Divine Spirit %(not in your spellbook%)"), "list Spirit")
''',
"learning a rank updates the slot, nothing else": r'''
  priestBook(); login(nil)
  local before = M.placeCount
  M.learn("Renew", 6, 106); M.fire("SPELLS_CHANGED"); M.runTimers()
  ok(entry("Renew").slot == 119 and M.actions[119].id == 106, "rank 6 placed in same slot")
  ok(M.placeCount == before + 1, "exactly one placement, got " .. (M.placeCount - before))
  ok(M.cursor == nil, "old rank not left on cursor")
''',
"learning in combat waits until combat ends": r'''
  priestBook(); login(nil)
  M.inCombat = true
  M.learn("Renew", 6, 106); M.fire("SPELLS_CHANGED"); M.runTimers()
  ok(M.actions[119].id == 105, "unchanged in combat")
  local out = cmd(""); ok(out:find("changes will apply when combat ends"), "list mentions pending")
  M.inCombat = false; M.fire("PLAYER_REGEN_ENABLED"); M.runTimers()
  ok(M.actions[119].id == 106, "updated after combat")
''',
"spell learned while out of combat but no event in combat is harmless": r'''
  priestBook(); login(nil)
  M.inCombat = true
  M.fire("PLAYER_REGEN_ENABLED") -- spurious
  M.runTimers()
  M.inCombat = false
''',
"player drops something into our slot: we move, never overwrite": r'''
  priestBook(); login(nil)
  M.actions[119] = { kind = "item", id = 9 }
  M.fire("ACTIONBAR_SLOT_CHANGED", 119); M.runTimers()
  ok(M.actions[119].kind == "item", "player's item kept")
  local r = entry("Renew"); ok(r.slot == 116, "moved to 116, got " .. tostring(r.slot))
  ok(DowncastRenew.attrs.action == 116, "button follows")
''',
"busy cursor delays the update": r'''
  priestBook(); login(nil)
  M.cursor = { kind = "item", id = 77 }
  M.learn("Renew", 6, 106); M.fire("SPELLS_CHANGED")
  local t = M.timers; M.timers = {}; for _, f in ipairs(t) do f() end
  ok(M.cursor and M.cursor.id == 77, "player's cursor kept")
  ok(M.actions[119].id == 105, "not updated yet")
  M.cursor = nil; M.runTimers()
  ok(M.actions[119].id == 106, "updated once cursor free")
''',
"add and remove": r'''
  priestBook(); login(nil)
  local out = cmd("add Abolish Disease")
  ok(out:find("/click DowncastAbolishDisease"), out)
  ok(entry("AbolishDisease").slot == 116 and M.actions[116].id == 500, "abolish placed")
  out = cmd("add Inner Fire as IF"); ok(entry("IF") and M.actions[entry("IF").slot].id == 400, "IF " .. out)
  out = cmd("add power word: shield as PWS"); ok(out:find("already covered by DowncastShield"), out)
  out = cmd("add Renew as Shield"); ok(out:find("already have a button called DowncastShield"), out)
  out = cmd("add Holy Nova as 9x"); ok(out:find("must start with a letter"), out)
  out = cmd("add Holy Nova"); ok(out:find("isn't in your spellbook"), out)
  ok(DowncastHolyNova.attrs.type == nil, "unknown spell button disabled")
  M.inCombat = true; out = cmd("add Flash Heal"); ok(out:find("can't add spells in combat"), out); M.inCombat = false
  local ifSlot = entry("IF").slot
  out = cmd("remove downcastif"); ok(out:find("removed DowncastIF"), out)
  ok(entry("IF") == nil and M.actions[ifSlot] == nil and DowncastIF.attrs.type == nil, "IF gone")
  out = cmd("remove Nope"); ok(out:find("no button called Nope"), out)
  ok(M.cursor == nil, "cursor clean")
  out = cmd("frobnicate"); ok(out:find("commands:"), "help")
''',
"removing a default stays removed after reload": r'''
  priestBook(); login(nil)
  cmd("remove Fort")
  local saved = DowncastCharDB
  M.events = {}; M.timers = {}
  login(saved)
  ok(entry("Fort") == nil and #DowncastCharDB.spells == 4, "Fort not re-added")
  ok(entry("Renew").slot == 119, "Renew keeps its slot")
''',
"spells lists helpful multi-rank spells and marks added ones": r'''
  priestBook()
  for r = 1, 3 do M.learn("Smite", r, 700 + r) end
  for r = 1, 2 do M.learn("Spiritual Guidance", r, 800 + r) end
  login(nil)
  local out = cmd("spells")
  ok(out:find("Renew %(rank 5%), added as DowncastRenew"), "Renew marked: " .. out)
  ok(out:find("Power Word: Shield %(rank 4%), added as DowncastShield"), "Shield marked")
  ok(out:find("\n  Flash Heal %(rank 1%)") == nil, "single-rank Flash Heal left out")
  ok(not out:find("Smite"), "harmful left out")
  ok(not out:find("Spiritual Guidance"), "passive left out")
  ok(not out:find("Inner Fire"), "single rank left out")
  M.learn("Flash Heal", 2, 602)
  out = cmd("spells")
  ok(out:find("\n  Flash Heal %(rank 2%)\n") or out:find("\n  Flash Heal %(rank 2%)$"), "Flash Heal now listed, not added: " .. out)
  local p1 = out:find("Flash Heal"); local p2 = out:find("Power Word: Fortitude"); local p3 = out:find("Renew")
  ok(p1 < p2 and p2 < p3, "sorted")
''',
"debug switch logs each click": r'''
  priestBook(); login(nil)
  M.out = {}
  M.click(DowncastRenew, false, true)
  ok(#M.out == 0, "silent by default")
  local out = cmd("debug"); ok(out:find("debug on"), out)
  M.out = {}; M.optionResult = "mouseover"
  M.click(DowncastRenew, false, true)
  local line = table.concat(M.out, "\n")
  ok(line:find("DowncastRenew click: down=false unit=mouseover type=action slot=119 holds Renew %(Rank 5%)"), line)
  M.out = {}; M.click(DowncastSpirit, false, true)
  line = table.concat(M.out, "\n")
  ok(line:find("DowncastSpirit click: down=false unit=mouseover type=nil slot=nil"), line)
  out = cmd("debug"); ok(out:find("debug off"), out)
''',
"slash command speaks up if setup never happened": r'''
  local chunk = assert(loadstring(ADDON_SRC, "Downcast.lua"))
  chunk("Downcast")
  local out = cmd("")
  ok(out:find("didn't finish loading"), "says it failed: " .. out)
''',
"non-priest gets no defaults": r'''
  M.class = "MAGE"; login(nil)
  ok(#DowncastCharDB.spells == 0, "empty")
  local out = cmd(""); ok(out:find("no spells yet"), out)
''',
"click picks unit and casts once per /click style": r'''
  priestBook(); login(nil)
  M.optionResult = "mouseover"
  local slot, unit = M.click(DowncastRenew, false, true)  -- plain /click, key-down setting on
  ok(slot == 119 and unit == "mouseover", "plain /click casts at mouseover")
  ok(M.lastRule == "[@mouseover,help,nodead] mouseover; [help,nodead] target; player", "rule")
  M.optionResult = "target"
  slot, unit = M.click(DowncastRenew, true, true)          -- /click X LeftButton 1
  ok(slot == 119 and unit == "target", "press click casts at target")
  M.optionResult = nil
  slot, unit = M.click(DowncastRenew, false, false)
  ok(slot == 119 and unit == "player", "falls back to player")
  M.inCombat = true
  slot = M.click(DowncastRenew, false, true)
  ok(slot == 119, "works in combat")
  M.inCombat = false
  ok(M.click(DowncastSpirit, false, true) == nil, "unlearned spell does nothing")
''',
}

failed = 0
for name, body in SCENARIOS.items():
    L = lua51.LuaRuntime(unpack_returned_tuples=True)
    L.execute(MOCK)
    L.globals().ADDON_SRC = ADDON
    L.execute(PRELUDE)
    # The secure snippet runs SetAttribute in combat legitimately (restricted env).
    try:
        L.execute(
            "local orig = M.click; M.click = function(b, d, c) local ic = M.inCombat; M.inCombat = false; "
            "local r1, r2 = orig(b, d, c); M.inCombat = ic; return r1, r2 end")
        L.execute(body)
        print("PASS", name)
    except Exception as e:
        failed += 1
        print("FAIL", name, "->", str(e).splitlines()[0])
print("failed:", failed)
sys.exit(1 if failed else 0)
