"""The same three agents, run by a manager instead of in a fixed order.

Identical to crew_sequential.py except for the Crew() call at the bottom.
Run `diff crew_sequential.py crew_hierarchical.py` and read what comes back --
that difference is the entire subject of this example.

    export OPENAI_API_KEY=sk-...        # or ANTHROPIC_API_KEY=sk-ant-...
    pip install -r requirements.txt
    python crew_hierarchical.py
    python crew_hierarchical.py "how sourdough starters actually work"
"""

import os
import sys
import time

from crewai import Agent, Crew, Process, Task

MODEL = "anthropic/claude-sonnet-4-5" if os.environ.get("ANTHROPIC_API_KEY") else "gpt-4o-mini"


# ---------------------------------------------------------------------------
# THREE AGENTS -- byte-identical in both files
# ---------------------------------------------------------------------------

researcher = Agent(
    role="Research Analyst",
    goal="Assemble the facts a newcomer needs about a topic",
    backstory="You summarise unfamiliar subjects for people who have to decide "
              "something by Friday. You prefer four solid points to ten padded "
              "ones, and you mark what is genuinely uncertain.",
    llm=MODEL,
    verbose=True,
)

fact_checker = Agent(
    role="Fact Checker",
    goal="Find the claims that are wrong, overstated, or quietly load-bearing",
    backstory="You have watched confident summaries collapse under one bad "
              "number. You challenge specifics rather than tone, you flag "
              "claims that are technically true but misleading, and you say so "
              "plainly when everything checks out instead of inventing problems.",
    llm=MODEL,
    verbose=True,
)

writer = Agent(
    role="Technical Writer",
    goal="Turn checked research into a brief a busy reader finishes",
    backstory="You write for someone who will read exactly one thing about this "
              "today. You lead with the point, you cut sentences that survive "
              "only out of politeness, and you never pad a section to make it "
              "look substantial.",
    llm=MODEL,
    verbose=True,
)


# ---------------------------------------------------------------------------
# THREE TASKS -- byte-identical in both files
# ---------------------------------------------------------------------------

research_task = Task(
    description=(
        "Research this topic: {topic}\n\n"
        "Identify the four or five things a newcomer most needs to know."
    ),
    expected_output=(
        "A markdown list of 4-5 bullets, each one sentence, each tagged "
        "(established) or (contested)."
    ),
    agent=researcher,
)

check_task = Task(
    description=(
        "Review the research notes on {topic}. Flag anything overstated, "
        "miscategorised, or wrong. If a bullet is sound, leave it alone."
    ),
    expected_output=(
        "The same list of bullets, each followed by either OK or a one-line "
        "correction. Then a single line: CHECKED or CHANGES REQUESTED."
    ),
    agent=fact_checker,
)

writing_task = Task(
    description=(
        "Write a short brief on {topic} using the checked research. Apply the "
        "fact checker's corrections. Preserve the established/contested split."
    ),
    expected_output=(
        "200-300 words. One-line summary first, then prose. No headings, no "
        "bullets, no closing 'in conclusion' paragraph."
    ),
    agent=writer,
)


# ---------------------------------------------------------------------------
# THE ONLY DIFFERENCE BETWEEN THE TWO FILES STARTS HERE
#
# hierarchical: CrewAI builds a manager agent you never declared, hands it a
# roster of your three agents, and gives it two tools -- "Delegate work to
# coworker" and "Ask question to coworker". The manager then takes every task
# itself and decides, per task, whether to do it or hand it off.
#
# Read that twice, because it is the part the diagrams leave out: the manager
# receives ALL THREE tasks. The agent= field on each Task above is IGNORED in
# this mode. Those assignments are still in the file, they still look load
# bearing, and they do nothing. What actually routes the work is the manager
# reading your role and goal strings and picking a name off the roster.
# ---------------------------------------------------------------------------

crew = Crew(
    agents=[researcher, fact_checker, writer],
    tasks=[research_task, check_task, writing_task],

    process=Process.hierarchical,

    # Required. Without manager_llm (or manager_agent) Crew() itself raises a
    # pydantic ValidationError right here, before any model is called:
    # "Attribute `manager_llm` or `manager_agent` is required when using
    # hierarchical process." The manager is a real agent making real calls, so
    # it needs a real model -- and it is the one reasoning about every task, so
    # making it the cheap model is usually a false economy.
    manager_llm=MODEL,

    verbose=True,
)


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "how container shipping rates are set"

    started = time.time()
    result = crew.kickoff(inputs={"topic": topic})
    elapsed = time.time() - started

    print("\n" + "=" * 70)
    print(result.raw)
    print("=" * 70)
    # Print these for both files and compare them. The argument in the README
    # is about cost and predictability, and these are the numbers behind it.
    print(f"process:  hierarchical")
    print(f"tokens:   {result.token_usage.total_tokens:,}")
    print(f"calls:    {result.token_usage.successful_requests}")
    print(f"elapsed:  {elapsed:.1f}s")
