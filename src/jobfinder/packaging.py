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
