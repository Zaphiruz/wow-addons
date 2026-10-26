# WoW addons

World of Warcraft addons, released to CurseForge from this repository.

| Addon | Game | What it does |
|---|---|---|
| [Downcast](mods/classic/Downcast) | Classic Era | Lets macros cast the best rank of a buff or HoT that can land on a low-level player |
| [Hawker](mods/classic/Hawker) | Classic Era | Keeps a list of advert lines and says a random one with `/hawk` |

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

### One-time setup for the repository

Create a CurseForge API token at https://authors.curseforge.com/#/settings/api-tokens and save it as a repository secret named `CF_API_TOKEN` (Settings, Secrets and variables, Actions).
