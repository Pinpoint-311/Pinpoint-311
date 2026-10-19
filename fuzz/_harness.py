"""Shared plumbing for the coverage-guided fuzz targets in this directory.

Each target is a script that GitLab's gitlab-cov-fuzz runs with the pythonfuzz
engine (the coverage-fuzz-* jobs in .gitlab-ci.yml). The targets import only
small, pure modules from backend/app -- no database, no settings, no network --
so a fuzz job needs nothing installed but pythonfuzz.

Run one locally:

    pip install psutil
    pip install --no-deps --require-hashes \
        --index-url https://gitlab.com/api/v4/projects/19904939/packages/pypi/simple \
        -r fuzz/requirements.txt
    python fuzz/sanitize_fuzz.py fuzz/corpus/sanitize      # until Ctrl-C

or, without pythonfuzz, a plain random-input smoke run for N seconds:

    python fuzz/sanitize_fuzz.py --smoke 30

The smoke run is not coverage-guided; it proves the target imports and holds
its invariants on ordinary and random input, nothing more.
"""
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def text(buf: bytes) -> str:
    """The fuzz input as text, the way a request body or form field arrives."""
    return buf.decode("utf-8", errors="replace")


# Fragments the smoke run splices into its random input, so it reaches the
# interesting branches without coverage feedback.
_TOKENS = [
    "Route", "County Road", "CR-", "US", "Hwy", "NJ", "I-", "Spur", "Bus",
    "Main St", "North", "Ave", "(", ")", " to ", " - ", " between ", " and ",
    "..", "/", "\\", "\x00", "\n", "\r", "\t", "\x7f", " ", ",", "-",
    "1e999", "nan", "inf", "-180", "90", "180.0", "0x1p3", "1_0", " ",
]


def _seeds(target_name: str):
    corpus = os.path.join(_HERE, "corpus", target_name)
    if not os.path.isdir(corpus):
        return []
    out = []
    for name in sorted(os.listdir(corpus)):
        with open(os.path.join(corpus, name), "rb") as f:
            out.append(f.read())
    return out


def _random_input(rng: random.Random, seeds) -> bytes:
    roll = rng.random()
    if seeds and roll < 0.4:
        buf = bytearray(rng.choice(seeds))
        for _ in range(rng.randint(1, 4)):
            pos = rng.randint(0, len(buf))
            if rng.random() < 0.5:
                buf[pos:pos] = rng.choice(_TOKENS).encode()
            elif buf:
                buf[min(pos, len(buf) - 1)] = rng.randrange(256)
        return bytes(buf)
    if roll < 0.8:
        parts = [rng.choice(_TOKENS) for _ in range(rng.randint(0, 12))]
        parts += [str(rng.randint(-1000, 1000)) for _ in range(rng.randint(0, 4))]
        rng.shuffle(parts)
        return "".join(parts).encode()
    return bytes(rng.randrange(256) for _ in range(rng.randint(0, 256)))


def _smoke(target, target_name: str, seconds: float) -> None:
    rng = random.Random(int(os.environ.get("FUZZ_SEED", "0")) or None)
    seeds = _seeds(target_name)
    runs = 0
    for seed in seeds:
        target(seed)
        runs += 1
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        buf = _random_input(rng, seeds)
        try:
            target(buf)
        except Exception:
            print(f"crash on input {buf!r}", file=sys.stderr)
            raise
        runs += 1
    print(f"{target_name}: {runs} inputs in {seconds:.0f}s, no failures")


def run(target, target_name: str) -> None:
    """Hand `target` to pythonfuzz, or do a timed random smoke run."""
    if "--smoke" in sys.argv:
        i = sys.argv.index("--smoke")
        seconds = float(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 30.0
        _smoke(target, target_name, seconds)
        return
    try:
        from pythonfuzz.main import PythonFuzz
    except ImportError:
        sys.exit("pythonfuzz is not installed; use --smoke SECONDS for a random-input run")
    PythonFuzz(target)()
