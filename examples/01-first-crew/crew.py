"""Two agents, two tasks, one crew. The smallest CrewAI program worth reading.

A researcher gathers points about a topic; a writer turns them into a brief.
That is the whole program. Everything else in this file is a comment explaining
why a parameter is there, because the parameters are the actual lesson.

    export OPENAI_API_KEY=sk-...        # or ANTHROPIC_API_KEY=sk-ant-...
    pip install -r requirements.txt
    python crew.py
    python crew.py "why lithium prices move"
"""

import os
import sys

from crewai import Agent, Crew, Process, Task

# CrewAI picks the provider from the model string prefix: "anthropic/..." goes
# to Anthropic, a bare "gpt-..." goes to OpenAI. We branch on which key you
# exported so this file runs either way. In your own code, hardcode the one you
# use -- a model that changes with the environment is a debugging problem.
MODEL = "anthropic/claude-sonnet-4-5" if os.environ.get("ANTHROPIC_API_KEY") else "gpt-4o-mini"


# ---------------------------------------------------------------------------
# THE AGENTS
#
# An Agent is a system prompt with a job title. role, goal and backstory are
# not documentation for you -- they are pasted into the prompt that the model
# sees on every single call. Writing them vaguely is the same act as writing a
# vague prompt, and it fails the same way.
# ---------------------------------------------------------------------------

researcher = Agent(
    # role is the job title, and the model plays this part. Keep it a noun
    # phrase a human could hold ("Research Analyst"), not a description of a
    # task ("finds facts") -- the task belongs in the Task, not here.
    role="Research Analyst",

    # goal is what success looks like across every task this agent is given.
    # It is the standing instruction. When the model has to choose between two
    # reasonable next moves, this is the tiebreaker it reads.
    goal="Find the handful of facts about a topic that a smart outsider would "
         "actually need, and separate what is established from what is contested",

    # backstory is where domain expertise and constraints go. It is the longest
    # of the three for a reason: it is the only place to say how this agent
    # should behave that is not a job title or a target. "You are skeptical of
    # single-source claims" changes the output. "You are helpful" does not.
    backstory="You spent a decade as a desk analyst summarising unfamiliar "
              "industries for people who had to make decisions by Friday. You "
              "are allergic to filler, you flag when something is genuinely "
              "uncertain rather than smoothing it over, and you would rather "
              "give four solid points than ten padded ones.",

    llm=MODEL,

    # verbose=True prints the agent's reasoning loop as it runs: the prompt it
    # was given, its intermediate thinking, and the answer it settled on. Leave
    # it on while you are learning. It is the only way to see that a "crew" is
    # a sequence of ordinary model calls rather than something magic.
    verbose=True,

    # Off by default, and we leave it off. Delegation lets an agent hand work to
    # another agent, which also lets it loop, argue, and burn tokens. Example 03
    # turns it on deliberately. A fixed two-step pipeline does not need it.
    allow_delegation=False,
)

writer = Agent(
    role="Technical Writer",
    goal="Turn research notes into a brief that a busy reader finishes",
    backstory="You write for people who will read exactly one thing about this "
              "topic today. You lead with the point rather than building up to "
              "it, you cut every sentence that survives only out of politeness, "
              "and you never pad a section to make it look substantial.",
    llm=MODEL,
    verbose=True,
    allow_delegation=False,
)


# ---------------------------------------------------------------------------
# THE TASKS
#
# A Task is a work order. The Agent says who this is; the Task says what to do
# once and what the finished thing looks like.
#
# {topic} is not an f-string. Leave the braces literal -- CrewAI substitutes
# them at kickoff() from the inputs dict. Formatting it here with an f-string is
# the most common way beginners break this, because it works right up until the
# value has a brace in it.
# ---------------------------------------------------------------------------

research_task = Task(
    description=(
        "Research this topic: {topic}\n\n"
        "Identify the four or five things a newcomer most needs to know. For "
        "each, note whether it is well established or still argued about. Do "
        "not write prose yet -- this is raw material for a writer."
    ),

    # expected_output matters more than beginners think. It is not a comment:
    # it is appended to the prompt as the acceptance criteria, and it is what
    # the agent checks its own draft against before deciding it is done. Vague
    # here ("a good summary") means the agent decides what done means, and it
    # will decide differently on every run. Specific here is how you get a
    # stable shape out of a stochastic process.
    expected_output=(
        "A markdown list of 4-5 bullets. Each bullet is one sentence of claim "
        "followed by a parenthetical tag of either (established) or (contested)."
    ),

    agent=researcher,
)

writing_task = Task(
    description=(
        "Using the research notes, write a short brief on {topic} for an "
        "intelligent reader who knows nothing about it. Preserve the "
        "established-versus-contested distinction the analyst drew."
    ),
    expected_output=(
        "A brief of 200-300 words with a one-line summary first, then prose. "
        "No headings, no bullet points, no closing 'in conclusion' paragraph."
    ),
    agent=writer,
    # Note what is NOT here: we never pass the researcher's output to this task.
    # In Process.sequential each task automatically receives the previous
    # task's output as context. That handoff is the thing a Crew does for you.
)


# ---------------------------------------------------------------------------
# THE CREW
#
# A Crew is the roster plus the running order. It owns no intelligence of its
# own; it decides who runs when and what each one gets to see.
# ---------------------------------------------------------------------------

crew = Crew(
    agents=[researcher, writer],

    # In Process.sequential this list IS the running order. The agents= list
    # above is just the roster and its order means nothing.
    tasks=[research_task, writing_task],

    # sequential: run tasks top to bottom, feeding each output into the next.
    # The other option is hierarchical, where a manager agent decides. That is
    # example 03, and the honest answer there is that you rarely want it.
    process=Process.sequential,

    verbose=True,
)


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "how container shipping rates are set"

    # kickoff() is the only thing that costs money. Everything above this line
    # just built objects. inputs= is what fills the {topic} placeholders in
    # every task description, in one substitution pass before the run starts.
    result = crew.kickoff(inputs={"topic": topic})

    # result is a CrewOutput, not a string. It carries the last task's output
    # (.raw), every task's output (.tasks_output), and the token count
    # (.token_usage). Printing it directly gives you .raw.
    print("\n" + "=" * 70)
    print(result.raw)
    print("=" * 70)
    print(f"tokens: {result.token_usage.total_tokens:,}  "
          f"calls: {result.token_usage.successful_requests}")
