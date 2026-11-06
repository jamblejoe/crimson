# crimsonland-modified

Mods for Crimsonland built on top of [banteg/crimson](https://github.com/banteg/crimson) (git remote `upstream`).
Our fork is [jamblejoe/crimson](https://github.com/jamblejoe/crimson) (remote `origin`); default branch `master`.
Pull upstream changes with `git fetch upstream && git merge upstream/master`.
Upstream rules for the codebase are in [CONTRIBUTING.md](CONTRIBUTING.md) — read it before changing sim code.

## Where mods go

Mods target the **Python port** (`src/crimson/`, engine in `src/grim/`), not the C decomp or WASM core.
Mod code lives in `src/crimson/mods/`, with thin hooks into upstream files; tests in `tests/mods/`.

- Play: `uv run crimson` (saves/replays in `%LOCALAPPDATA%\banteg\crimsonland`;
  override with `--base-dir`). `just run` builds the *native C client*, not the Python game.
- Test: `uv run pytest tests/mods` (needs assets in `artifacts/assets/`; fetch with
  `crimson.assets_fetch.download_missing_paqs`).
- Lint/type: `uv run ruff check <paths>`, `uv run ty check <paths>`. Upstream files are not `ruff format`-clean;
  don't reformat them (keeps merge diffs small).

## Windows notes

- `crimson-re/src/crimson_re/match.py`: `import fcntl` moved inside `_locked_staging_dir` — without it the
  `crimson` CLI (and game launch) crashes on Windows.
- `git config core.autocrlf=true`; Python `Path.write_text` writes CRLF on Windows — write LF (`write_bytes`
  or `newline="\n"`) when scripting edits to upstream files.

## Mod 1: auto perk picker

When a perk ("upgrade") is pending, it is picked immediately from a priority list; no menu, no pause.

- Logic: `src/crimson/mods/auto_perks.py`. Config: `auto_perks.toml` in the repo root (tracked; the user's own
  settings). Path order: `CRIMSON_AUTO_PERKS_CONFIG` env, repo root of a checkout, runtime dir (written with defaults
  if missing). Keys `enabled`, `fallback` (`first`|`menu`), `priority`, `avoid`; the default ranks every perk.
  Loaded in `BaseGameplayMode.open()`.
- Hooks in `src/crimson/modes/base_gameplay_mode.py`: `_update_perk_ui` → `_update_auto_perks` sends
  `PerkMenuOpenCommand`; `_on_tick_applied` → `_auto_pick_perk` queues `PerkPickCommand` for the very next tick.
- Active in Survival and Quests only (`_auto_perks_active`); tutorial keeps the menu, Rush/Typ-o have no perks.
- `fallback = "menu"`: if the player cancels that menu, auto-pick stays off until the pending count changes
  (`_auto_perks_menu_pending`).
- `CRIMSON_AUTO_PERKS=0` disables the mod; `tests/conftest.py` sets it so upstream perk-menu tests keep passing.
- Known upstream failure on Windows: `tests/replay/cli/test_list.py` (path separators), unrelated.
- Why commands: the session requires open-then-pick on consecutive ticks; going through commands keeps RNG and
  replays valid (test `tests/mods/test_auto_perks.py` replays a live run and compares state digests).

## Conventions

- Keep mod changes small and isolated (new modules + thin hooks) so upstream merges stay easy.
- Don't touch leaderboard/submission code.
