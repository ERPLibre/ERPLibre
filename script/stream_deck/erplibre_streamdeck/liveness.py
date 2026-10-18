# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Whether a session's pid still belongs to the session's process.

A pid number is reused once its process dies; a process that started
after the session's first timestamp is another program. The start time
comes from /proc/<pid>/stat (clock ticks since boot, field 22) and the
boot time `btime` of /proc/stat."""

import os


def parse_start_ticks(stat_line):
    """Field 22 of a /proc/<pid>/stat line. The command name (field 2)
    may hold spaces and parentheses: the fields are counted after the
    last ')'."""
    rest = stat_line[stat_line.rindex(")") + 2:].split()
    # rest[0] is field 3 (state): field 22 is rest[19].
    return int(rest[19])


def _boot_time():
    with open("/proc/stat", encoding="utf-8") as f:
        for line in f:
            if line.startswith("btime "):
                return int(line.split()[1])
    raise OSError("no btime in /proc/stat")


def started_ms(pid):
    """Start time of `pid` in epoch milliseconds; None when the process
    is gone or its files cannot be read."""
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as f:
            ticks = parse_start_ticks(f.read())
        hz = os.sysconf("SC_CLK_TCK")
        return int((_boot_time() + ticks / hz) * 1000)
    except (OSError, ValueError, IndexError):
        return None


def alive(pid, born_by_ms, slack_ms=5000):
    """True when `pid` runs and started no later than `born_by_ms` plus
    `slack_ms`: btime has a one-second resolution, and a writer may
    stamp its file just before the process starts."""
    start = started_ms(pid)
    return start is not None and start <= born_by_ms + slack_ms
