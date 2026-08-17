"""What goes inside `JobFinder.exe`, and how a new build replaces an old one.

PyInstaller works by reading the import graph, so it finds every module and
none of the files this app opens by name at runtime. Each of those is invisible
here and fatal on her laptop:

- **the Jinja templates** — every page is one, so without them the app starts
  and then returns a 500 for `/`;
- **`static/`** — htmx and both font faces are local files precisely so the exe
  works offline, and a bundle without them is an unstyled page where clicking
  does nothing;
- **the prompt files** — `load_prompt` reads `.md` files off disk, so a missing
  one breaks explaining jobs, and only once she presses the button;
- **uvicorn's protocol modules** — imported by string at startup, so a build
  without them exits the moment it tries to listen.

The lists live here rather than in `JobFinder.spec` because a spec file cannot
be imported by a test, and an untested list of "things that must not be
forgotten" is exactly the list that gets forgotten.
"""

from __future__ import annotations

import shutil
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

# (source, destination) with the source relative to the package directory and
# the destination relative to the bundle root. The layout has to match the
# package's own, or `Path(__file__).parent / "templates"` finds nothing.
BUNDLED_DATA: tuple[tuple[str, str], ...] = (
    ("web/templates", "jobfinder/web/templates"),
    ("web/static", "jobfinder/web/static"),
    ("llm/prompts", "jobfinder/llm/prompts"),
)

# Imported by name at runtime, so nothing in the import graph points at them.
HIDDEN_IMPORTS: tuple[str, ...] = (
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
)

# What the built program is called, and what it runs.
APP_NAME = "JobFinder"
ENTRY_SCRIPT = "run_jobfinder.py"


def _llmpool_data() -> list[tuple[Path, str]]:
    """`llmpool`'s own data file, which is as invisible to PyInstaller as ours.

    Found by building the exe and opening the first page: `/setup` was a 500
    because `load_catalog()` opens `catalog.yaml` beside its own module, and
    nothing in the import graph mentions it. Every provider, every signup link
    and every model in this app comes out of that one file.
    """
    import llmpool

    root = Path(llmpool.__file__).resolve().parent
    return [(path, "llmpool") for path in sorted(root.glob("*.yaml"))]


def bundled_pairs() -> list[tuple[Path, str]]:
    """The data list with absolute sources, for the spec and for the tests."""
    ours = [(PACKAGE_DIR / source, destination) for source, destination in BUNDLED_DATA]
    return ours + _llmpool_data()


def spec_datas() -> list[tuple[str, str]]:
    """`datas=` as PyInstaller wants it: plain strings, absolute sources."""
    return [(str(source), destination) for source, destination in bundled_pairs()]


# -- handing an install over ---------------------------------------------------

# What may be copied out of a developer `.env` into hers. A `.env` on this
# machine collects tokens for things that have nothing to do with JobFinder, and
# handing those over would be a mistake nobody would notice: the file is copied
# once and read forever.
SHAREABLE_ENV_PREFIXES = ("ADZUNA_",)
SHAREABLE_ENV_SUFFIXES = ("_API_KEY", "_API_TOKEN", "_ACCOUNT_ID")


def shareable_env(text: str) -> str:
    """The provider and source variables from a `.env`, and nothing else."""
    kept: list[str] = []
    for line in text.splitlines():
        name, separator, _value = line.partition("=")
        if not separator or line.lstrip().startswith("#"):
            continue
        name = name.strip()
        if name.endswith(SHAREABLE_ENV_SUFFIXES) or name.startswith(SHAREABLE_ENV_PREFIXES):
            kept.append(line)
    return "\n".join(kept) + "\n" if kept else ""


def stage_install(
    exe: Path,
    target: Path,
    *,
    env_file: Path | None = None,
    seed_from: Path | None = None,
    cv: Path | None = None,
) -> Path:
    """Put a build, its keys, and the work already done into a folder to hand over.

    The keys travel as a `.env` beside the exe — the file `Settings.load`
    already reads — and never inside the binary. A key baked into 19 MB of
    program cannot be seen, cannot be rotated, and goes wherever a copy of that
    program goes.

    `seed_from` is a `data/` directory whose *files* are copied: the database,
    the CSVs, the cache of answers already paid for. Its *directories* are not —
    `http-cache/` is pages any run can fetch again, and `backups/` are backups of
    a machine that is not hers.

    **Nothing already in the folder is ever replaced.** A store, a CV or a
    `config.yaml` in the target belongs to whoever has been using it, and this
    runs again every time a new build is installed.
    """
    exe = Path(exe)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, target / f"{APP_NAME}.exe")

    if env_file is not None:
        keys = shareable_env(Path(env_file).read_text(encoding="utf-8"))
        if keys and not (target / ".env").exists():
            (target / ".env").write_text(keys, encoding="utf-8")

    if cv is not None and Path(cv).exists() and not (target / "pool.yaml").exists():
        shutil.copy2(cv, target / "pool.yaml")

    if seed_from is not None:
        _seed_data(Path(seed_from), target / "data")
    return target


def _seed_data(source: Path, destination: Path) -> list[Path]:
    """Copy the state files, once, into a `data/` that has none of its own."""
    if not source.is_dir() or (destination / "jobfinder.db").exists():
        return []

    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in sorted(source.iterdir()):
        if path.is_dir() or path.name.endswith(("-wal", "-shm")):
            # A WAL sidecar without its database is meaningless, and SQLite
            # rebuilds both from a cleanly closed file.
            continue
        shutil.copy2(path, destination / path.name)
        copied.append(destination / path.name)
    return copied


# -- updating an install -------------------------------------------------------


class UpdateRefused(Exception):
    """The update cannot be applied, said in a sentence rather than a trace."""


def apply_update(new_exe: Path, install_dir: Path) -> Path:
    """Put a new build in place, keeping the old one and touching nothing else.

    Her data, her CV and her keys are never inputs here: an update replaces one
    file. The previous exe is kept as `JobFinder.exe.previous`, so a bad build
    is one rename away from being undone — which matters more than tidiness
    when the person affected cannot read a stack trace.
    """
    new_exe = Path(new_exe)
    install_dir = Path(install_dir)

    if not new_exe.exists():
        raise UpdateRefused(f"There is no file at {new_exe} to update from.")
    if new_exe.suffix.lower() != ".exe":
        raise UpdateRefused(f"{new_exe.name} is not a program file (.exe), so nothing was changed.")

    install_dir.mkdir(parents=True, exist_ok=True)
    target = install_dir / f"{APP_NAME}.exe"
    if target.exists():
        previous = install_dir / f"{APP_NAME}.exe.previous"
        previous.unlink(missing_ok=True)
        try:
            target.rename(previous)
        except OSError as exc:
            # Measured, not assumed: updating over a *running* JobFinder works
            # on Windows — a running image can be renamed, the old build becomes
            # `.previous`, and the open app goes on running it until she closes
            # it. So this branch is not "the app is open"; it is a genuinely
            # locked file — an antivirus scan mid-copy, or a folder she cannot
            # write to.
            raise UpdateRefused(
                "JobFinder's program file could not be replaced. Close its window if it "
                "is open, wait a moment, and run the update again."
            ) from exc

    shutil.copy2(new_exe, target)
    return target
