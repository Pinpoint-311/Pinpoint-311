"""Resource checks have to be about this container, not the machine under it.

Both probes measured the host and presented the answer as ours:

  * Memory came from `/proc/meminfo`, which is not namespaced -- a container
    reads the whole server's RAM whatever its own cap is. compose limits the
    backend to 1G. On a 32GB host, a backend sitting at 990MB and one
    allocation away from being OOM-killed in the middle of a resident's report
    displayed "3% used" and a green tick. The number that matters is the one
    the kernel kills the process at.

  * Disk came from `shutil.disk_usage("/")`, the filesystem behind the
    container's root. On a default Docker install that is the host disk, so it
    was right by accident. Photos and pre-migration database dumps live on
    named volumes; mount either on a second disk and the probe faithfully
    watched the filesystem that was not filling up.

Everything here runs against files in a temporary directory, so the cgroup
layouts of both versions are exercised in CI on a machine that has neither.
"""

from app.services import system_probes as probes

GB = 1024 ** 3


# ---- memory: whose limit is being reported ----

def test_the_container_cap_wins_over_the_hosts_ram():
    """The whole point. 990MB of a 1G cap is an emergency; the same 990MB of a
    32GB host is nothing, and the old probe reported the second one."""
    reading = probes.interpret_memory(
        limit_bytes=1 * GB, usage_bytes=int(0.97 * GB),
        host_total_bytes=32 * GB, host_available_bytes=31 * GB,
    )
    assert reading["scope"] == "container"
    assert reading["percent"] > 95
    assert probes.classify_memory(reading)["ok"] is False


def test_an_uncapped_container_falls_back_to_the_host():
    """cgroup writes a number near 2^63 to mean "no limit". Taken literally it
    is a 8-exabyte limit and every reading rounds to 0%."""
    reading = probes.interpret_memory(
        limit_bytes=9223372036854771712, usage_bytes=8 * GB,
        host_total_bytes=16 * GB, host_available_bytes=4 * GB,
    )
    assert reading["scope"] == "host"
    assert reading["percent"] == 75.0


def test_the_reading_says_which_it_measured():
    """"Memory is 40% used" is two different sentences depending on 40% of
    what, and only one of them is actionable."""
    container = probes.classify_memory(probes.interpret_memory(1 * GB, int(0.4 * GB)))
    host = probes.classify_memory(probes.interpret_memory(None, None, 16 * GB, int(9.6 * GB)))
    assert "container" in container["detail"]
    assert "server" in host["detail"]


def test_nothing_readable_is_reported_as_nothing_rather_than_zero():
    reading = probes.interpret_memory(None, None, None, None)
    out = probes.classify_memory(reading)
    assert out["recorded"] is False and out["ok"] is False


def test_cgroup_v2_is_read_and_page_cache_is_not_counted(tmp_path):
    """A container that has read files has a large `inactive_file`, which the
    kernel reclaims under pressure instead of OOM-killing. Counting it has every
    long-running deployment at 99% by the second week, and a gauge that is
    always red is a gauge nobody looks at."""
    (tmp_path / "memory.max").write_text("1073741824\n")
    (tmp_path / "memory.current").write_text("805306368\n")   # 768MB
    (tmp_path / "memory.stat").write_text("anon 100\ninactive_file 268435456\n")  # 256MB cache

    limit, usage = probes.read_cgroup_memory(str(tmp_path))
    assert limit == 1 * GB
    assert usage == 512 * 1024 * 1024


def test_cgroup_v1_is_read_too(tmp_path):
    """Amazon Linux 2, Debian 10 and any host booted with
    systemd.unified_cgroup_hierarchy=0 are still v1."""
    v1 = tmp_path / "memory"
    v1.mkdir()
    (v1 / "memory.limit_in_bytes").write_text("536870912\n")
    (v1 / "memory.usage_in_bytes").write_text("268435456\n")
    (v1 / "memory.stat").write_text("total_inactive_file 67108864\n")

    limit, usage = probes.read_cgroup_memory(str(tmp_path))
    assert limit == 512 * 1024 * 1024
    assert usage == 201326592


def test_an_unlimited_v2_cgroup_reports_no_limit(tmp_path):
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "memory.current").write_text("805306368\n")
    assert probes.read_cgroup_memory(str(tmp_path)) == (None, None)


def test_no_cgroup_at_all_is_not_an_error(tmp_path):
    """Podman, a bare-metal install, a Mac. None of them should make the health
    page show a crash."""
    assert probes.read_cgroup_memory(str(tmp_path / "nothing")) == (None, None)


def test_host_memory_is_read_in_bytes(tmp_path):
    """/proc/meminfo is in kB. Treating it as bytes is a 1024x error in the
    safe direction, which is the kind that is never noticed."""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       16384000 kB\nMemFree: 1 kB\nMemAvailable:    8192000 kB\n")
    total, avail = probes.read_host_memory(str(meminfo))
    assert total == 16384000 * 1024
    assert avail == 8192000 * 1024


# ---- disk: which filesystem is being watched ----

def _fs(path, label, device, total, used):
    return {"path": path, "label": label, "device": device,
            "total": total, "used": used, "free": total - used}


def test_the_fullest_volume_is_the_one_reported():
    """Uploads on their own disk is the case the old probe missed entirely: `/`
    reads 30% and stays green while photo storage fills and every new report
    with a picture starts failing."""
    worst = probes.worst_disk([
        _fs("/", "The server disk", 1, 100 * GB, 30 * GB),
        _fs("/project/uploads", "Photo storage", 2, 50 * GB, 47 * GB),
        _fs("/backups", "Backup storage", 3, 50 * GB, 10 * GB),
    ])
    assert worst["path"] == "/project/uploads"
    assert worst["percent"] == 94.0


def test_the_reading_names_the_volume():
    """"Disk is 94% full" with three disks tells somebody there is a problem
    and not where it is."""
    out = probes.describe_disk(probes.worst_disk([
        _fs("/project/uploads", "Photo storage", 2, 50 * GB, 47 * GB),
    ]))
    assert out["ok"] is False
    assert out["detail"].startswith("Photo storage is 94% full")


def test_one_filesystem_behind_three_paths_is_counted_once():
    """The common case: every volume is on the host's single disk. Reporting it
    three times would be three identical alerts for one problem."""
    readings = [
        _fs("/", "The server disk", 7, 100 * GB, 91 * GB),
        _fs("/project/uploads", "Photo storage", 7, 100 * GB, 91 * GB),
        _fs("/backups", "Backup storage", 7, 100 * GB, 91 * GB),
    ]
    assert probes.worst_disk(readings)["path"] == "/"


def test_a_path_that_is_not_mounted_is_skipped_not_failed():
    """The backend does not see the database volume, and a dev checkout has no
    /backups. Neither is a fault to report every hour."""
    assert probes.read_disks([("/definitely/not/here", "Nowhere")]) == []


def test_the_real_paths_are_probed():
    """The volumes compose actually mounts. If a path here stops matching the
    compose file, this probe quietly goes back to watching only `/`."""
    paths = dict(probes.DISK_PATHS)
    assert "/" in paths
    assert "/project/uploads" in paths
    assert "/backups" in paths


def test_the_root_filesystem_is_still_read_here():
    """Whatever else is mounted, this one always exists -- so the probe can
    never come back empty on a real deployment."""
    found = {r["path"] for r in probes.read_disks()}
    assert "/" in found


# ---- cpu ----

def test_cpu_is_measured_against_the_containers_allowance():
    """A backend limited to one core on an eight-core host is saturated at what
    the machine would call 12%."""
    # 0.4s of CPU time in a 0.4s window, on a one-core allowance.
    assert probes.cpu_percent(0.4, 0.4, 1.0) == 100.0
    assert probes.cpu_percent(0.4, 0.4, 4.0) == 25.0


def test_cpu_without_a_quota_is_still_a_number():
    assert probes.cpu_percent(0.2, 0.4, None) == 50.0


def test_an_unreadable_cpu_reading_is_not_a_zero():
    assert probes.cpu_percent(None, 0.4, 1.0) is None


def test_a_cpu_spike_is_not_treated_as_a_fault():
    """One 0.4s sample cannot tell a PDF being rendered from a server in
    trouble. Alerting on it would send an email a day about nothing, and an
    alert nobody believes is worse than no alert at all."""
    assert probes.describe_cpu(100.0, 1.0, 0.4)["ok"] is True


def test_cpu_quota_is_read_from_either_cgroup_version(tmp_path):
    (tmp_path / "cpu.max").write_text("50000 100000\n")
    assert probes.read_cpu_allowance(str(tmp_path)) == 0.5

    v1 = tmp_path / "v1"
    (v1 / "cpu").mkdir(parents=True)
    (v1 / "cpu" / "cpu.cfs_quota_us").write_text("200000\n")
    (v1 / "cpu" / "cpu.cfs_period_us").write_text("100000\n")
    assert probes.read_cpu_allowance(str(v1)) == 2.0


def test_an_uncapped_cpu_reports_no_quota(tmp_path):
    """-1 in v1 and "max" in v2 both mean unlimited. Taken as a quota, -1 makes
    every percentage negative."""
    (tmp_path / "cpu.max").write_text("max 100000\n")
    assert probes.read_cpu_allowance(str(tmp_path)) is None

    v1 = tmp_path / "v1"
    (v1 / "cpu").mkdir(parents=True)
    (v1 / "cpu" / "cpu.cfs_quota_us").write_text("-1\n")
    assert probes.read_cpu_allowance(str(v1)) is None


def test_cpu_time_is_read_in_seconds(tmp_path):
    """v2 reports microseconds and v1 nanoseconds. Mixing them up is a
    thousandfold error that still produces a plausible-looking percentage."""
    (tmp_path / "cpu.stat").write_text("usage_usec 2500000\nuser_usec 1\n")
    assert probes.read_cpu_seconds(str(tmp_path)) == 2.5

    v1 = tmp_path / "v1"
    (v1 / "cpuacct").mkdir(parents=True)
    (v1 / "cpuacct" / "cpuacct.usage").write_text("2500000000\n")
    assert probes.read_cpu_seconds(str(v1)) == 2.5


# ---- the callers actually use it ----

def test_neither_probe_reads_the_host_directly_any_more():
    """The regression this guards is a one-line revert: somebody reaching for
    the host-wide call again because it is shorter.

    Matched on the parsed syntax tree, not on the text. An earlier version
    searched the source for the string and failed on the comment explaining why
    the call had been removed -- prose about a mistake is not the mistake.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for name in ("backend/app/services/proactive_health.py",
                 "backend/app/services/connector_verification.py"):
        tree = ast.parse(root.joinpath(name).read_text())
        calls = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        assert not [c for c in calls if c.startswith("shutil.disk_usage")], (
            f"{name} is reading the host disk again"
        )
        assert not [c for c in calls if "/proc/meminfo" in c], (
            f"{name} is reading host memory directly again"
        )


def test_memory_is_on_the_hourly_system_sweep():
    """Disk was swept hourly and recorded as a connector-health row; memory was
    only ever on a page somebody had to be looking at. A container being
    OOM-killed deserves the same escalation and the same email."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    source = root.joinpath("backend/app/services/connector_verification.py").read_text()
    assert '"system:memory"' in source
    assert probes.label_for("system:memory") == "Memory"
