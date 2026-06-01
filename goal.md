# Goal — RepairAgent on Defects4J (Java)

**Agent × Benchmark.** RepairAgent (AutoGPT-derived multi-state repair loop) on
**Defects4J 1.2/2.0**, denominator **113 bugs**. See the root index at
`/data/wangjian/wj_code/defects4c_dirs/.claude/CLAUDE.md` for the broader map.

**Target fix rate.** **57.5%** at `c40` (max 40 agent cycles per bug) — the cell
used for the *RA-D4J* row in the thesis tables:
- `tab:discuss-overview` / `tbl-agent-fix-rates` (`sec:agent-crosslang`)
- `tab:discuss-fail`     / `tbl-failure-phase`  (`sec:agent-failure`)
- `tab:discuss-scaling`  / `tbl-scaling`        (`sec:agent-scaling`)

**Architecture.** Agent runs natively on the host (`./venv/bin/python …`,
Python 3.11), edits Java files in `repair_agent/auto_gpt_workspace/`, and
delegates **every `defects4j` call** (checkout / compile / test / info) to the
shared **`defects4j_docker_web`** service over HTTP via
`repair_agent/d4j_client.py`. That workspace dir is the bind-mounted
`/workspace` inside the service container, so file edits and validation see the
same files. Set `DEFECTS4J_URL=http://localhost:<port>` (currently **8091**
because 8090 was taken; service `.env` controls the port).

The agent reads fault-localisation metadata locally from
`repair_agent/defects4j/`: `framework/projects/*/patches/*.src.patch` (copied
from the container with `docker cp defects4j1:/defects4j/framework`) plus
`buggy-lines/` and `buggy-methods/` (symlinked to repo-root `data/`).

**LLM.** Pluggable via `--model` (env `OPENAI_API_BASE_URL` for any
OpenAI-compatible host). RepairAgent uses the legacy `openai==0.27.8` API path
(also handles `claude-*` and now `deepseek-*` via the Anthropic provider).

**Run recipe** (one bug, smoke test):
```
cd repair_agent
export DEFECTS4J_URL=http://localhost:8091
./venv/bin/python repairagent.py run --bugs "Lang 1" --model <model> --max-cycles 5
```
Batch: `./run_on_defects4j.sh <bugs_file> hyperparams.json <model>`.

**Metric.** Sum of terminal "patch succeeded" statuses
(`final_status=plausible` + `patch_produced` + some `trigger_fail`), per
`analyze_d4c_results.py` — **not** the raw `trigger_pass` count. Match this when
re-aggregating; the 57.5% number maps to 65/113 plausible on disk.

**Status.** ✅ Reproduces (65 plausible confirmed). The earlier self-contained
`--docker` mode was replaced with the docker-web HTTP backend (this is the only
D4J folder of the three that needed that restructure).

**Sibling.** [`agent_apr_d4c/repairagent_selfcontainedqwen/`](../../agent_apr_d4c/repairagent_selfcontainedqwen/)
runs the same agent on Defects4C.
