"""What CrewAI does not give you: a boundary, a record, and a ceiling.

Example 02's crew works. This file is what you add before it runs anywhere that
matters. Nothing here makes the agents smarter -- every line exists to answer a
question somebody asks afterwards:

    Allowlist   what may it touch?       -> deny by default, resolve then compare
    AuditLog    what did it actually do? -> append-only JSONL, one row per event
    Budget      what may it spend?       -> caps up front, tripwire during, truth after

Verified against crewai 1.15.17. Where the framework gives you a real control we
use it and say so; where it does not, the gap is documented rather than papered
over. The comments name which is which, because knowing the difference is the
entire skill.
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from crewai.tools import tool


class GovernanceError(Exception):
    """A gate stopped this on purpose. Not a bug, and not the same event."""


class PermissionDenied(GovernanceError):
    """A path outside the allowlist was requested."""


class BudgetExceeded(GovernanceError):
    """A ceiling was crossed, so the run was stopped."""


# ---------------------------------------------------------------------------
# GATE 1 -- PERMISSIONS
#
# CrewAI gives you NOTHING here. An agent's reach is exactly the reach of the
# functions you hand it, and a tool that calls open() on a model-supplied string
# can open anything the process can. There is no framework setting that changes
# that, which makes this file the most security-relevant one in the example.
#
# The failure this prevents: the filename does not come from you. It comes from
# the model, which read it out of a document, which someone else wrote.
# ---------------------------------------------------------------------------


class Allowlist:
    """One readable root. Everything else is denied."""

    def __init__(self, read_root: Path):
        # resolve() at construction so the boundary is an absolute path that
        # cannot drift when the working directory changes.
        self.read_root = Path(read_root).resolve()

    def read(self, filename: str) -> Path:
        """Map an untrusted filename onto a real path, or refuse."""
        # resolve() FIRST, compare second. "../../../etc/passwd" only looks
        # dangerous after resolution; as a raw string it passes any startswith()
        # check you write. String comparison is the classic way to get this
        # wrong, and it fails silently.
        candidate = (self.read_root / filename).resolve()

        if not candidate.is_relative_to(self.read_root):
            raise PermissionDenied(f"{filename!r} resolves outside the allowlist")
        if candidate.suffix != ".md":
            raise PermissionDenied(f"{filename!r} is not a .md file")
        if not candidate.exists():
            raise PermissionDenied(f"{filename!r} does not exist")
        return candidate

    def list(self) -> list[str]:
        return sorted(p.name for p in self.read_root.glob("*.md"))


# ---------------------------------------------------------------------------
# GATE 2 -- AUDIT
#
# What CrewAI gives you: two callback hooks, and they are genuinely useful.
#
#   step_callback   set on Crew or Agent. Fires on tool steps -- AgentAction
#                   (a tool is about to run) and ToolResult (what came back).
#                   VERIFIED 1.15.17: it does NOT fire for a plain final answer
#                   in the text-ReAct path, so it is a record of tool use, not
#                   of thinking. That is the half worth auditing anyway.
#   task_callback   set on Crew. Fires once per finished task with a TaskOutput.
#
# What you build: the log itself, what goes in it, and what must never go in it.
# ---------------------------------------------------------------------------


class AuditLog:
    """Append-only JSONL. One line per event, written as it happens."""

    # Keys that would turn an audit trail into a second copy of the source data.
    # An audit log is read by more people, and kept longer, than the documents
    # it describes. Refuse loudly rather than quietly leaking.
    FORBIDDEN = {"content", "text", "body", "raw_text", "payload"}

    def __init__(self, path: Path, run_id: str, prompt_version: str):
        self.path = Path(path)
        self.run_id = run_id
        self.prompt_version = prompt_version
        self.counts: dict[str, int] = {}

    def record(self, event: str, **fields) -> None:
        leaked = self.FORBIDDEN & set(fields)
        if leaked:
            raise GovernanceError(f"refusing to audit raw content: {sorted(leaked)}")

        self.counts[event] = self.counts.get(event, 0) + 1
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": self.run_id,
            # The field people leave out and then need most. An output is only
            # explainable if you know which prompt produced it, and the prompt
            # will have been edited twice by the time anyone asks.
            "prompt_version": self.prompt_version,
            "event": event,
            **fields,
        }
        # Open, append, close, per record. Holding a handle buffers away exactly
        # the records you wanted, because the interesting runs are the ones that
        # die halfway.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    # -- the two CrewAI hooks -------------------------------------------------

    def step(self, step) -> None:
        """Wire to Crew(step_callback=...). Fires on tool steps.

        Duck-typed on purpose: 1.15.17 hands this three different shapes and
        they share no base class worth matching on.

            AgentAction  thought, tool, tool_input, text, result
            ToolResult   result, result_as_answer
            AgentFinish  thought, output, text
        """
        kind = type(step).__name__
        fields: dict = {"step_type": kind}

        if kind == "AgentAction":
            # The tool INPUT is the governance-relevant half: it is what the
            # agent asked to touch, before anyone decided whether it could.
            fields["tool"] = getattr(step, "tool", None)
            fields["tool_input"] = str(getattr(step, "tool_input", ""))[:200]
        elif kind == "ToolResult":
            # Size only. The result of read_knowledge_file IS the supplier
            # brief, so logging it would make the audit trail a second, less
            # protected copy of the source data. Record that bytes came back.
            fields["result_chars"] = len(str(getattr(step, "result", "")))
        else:
            fields["output_chars"] = len(str(getattr(step, "output", "")))

        self.record("agent_step", **fields)

    def task(self, task_output) -> None:
        """Wire to Crew(task_callback=...). Fires once per finished task."""
        raw = getattr(task_output, "raw", "") or ""
        self.record(
            "task_complete",
            agent=getattr(task_output, "agent", None),
            name=getattr(task_output, "name", None),
            # Hash and size instead of the text. Proves which output this was
            # without becoming a copy of it.
            output_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            output_chars=len(raw),
        )


# ---------------------------------------------------------------------------
# GATE 3 -- BUDGET
#
# The honest version, in three layers, because no single one of them is a cap.
#
#   1. CAPS UP FRONT (real, and the only pre-emptive control CrewAI has):
#      max_iter and max_execution_time on each Agent. VERIFIED: max_iter=3 on a
#      tool loop that never finishes stops it at 4 model calls. Note what it
#      does NOT do -- it does not raise. It forces a final answer, so a capped
#      run returns something that looks like a real answer and is not one.
#
#   2. A TRIPWIRE DURING (blunt): step_callback can read live token counts and
#      raise. VERIFIED: the exception does escape kickoff() and stop the run,
#      but not cleanly -- CrewAI's listener catches the first few, logs
#      "Error executing listener", and the run overshoots by a step or two.
#      This is an emergency brake, not a thermostat.
#
#   3. THE TRUTH AFTER: crew.usage_metrics. Accurate, and useless as a control,
#      because by the time you can read it the money is spent. A ceiling you
#      only compare against afterwards is a report.
# ---------------------------------------------------------------------------


class Budget:
    """Ceilings on tokens and tool calls, checked while the run is happening."""

    def __init__(self, max_tokens: int, max_tool_calls: int):
        self.max_tokens = max_tokens
        self.max_tool_calls = max_tool_calls
        self.tool_calls = 0
        self._llms: list = []
        self.stopped_by: str | None = None

    def watch(self, agents) -> None:
        """Register each agent's LLM so we can read usage mid-run.

        Deduplicated by id() for a reason worth knowing. Token counters live on
        the LLM INSTANCE and are cumulative for its lifetime, so if two agents
        share one LLM object, crew.usage_metrics adds that instance's total once
        per agent. VERIFIED 1.15.17: two agents sharing one instance report 2x
        the real tokens. Give each agent its own instance, as crew.py does.
        """
        for agent in agents:
            llm = getattr(agent, "llm", None)
            if llm is not None and not any(llm is seen for seen in self._llms):
                self._llms.append(llm)

    def tokens_so_far(self) -> int:
        total = 0
        for llm in self._llms:
            try:
                total += llm.get_token_usage_summary().total_tokens
            except Exception:
                # A provider that does not report usage must not take the run
                # down. The post-run reconcile is the backstop.
                pass
        return total

    def step(self, step) -> None:
        """Wire to Crew(step_callback=...). The tripwire."""
        if getattr(step, "tool", None):
            self.tool_calls += 1

        if self.tool_calls > self.max_tool_calls:
            self.stopped_by = "tool_calls"
            raise BudgetExceeded(
                f"tool calls {self.tool_calls} exceeded cap {self.max_tool_calls}"
            )

        spent = self.tokens_so_far()
        if spent > self.max_tokens:
            self.stopped_by = "tokens"
            raise BudgetExceeded(f"tokens {spent:,} exceeded cap {self.max_tokens:,}")

    def reconcile(self, crew) -> dict:
        """Post-run truth from crew.usage_metrics. A report, not a gate.

        VERIFIED 1.15.17: crew.usage_metrics is populated by
        calculate_usage_metrics() only when the run COMPLETES. A run that was
        stopped -- by our own tripwire, by an error, by a human refusing --
        leaves it None, so the number you most want after a stop is precisely
        the one the framework does not give you. Falling back to the live
        counters on the LLM instances is what makes an aborted run auditable
        rather than a row of zeros.
        """
        metrics = getattr(crew, "usage_metrics", None)
        if metrics is not None and metrics.total_tokens:
            tokens, requests, source = (
                metrics.total_tokens, metrics.successful_requests, "usage_metrics")
        else:
            tokens, requests, source = self.tokens_so_far(), self._live_requests(), "live"
        return {
            "tokens": tokens,
            "requests": requests,
            "source": source,
            "over": tokens > self.max_tokens,
        }

    def _live_requests(self) -> int:
        total = 0
        for llm in self._llms:
            try:
                total += llm.get_token_usage_summary().successful_requests
            except Exception:
                pass
        return total


# ---------------------------------------------------------------------------
# THE TOOLS, BUILT AROUND THE ALLOWLIST
#
# A factory rather than module-level tools, so the boundary and the audit log
# are closed over rather than global. Every file read goes through Allowlist and
# lands in the audit BEFORE the bytes are returned -- the log records what the
# agent touched, which is not the same as what it later says it read.
# ---------------------------------------------------------------------------


def build_knowledge_tools(allowlist: Allowlist, audit: AuditLog):
    """Return the two file tools, bound to this allowlist and this log."""

    @tool("list_knowledge_files")
    def list_knowledge_files() -> str:
        """List the supplier brief files available to read.

        Call this first, before reading anything, so you know which files exist.
        Returns one filename per line. Takes no arguments.
        """
        names = allowlist.list()
        audit.record("tool_list", count=len(names))
        return "\n".join(names) if names else "No files available."

    @tool("read_knowledge_file")
    def read_knowledge_file(filename: str) -> str:
        """Read one supplier brief and return its full text.

        Pass exactly one filename as it appeared in list_knowledge_files, for
        example "northgate-supply.md". Do not pass a path, a wildcard, or more
        than one name. To read several briefs, call this tool once per file.
        """
        try:
            path = allowlist.read(filename)
        except PermissionDenied as err:
            # A refusal is an audit event in its own right, and the one you most
            # want a record of. It is also the one nobody logs.
            audit.record("tool_denied", requested=str(filename)[:200], reason=str(err))
            # Returned as a string, not raised: the model can read a sentence and
            # correct itself next turn. An exception just ends the run, and a
            # mistyped filename should be recoverable.
            return f"Refused: {err}. Call list_knowledge_files for valid names."

        body = path.read_text(encoding="utf-8")
        audit.record(
            "tool_read",
            file=path.name,
            bytes=len(body),
            # Hash, never the text. See AuditLog.FORBIDDEN.
            sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        )
        return body

    return [list_knowledge_files, read_knowledge_file]


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{os.urandom(3).hex()}"


# ---------------------------------------------------------------------------
# THE THING THAT WILL CATCH YOU OUT
#
# VERIFIED 1.15.17. When a task raises, crewai/agent/core.py does two things you
# have to know about before you write any guard that stops a run:
#
#   1. It RETRIES. _handle_execution_error re-enters execute_task until
#      max_retry_limit is exceeded, and the default is 2. So a tripwire that
#      raises to save money gets run three times, and your cap costs MORE than
#      no cap at all. crew.py sets max_retry_limit=0 on every agent for exactly
#      this reason.
#
#   2. It WRAPS. _execute_with_timeout turns your exception into
#      RuntimeError("Task execution failed: ...") from e. So `except
#      BudgetExceeded` never matches, and your carefully typed gate arrives at
#      the top level as an anonymous RuntimeError.
#
# There is a private passthrough list (ToolExecutionFailedError) that avoids the
# wrapping, but building on a framework internal to smuggle a stop out is not
# worth it. Walking __cause__ is boring, public, and does not break on upgrade.
# ---------------------------------------------------------------------------


def find_cause(err: BaseException, *types: type) -> BaseException | None:
    """Walk the __cause__ chain for the first exception of any given type.

    Needed for more than our own errors. The EOFError raised when human_input
    has no terminal to read from gets wrapped exactly the same way, so
    `except EOFError` around kickoff() silently never fires either.
    """
    seen: set[int] = set()
    current: BaseException | None = err
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, types):
            return current
        current = current.__cause__
    return None
