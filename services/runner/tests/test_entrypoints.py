"""The two command lines: the local runner (`python -m pitchmind_runner`) and the per-stage cloud entrypoint."""

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from pitchmind_runner import __main__ as runner_main
from pitchmind_runner import cloud

REPO = Path(__file__).resolve().parents[3]


def small_recording(tmp_path: Path, lines: int = 100) -> Path:
    source = (REPO / "data/mock/stream.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(source) >= lines
    path = tmp_path / "recording.jsonl"
    path.write_text("\n".join(source[:lines]) + "\n", encoding="utf-8")
    return path


async def run_until_match_over(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> list[str]:
    """Run the runner until it logs "match over", then stop it (it would otherwise serve forever)."""
    over = asyncio.Event()
    logged: list[str] = []

    class Spy:
        def info(self, message: str, *args: Any) -> None:
            logged.append(message % args)
            if message.startswith("match over"):
                over.set()

    monkeypatch.setattr(runner_main, "logger", Spy())
    task = asyncio.create_task(runner_main.run(runner_main.parse_args(argv)))
    await asyncio.wait_for(over.wait(), timeout=120)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return logged


def test_negative_speed_is_refused() -> None:
    with pytest.raises(SystemExit):
        runner_main.parse_args(["--speed", "-1"])


def test_runner_replays_a_recording(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recording = small_recording(tmp_path)
    logged = asyncio.run(run_until_match_over(monkeypatch, ["--replay", str(recording), "--speed", "0", "--port", "0"]))
    assert any(line.startswith("replaying 100 messages") for line in logged)


def test_runner_plays_and_records_a_whole_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "match.jsonl"
    argv = ["--speed", "0", "--port", "0", "--record", str(out), "--disable", "persona"]
    logged = asyncio.run(run_until_match_over(monkeypatch, argv))
    full_time = next(line for line in logged if line.startswith("full time"))
    assert " 0 insights" not in full_time
    assert out.stat().st_size > 0


def test_runner_main_loads_the_env_file_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PITCHMIND_ENTRYPOINT_TEST=loaded\n", encoding="utf-8")
    monkeypatch.delenv("PITCHMIND_ENTRYPOINT_TEST", raising=False)

    async def interrupted(_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner_main, "run", interrupted)
    runner_main.main(["--env-file", str(env_file)])
    assert os.environ.pop("PITCHMIND_ENTRYPOINT_TEST") == "loaded"
    assert "stopped" in capsys.readouterr().err


def test_simulator_stage_loops_matches_with_new_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    played: list[str] = []
    announce_every: list[object] = []

    async def fake_simulator(_bus: object, meta: Any, *args: object) -> None:
        played.append(meta.match_id)
        announce_every.append(args[-1])

    async def pause(_: float) -> None:
        if len(played) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(cloud, "simulator_stage", fake_simulator)
    monkeypatch.setattr(asyncio, "sleep", pause)  # cloud calls asyncio.sleep between matches
    config = cloud.config_from_env({})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cloud.loop_matches(object(), config, 0, 20))  # type: ignore[arg-type]
    # A per-process token: after a simulator restart, M001 is a new match, not the old one.
    run = played[0].removeprefix("M001-")
    assert len(run) == 6 and played == [f"M00{n}-{run}" for n in (1, 2, 3)]
    assert announce_every == [20, 20, 20]


class FakeBus:
    closed = False

    async def close(self) -> None:
        self.closed = True


def stub_stage(calls: list[str], name: str) -> Callable[..., Awaitable[None]]:
    async def stage(*_: object) -> None:
        calls.append(name)

    return stage


@pytest.mark.parametrize("stage", ["simulator", "stats", "moments", "agents", "render"])
def test_run_stage_starts_the_named_stage_and_closes_the_bus(monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    calls: list[str] = []
    bus = FakeBus()
    monkeypatch.setattr(cloud, "make_bus", lambda _env: bus)
    monkeypatch.setattr(cloud, "loop_matches", stub_stage(calls, "simulator"))
    for name in ("stats", "moments", "agents", "render"):
        monkeypatch.setattr(cloud, f"{name}_stage", stub_stage(calls, name))
    asyncio.run(cloud.run_stage(stage, {}))
    assert calls == [stage]
    assert bus.closed


def test_run_stage_serves_the_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = FakeBus()
    monkeypatch.setattr(cloud, "make_bus", lambda _env: bus)

    class QuickGateway:
        async def handler(self, _connection: object) -> None:
            return None

        async def run(self, _bus: object) -> None:
            return None  # the consumer ends at once, so the server shuts down

    monkeypatch.setattr(cloud, "Gateway", QuickGateway)
    asyncio.run(cloud.run_stage("gateway", {"PORT": "0"}))
    assert bus.closed


def test_unknown_stage_is_refused_and_the_bus_still_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = FakeBus()
    monkeypatch.setattr(cloud, "make_bus", lambda _env: bus)
    with pytest.raises(ValueError, match="unknown stage"):
        asyncio.run(cloud.run_stage("referee", {}))
    assert bus.closed


def test_cloud_main_runs_the_chosen_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake_run_stage(stage: str, _env: object) -> None:
        seen.append(stage)

    monkeypatch.setattr(cloud, "run_stage", fake_run_stage)
    cloud.main(["stats"])
    assert seen == ["stats"]
