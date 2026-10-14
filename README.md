# questlog

questlog is a Claude Code skill that scores your engineering work like a game. It reads your merged and reviewed PRs from GitHub and adds the cards and checks that you log by hand. The game pays more for small, tested PRs and careful reviews than for a high PR count.

```
LEVEL UP: level 1 -> 4, Journeyman
UNLOCKED: Clean Slicer
QUESTLOG 2026-Q4 | day 14 of 92
Level 4 Journeyman | 326 XP | 74 XP to level 5
Workday streak: 6 (best this season: 6)
         season                      this week
Merged   12 (10 clean, 6 tested)     4 (4 clean, 1 tested)
Reviews  9                           3
Cards    6                           1
Checks   4                           1
Areas    20                          8
Achievements
[x] Clean Slicer         10/10
[ ] Test Pilot           6/10
[ ] Second Pair of Eyes  9/20
[ ] Scholar              6/15
[ ] Deep Diver           2/5
[ ] Cartographer         20/25
[ ] Iron Streak          6/10
Today's quests
1. Review acme/api#88 "Paginate the audit log" (PR is 6 days old)
2. Review acme/web#123 "Fix login redirect" (PR is 3 days old)
3. Write one learning card
```

The names in this sample are made up. The LEVEL UP and UNLOCKED lines print once, on the first run that earns them.

## Requirements

- Claude Code.
- `gh`, the GitHub CLI, logged in.
- `python3` 3.9 or newer. The script uses only the standard library.

## Install

questlog reads only the GitHub account that `gh` is logged in to on the machine where it runs. On the work machine, that is the work account.

```sh
git clone https://github.com/m0n01d/questlog ~/code/questlog
mkdir -p ~/.claude/skills
ln -s ~/code/questlog ~/.claude/skills/questlog
gh auth status
python3 ~/code/questlog/questlog.py selftest
```

1. Run `gh auth status`. Make sure that it shows the account that you want to score.
2. Run the self-test. It prints `ok`.
3. Start Claude Code and run `/questlog`.

## Use

```
/questlog                  show level, streak, counts, achievements and quests
/questlog slice <task>     plan a stack of small PRs for a task
/questlog review <pr>      answer three questions, then read the findings
/questlog card <text>      log one thing that you learned
/questlog off <date>       mark a day off
/questlog recap [days]     write a brag-doc recap (default 7 days)
```

- `<pr>` is `owner/repo#n`, a PR URL, or a number in the current repo.
- `slice` refuses to split a change only to raise the PR count.
- `review` asks you three questions about the PR before it shows any finding. It logs a check from your answers, then asks for one card.
- Claude never posts, pushes, merges or opens a PR without your yes.

The script also runs alone: `python3 ~/.claude/skills/questlog/questlog.py status`.

## How scoring works

The script scores your work again on each run. The constants live at the top of `questlog.py`. If you change one, the whole season scores again.

| Event | XP | Constant |
|---|---|---|
| Merged PR | 10 | `XP_MERGED` |
| Clean slice: 10 to 400 changed lines | +5 | `XP_CLEAN`, `CLEAN_MIN`, `CLEAN_MAX` |
| Tested: the PR changes a test file | +5 | `XP_TESTED`, `TEST_RE` |
| Review of a PR by someone else | 10 | `XP_REVIEWED` |
| Learning card | 3 | `XP_CARD` |
| Check: each point of a score out of 3 | 2 | `XP_CHECK_POINT` |
| Off day | 0 | none |

Lockfiles, generated files, snapshots, `dist` and `.min.js` files do not count as changed lines (`SKIP_RE`). If a PR has more than 100 files, the script uses the PR totals (`MAX_FILES`).

Level is 1 + floor(sqrt(XP / 25)) (`XP_PER_STEP`). The titles are Apprentice (level 1), Journeyman (3), Artisan (5), Expert (7), Master (9) and Legend (11) (`TITLES`).

A season is a calendar quarter. XP, level, streak and achievements start again each season. The log file keeps the old entries.

The streak counts workdays back from today. Weekends and off days neither count nor break it. An empty today does not break it. The status also shows the best streak of the season.

| Achievement | Goal |
|---|---|
| Clean Slicer | 10 clean slices |
| Test Pilot | 10 tested PRs |
| Second Pair of Eyes | 20 reviews |
| Scholar | 15 cards |
| Deep Diver | 5 perfect checks (3 out of 3) |
| Cartographer | 25 areas |
| Iron Streak | a best streak of 10 workdays |

An area is a `repo:dir1/dir2` value from the paths that your merged PRs touch. Change the goals in `ACHIEVEMENTS`.

A game can be gamed. questlog counts only merged PRs, and it weights tests, reviews and checks. The coach refuses to pad the count.

## Data and privacy

- The script keeps its data in `~/.claude/questlog/`. Set `QUESTLOG_DIR` to use another folder.
- `log.jsonl` holds your cards, checks and off days. `state.json` holds the season, the level and the unlocked achievements.
- If you say yes to a recap append, Claude writes the recap to `brag.md`.
- The script talks to GitHub through `gh` and to nothing else. It has no telemetry.
- Claude reads PR titles in your session. For `review`, Claude also reads the diff. questlog sends neither anywhere else.
- To start over, remove the `~/.claude/questlog/` folder.

## GitHub Enterprise

If you use GitHub Enterprise, set `GH_HOST` to its host name before you start Claude Code. Example: `export GH_HOST=github.example.com`. Then `gh` and questlog both use that host.

If `gh` is not logged in to that host, run `gh auth login --hostname github.example.com` first.
