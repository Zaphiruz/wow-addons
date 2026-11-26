# WoW addons

World of Warcraft Classic Era addons (Bushel, Downcast, Gander, GanderData, Hawker, Hopscotch, Huzzah, Storied), released to
CurseForge and GitHub from this one repository. The README covers the layout
and release commands for people; this file is how we work on it.

## The game

- Classic Era, client 1.15.9, `## Interface: 11509`. Installed at
  `D:\Battle.net\Games\World of Warcraft\_classic_era_`.
- Each `mods/classic/<Addon>` folder is junction-linked into the game's
  `Interface\AddOns`, so edits and newly linked addons show up after `/reload`.
  Remove a link with `cmd /c rmdir <link>`, never `Remove-Item` (it can delete
  the files the link points to).
- In-game errors are caught by BugGrabber/BugSack and saved to
  `WTF\Account\<account>\SavedVariables\!BugGrabber.lua` after `/reload` or logout.
- Look up Blizzard's own UI code in the `classic_era` branch of
  https://github.com/Gethe/wow-ui-source before relying on an event, function
  or template. Names differ from retail, and a wrong one can break loading.

### Forever

- World of Warcraft: Forever is a separate client at
  `D:\Battle.net\Games\World of Warcraft\_forever_`, version 1.60.1,
  `## Interface: 16001`. Its UI is built on modern retail code (12.1), so check
  APIs against the `forever` branch of wow-ui-source, not `classic_era`.
- Bushel, Gander, GanderData, Hawker, Hopscotch, Huzzah and Storied support both games from one folder:
  `## Interface: 11509, 16001`. Downcast is Classic Era only.
- On Forever the CurseForge app installs the released addons as real folders
  (it replaced the junctions), so the game there runs the last release, not
  your edits. Check with `Get-Item <folder>`: `LinkType` is empty for a real
  folder. An addon that isn't on CurseForge yet can still be junction-linked.
- Differences that matter so far: chat is `C_ChatInfo.SendChatMessage` (no
  global `SendChatMessage`), and addon chat started from a macro is blocked
  during instance encounters. Prefer the modern name and fall back to the
  Classic one: `(C_ChatInfo and C_ChatInfo.SendChatMessage) or SendChatMessage`.
- Forever has no `CombatLogGetCurrentEventInfo`: addons can't read the combat
  log. The `PARTY_KILL` event (attacker and victim GUIDs) works in both games.
- Forever adds "secret values": some API results can't be read by addons in
  restricted moments. Check a function's documentation for `Secret*` flags
  before using its results.
- For mobs, Forever sends `UnitDefenseSkill` (level x 5) and `UnitAttackSpeed`.
  `UnitArmor`, `UnitResistance`, `UnitDamage` and `UnitAttackPower` return 0
  for them (tested on 1.60.1). Zero means "not sent", not a real zero.
- In a dungeon fight on Forever (Blackfathom Deeps trash, 1.60.1), the
  `UNIT_SPELLCAST_*` events fire for nameplate units but the mob's name, GUID
  and the spell ID are all secret, and so is the `C_LossOfControl` data for a
  disarm on the player. In the open world (The Barrens) the mob's name and
  GUID are readable during the fight, but the spell ID is still secret. So an
  addon can't learn what any mob casts on Forever, in or out of a dungeon.
- Forever's Combat Log chat tab is fed by `COMBAT_LOG_MESSAGE`, whose text is
  a `|K`-protected string (from Blizzard's source, not tested): it draws on
  screen but code can't read what it says.
- The combat log *file* on Forever is complete, even in a dungeon: `/combatlog`
  writes `Logs\WoWCombatLog-<date>.txt` with mob GUIDs, names, spell IDs and
  spell names (seen in Blackfathom Deeps). The game writes it in batches
  about five minutes apart (seen twice); until then the file is 0 bytes, and
  neither `/reload` nor switching logging off forces a write. Addons can't read it; a script outside the game
  can. `LoggingCombat(true)` from `/run` switched it on in a dungeon without
  an error, and Gander 0.8.0 switches it on from `PLAYER_ENTERING_WORLD` when
  entering a dungeon (seen working in game), so no key press is needed.
- Forever character names can have a surname ("Elicia Antikleia"), and the
  sender of an addon message is written that way. Don't spot yourself by
  comparing names: use the GUID, or for your own addon messages coming back,
  the text you just sent.
- Addon messages can go to a custom chat channel on Forever:
  `C_ChatInfo.SendAddonMessage(prefix, text, "CHANNEL", GetChannelName(name))`
  returned 0 (Success) in game. Gander joins its channel with
  `JoinTemporaryChannel`. Untested on Classic Era.
- The boss-fight check is `C_InstanceEncounter.IsEncounterInProgress` on
  Forever and the global `IsEncounterInProgress` on Classic Era.

## How we build a change

1. **Agree on it first.** Ask what the player wants to see or do, then describe
   the change back (with a quick mockup for anything on screen) and wait for a
   yes before writing code. Mark guesses as guesses.
2. **Tests first.** Each addon has mock-game tests in
   `mods/classic/tests/<addon>/run_tests.py`: the real addon Lua runs against a
   small fake WoW API through Python `lupa` (Lua 5.1). Write the scenario, see it
   fail, then write the addon code.
3. **Run everything:** `python mods/classic/tools/run_tests.py` (or one addon by
   name). Needs `pip install lupa pyyaml pillow`; a venv in `$TEMP/luaenv` has them.
4. **Test in game.** The mock can't show timing, taint or how the client really
   behaves. After `/reload`, the player tries it. Anything uncertain gets a
   `/<cmd> debug` that prints what the addon sees, so the player can send it.
5. **Fix bugs from the cause.** Read the full error, trace it in Blizzard's
   source, add a test that fails for that reason, then fix it.

Mock widgets answer any missing field with a no-op function, which is truthy.
Give the mock a real starting value for every field the addon reads
(`moving = false`, `checked = false`), or the test passes for the wrong reason.

## Addon code rules

### Never assign the game's globals

Addon code must never assign to a global the game owns, even with the same
value. This includes `StaticPopupDialogs = StaticPopupDialogs or {}`,
`UISpecialFrames = ...` and `SlashCmdList = ...`. The assignment taints the
global, and then Blizzard's own protected code that reads it is blocked and
blamed on the addon. This caused ADDON_ACTION_FORBIDDEN on bind-on-use
confirmations (`ConfirmBindOnUse`) and Logout in Downcast and Hawker 0.2.0.

- Adding a key is fine: `StaticPopupDialogs.MYADDON_X = {...}`,
  `SlashCmdList.MYADDON = fn`, `tinsert(UISpecialFrames, "MyFrame")`.
- Every global the addon creates starts with the addon's name, such as
  `DowncastEditor` or `SLASH_HAWKER1`. Keep everything else `local`.
- Each addon's tests load `mods/classic/tests/guard_globals.lua` after the mock,
  which makes reassigning a guarded global fail the tests. When an addon starts
  using another game global, add it to that file's list.

### Other rules

- Register events with `pcall`. An unknown event name throws and stops the
  whole addon loading (`LEARNED_SPELL_IN_TAB` doesn't exist in 1.15.9).
- If loading failed, the slash command says so ("didn't finish loading")
  instead of doing nothing.
- Saved data: `<Addon>DB` is shared by the account, `<Addon>CharDB` is per
  character. Migrate old shapes on load instead of dropping them.
- Nothing that changes action bars or secure frames runs in combat. Defer it
  until `PLAYER_REGEN_ENABLED` and tell the player it's waiting.
- The same goes for opening the settings window: `Settings.OpenToCategory`
  calls the protected `C_SettingsUtil.OpenSettingsPanel` in both games, and in
  combat it does nothing but log ADDON_ACTION_BLOCKED against the addon
  (`pcall` doesn't catch that). Check `InCombatLockdown()` first.
- `/<cmd> help` lists every command. An unknown word says so and points to help.
- Chat lines are capped at 255 characters; refuse longer ones when they're added.
- Lua 5.1 allows 200 local variables in one function, and a file's top level
  is one function. Over that, the file doesn't load at all ("main function
  has more than 200 local variables"). Gander.lua has about 194, so put a new
  section's locals inside `do ... end` and declare only what the rest of the
  file calls outside it, as "Sending to the database" does.

### Classic Era behaviour we verified in game

- Buffs and HoTs cast by name (`/cast`) fail on low-level targets ("Target is
  too low level"). Cast from an action slot, the client picks the highest rank
  that can land. Downcast is built on this.
- A failed "too low level" cast still triggers the global cooldown, so a second
  `/cast` in the same macro can't be a fallback.
- A bare `/click Button` sends a key release. Secure action buttons ignore it
  unless `useOnKeyDown` is set to match `down` in a WrapScript pre-snippet.
- The restricted environment has no `UnitLevel` or `UnitIsUnit`, and macro
  conditionals have no level check.
- Emotes aim only at your current target. A name after the emote (`/cheer Bob`,
  or the target name given to `C_ChatInfo.PerformEmote`) is ignored: it gives
  a plain "You cheer." Addons can't change the target, so Huzzah sends a custom
  emote line naming the player instead.
- The jump key calls `JumpOrAscendStart` on press and `AscendStop` on release;
  `hooksecurefunc` on both is safe. A real hop is `IsFalling()` turning true
  just after a press.

## GanderData, Gander's database

- GanderData is its own addon: what each mob casts, and stats players have
  seen, per game (`forever`, `classic`). Gander lists it as an optional
  dependency and treats it as a third source after "seen" and "heard": the
  most recent sighting wins, and a live reading beats everything. Without it
  Gander works alone, and has no Casts line on Forever.
- `mods/classic/GanderData/GanderData.lua` is generated: never edit it by hand.
  Run `python mods/classic/tools/gander_import.py`. It reads new combat logs
  from both games' `Logs` folders and the saved Gander database under `WTF`
  (own sightings only, never what was heard or from whom) into
  `mods/classic/data/gander_data.json`, then rewrites the Lua file.
- Every data change is a patch version: when an import changes the data, the
  importer bumps GanderData's `.toc` and adds the changelog line itself. Commit
  that and push the `GanderData/v<version>` tag as for any release. `--no-bump`
  skips it.
- The importer deletes each log it has finished unless `--keep` is given; ask
  before running it without `--keep`.
- The game keeps its current log file open until the client exits, even after
  logging is switched off, so that file can't be deleted while the game runs.
  The importer remembers how far it read and deletes it on a later run.
- The page (`site/`) and the importer each remember what they have read,
  separately: the browser's `localStorage` and `gander_import_state.json`. A
  log that goes through both is counted twice. Before importing a log the
  owner already sent from the page, set its `offset` in the state file to
  where the page stopped, after checking that reading that part gives exactly
  the casts in the issue. Then check the counts didn't change.
- Data only ever grows: a later import adds spells, counts and newer
  sightings, it never removes a mob or a spell.
- Account folder names are private: the importer finds the saved database by
  pattern and never writes its path anywhere.
- Other players send data as issues (label `gander-data`). The "Gander data"
  workflow runs `tools/gander_submit.py`: facts that pass the checks are
  merged by a pull request the workflow opens and merges itself; new names
  and values that disagree with the database wait in
  `data/gander_held.json` until a second sender agrees or the owner approves
  the "Held Gander data" pull request (or comments `approve ...` / `drop ...`
  on it). Never edit `gander_held.json` by hand.
- Those merges don't bump the version. The "GanderData release" workflow does
  that once a day and releases it, so don't push a `GanderData/v...` tag for
  data: run that workflow by hand if a release can't wait.
- `main` now moves by itself. Pull before working on GanderData or running
  the importer:
  `git -c credential.helper= -c "credential.helper=!gh auth git-credential" pull https://github.com/Zaphiruz/wow-addons.git main`
- Gander's `/gander send` window makes the submission block in Lua
  (`buildBlock`). Its format and `gander_submit.py`'s checks must change
  together: Gander's tests run each block through `gander_submit.validate`.
- `site/` is the page players send combat log data from, published by the
  "Site" workflow with GitHub Pages. `site/gander-log.js` reads a log exactly
  as `gander_import.py`'s `Reader` does and makes submission blocks from it:
  change the two readers together. `test_gander_site.py` reads the same logs
  with both and runs every block through `gander_submit.validate`. It needs
  Node.js (`node`), and is skipped without it.
- `worker/gander-worker.mjs` is the Cloudflare Worker the page sends to. It
  files each block as a `gander-data` issue with the owner's token, which is
  why `sender_of` believes a `sender` stamp only on the owner's own issues.
  Its `tidy()` must keep every field `gander_submit.validate` accepts and
  nothing with free text: `test_gander_worker.py` sends sample blocks through
  both and compares. A new field in the format goes in all three places
  (Gander's `buildBlock` or the page, `tidy()`, `validate`).
- The Worker's token and salt are Cloudflare secrets the owner sets with
  `npx wrangler secret put`. Never ask for them or write them anywhere. The
  owner deploys it (`worker/README.md`); its address goes in `site/config.js`.
- Try the page with the `gander-site` preview (`python -m http.server` on
  `site/`). Text from a log goes on the page with `textContent`, never as HTML.
- Chrome and Edge won't let a page keep a folder under `Program Files`
  (`showDirectoryPicker` and stored handles are blocked there), which is where
  the game installs by default. So the page takes dropped or chosen files and
  remembers what it sent in `localStorage` instead.
- Issue text is untrusted. The workflow never puts it in a command, and the
  only free text taken from a submission is a name that passes
  `good_name` and is then held. Keep it that way when changing either.

## Releasing

1. Bump `## Version:` in the `.toc`.
2. Add `## <version> (<date>)` at the top of the addon's `CHANGELOG.md`. Write
   for players: what changed for them, in plain words, one bullet each.
3. Commit, push `main`, then push a tag `<Addon>/v<version>`.

The release workflow checks the tag against the `.toc` and changelog, runs that
addon's tests, builds the zip, uploads it to CurseForge, then makes the GitHub
release. Watch the run and report the CurseForge file id and release link.

If a GitHub release for the tag already exists, the workflow skips the upload:
that version was released by hand. For a first version uploaded by hand on
CurseForge, create the GitHub release with `gh release create` (pass the full
commit SHA to `--target`) instead of pushing the tag.

## Adding a new addon

1. Check the name is free with CurseForge's WoW addon search.
2. Add the addon folder, tests, `CHANGELOG.md`, and a 400x400 logo drawn by
   `mods/classic/tools/<addon>_logo.py` with the shared `badge.py` style.
3. Junction-link it into the game and have the player try it.
4. Write a CurseForge summary and description for the player to paste. The
   player creates the project, uploads 0.1.0 by hand, and sets the Issues
   tracker to External with
   `https://github.com/Zaphiruz/wow-addons/issues/new/choose`.
5. Put the project ID in the `.toc`: `## X-Curse-Project-ID: <id>`. An addon
   that works better with another one lists it with
   `## X-Curse-Optional: <slug>` (the last part of that project's CurseForge
   address), as Gander does for GanderData.
6. Add the addon's name to:
   - the Addon dropdown in `.github/ISSUE_TEMPLATE/bug.yml` and `feature.yml`
   - the `addons` list in `.github/workflows/issue-labels.yml`
   - a GitHub label of the same name (`gh label create <Addon>`)
   - the table in `README.md`

## Git

- Commit and push only when asked. Work happens on `main`.
- The repository is public. The repo-local git email is the GitHub no-reply
  address on purpose; never commit with a personal email, and keep tokens and
  account names out of files. The CurseForge token lives only in the
  `CF_API_TOKEN` repository secret, which the player sets.
