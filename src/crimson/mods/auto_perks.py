"""Mod: pick perks automatically from a priority list, without opening the perk menu.

The picker drives the same commands a player would (open the menu, then pick a
choice on the next tick), so runs stay deterministic and replays still play back.
It only ever chooses among the perks the game offered.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

import msgspec

from ..perks.ids import PERK_BY_ID, QUICK_LEARNER_NAME, PerkId

CONFIG_FILE_NAME = "auto_perks.toml"
# Set to "0" to turn the mod off regardless of the config file (the upstream test suite does).
DISABLE_ENV_VAR = "CRIMSON_AUTO_PERKS"
# Set to a file path to load the config from there instead.
CONFIG_PATH_ENV_VAR = "CRIMSON_AUTO_PERKS_CONFIG"

# src/crimson/mods/auto_perks.py -> repository root, when running from a checkout.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def auto_perk_config_path(runtime_dir: Path) -> Path:
    """Where the config lives: the env override, else the repo root of a checkout, else the runtime dir."""

    override = os.environ.get(CONFIG_PATH_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if (_REPO_ROOT / "pyproject.toml").is_file():
        return _REPO_ROOT / CONFIG_FILE_NAME
    return runtime_dir / CONFIG_FILE_NAME


class Fallback(StrEnum):
    # Take the first offered perk that is not on the avoid list.
    FIRST = "first"
    # Open the normal perk menu and let the player choose.
    MENU = "menu"


class AutoPerkConfig(msgspec.Struct, frozen=True):
    enabled: bool = True
    fallback: Fallback = Fallback.FIRST
    priority: tuple[PerkId, ...] = ()
    avoid: frozenset[PerkId] = frozenset()


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _build_name_index() -> dict[str, PerkId]:
    index: dict[str, PerkId] = {}
    for perk_id in PerkId:
        if perk_id == PerkId.ANTIPERK:
            continue
        index[_normalize(perk_id.name)] = perk_id
        index[_normalize(PERK_BY_ID[perk_id].name)] = perk_id
    index[_normalize(QUICK_LEARNER_NAME)] = PerkId.BLOODY_MESS_QUICK_LEARNER
    index[_normalize("Fire Cough")] = PerkId.FIRE_CAUGH
    return index


_PERK_BY_NAME = _build_name_index()


def parse_perk_name(name: str) -> PerkId | None:
    """Match a perk by display name or enum name, ignoring case, spaces and punctuation."""

    return _PERK_BY_NAME.get(_normalize(name))


def _parse_perk_list(raw: object, *, key: str, warnings: list[str]) -> list[PerkId]:
    if not isinstance(raw, list):
        warnings.append(f"auto_perks: `{key}` must be a list of perk names")
        return []
    perks: list[PerkId] = []
    for entry in raw:
        perk_id = parse_perk_name(entry) if isinstance(entry, str) else None
        if perk_id is None:
            warnings.append(f"auto_perks: unknown perk {entry!r} in `{key}`")
        elif perk_id not in perks:
            perks.append(perk_id)
    return perks


def parse_auto_perk_config(text: str) -> tuple[AutoPerkConfig, list[str]]:
    """Parse the TOML config. Bad entries are reported as warnings and skipped."""

    warnings: list[str] = []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return AutoPerkConfig(enabled=False), [f"auto_perks: invalid TOML ({exc}); auto-pick disabled"]

    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        warnings.append("auto_perks: `enabled` must be true or false; auto-pick disabled")
        enabled = False

    fallback = Fallback.FIRST
    raw_fallback = data.get("fallback", Fallback.FIRST.value)
    try:
        fallback = Fallback(raw_fallback)
    except ValueError:
        warnings.append(f"auto_perks: `fallback` must be 'first' or 'menu', got {raw_fallback!r}; using 'first'")

    priority = _parse_perk_list(data.get("priority", []), key="priority", warnings=warnings)
    avoid = _parse_perk_list(data.get("avoid", []), key="avoid", warnings=warnings)
    config = AutoPerkConfig(
        enabled=enabled,
        fallback=fallback,
        priority=tuple(priority),
        avoid=frozenset(avoid),
    )
    return config, warnings


def load_auto_perk_config(path: Path) -> tuple[AutoPerkConfig, list[str]]:
    """Load the config, writing the default file first if it does not exist."""

    if os.environ.get(DISABLE_ENV_VAR) == "0":
        return AutoPerkConfig(enabled=False), []
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return parse_auto_perk_config(path.read_text(encoding="utf-8"))


def choose_perk(choices: Sequence[PerkId], config: AutoPerkConfig) -> int | None:
    """Return the index of the perk to pick, or None to leave the choice to the player."""

    if not choices:
        return None
    for perk_id in config.priority:
        if perk_id in choices:
            return list(choices).index(perk_id)
    if config.fallback == Fallback.MENU:
        return None
    for index, perk_id in enumerate(choices):
        if perk_id not in config.avoid:
            return index
    # Every offered perk is on the avoid list; a pick is still required to keep playing.
    return 0


_DEFAULT_PRIORITY = (
    "Perk Expert",
    "Perk Master",
    "Bloody Mess",
    "Lean Mean Exp Machine",
    "Uranium Filled Bullets",
    "Fastshot",
    "Fastloader",
    "Ammo Maniac",
    "Regeneration",
    "Greater Regeneration",
    "Thick Skinned",
    "Dodger",
    "Ninja",
    "Reflex Boosted",
    "Telekinetic",
    "Bonus Magnet",
    "Bonus Economist",
    "Long Distance Runner",
    "Poison Bullets",
    "Pyrokinetic",
    "Evil Eyes",
    "Radioactive",
    "Toxic Avenger",
    "Veins of Poison",
    "Living Fortress",
    "Man Bomb",
    "Fire Caugh",
    "Hot Tempered",
    "Sharpshooter",
    "Angry Reloader",
    "Stationary Reloader",
    "Tough Reloader",
    "Anxious Loader",
    "Barrel Greaser",
    "Doctor",
    "Alternate Weapon",
    "Ion Gun Master",
    "Pyromaniac",
    "Plaguebearer",
    "Final Revenge",
    "Unstoppable",
    "Mr. Melee",
    "Regression Bullets",
    "Monster Vision",
    "Instant Winner",
    "Bandage",
    "Lifeline 50-50",
    "My Favourite Weapon",
    "Ammunition Within",
)

_DEFAULT_AVOID = (
    "Grim Deal",
    "Fatal Lottery",
    "Infernal Contract",
    "Death Clock",
    "Jinxed",
    "Highlander",
    "Random Weapon",
    "Breathing Room",
)


def _toml_list(names: Sequence[str]) -> str:
    return "[\n" + "".join(f'    "{name}",\n' for name in names) + "]"


def _all_perk_names() -> str:
    names = [PERK_BY_ID[perk_id].name for perk_id in PerkId if perk_id != PerkId.ANTIPERK]
    lines: list[str] = []
    line = "#  "
    for name in names:
        piece = f" {name},"
        if len(line) + len(piece) > 100:
            lines.append(line)
            line = "#  "
        line += piece
    lines.append(line.rstrip(","))
    return "\n".join(lines)


DEFAULT_CONFIG_TEXT = f"""\
# Auto perk picker (crimsonland-modified mod).
#
# When a perk becomes available, the game picks one right away and keeps
# playing: no perk menu, no pause. Edits apply when the next run starts.
# Active in Survival and Quests; the tutorial keeps the perk menu.
#
# Perk names ignore case, spaces and punctuation ("ammo maniac" works).
# All perks:
{_all_perk_names()}

# Set to false to get the normal perk menu back.
enabled = true

# What to do when none of the offered perks is in `priority`:
#   "first" - take the first offered perk that is not in `avoid`
#   "menu"  - open the normal perk menu and choose yourself
fallback = "first"

# Highest priority first. The best-ranked perk among the offered ones is picked.
priority = {_toml_list(_DEFAULT_PRIORITY)}

# Never picked by the "first" fallback (unless every offered perk is listed here).
# Perks in neither list count as lowest priority.
avoid = {_toml_list(_DEFAULT_AVOID)}
"""
