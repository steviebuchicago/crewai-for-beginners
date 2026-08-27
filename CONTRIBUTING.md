# Contributing

Contributions are welcome, and one kind is worth more than the rest.

## The most useful thing you can send

**An error you hit that [docs/02-troubleshooting.md](docs/02-troubleshooting.md) does not cover.** Open an issue with the traceback, the CrewAI version, and the smallest code that reproduces it. That file exists because somebody lost an afternoon to each entry, and every addition saves the next reader the same afternoon. A pull request adding the entry yourself — symptom, one-sentence cause, fix with code — is better still.

Corrections are equally welcome. If something here is wrong, or was true in 1.15 and is not true now, say so. This repo's whole claim is that it was verified by running it, and that claim expires.

## If you are adding or changing an example

**Keep it runnable with one LLM key and nothing else.** No search-API signups, no vector databases, no cloud accounts. A beginner should be able to export one key and run. If your example needs data, put it in a local `knowledge/` folder the way [example 02](examples/02-research-crew/) does.

**Run it before you send it**, against the version pinned in `requirements.txt`, and say in the PR which version you used. If you change what a README claims about CrewAI's behaviour, show the output you got.

**Match the tone.** Comments explain *why* a parameter is there, not what the line does. Where the framework gives you a real control, use it and say so; where it does not, document the gap rather than papering over it.

## No real-firm content

Every company, supplier and figure in this repo is invented. Northgate Supply, Lakeshore Print and Ridgeline Logistics do not exist, and that is deliberate. Do not contribute anything naming a real firm, person or client engagement — not in an example, not in a knowledge file, not in a comment. Need a fourth fictional company? Invent one in the same register.

And no API keys, no `.env` files, no logs with real data in them.
