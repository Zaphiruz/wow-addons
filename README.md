# WoW addons

World of Warcraft addons, released to CurseForge from this repository.

| Addon | Game | What it does |
|---|---|---|
| [Bushel](mods/classic/Bushel) | Classic Era, Forever | Counts the herbs, ore and skins you gather by type, shown in tooltips |
| [Downcast](mods/classic/Downcast) | Classic Era | Lets macros cast the best rank of a buff or HoT that can land on a low-level player |
| [Gander](mods/classic/Gander) | Classic Era, Forever | Shows a mob's stats on its tooltip, remembers them in a bestiary for when the game hides them, and shares them with other players |
| [GanderData](mods/classic/GanderData) | Classic Era, Forever | The database Gander reads: what each mob casts and its stats, gathered by players. Optional |
| [Hawker](mods/classic/Hawker) | Classic Era, Forever | Keeps a list of advert lines and says a random one with `/hawk` |
| [Hopscotch](mods/classic/Hopscotch) | Classic Era, Forever | Counts every hop off the ground, for each character and the whole account |
| [Huzzah](mods/classic/Huzzah) | Classic Era, Forever | Emotes and sends a message when your group, guild, a stranger nearby or you level up |
| [Storied](mods/classic/Storied) | Classic Era, Forever | Remembers your gear's history, who you grouped with and who helped you, and your level-ups and deaths |

## Layout

```
mods/classic/<Addon>/      the addon itself, exactly as it goes in Interface/AddOns
mods/classic/tests/        mock-game tests, one folder per addon, plus tests for the tools
mods/classic/tools/        packaging, release and logo scripts
mods/classic/assets/       CurseForge logos
```

## Playing from this checkout

Link each addon folder into the game instead of copying it, so edits show up after `/reload`:

```powershell
New-Item -ItemType Junction -Path "<WoW>\_classic_era_\Interface\AddOns\Hawker" -Target "<repo>\mods\classic\Hawker"
```

Remove a link with `cmd /c rmdir <link>`. `Remove-Item` can delete the files it points to.

## Tests

```bash
pip install lupa
python mods/classic/tools/run_tests.py          # every addon plus the tools
python mods/classic/tools/run_tests.py Hawker   # one addon
```

The addon tests run the real Lua against a small fake of the WoW API. They run on every push to `main`.

## GanderData: Gander's database

GanderData is a separate, optional addon holding what each mob casts and the
stats players have seen. Gander reads it when it's installed. It is generated,
never edited by hand:

```
python mods/classic/tools/gander_import.py            # import, bump GanderData's version, delete the logs
python mods/classic/tools/gander_import.py --keep     # import, leave the log files alone
python mods/classic/tools/gander_import.py --dry-run  # only report
```

The importer reads two things from the game folders:

- **Combat logs.** Addons can't see which spell a mob casts on Forever, but the
  game's combat log file has it. Play with logging on (`/combatlog`, or Gander's
  "log combat" setting). It keeps one kind of fact: "this hostile mob used this
  spell".
- **Gander's saved database.** The stats you saw yourself. What Gander only
  heard from other players is left out.

No player or account name is written anywhere. Everything imported so far is in
`mods/classic/data/gander_data.json`; `mods/classic/GanderData/GanderData.lua`
is the same data for the game. When an import changes the data, GanderData gets
the next patch version and a changelog line, ready to release with its tag.

### Data from other players

Players can send what their Gander has learned with the "Send Gander data"
issue form. Gander makes the block to paste there: `/gander send` in game. The **Gander data** workflow checks each submission with
`mods/classic/tools/gander_submit.py` and sorts every fact in it:

- **It passes the checks** (a sane value, nothing in the database says
  otherwise): merged by the workflow, through a pull request it opens and
  merges itself.
- **A machine can't judge it** (a name the database doesn't have, or a value
  that differs from the database): it waits in `mods/classic/data/gander_held.json`
  and shows on one pull request, "Held Gander data". It goes in when a second
  sender reports the same thing, or when the repository owner approves that
  pull request. The owner can also comment `approve m3273 s5401`,
  `approve zones`, `approve words` or `drop ...` on it. Nobody else's approval
  or comment does anything, and what waits 90 days is forgotten.
- **Broken or impossible:** left out, and the sender is told.

A merge is not a release. The **GanderData release** workflow runs once a day
and gives whatever was merged one new patch version. Nothing records who sent
what: a sender is only a scrambled marker, used to tell two senders apart.

A submission is one JSON block, shaped like one game's part of
`gander_data.json`:

```json
{"format": 1, "game": "forever", "locale": "enUS",
 "mobs": {"3238": {"name": "Stormhide",
                   "levels": {"22": {"at": 1795396923, "v": {"spd": 2, "ty": "Beast"}}},
                   "spells": {"5401": {"n": 4, "spawns": 2, "at": "2026-11-24", "build": "1.60.1"}}}},
 "spells": {"5401": "Lizard Bolt"},
 "instances": {"48": {"minutes": 24.7, "name": "Blackfathom Deeps"}}}
```

### Combat logs from other players

What mobs cast is only in the combat log file, which an addon can't read. The
page in `site/` reads it instead, in the player's browser: they drop their
`Logs` folder on it, and it makes the same kind of block from what hostile mobs
cast and how long each dungeon took. The log never leaves their computer, and
no player's name is taken from it. The page remembers which logs that browser
has sent (and how far into each), so dropping the whole folder again is fine.

- `site/gander-log.js` is the reader. It is `gander_import.py`'s log reader
  written again for the browser, and the tests in
  `mods/classic/tests/tools/test_gander_site.py` (they need Node.js) read the
  same logs with both and compare.
- The **Site** workflow publishes `site/` with GitHub Pages when it changes.
- The page is at https://zaphiruz.github.io/wow-addons/.
- `worker/` is a small Cloudflare Worker that files what the page sends as
  issues, so players don't need a GitHub account. It rebuilds each block from
  the fields the database has, so no free text reaches an issue, stamps it
  with a scrambled sender, and caps how much can be sent in a day.
  `worker/README.md` has the one-time setup.
- Until the Worker's address is in `site/config.js`, the page hands the player
  blocks to paste into the issue form instead. That way stays as the fallback.

## Releasing

1. Bump `## Version:` in the addon's `.toc`.
2. Add a `## <version> (<date>)` section at the top of its `CHANGELOG.md`.
3. Commit, then tag and push:

   ```bash
   git tag Hawker/v0.2.0
   git push origin main Hawker/v0.2.0
   ```

The release workflow checks the tag matches the `.toc`, runs the tests, builds the zip, uploads it to CurseForge with that version's changelog, and attaches it to a GitHub release. A version containing `beta` or `alpha` is uploaded as that release type.

To see what would be sent without uploading:

```bash
python mods/classic/tools/package.py Hawker
python mods/classic/tools/release.py upload Hawker --dry-run
```

### One-time setup per addon

1. Create the project on CurseForge and upload the first file by hand.
2. Copy the project ID from the project page into the `.toc`: `## X-Curse-Project-ID: 123456`.
3. Optionally make a GitHub release for that first version, so it doesn't upload again:

   ```bash
   python mods/classic/tools/release.py notes Hopscotch > notes.md
   gh release create Hopscotch/v0.1.0 mods/classic/dist/Hopscotch-0.1.0.zip --target main --title "Hopscotch 0.1.0" --notes-file notes.md
   ```

   The release workflow still runs the checks and tests for that tag, but skips the upload because the GitHub release already exists.

### One-time setup for the repository

Create a CurseForge API token at https://authors.curseforge.com/#/settings/api-tokens and save it as a repository secret named `CF_API_TOKEN` (Settings, Secrets and variables, Actions).
