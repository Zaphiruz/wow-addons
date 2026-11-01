# Hopscotch changelog

## 0.3.0 (2026-11-01)

- Perfect hops: a fresh press that leaves the ground right as you land (within one frame at 60 FPS, measured in time so high frame rates aren't punished). Holding the jump key doesn't count, since the game re-jumps for you, but it doesn't break a streak either.
- Streaks of 3 or more perfect hops in a row pop up above the counter as "Perfect x4!", growing with each hop and fading when the streak ends.
- Beating your best streak shows "New best!" and plays a chime, once per streak.
- The My characters tab shows each character's best streak, and your perfect hops and best streak on this character.
- The Places tab shows the best streak in each zone.
- Your best streak is shared with other players and shown on the Players tab. Older versions still read the rest of your numbers.
- `/hop debug` prints how many milliseconds after landing each hop left the ground.

## 0.2.0 (2026-11-01)

- Compare jumps with other players who run Hopscotch. The window has a new Players tab ranking everyone you've heard from by account total, with you highlighted.
- Your guild and group hear your numbers when you log in or join a group, and get updates about once a minute while you hop. Only the character you're on and your account total are shared, never your alts' names.
- Filter the Players tab by All, Guild or Group. Each player shows where you heard from them and how long ago.
- `/hop compare <name>` asks one player for their jumps and prints the answer in chat.
- Turn off "Share my jumps" on the Players tab to stop sending your numbers. You still see what others share.
- Players you haven't heard from in 30 days drop off the list.
- Jumps are counted per zone too. The new Places tab ranks zones by jumps, for this character or your whole account. Dungeons and raids count as zones.
- Dungeon runs: entering a dungeon or raid starts a run, and leaving ends it. Coming back within 15 minutes, after a corpse run or a repair trip, continues the same run. When a run ends, chat tells you how many jumps it took and how long.
- The Places tab lists your last 20 runs, with the fewest and most jumps for each dungeon.
- The counter has a second line showing your jumps where you are now, or the current run inside a dungeon. Set it on the My characters tab: since login, this visit, or off.
- Zones and runs stay private. Other players only see your character and account totals.
- Jumps per hour: for this session in the counter's tooltip and on the My characters tab, for each character and the account, for each zone, and for each dungeon run. Hopscotch keeps its own time online for this, starting now, so jumps from before don't skew the numbers. Rates appear once there's at least 5 minutes behind them.

## 0.1.0 (2026-11-01)

First release.

- Counts every hop off the ground. Pressing jump again in mid-air, swimming upward, and jumps while dead or on a flight path don't count. Holding jump to bunny-hop counts each take-off.
- An on-screen counter shows this character's jumps. Drag it anywhere, and it stays there.
- Click the counter, or type `/hop`, to see every character's jumps with the account total. Characters are listed most jumps first, in class colours.
- Remove old or deleted characters from the list with the X on their row.
- Lock or hide the counter from the window, or with `/hop lock`, `/hop unlock`, `/hop hide` and `/hop show`.
- `/hop debug` prints each jump press, to check what counts.
- Classic Era doesn't record jumps, so every character starts at 0 when Hopscotch is installed.
