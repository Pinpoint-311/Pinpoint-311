import json

import pytest
import yaml

from conftest import FakeProbe, FakeSource, base_config, good_runner, healthy, is_cosign, make_instance_dir
from pinpoint_updater import cli, exitcodes
from pinpoint_updater.lockfile import read_lock


@pytest.fixture
def setup(tmp_path):
    make_instance_dir(tmp_path)
    path = tmp_path / "instances.yml"
    path.write_text(yaml.safe_dump(base_config(tmp_path)))
    return tmp_path, path


def hooks(runner=None, probe=None, source=None):
    h = cli.Hooks()
    h.source_factory = lambda cfg: source or FakeSource()
    runner = runner or good_runner()
    h.runner_factory = lambda: runner
    probe = probe or FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")])
    h.probe_factory = lambda url: probe
    h.deps_overrides = {"sleep": lambda s: None}
    return h


def test_upgrade_yes_json(setup, capsys):
    tmp, path = setup
    code = cli.main(["-c", str(path), "--json", "upgrade", "town", "v1.8.0", "--yes"], hooks())
    out = json.loads(capsys.readouterr().out)
    assert code == exitcodes.OK and out["outcome"] == "succeeded" and out["instance"] == "town"
    assert [s["name"] for s in out["steps"]][-1] == "commit"
    assert read_lock(tmp / "pinpoint-town" / "release.lock").current.version == "v1.8.0"


def test_upgrade_without_yes_off_a_tty_is_not_confirmed(setup, capsys, monkeypatch):
    _, path = setup
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    code = cli.main(["-c", str(path), "upgrade", "town", "v1.8.0"], hooks())
    assert code == exitcodes.NOT_CONFIRMED


def test_human_output_for_plan(setup, capsys):
    _, path = setup
    code = cli.main(["-c", str(path), "plan", "town", "v1.8.0"], hooks())
    text = capsys.readouterr().out
    assert code == 0 and "[plan] migrate" in text and "PLANNED" in text


def test_exit_codes_for_refusals(setup):
    _, path = setup
    runner = good_runner().on(is_cosign, 1, "", "bad sig")
    assert cli.main(["-c", str(path), "upgrade", "town", "v1.8.0", "-y"], hooks(runner=runner)) == exitcodes.REFUSED
    assert cli.main(["-c", str(path), "verify", "town", "v1.8.0"], hooks(runner=runner)) == exitcodes.REFUSED
    assert cli.main(["-c", str(path), "verify", "town", "v1.8.0"], hooks()) == exitcodes.OK


def test_rolled_back_exit_code(setup):
    _, path = setup
    probe = FakeProbe([healthy("1.7.0", "aaa"), healthy("1.7.0", "bbb"), healthy("1.7.0", "bbb")])
    assert cli.main(["-c", str(path), "upgrade", "town", "v1.8.0", "-y"], hooks(probe=probe)) == exitcodes.ROLLED_BACK


def test_insecure_flag_needs_the_env_var(setup, capsys, monkeypatch):
    _, path = setup
    monkeypatch.delenv(cli.ALLOW_INSECURE_ENV, raising=False)
    code = cli.main(["-c", str(path), "--insecure-skip-verify", "plan", "town", "v1.8.0"], hooks())
    assert code == exitcodes.USAGE and "refused" in capsys.readouterr().err

    monkeypatch.setenv(cli.ALLOW_INSECURE_ENV, "1")
    runner = good_runner()
    code = cli.main(["-c", str(path), "--insecure-skip-verify", "plan", "town", "v1.8.0"], hooks(runner=runner))
    err = capsys.readouterr().err
    assert code == exitcodes.OK and "SIGNATURES WILL NOT BE CHECKED" in err
    assert not any(is_cosign(c) for c in runner.calls)


def test_missing_env_file_is_a_usage_error(setup, capsys):
    tmp, path = setup
    (tmp / "pinpoint-town" / ".env.town").unlink()
    assert cli.main(["-c", str(path), "upgrade", "town", "v1.8.0", "-y"], hooks()) == exitcodes.USAGE
    assert "refusing to act" in capsys.readouterr().err


def test_bad_config_and_unknown_instance(setup, tmp_path):
    _, path = setup
    (tmp_path / "bad.yml").write_text("instances: {}\n")
    assert cli.main(["-c", str(tmp_path / "bad.yml"), "status", "town"], hooks()) == exitcodes.USAGE
    assert cli.main(["-c", str(path), "status", "nope"], hooks()) == exitcodes.USAGE
    assert cli.main(["-c", str(path), "bogus-command"], hooks()) == exitcodes.USAGE


def test_status_reports_drift(setup, capsys):
    tmp, path = setup
    runner = good_runner().on(
        lambda a: "ps" in a, 0,
        json.dumps({"Service": "backend", "Image": "pinpoint-311-backend:latest", "State": "running"}) + "\n")
    code = cli.main(["-c", str(path), "--json", "status", "town"], hooks(runner=runner))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["lock"]["current"]["version"] == "v1.7.0"
    assert out["drift"] and "pinpoint-311-backend:latest" in out["drift"][0]


def test_poll_with_cli_source_only_reports(setup, capsys):
    _, path = setup
    runner = good_runner()
    assert cli.main(["-c", str(path), "--json", "poll"], hooks(runner=runner)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["town"]["pending"] == 0
    assert not any("up" in c for c in runner.calls)
