# Troubleshooting

The errors you will actually hit, with the real text you will actually see.

Every message below was reproduced against **CrewAI 1.15.17** by running code that breaks on purpose. Nothing here is paraphrased from a docs page. The entries run roughly in the order a beginner meets them, and the worst ones are at the bottom, because the worst ones do not raise.

---

## 1. `ValueError: OPENAI_API_KEY is required`

**Symptom.** You run `python crew.py`, the banner prints, and then:

```
ERROR:root:OpenAI API call failed: OPENAI_API_KEY is required
ValueError: OPENAI_API_KEY is required
```

With `llm="anthropic/..."` the same shape, different word: `ANTHROPIC_API_KEY is required`.

**Cause.** CrewAI reads the key from the environment at call time, not at import time, so the failure lands after the run has started.

**Fix.** Export the key in the shell that runs Python, not the one you opened yesterday.

```bash
export OPENAI_API_KEY=sk-...          # or ANTHROPIC_API_KEY=sk-ant-...
python -c "import os; print(bool(os.environ.get('OPENAI_API_KEY')))"
```

## 2. `ImportError: Anthropic native provider not available`

**Symptom.** An Anthropic model string on a fresh install:

```
ImportError: Anthropic native provider not available, to install: uv add "crewai[anthropic]"
```

**Cause.** The OpenAI client is a core dependency of `crewai`; every other native provider ships behind an extra, and `anthropic` is one of them.

**Fix.** Install the extra. The message suggests `uv`; pip is the same package.

```bash
pip install 'crewai[anthropic]'
```

## 3. `ValidationError` from a wrong Agent parameter

**Symptom.** The program dies on the `Agent(...)` line before anything runs:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Agent
backstory
  Field required [type=missing, input_value={'role': 'Research Analyst', 'goal': 'find facts'}, input_type=dict]
```

A wrong *type* looks the same but names the coercion:

```
1 validation error for Agent
max_iter
  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='three', input_type=str]
```

**Cause.** `Agent`, `Task` and `Crew` are pydantic models, so every argument is validated at construction.

**Fix.** Read the second line: it names the field. Agent requires `role`, `goal` and `backstory`; Task requires `description` and `expected_output`. This is the framework being helpful — it fails before you spend money.

## 4. A misspelled parameter is silently thrown away

**Symptom.** You set `verbose=True` and get no output. You set a cap and it has no effect. No error, anywhere.

```python
a = Agent(role="R", goal="g", backstory="b", verbos=True, max_iterations=3)
a.verbose     # False
a.max_iter    # 25
```

**Cause.** These models use pydantic's default `extra="ignore"`, so an unrecognised keyword is dropped without a word — and `max_iterations`, `verbos` and `expcted_output` are all unrecognised keywords.

**Fix.** There is no setting that turns this into an error. Assert what you meant, once, near the top of your crew file.

```python
assert researcher.verbose and researcher.max_iter == 8, "an Agent kwarg didn't land"
```

## 5. `{topic}` shows up in the prompt, literally

**Symptom.** The agent researches the topic "{topic}". The run succeeds and bills you for it.

**Cause.** `kickoff()` skips interpolation entirely when `inputs` is empty or absent, so the braces are passed through to the model as text.

Give it a non-empty dict with the wrong key and you get the opposite, which is much better:

```
ValueError: Missing required template variable 'Template variable 'topic' not found
in inputs dictionary' in description
```

**Fix.** Always pass every placeholder, and let the loud failure be the one you keep.

```python
crew.kickoff(inputs={"topic": topic})     # not kickoff(), not kickoff(inputs={})
```

JSON braces in a `description` or `expected_output` are safe, incidentally — only `{identifier}` is treated as a placeholder.

## 6. The model name is never checked

**Symptom.** `llm="gpt-4o-minii"` builds an Agent without complaint and fails at the API, minutes later, with a provider error.

**Cause.** CrewAI routes on the *prefix* to pick a provider and passes the rest of the string through untouched; only the vendor's API knows which model names exist.

**Fix.** Make one cheap call before the crew runs.

```python
MODEL = "gpt-4o-mini"
LLM(model=MODEL).call("ping")     # fails here, not on task three
```

## 7. `except MyError:` around `kickoff()` never fires

**Symptom.** Your budget guard raises `BudgetExceeded`. Your handler does not catch it. What escapes is:

```
RuntimeError: Task execution failed: tool calls 1 exceeded cap 0
```

**Cause.** When an Agent has `max_execution_time` set, execution runs through `_execute_with_timeout`, which turns any exception into `RuntimeError(f"Task execution failed: {e!s}") from e`.

**Fix.** Walk the `__cause__` chain instead of matching the type. `find_cause()` in [example 04](../examples/04-governed-crew/governance.py) is nine lines and does not break on upgrade.

```python
try:
    crew.kickoff()
except (Exception, KeyboardInterrupt) as err:
    gate = find_cause(err, BudgetExceeded)   # your typed error, recovered
```

Verified: with `max_execution_time=None` your exception arrives unwrapped, and with it set it does not. The same wrapping hides the `EOFError` from `human_input` on a closed stdin.

## 8. Your guard fires, and the run finishes anyway

**Symptom.** The tripwire raises. The crew returns a normal-looking result. Nothing surfaced.

**Cause.** `max_retry_limit` defaults to **2**, so a task that raises is re-run twice more, and a guard that happened not to trip on the third attempt leaves no trace.

**Fix.** Turn the retry off on every agent that a guard can stop.

```python
Agent(..., max_retry_limit=0)
```

Verified: same crew, same tripwire. With `max_retry_limit=0` the exception escapes after 1 model call. With the default 2 it made 3 calls and raised nothing at all.

## 9. `crew.usage_metrics` is `None` after a stop

**Symptom.** The run halts and your cost summary prints zeros — at exactly the moment you most want the number.

**Cause.** `usage_metrics` is computed only when the run completes, so any abort leaves it unset.

**Fix.** Fall back to the live counters on each LLM instance, and label which source you used.

```python
summary = llm.get_token_usage_summary()
tokens = summary.total_tokens          # cumulative, works mid-run and after a stop
```

Related, and it will double your numbers: those counters live on the **instance**, and `usage_metrics` sums them per agent. Two agents sharing one `LLM` object report exactly 2x — verified, 400 tokens for 200 tokens of real work. Pass model *strings* and let CrewAI build one instance per agent.

## 10. `max_iter` does not stop a runaway agent

**Symptom.** A capped agent returns a confident answer that is wrong, or returns its own half-finished `Thought:` text as the final result. No exception, no flag on `CrewOutput`.

**Cause.** Hitting the cap does not raise — CrewAI appends one more message and makes one more call:

```
Now it's time you MUST give your absolute best final answer. You'll ignore all
previous instructions, stop using any tools, and just return your absolute BEST
Final answer.
```

Verified: `max_iter=3` against a loop that never terminates produced **4** model calls and a `CrewOutput` indistinguishable from a real one.

**Fix.** `max_iter` is a cost cap, not a correctness cap. With `verbose=True` the line `Maximum iterations reached. Requesting final answer.` prints in yellow — treat it as a failed run, and print your caps in every summary so a capped answer is never mistaken for a finished one.

## 11. Hierarchical mode ignores `task.agent`

**Symptom.** You assign a task to the Technical Writer. The logs show `Crew Manager` doing it.

**Cause.** `Crew._get_agent_to_use()` returns `self.manager_agent` whenever the process is hierarchical and never reads `task.agent`.

**Fix.** Nothing to fix — know it. Your `agent=` fields stay in the file looking load-bearing and do nothing; routing is the manager reading `role` and `goal` off the roster. Two related refusals, both verified: omitting `manager_llm` raises a pydantic `ValidationError` at `Crew(...)`, and a `manager_agent` with any tools raises `Exception: Manager agent should not have tools`. See [example 03](../examples/03-sequential-vs-hierarchical/) for what it costs.

## 12. Tool names are fuzzy-matched

**Symptom.** The model asks for a tool that does not exist and a different one runs.

**Cause.** `ToolUsage._select_tool` sorts your tools by `difflib.SequenceMatcher` ratio against the requested name and accepts anything above **0.85**.

**Fix.** Keep tool names far apart in string distance, not just in meaning. `read_knowlege_file` scores 0.973 against `read_knowledge_file`, and `delete_record` scores 0.963 against `delete_records` — a typo that silently hits a destructive tool is the shape of the accident here. Another reason to give each agent the fewest tools that let it finish.

## 13. `memory=True` does nothing, quietly

**Symptom.** Memory is on, the run succeeds, and nothing is ever remembered. Buried in the noise:

```
[CrewAIEventsBus] Warning: Ending event 'memory_save_failed' emitted with empty scope stack.
Memory requires an embedder for vector search but initialization failed:
The CHROMA_OPENAI_API_KEY environment variable is not set.
```

**Cause.** Memory needs an *embedding* model, which defaults to OpenAI regardless of which provider your agents use — so an Anthropic-only setup fails every save and the run reports success.

**Fix.** Export an OpenAI key alongside your model key, or name a different embedder.

```python
Crew(..., memory=True, embedder={"provider": "google", "config": {...}})
```

## 14. Telemetry, and the trace prompt that is not telemetry

**Symptom.** Two different things phone home, and disabling one does not disable the other.

**Cause.** Anonymous telemetry is on by default. Separately, on your first run in a directory CrewAI buffers execution events and prompts you at the terminal:

```
Would you like to view your execution traces? [y/N] (20s timeout):
```

Answer `y` and it uploads that run and opens a browser. Verified: `CREWAI_DISABLE_TELEMETRY=true` does **not** suppress this prompt — the two systems are unrelated.

**Fix.** Set the telemetry variable, and answer `N` once so the decline is saved.

```bash
export CREWAI_DISABLE_TELEMETRY=true
export CREWAI_STORAGE_DIR=~/.crewai-local     # otherwise: see below
```

That last line matters more than it looks. `db_storage_path()` is `~/.local/share/<name of your current directory>`, so the saved "I already declined" flag, plus memory and knowledge stores, are keyed on your **folder name**. Move to a new project folder and you are prompted again; two unrelated projects both called `crew/` share one store. Set it explicitly and stop guessing.

---

Hit something this file does not cover? [Open an issue](https://github.com/steviebuchicago/crewai-for-beginners/issues) with the traceback — see [CONTRIBUTING.md](../CONTRIBUTING.md). An error somebody else spent an afternoon on is the most useful thing you can add here.
