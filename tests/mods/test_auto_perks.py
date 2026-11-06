from __future__ import annotations

from pathlib import Path

import pytest

from crimson.game_modes import GameMode
from crimson.modes.survival_mode import SurvivalMode
from crimson.mods.auto_perks import (
    CONFIG_FILE_NAME,
    CONFIG_PATH_ENV_VAR,
    DEFAULT_CONFIG_TEXT,
    DISABLE_ENV_VAR,
    AutoPerkConfig,
    Fallback,
    auto_perk_config_path,
    choose_perk,
    load_auto_perk_config,
    parse_auto_perk_config,
    parse_perk_name,
)
from crimson.perks import PerkId
from crimson.replay.driver.playback_driver import PlaybackDriver
from crimson.sim.commands import PerkMenuOpenCommand, PerkPickCommand
from grim.rand import Crand
from grim.view import ViewContext
from tests.support.replay_runner_helpers import unverified_replay
from tests.support.state_digest import session_digest


@pytest.fixture(autouse=True)
def _auto_perks_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # tests/conftest.py turns the mod off for upstream tests; never touch the repo's own config here.
    monkeypatch.delenv(DISABLE_ENV_VAR, raising=False)
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(tmp_path / CONFIG_FILE_NAME))


def test_config_path_prefers_env_then_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert auto_perk_config_path(Path("runtime")) == tmp_path / CONFIG_FILE_NAME
    monkeypatch.delenv(CONFIG_PATH_ENV_VAR)
    repo_root = Path(__file__).resolve().parents[2]
    assert auto_perk_config_path(Path("runtime")) == repo_root / CONFIG_FILE_NAME


def test_repo_config_parses_cleanly() -> None:
    repo_config = Path(__file__).resolve().parents[2] / CONFIG_FILE_NAME
    _, warnings = parse_auto_perk_config(repo_config.read_text(encoding="utf-8"))
    assert warnings == []


def test_default_config_ranks_or_avoids_every_perk() -> None:
    config, _ = parse_auto_perk_config(DEFAULT_CONFIG_TEXT)
    listed = set(config.priority) | config.avoid
    assert {perk for perk in PerkId if perk != PerkId.ANTIPERK} == listed
    assert not set(config.priority) & config.avoid


def test_env_var_disables_the_mod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DISABLE_ENV_VAR, "0")
    config, _ = load_auto_perk_config(tmp_path / CONFIG_FILE_NAME)
    assert not config.enabled


@pytest.mark.parametrize(
    ("name", "perk"),
    [
        ("Ammo Maniac", PerkId.AMMO_MANIAC),
        ("ammo_maniac", PerkId.AMMO_MANIAC),
        ("AMMO MANIAC", PerkId.AMMO_MANIAC),
        ("Mr Melee", PerkId.MR_MELEE),
        ("Lifeline 50/50", PerkId.LIFELINE_50_50),
        ("Quick Learner", PerkId.BLOODY_MESS_QUICK_LEARNER),
        ("Fire Cough", PerkId.FIRE_CAUGH),
        ("not a perk", None),
        ("AntiPerk", None),
    ],
)
def test_parse_perk_name(name: str, perk: PerkId | None) -> None:
    assert parse_perk_name(name) == perk


def test_default_config_parses_cleanly() -> None:
    config, warnings = parse_auto_perk_config(DEFAULT_CONFIG_TEXT)
    assert warnings == []
    assert config.enabled
    assert config.fallback == Fallback.FIRST
    assert config.priority[0] == PerkId.PERK_EXPERT
    assert PerkId.GRIM_DEAL in config.avoid


def test_bad_entries_warn_and_are_skipped() -> None:
    config, warnings = parse_auto_perk_config(
        'fallback = "sometimes"\npriority = ["Regeneration", "Nope", 3, "regeneration"]\n',
    )
    assert config.priority == (PerkId.REGENERATION,)
    assert config.fallback == Fallback.FIRST
    assert len(warnings) == 3


def test_invalid_toml_disables_auto_pick() -> None:
    config, warnings = parse_auto_perk_config("priority = [")
    assert not config.enabled
    assert warnings


def test_load_writes_default_file(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILE_NAME
    config, warnings = load_auto_perk_config(path)
    assert path.read_text(encoding="utf-8") == DEFAULT_CONFIG_TEXT
    assert warnings == []
    assert config.enabled


CHOICES = [PerkId.GRIM_DEAL, PerkId.BANDAGE, PerkId.REGENERATION, PerkId.FASTSHOT, PerkId.DODGER]


def test_choose_highest_priority_offered() -> None:
    config = AutoPerkConfig(priority=(PerkId.NINJA, PerkId.FASTSHOT, PerkId.REGENERATION))
    assert choose_perk(CHOICES, config) == 3


def test_fallback_first_skips_avoided() -> None:
    config = AutoPerkConfig(priority=(PerkId.NINJA,), avoid=frozenset({PerkId.GRIM_DEAL}))
    assert choose_perk(CHOICES, config) == 1


def test_fallback_first_when_everything_is_avoided() -> None:
    config = AutoPerkConfig(avoid=frozenset(CHOICES))
    assert choose_perk(CHOICES, config) == 0


def test_fallback_menu_leaves_choice_to_player() -> None:
    config = AutoPerkConfig(priority=(PerkId.NINJA,), fallback=Fallback.MENU)
    assert choose_perk(CHOICES, config) is None


def _open_survival(make_mode_config, assets_dir, tmp_path: Path, config_text: str) -> SurvivalMode:
    (tmp_path / CONFIG_FILE_NAME).write_text(config_text, encoding="utf-8")
    mode = SurvivalMode(
        ViewContext(assets_dir=assets_dir),
        config=make_mode_config(game_mode=GameMode.SURVIVAL),
        audio_rng=Crand(1),
    )
    mode.open()
    return mode


@pytest.mark.usefixtures("headless_resources")
def test_menu_fallback_opens_the_menu_once_and_respects_cancel(make_mode_config, assets_dir, tmp_path) -> None:
    mode = _open_survival(make_mode_config, assets_dir, tmp_path, 'fallback = "menu"\npriority = []\n')
    session = mode._sim_session
    assert session is not None
    mode.state.perk_selection.pending_count = 1

    mode._update_perk_ui(dt_ui_ms=1000 / 60)
    mode._run_deterministic_session_ticks(dt_frame=1 / 60, session=session, recorder=mode._replay_recorder)
    assert mode._perk_menu.open

    # Cancel: the menu must not come straight back for the same perk.
    mode._perk_menu.reset()
    for _ in range(4):
        mode._update_perk_ui(dt_ui_ms=1000 / 60)
        mode._run_deterministic_session_ticks(dt_frame=1 / 60, session=session, recorder=mode._replay_recorder)
        assert not mode._perk_menu.active
    assert mode.state.perk_selection.pending_count == 1


@pytest.mark.usefixtures("headless_resources")
def test_live_auto_pick_never_opens_the_menu_and_replays(make_mode_config, assets_dir, tmp_path) -> None:
    mode = _open_survival(make_mode_config, assets_dir, tmp_path, 'priority = ["Regeneration", "Fastshot"]\n')
    session = mode._sim_session
    recorder = mode._replay_recorder
    assert session is not None and recorder is not None

    def _grant_perks(state) -> None:
        selection = state.perk_selection
        selection.pending_count = 2
        selection.choices_dirty = False
        selection.choices = list(CHOICES) + [PerkId.NINJA, PerkId.NINJA]

    _grant_perks(mode.state)

    for _ in range(8):
        mode._update_perk_ui(dt_ui_ms=1000 / 60)
        assert not mode._perk_menu.active
        mode._run_deterministic_session_ticks(dt_frame=1 / 60, session=session, recorder=recorder)

    selection = mode.state.perk_selection
    assert selection.pending_count == 0
    assert PerkId.REGENERATION in mode.state.perks

    replay = unverified_replay(recorder)
    commands = [command for tick in replay.ticks for command in tick.commands]
    # Open, pick Regeneration (index 2), then the same again for the second pending perk.
    assert commands[:3] == [
        PerkMenuOpenCommand(player_index=0),
        PerkPickCommand(player_index=0, choice_index=2),
        PerkMenuOpenCommand(player_index=0),
    ]
    assert len(commands) == 4
    assert isinstance(commands[3], PerkPickCommand)

    # The recorded commands are legal and replay to the same state.
    playback = PlaybackDriver(replay)
    _grant_perks(playback.world.state)
    for index in range(len(replay.ticks)):
        playback.step_tick(index)
    assert session_digest(playback.session) == session_digest(session)
