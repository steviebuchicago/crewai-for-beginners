# 04 — The Governed Crew

Example 02's research crew, plus the four things it needs before it runs anywhere that matters: a boundary, a record, a ceiling, and a human.

```bash
cd examples/04-governed-crew
pip install -r requirements.txt

export OPENAI_API_KEY=sk-...          # or: export ANTHROPIC_API_KEY=sk-ant-...

python crew.py                        # pauses at the end for your approval
echo "" | python crew.py              # auto-accepts (and see what that costs you)

cat out/audit.jsonl | python -m json.tool --json-lines
```

Exit codes: `0` accepted, `1` budget stopped the run, `2` a gate refused, `3` nobody approved it.

This example reads [example 02's](../02-research-crew/knowledge/) supplier briefs rather than keeping a second copy, so run it from a full clone. If that folder is missing it exits immediately and tells you, which is the cheapest possible demonstration of failing closed.

---

## The argument

Getting a crew to read files and produce a good answer is example 02, and it took an afternoon. Everything in *this* directory exists to answer questions somebody asks afterwards:

> What could it reach? What did it actually do? What did it cost? Who said the output was fine?

None of those are model problems. All of them are engineering problems, and this repo's companion — [agents-are-easy-governance-is-hard](https://github.com/steviebuchicago/agents-are-easy-governance-is-hard) — is about why they are the ones that stall projects. This example is that argument ported to CrewAI.

Diff `crew.py` against `../02-research-crew/crew.py`. The agents, the tasks and the tools do the same work. Every difference is a gate.

## What CrewAI gives you, and what it does not

The honest inventory, verified against 1.15.17 rather than taken from the docs.

| | Native? | What it actually is |
| --- | --- | --- |
| `max_iter` on Agent | **yes** | Real pre-emptive cap on the think-act loop |
| `max_execution_time` on Agent | **yes** | Real wall-clock cap, per agent |
| `max_rpm` on Agent/Crew | **yes** | Real rate limit |
| `human_input=True` on Task | **yes** | Real blocking approval at the terminal |
| `step_callback` / `task_callback` | **yes** | Real hooks — but see the caveats below |
| `crew.usage_metrics` | partly | Accurate, and **only after the run finishes** |
| A path boundary on tools | **no** | You write it |
| An audit log | **no** | You write it |
| A spend cap that actually stops a run | **no** | You write it, and it fights you |
| An approval record | **no** | You write it |

The top half is genuinely good and you should use all of it. The bottom half is the afternoon that turns into a quarter.

## Gate 1 — Permissions

`Allowlist` declares one readable root. Every filename the model produces goes through `allowlist.read()`, which resolves it and then refuses anything landing outside.

`resolve()` happens **before** the comparison, because `../../../etc/passwd` only looks dangerous after resolution — as a raw string it passes any `startswith()` test you write. The root is a module constant, never derived from `argv`: an allowlist built out of the arguments it is meant to check is a formality.

The tools are built by a factory that closes over the allowlist and the log, so there is no code path that reads a file while skipping either. A tool that *could* bypass the gate eventually will.

*The failure this prevents.* The filename does not come from you. It comes from the model, which read it out of a document, which somebody else wrote. Without the check, `read_knowledge_file` is `open()` on a string a stranger influenced, running with your credentials.

## Gate 2 — Audit

`AuditLog` appends one JSON object per event to `out/audit.jsonl`, as it happens. A real run produces twenty rows:

```json
{"ts":"2026-08-27T06:07:05+00:00","run_id":"20260827T060705Z-d74f97","prompt_version":"2026-01-15.1","event":"tool_read","file":"northgate-supply.md","bytes":1683,"sha256":"..."}
{"ts":"...","run_id":"...","prompt_version":"2026-01-15.1","event":"tool_denied","requested":"../../../etc/passwd","reason":"'../../../etc/passwd' resolves outside the allowlist"}
```

Four decisions are worth copying.

**It records refusals.** `tool_denied` is the row you most want and the one nobody writes. A log that only shows successful reads cannot tell you the agent spent the afternoon trying to get out of its box.

**It records the prompt version.** An output is only explainable if you know which prompt produced it, and the prompt will have been edited twice before anyone asks. Bump `PROMPT_VERSION` whenever you touch a `role`, `goal`, `backstory`, `description` or `expected_output`.

**It refuses to log content.** Pass a key named `content`, `text`, `body`, `raw_text` or `payload` and `record()` raises. Task outputs are stored as a SHA-256 plus a length; tool results are stored as a size. An audit trail is read by more people, and kept far longer, than the documents it describes, so it must prove what happened without becoming a second, less protected copy of the source.

**It opens, appends and closes per row.** Holding a file handle buffers away exactly the records you wanted, because the interesting runs are the ones that die halfway.

### The callback caveats

Both hooks are real, and both behave in ways the docs do not lead you to expect.

**`step_callback` fires on tool steps only.** It is called with an `AgentAction` before a tool runs and a `ToolResult` after. It is *not* called for a plain final answer in the text-ReAct path, so it is a record of what the crew **touched**, not of what it thought. That happens to be the half worth auditing. It can be set on the `Crew` or on an `Agent`; both work.

**The three shapes share no useful base class**, so `AuditLog.step` duck-types on the class name:

```
AgentAction   thought, tool, tool_input, text, result
ToolResult    result, result_as_answer
AgentFinish   thought, output, text
```

**`task_callback` fires once per finished task** with a `TaskOutput`, which is the natural place to hash the output.

## Gate 3 — Budget, and why it fights you

This is the gate that taught me the most, and it is the reason to read `governance.py` rather than skim it. It works in three layers because no single one of them is a cap.

**1. Caps up front — real.** `max_iter` and `max_execution_time`, set per agent. Verified: `max_iter=3` against a tool loop that never terminates stops it after 4 model calls. But note what it does **not** do — it does not raise. It forces a final answer out of the agent, so **a capped run returns something that looks exactly like a real answer and is not one.** That is why the summary prints the caps on every run.

**2. A tripwire during — blunt.** `Budget.step` reads live token counters off the LLM instances and raises `BudgetExceeded`. It does stop the run, but not politely: CrewAI's event listener swallows the first few raises, logs `Error executing listener`, and the run overshoots by a step or two. An emergency brake, not a thermostat.

**3. The truth after — a report, not a gate.** `crew.usage_metrics` is accurate and arrives far too late to control anything. A ceiling you only compare against once the money is gone is a report.

### Three things that will catch you out

All three are verified against 1.15.17, and all three make a naive budget guard worse than none.

**CrewAI retries a failed task.** `max_retry_limit` defaults to **2**, and a task that dies re-enters `execute_task`. So a tripwire that raises to save money gets run three times, and your cap costs *triple* what it was meant to save. `crew.py` sets `max_retry_limit=0` on every agent.

**CrewAI wraps your exception.** `_execute_with_timeout` turns anything a task raises into `RuntimeError("Task execution failed: ...") from e`. So `except BudgetExceeded:` around `kickoff()` **silently never matches** — and neither does `except EOFError:` when `human_input` has no terminal. `governance.find_cause()` walks the `__cause__` chain instead, which is boring, public, and does not break on upgrade.

**`usage_metrics` is `None` on a run that stopped.** It is only computed on successful completion, so the number you most want after a halt is precisely the one the framework does not give you. `Budget.reconcile()` falls back to the live counters and labels which source it used — that is the `(live)` vs `(usage_metrics)` tag in the summary.

### And one that will double your numbers

Token counters live on the **LLM instance** and are cumulative for its lifetime. `crew.usage_metrics` sums them per agent — so if two agents share one `LLM` object, that instance's total is counted **once per agent**. Verified: two agents, one shared instance, exactly 2x the real tokens.

```python
llm = LLM(model="gpt-4o-mini")
Agent(..., llm=llm)          # shared instance  -> usage_metrics double counts
Agent(..., llm=llm)

Agent(..., llm="gpt-4o-mini")  # a STRING -> CrewAI builds one instance per agent
Agent(..., llm="gpt-4o-mini")  #             and the totals are right
```

Passing a model string is the safe habit, and it is why `crew.py` does.

## Gate 4 — The human

`human_input=True` on the final task. CrewAI prints the draft, shows a **Human Feedback Required** panel, and blocks on `input()`. Enter alone accepts; any text is treated as a revision request and the agent goes round again, for as many rounds as you want.

It is on the *last* task deliberately. A gate in the middle interrupts work; a gate at the end reviews a result.

Now the honest part. This is **a person at a terminal, not an approval record.** Nobody can later prove who pressed Enter, when, or what they were looking at. `echo "" | python crew.py` satisfies it completely — which is exactly why the run that consumed a piped newline records `no_human_approval` and exits 3 rather than pretending. Real approval means a record a *different* person created, bound to the prompt version that was reviewed, and able to expire. That is the [companion repo's Gate 5](https://github.com/steviebuchicago/agents-are-easy-governance-is-hard), and CrewAI gives you none of it.

## What a run tells you

```
run           20260827T060705Z-d74f97
prompt        2026-01-15.1
tool calls    5/12
tokens        6,300/120,000  (usage_metrics)
model calls   7
elapsed       0.1s
audit         out/audit.jsonl  (20 events)
events        {'agent_step': 10, 'run_complete': 1, 'run_start': 1, 'run_summary': 1,
               'task_complete': 2, 'tool_denied': 1, 'tool_list': 1, 'tool_read': 3}
```

One `tool_denied` in a clean run is the allowlist doing its job on a path the model tried anyway.

## Try the refusals

```bash
CREW_MAX_TOOL_CALLS=2 python crew.py     # budget stops the run      -> exit 1
CREW_MAX_TOKENS=1000  python crew.py     # the other ceiling         -> exit 1
python crew.py < /dev/null               # nobody approved it        -> exit 3
```

Each one writes a `run_stopped` row naming the outcome before it exits. A scheduler should be able to tell "the gate said no" apart from "the code fell over", and both apart from success.

Watch the numbers on a budget stop: `tool calls 3/2` is honest about the overshoot, and the token count is tagged `(live)` because `usage_metrics` was never populated.

## What this still is not

One process on one machine. No shadow mode, no secret management, no log rotation, no alerting when refusals spike, and an "approval" that is a keystroke rather than a record. The tripwire overshoots. The audit log is a file anyone who can run the crew can also edit.

All real gaps. None of them changes the argument: the distance between example 02 and this one is not capability. Both produce the same analysis. This one can be asked about afterwards.

**Agents are easy. Governance is hard.** → [github.com/steviebuchicago/agents-are-easy-governance-is-hard](https://github.com/steviebuchicago/agents-are-easy-governance-is-hard)
