# 01 — Your First Crew

Two agents, two tasks, one sequential handoff. The smallest CrewAI program that teaches you something.

```bash
cd examples/01-first-crew
pip install -r requirements.txt

export OPENAI_API_KEY=sk-...          # or: export ANTHROPIC_API_KEY=sk-ant-...

python crew.py
python crew.py "why lithium prices move"
```

---

## What it does

A Research Analyst gathers four or five points about a topic and tags each one *established* or *contested*. A Technical Writer turns those points into a 200-300 word brief. The researcher's output becomes the writer's input automatically, and you never write the line that passes it along.

That last sentence is the entire reason to use a framework.

## The mental model

Three objects, and they are smaller than they sound.

**An Agent is a system prompt with a job title.** `role`, `goal` and `backstory` are not metadata for your own benefit — they are concatenated into the system prompt that the model receives on every call. There is no hidden intelligence attached to an Agent object. When you write `backstory="You are allergic to filler"`, you have written a prompt, and it works exactly as well as that prompt would work if you had typed it into a chat window.

This is worth internalising early, because it tells you how to debug. If an agent behaves badly, the fix is almost never a different framework parameter. It is better words in those three fields.

**A Task is a work order.** The Agent says *who this is*; the Task says *what to do once, and what the finished thing looks like*. The split matters when one agent has several tasks: the role stays put, the work orders change.

**A Crew is the roster plus the running order.** It owns no intelligence at all. It decides who runs when, and what each one is allowed to see. In `Process.sequential` the `tasks=[...]` list *is* the running order, and the `agents=[...]` list is only a roster — its order means nothing.

## The four parameters worth slowing down on

**`role`** — a noun phrase a human could hold. "Research Analyst", not "finds facts about things". The task belongs in the Task. Models play roles well and they play job descriptions badly.

**`goal`** — the standing instruction across every task this agent gets. When the model faces two reasonable next moves, this is the tiebreaker. Ours says *separate what is established from what is contested*, and that single clause is what puts the tags in the output.

**`backstory`** — the longest field, and the one people waste. This is the only place to say how the agent should behave that is neither a title nor a target. Concrete constraints change the output: *"you flag when something is genuinely uncertain rather than smoothing it over"* does work. *"You are a helpful assistant"* does nothing at all — the model was already going to be that.

**`expected_output`** — the one beginners skip, and the one that decides whether your program is repeatable.

## Why `expected_output` matters more than you think

It reads like documentation. It is not. It gets appended to the prompt as the acceptance criteria, and it is what the agent checks its own draft against before deciding it is finished.

Write `expected_output="a good summary"` and you have delegated the definition of *done* to a stochastic process, which will define it differently every run. Write this instead:

```python
expected_output=(
    "A brief of 200-300 words with a one-line summary first, then prose. "
    "No headings, no bullet points, no closing 'in conclusion' paragraph."
)
```

and you get the same *shape* every run even though the words differ. Specific acceptance criteria are how you get stable structure out of a system that is stable at nothing else. If you take one habit from this example, take this one.

## `{topic}` is not an f-string

```python
description="Research this topic: {topic}"     # correct, braces stay literal
description=f"Research this topic: {topic}"    # wrong
```

CrewAI substitutes `{topic}` at `kickoff()` time from the `inputs` dict, in one pass before anything runs. Reaching for an f-string is the most common way this breaks, and it breaks late — it works until a value contains a brace, and then it fails somewhere unhelpful.

## Reading the verbose output

`verbose=True` on the agents and the crew prints the whole loop. You will see, per task, the prompt as assembled, the agent's thinking, and the answer it settled on. It is noisy and you should leave it on anyway, because it makes the central fact obvious: **a crew is a sequence of ordinary model calls.** Two tasks, two calls. Nothing is running in parallel, nothing is negotiating. Once you have seen that, framework behaviour stops being mysterious.

## Choosing a model

The `llm=` parameter takes a `provider/model` string:

```python
Agent(..., llm="anthropic/claude-sonnet-4-5")   # Anthropic
Agent(..., llm="gpt-4o-mini")                   # OpenAI, provider inferred
```

CrewAI 1.x routes these through its own native provider clients. If you have read older tutorials describing these as LiteLLM strings, the syntax is the same but the plumbing changed — LiteLLM is now an optional fallback that is not installed by default. The OpenAI client is a core dependency; Anthropic arrives via the `[anthropic]` extra, which is why `requirements.txt` asks for it.

`crew.py` picks its model from whichever key you exported, so the example runs either way. **In your own code, hardcode one.** A model that changes with the environment is a debugging problem waiting to happen.

## Two things to try

Both take a minute and both teach more than reading does.

1. **Gut the `expected_output` on the writing task.** Replace it with `"a summary"` and run three times. Watch the length and structure wander.

2. **Add a third agent.** Give it `role="Fact Checker"`, put its task between the other two, and note what you did *not* have to write: no plumbing, no passing of outputs. That is the framework earning its place.

## What this example is missing

No tools, so the agents work purely from what the model already knows and cannot look anything up — [example 02](../02-research-crew/) fixes that. No cost ceiling, no record of what happened, no human check before output is accepted — that is [example 04](../04-governed-crew/), and it is where this stops being a toy.

## Telemetry

CrewAI reports anonymous usage data by default. To turn it off:

```bash
export CREWAI_DISABLE_TELEMETRY=true
```

Worth knowing before you run it on anything that belongs to your employer.
