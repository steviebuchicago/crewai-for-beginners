"""Two tools that can read one folder and nothing else.

A tool is a Python function the model is allowed to call. CrewAI shows the model
the function's name, its parameters, and its docstring -- then the model decides
whether calling it would help. That is the whole mechanism. There is no magic
layer that teaches the model what your function does, which is why the docstring
below is written as an instruction rather than as a note to yourself.

Both tools resolve every path against KNOWLEDGE_DIR and refuse anything that
lands outside it. That check is four lines and it is the difference between a
tool and a hole.
"""

from pathlib import Path

from crewai.tools import tool

# Anchored to this file, not to the working directory. A tool whose boundary
# moves when you cd is not a boundary -- and the agent has no idea where you
# launched it from.
KNOWLEDGE_DIR = (Path(__file__).parent / "knowledge").resolve()


def _resolve_inside(filename: str) -> Path:
    """Map a model-supplied filename onto a real path, or refuse.

    The filename comes from the model, which means it comes from whatever the
    model read -- including the contents of the files themselves. Treat it as
    untrusted input, because it is.
    """
    # resolve() first, compare second. "../../etc/passwd" only looks dangerous
    # after resolution; as a raw string it passes any startswith() check you
    # write, which is why string comparison is the classic way to get this wrong.
    candidate = (KNOWLEDGE_DIR / filename).resolve()

    if not candidate.is_relative_to(KNOWLEDGE_DIR):
        raise ValueError(
            f"Refused: {filename!r} resolves outside the knowledge folder."
        )
    if candidate.suffix != ".md":
        raise ValueError(f"Refused: {filename!r} is not a .md file.")
    return candidate


# ---------------------------------------------------------------------------
# The @tool decorator turns a function into something an agent can call. It
# requires a docstring (it becomes the tool's description) and type annotations
# (they become the parameter schema). Omit either and it raises at import time,
# which is the right moment to find out.
# ---------------------------------------------------------------------------


@tool("list_knowledge_files")
def list_knowledge_files() -> str:
    """List the supplier brief files available to read.

    Call this first, before reading anything, so you know which files exist.
    Returns one filename per line. Takes no arguments.
    """
    names = sorted(p.name for p in KNOWLEDGE_DIR.glob("*.md"))
    if not names:
        return "No files found in the knowledge folder."
    return "\n".join(names)


@tool("read_knowledge_file")
def read_knowledge_file(filename: str) -> str:
    """Read one supplier brief and return its full text.

    Pass exactly one filename as it appeared in list_knowledge_files, for
    example "northgate-supply.md". Do not pass a path, a wildcard, or more than
    one name. To read several briefs, call this tool once per file.
    """
    # Returning the error as a string rather than raising is deliberate. The
    # model can read a sentence and correct itself on the next turn; an
    # exception usually just ends the run. Failures the agent can recover from
    # should be recoverable, and this one is: it mistyped a name.
    try:
        path = _resolve_inside(filename)
    except ValueError as err:
        return f"{err} Call list_knowledge_files to see the valid names."

    if not path.exists():
        available = ", ".join(sorted(p.name for p in KNOWLEDGE_DIR.glob("*.md")))
        return f"No such file: {filename!r}. Available files: {available}"

    return path.read_text(encoding="utf-8")
