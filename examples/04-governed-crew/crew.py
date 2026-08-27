"""Example 02's research crew, with the four things that let it run somewhere real.

Same two agents, same tools, same job. What is added is a boundary, a record, a
ceiling and a human. Diff this against ../02-research-crew/crew.py and every
difference is a gate.

    export OPENAI_API_KEY=sk-...        # or ANTHROPIC_API_KEY=sk-ant-...
    pip install -r requirements.txt

    python crew.py                      # stops at the end for your approval
    echo "" | python crew.py            # auto-accepts -- see the README

Exit codes: 0 accepted, 1 budget stopped the run, 2 a gate refused, 3 rejected
by the human. A scheduler should be able to tell those apart.
"""

import os
import sys
import time
from pathlib import Path

from crewai import Agent, Crew, Process, Task

from governance import (
    Allowlist,
    AuditLog,
    Budget,
    BudgetExceeded,
    GovernanceError,
    build_knowledge_tools,
    find_cause,
    new_run_id,
)

MODEL = "anthropic/claude-sonnet-4-5" if os.environ.get("ANTHROPIC_API_KEY") else "gpt-4o-mini"

# Bump this whenever you edit a role, goal, backstory, description or
# expected_output below. Every audit row carries it, which is the only way to
# answer "which version of the prompt produced this?" six weeks later.
PROMPT_VERSION = "2026-01-15.1"

# The one directory this crew may read. A constant, never derived from argv --
# an allowlist built out of the arguments it is meant to check is a formality.
# We borrow example 02's knowledge folder rather than duplicating it.
KNOWLEDGE_DIR = Path(__file__).parent.parent / "02-research-crew" / "knowledge"

AUDIT_PATH = Path(__file__).parent / "out" / "audit.jsonl"

# Ceilings. Pick numbers a normal run does not come near, so that hitting one is
# information rather than noise. Overridable from the environment only so you
# can watch them fire -- see "Try the refusals" in the README.
MAX_TOKENS = int(os.environ.get("CREW_MAX_TOKENS", 120_000))
MAX_TOOL_CALLS = int(os.environ.get("CREW_MAX_TOOL_CALLS", 12))


if not KNOWLEDGE_DIR.is_dir():
    # Fail here rather than letting the crew run against an empty folder and
    # produce a confident answer about nothing. A governed example that starts
    # up broken and says so is the whole lesson in miniature.
    sys.exit(
        f"Knowledge folder not found: {KNOWLEDGE_DIR}\n"
        "This example reads example 02's briefs. Clone the whole repo, or point "
        "KNOWLEDGE_DIR at a folder of .md files of your own."
    )

run_id = new_run_id()
allowlist = Allowlist(KNOWLEDGE_DIR)
audit = AuditLog(AUDIT_PATH, run_id=run_id, prompt_version=PROMPT_VERSION)
budget = Budget(max_tokens=MAX_TOKENS, max_tool_calls=MAX_TOOL_CALLS)

# The tools are built around the allowlist and the log, so there is no way to
# read a file that skips either one. That is the point of the factory: a tool
# that COULD bypass the gate eventually will.
knowledge_tools = build_knowledge_tools(allowlist, audit)


# ---------------------------------------------------------------------------
# THE AGENTS -- same two as example 02, now with caps
# ---------------------------------------------------------------------------

researcher = Agent(
    role="Procurement Research Analyst",
    goal="Answer questions about our suppliers using only what the briefs "
         "actually say, and be explicit when they do not say it",
    backstory="You are a procurement analyst who has been burned by partial "
              "reads. You list the available files before you read any of them, "
              "and you read every file that could possibly bear on the question "
              "before you answer. You quote figures exactly as written. When the "
              "briefs do not contain something, you say so rather than filling "
              "the gap from memory.",
    tools=knowledge_tools,

    # llm= is a STRING deliberately. CrewAI builds one LLM instance per agent
    # from a string, so their token counters stay separate. Hand both agents the
    # same LLM OBJECT instead and crew.usage_metrics counts that instance once
    # per agent -- verified 1.15.17, two agents share one instance and the
    # reported total is exactly double. A budget computed from a number that is
    # wrong by 2x is not a budget.
    llm=MODEL,

    # The only pre-emptive spend controls CrewAI actually has.
    #
    # max_iter caps the think-act loop. Verified: a tool loop that never
    # finishes stops at max_iter. But it does NOT raise -- it forces a final
    # answer out of the agent. A capped run therefore returns something that
    # looks exactly like a real answer and is not one, which is why the summary
    # at the bottom prints the caps every time.
    max_iter=8,

    # Wall-clock ceiling for this agent, in seconds. Catches the failure
    # max_iter cannot see: one call that hangs rather than many that loop.
    max_execution_time=180,

    # Defaults to 2, and the default is wrong for anything with a budget guard.
    # CrewAI retries a failed task, so an agent stopped by our own tripwire gets
    # started again twice more -- a cap that fires would cost three times what
    # it was meant to save. See governance.unwrap_governance_error.
    max_retry_limit=0,

    verbose=True,
    allow_delegation=False,
)

analyst = Agent(
    role="Supply Chain Risk Analyst",
    goal="Turn supplier facts into a ranked judgement someone can act on",
    backstory="You advise a procurement director who has budget for exactly one "
              "intervention this quarter. You rank by consequence rather than by "
              "how alarming a number looks, you distinguish a trend that is bad "
              "from a position that is fragile, and you never recommend an "
              "action without naming what happens if nobody takes it.",
    # No tools. It cannot reach the files at all, which is a permission boundary
    # drawn with an empty list rather than a config setting.
    llm=MODEL,
    max_iter=6,
    max_execution_time=180,
    max_retry_limit=0,
    verbose=True,
    allow_delegation=False,
)


# ---------------------------------------------------------------------------
# THE TASKS
# ---------------------------------------------------------------------------

research_task = Task(
    description=(
        "Answer this question about our suppliers: {question}\n\n"
        "Start by listing the knowledge files. Then read every file that could "
        "bear on the question. Pull out the specific figures, dates and contract "
        "terms that matter. Do not draw conclusions yet."
    ),
    expected_output=(
        "A markdown section per supplier you read, each with the supplier name "
        "as a heading and bullets giving the concrete facts, with figures quoted "
        "exactly as the brief states them. End with a line naming the files read."
    ),
    agent=researcher,
)

analysis_task = Task(
    description=(
        "Using the researcher's findings, answer: {question}\n\n"
        "Rank the suppliers by how much they should worry us. A declining trend "
        "and a structurally fragile position are not the same thing."
    ),
    expected_output=(
        "A ranked list, highest concern first. Each entry gives the supplier "
        "name, a one-sentence verdict, the two or three facts that drive it, and "
        "what happens if nothing is done. Then one short closing paragraph "
        "naming the single action you would take first."
    ),
    agent=analyst,

    # GATE 4 -- THE HUMAN.
    #
    # This is real and it is native. CrewAI pauses here, prints the draft, and
    # blocks on input(). Enter alone accepts it; any text is treated as a
    # revision request and the agent goes round again, for as many rounds as you
    # want. The run does not finish until a person has looked.
    #
    # It is on the LAST task on purpose. A gate in the middle interrupts work;
    # a gate at the end reviews a result. And note what it is not: this is a
    # person at a terminal, not an approval record. Nobody else can later prove
    # who pressed Enter. Bridging that gap is the subject of the companion repo.
    human_input=True,
)


# ---------------------------------------------------------------------------
# THE CREW -- with both audit hooks wired
# ---------------------------------------------------------------------------


def on_step(step) -> None:
    """Every tool step: record it, then check we are still inside the budget.

    Order matters. Audit first so the step that trips the ceiling is in the log,
    then let Budget raise. A tripwire that fires before the record is written
    loses the one event you most wanted to see.
    """
    audit.step(step)
    budget.step(step)


crew = Crew(
    agents=[researcher, analyst],
    tasks=[research_task, analysis_task],
    process=Process.sequential,

    # Fires on tool steps: AgentAction and ToolResult. Verified 1.15.17 -- it
    # does NOT fire on a plain final answer, so this is a record of what the
    # crew touched rather than of what it thought.
    step_callback=on_step,

    # Fires once per finished task, with the TaskOutput.
    task_callback=audit.task,

    verbose=True,
)

budget.watch(crew.agents)


if __name__ == "__main__":
    question = (
        sys.argv[1] if len(sys.argv) > 1
        else "which supplier presents the most risk going into next quarter?"
    )

    audit.record("run_start", question=question[:200], model=MODEL,
                 max_tokens=MAX_TOKENS, max_tool_calls=MAX_TOOL_CALLS,
                 knowledge_dir=str(allowlist.read_root))

    started = time.time()
    exit_code = 0
    result = None

    try:
        result = crew.kickoff(inputs={"question": question})
        audit.record("run_complete", outcome="accepted")

    except (Exception, KeyboardInterrupt) as err:
        # Catch broadly and re-classify, because a gate does not arrive as the
        # type it was raised as. CrewAI wraps task exceptions in RuntimeError,
        # so `except BudgetExceeded` -- or `except EOFError` -- would silently
        # never match here. The real exception is on the __cause__ chain.
        gate = find_cause(err, GovernanceError)

        if find_cause(err, EOFError, KeyboardInterrupt):
            # Nobody was at the terminal to approve, so nothing is approved.
            # Failing closed is the whole point of a gate.
            audit.record("run_stopped", outcome="no_human_approval")
            print("\nNo approval given -- output not accepted.", file=sys.stderr)
            exit_code = 3

        elif isinstance(gate, BudgetExceeded):
            # Stop, do not resume. The next step costs about what the last one
            # cost, so continuing is how a ceiling becomes a suggestion.
            audit.record("run_stopped", outcome="budget_exceeded",
                         detail=str(gate), stopped_by=budget.stopped_by)
            print(f"\nBUDGET STOPPED THE RUN: {gate}", file=sys.stderr)
            exit_code = 1

        elif isinstance(gate, GovernanceError):
            audit.record("run_stopped", outcome="gate_refused", detail=str(gate))
            print(f"\nA GATE REFUSED: {gate}", file=sys.stderr)
            exit_code = 2

        else:
            # Not ours. Record that the run died and let it surface -- a crash
            # dressed up as a clean stop is how you lose a real bug.
            audit.record("run_failed", error_type=type(err).__name__,
                         detail=str(err)[:300])
            raise

    elapsed = time.time() - started
    spend = budget.reconcile(crew)
    audit.record("run_summary", elapsed_s=round(elapsed, 1), **spend)

    if result is not None:
        print("\n" + "=" * 70)
        print(result.raw)

    print("=" * 70)
    print(f"run           {run_id}")
    print(f"prompt        {PROMPT_VERSION}")
    print(f"tool calls    {budget.tool_calls}/{MAX_TOOL_CALLS}")
    print(f"tokens        {spend['tokens']:,}/{MAX_TOKENS:,}"
          f"  ({spend['source']}){'  OVER' if spend['over'] else ''}")
    print(f"model calls   {spend['requests']}")
    print(f"elapsed       {elapsed:.1f}s")
    print(f"audit         {AUDIT_PATH}  ({sum(audit.counts.values())} events)")
    print(f"events        {dict(sorted(audit.counts.items()))}")
    print("=" * 70)

    sys.exit(exit_code)
