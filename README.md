# AETHRON
### Discover. Reason. Validate. Report.

AETHRON is an isolated-lab autonomous security assessment prototype built around a strict principle: **the agent may reason, but deterministic policy code authorizes every action**.

## What is implemented
- Editorial, oxblood-themed assessment console (Bodoni Moda / Manrope / IBM Plex Mono / Cormorant Garamond).
- FastAPI service with SQLite persistence for assessments, events, hosts, services, and findings.
- Scope-file parser for IPv4 addresses, CIDRs, and explicit hostnames; every requested target is checked before execution.
- Nmap TCP connect/service discovery adapter. No arbitrary shell tool, exploit payloads, credential attacks, or out-of-scope pivoting.
- Agent loop that observes discovery output, asks Bifrost for a constrained next-step proposal, validates it against a fixed action schema, and executes only approved actions.
- Tavily integration for post-discovery defensive remediation research, never for target discovery or authorization.
- Evidence-backed findings and Markdown report export.
- Demo mode with synthetic lab data, clearly labelled as simulated.

## Safety boundary
Use only on systems you own or have explicit written authorization to assess. The supplied lab must be isolated. AETHRON does not implement arbitrary command execution or automatic lateral movement. Multi-host movement is not enabled by this starter: it must be explicitly scoped and separately implemented with a narrow, auditable action adapter before judging.

## Requirements
- Python 3.11+
- Nmap installed and available on PATH for live discovery
- Optional: Bifrost endpoint/key and Tavily API key

## Run
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000

## Configure integrations
`BIFROST_BASE_URL` should be the OpenAI-compatible chat-completions base URL exposed by your Bifrost deployment (often ending in `/v1`). `BIFROST_API_KEY` and `BIFROST_MODEL` are deployment-specific. If absent, the agent uses a deterministic local planner; the UI makes the mode visible.

`TAVILY_API_KEY` enables retrieval of defensive remediation references after a finding is recorded. Tavily is not used to scan targets, and no target IP is sent to it.

## Scope file format
Plain text, one entry per line. Supports IPv4 addresses, CIDRs, and explicit hostnames. Blank lines and `#` comments are ignored.

Example:
```text
# isolated local lab only
192.168.56.10
192.168.56.0/28
lab-web.local
```
A target must be present in the supplied scope file. A hostname is accepted only when explicitly listed; DNS resolution is not used to expand authorization.

## Current limitations (intentional)
- Discovery uses Nmap TCP connect scans with service/version detection. UDP, OS fingerprinting, exploitation, credential testing, and lateral movement are not implemented.
- The LLM is a planner, not an executor. It can choose only from the narrow action catalogue in `app/agent.py`.
- CVE matching is not inferred from banners alone. Findings remain observations until validated with reliable evidence.
- The judging lab's actual scope format, target interface, and objective protocol are not included in the supplied statement. Add a lab-specific adapter once the organizer provides those details.

## Project layout
```text
app/
  main.py          FastAPI routes and lifecycle
  config.py        environment configuration
  database.py      SQLite persistence
  models.py        request/response models
  scope.py         deterministic scope enforcement
  scanner.py       Nmap adapter
  agent.py         constrained autonomous loop + Bifrost
  intelligence.py  Tavily remediation research
  reporting.py     Markdown report generation
  templates/       console shell
  static/          visual system and client interactions
examples/          sample scope
 tests/            policy tests
```
