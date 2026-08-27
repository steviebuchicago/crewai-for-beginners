"""A researcher that can read files, and an analyst that cannot.

Example 01's agents worked from what the model already knew. These two work from
a folder of supplier briefs, because one of them has tools. The tools live in
tools.py and can reach exactly one directory.

    export OPENAI_API_KEY=sk-...        # or ANTHROPIC_API_KEY=sk-ant-...
    pip install -r requirements.txt
    python crew.py
    python crew.py "which supplier should we renegotiate first?"
"""

import os
import sys

from crewai import Agent, Crew, Process, Task

from tools import list_knowledge_files, read_knowledge_file

MODEL = "anthropic/claude-sonnet-4-5" if os.environ.get("ANTHROPIC_API_KEY") else "gpt-4o-mini"


# ---------------------------------------------------------------------------
# THE RESEARCHER -- the only agent with tools
#
# Giving an agent tools does not make it use them well. The model sees each
# tool's name, parameters and docstring on every turn and decides for itself
# whether calling one would help. Everything you can do to improve that decision
# happens in two places: the docstrings in tools.py, and the backstory here.
# ---------------------------------------------------------------------------

researcher = Agent(
    role="Procurement Research Analyst",
    goal="Answer questions about our suppliers using only what the briefs "
         "actually say, and be explicit when they do not say it",

    # This backstory is doing tool-discipline work, not personality work. Agents
    # with file tools have two failure modes: reading one file and answering
    # confidently, or answering from general knowledge without reading at all.
    # Both are cheap to prevent here and expensive to notice later.
    backstory="You are a procurement analyst who has been burned by partial "
              "reads. You list the available files before you read any of them, "
              "and you read every file that could possibly bear on the question "
              "before you answer. You quote figures exactly as written. When the "
              "briefs do not contain something, you say so rather than filling "
              "the gap from memory.",

    # Two tools, not ten. See the README -- this is a deliberate limit, not a
    # limitation of the example.
    tools=[list_knowledge_files, read_knowledge_file],

    llm=MODEL,
    verbose=True,
    allow_delegation=False,
)


# ---------------------------------------------------------------------------
# THE ANALYST -- deliberately toolless
#
# It cannot read files. It works only from what the researcher hands it. That is
# a design choice worth copying: the agent that gathers and the agent that
# judges are different jobs, and keeping the judge away from the raw source
# means its conclusions have to survive the summary.
# ---------------------------------------------------------------------------

analyst = Agent(
    role="Supply Chain Risk Analyst",
    goal="Turn supplier facts into a ranked judgement someone can act on",
    backstory="You advise a procurement director who has budget for exactly one "
              "intervention this quarter. You rank by consequence rather than by "
              "how alarming a number looks, you distinguish a trend that is bad "
              "from a position that is fragile, and you never recommend an "
              "action without naming what happens if nobody takes it.",
    llm=MODEL,
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
        "bear on the question -- all of them, unless one is obviously "
        "irrelevant. Pull out the specific figures, dates and contract terms "
        "that matter. Do not draw conclusions yet; that is the analyst's job."
    ),
    expected_output=(
        "A markdown section per supplier you read, each with the supplier name "
        "as a heading and bullets underneath giving the concrete facts relevant "
        "to the question, with figures quoted exactly as the brief states them. "
        "End with a line naming which files you read."
    ),
    agent=researcher,
)

analysis_task = Task(
    description=(
        "Using the researcher's findings, answer: {question}\n\n"
        "Rank the suppliers by how much they should worry us. A declining "
        "trend and a structurally fragile position are not the same thing, and "
        "the more alarming numbers are not always the bigger problem."
    ),
    expected_output=(
        "A ranked list, highest concern first. Each entry gives the supplier "
        "name, a one-sentence verdict, the two or three facts that drive it, "
        "and what happens if nothing is done. Then one short closing paragraph "
        "naming the single action you would take first."
    ),
    agent=analyst,
)


crew = Crew(
    agents=[researcher, analyst],
    tasks=[research_task, analysis_task],
    process=Process.sequential,
    verbose=True,
)


if __name__ == "__main__":
    question = (
        sys.argv[1] if len(sys.argv) > 1
        else "which supplier presents the most risk going into next quarter?"
    )
    result = crew.kickoff(inputs={"question": question})

    print("\n" + "=" * 70)
    print(result.raw)
    print("=" * 70)
    print(f"tokens: {result.token_usage.total_tokens:,}  "
          f"calls: {result.token_usage.successful_requests}")
