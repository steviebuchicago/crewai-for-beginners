# 02 — Giving an Agent Tools

A researcher that can read a folder of supplier briefs, an analyst that cannot, and two custom tools that can reach exactly one directory.

```bash
cd examples/02-research-crew
pip install -r requirements.txt

export OPENAI_API_KEY=sk-...          # or: export ANTHROPIC_API_KEY=sk-ant-...

python crew.py
python crew.py "which supplier should we renegotiate first?"
```

No web search, no API key beyond the model. Everything the crew learns comes from `knowledge/`.

---

## What it does

`knowledge/` holds three supplier briefs for fictional companies — Northgate Supply, Lakeshore Print, Ridgeline Logistics. The researcher lists the folder, reads the briefs, and pulls out the figures. The analyst, who has no tools at all, ranks the suppliers by risk.

The interesting answer is not the obvious one. Northgate has the ugly numbers: on-time delivery falling four quarters straight. Ridgeline's numbers are *improving* — and Ridgeline is the real problem, because it handles 71% of outbound freight on a contract that expired and now runs month-to-month with a 30-day termination right. A declining trend and a fragile position are different things. That distinction is why the analyst exists.

## What a tool actually is

A tool is a Python function the model is allowed to call. That is the whole idea, and it is less magical than the word suggests.

What the model receives is not your function. It receives a **description** of your function: its name, its parameters, and its docstring. On each turn it decides whether calling one would help, and if so it emits a name and some JSON arguments. CrewAI parses that, runs your actual Python, and feeds the return value back into the conversation as the next message.

So the model never sees your code. It sees a signature and a docstring, and it makes its decision entirely from those. In CrewAI 1.15.17 the default agent executor puts them straight into the prompt as text:

```
Tool Name: read_knowledge_file
Tool Arguments: {
  "properties": {
    "filename": {
      "title": "Filename",
      "type": "string"
    }
  },
  "required": [
    "filename"
  ],
  "title": "Read_Knowledge_File",
  "type": "object",
  "additionalProperties": false
}
Tool Description: Read one supplier brief and return its full text.

    Pass exactly one filename as it appeared in list_knowledge_files, for
    example "northgate-supply.md". Do not pass a path, a wildcard, or more
    than one name. To read several briefs, call this tool once per file.
```

The name comes from the decorator, the arguments schema is generated from your type annotations, and the description is your docstring, verbatim, indentation and all.

## The docstring is the prompt

Which leads to the point people miss for weeks: **your docstring is not documentation, it is prompt engineering.** It is the only instruction the model gets about when and how to use the tool. Write it for the model, in the imperative, and put the failure modes in it.

Compare:

```python
"""Reads a file."""                                    # a note to yourself
```

```python
"""Read one supplier brief and return its full text.

Pass exactly one filename as it appeared in list_knowledge_files, for
example "northgate-supply.md". Do not pass a path, a wildcard, or more than
one name. To read several briefs, call this tool once per file.
"""
```

The second one pre-empts three real failures: passing a path, passing a glob, and trying to batch several files into one call. Every one of those is something a model will attempt if you do not say otherwise, and each costs a wasted turn.

The `@tool` decorator enforces the minimum. Omit the docstring or the type annotations and it raises at import — which is the right moment to find out, rather than three turns into a run.

```python
from crewai.tools import tool

@tool("read_knowledge_file")
def read_knowledge_file(filename: str) -> str:
    """..."""
```

## Why two tools and not ten

Every tool you add is a permanent tax. Its name, schema and full docstring sit in the prompt on *every single turn* for that agent, so ten tools means ten descriptions consuming context before the model reads a word of the actual task. And the failure is not just cost — the more similar options a model is holding, the worse it chooses between them. Three overlapping file-reading tools produce more wrong calls than one clear one.

The habit worth forming: **give each agent the smallest set of tools that lets it finish its job, and give different jobs to different agents.** The analyst here has zero tools, which is not an oversight. Gathering and judging are separate jobs. Keeping the judge away from the raw files means its conclusions have to survive the researcher's summary, and when the ranking is wrong you know which of the two to go and fix.

## A tool is a permission boundary

Here is the part that matters more than any of the above, and it is one paragraph because it is the seed of a much longer argument.

`read_knowledge_file` resolves every filename against `KNOWLEDGE_DIR` and refuses anything that lands outside it. Four lines, and they are the difference between a tool and a hole. Without them the function is `open(whatever_the_model_said)` — and what the model said came from somewhere, possibly from inside a document it just read. The check does `resolve()` *before* comparing, because `../../../etc/passwd` only looks dangerous after resolution; as a raw string it sails past any `startswith()` test you write. **The scope of a tool is the scope of the agent.** An agent has exactly the reach of the functions you hand it, which means the file that decides what your agent may touch is `tools.py`, and it is the most security-relevant file in this repo. Example 04 takes this seriously.

Try it. The refusal is a plain sentence, not an exception:

```python
>>> from tools import read_knowledge_file
>>> read_knowledge_file.run(filename="../../../etc/passwd")
"Refused: '../../../etc/passwd' resolves outside the knowledge folder. Call list_knowledge_files to see the valid names."
```

Returning a sentence instead of raising is deliberate. The model can read it and correct itself next turn; an exception usually just ends the run. Failures an agent can recover from should be recoverable, and a mistyped filename is exactly that.

## Reading the verbose output

With `verbose=True` you will see the researcher's loop, and it looks like this:

```
Thought: I should see what files are available.
Action: list_knowledge_files
Action Input: {}
Observation: lakeshore-print.md
northgate-supply.md
ridgeline-logistics.md

Thought: Now read each one.
Action: read_knowledge_file
Action Input: {"filename": "northgate-supply.md"}
Observation: # Supplier Brief — Northgate Supply Co. ...
```

`Thought` / `Action` / `Action Input` / `Observation`, repeating until the model emits `Final Answer:`. That loop is all an agent is. The researcher takes several turns because each file is a separate call; the analyst takes one, because it has nothing to call.

If an agent never calls a tool it plainly should, the problem is nearly always the docstring or the backstory — not the wiring.

## Two things to try

1. **Break the docstring.** Change `read_knowledge_file`'s docstring to `"""Reads a file."""` and run again. Watch it guess at filenames it was never given.

2. **Delete `list_knowledge_files`.** Leave only the reader. The model now has to invent filenames, and you will see it hallucinate plausible ones. A discovery tool alongside an access tool is a pattern worth keeping.

## What this example is still missing

Nothing stops the researcher looping on the same file twenty times. Nothing caps the spend. Nothing records what it read. Nobody approves the output before it is used. Those are [example 04](../04-governed-crew/).

First, though, [example 03](../03-sequential-vs-hierarchical/) answers the question you are probably already asking: what if a manager agent decided all this instead?
