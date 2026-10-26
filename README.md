# needlemark — AEMS scanner (T0/T1)

A thin, auditable scanner for the **Agentic Engineering Maturity Score (AEMS)**, a method for
rating how far a team's engineering system supports work done with coding agents (see
[Method](#method)). Point it at a local git repository and it writes a per-repo AEMS report as
JSON and as a self-contained HTML file. Portfolio mode scans a directory of repositories and
writes one summary table.

Python 3.11+, standard library only. It shells out to `git`, and to `gh` for read-only GitHub
evidence when `gh` is installed and authenticated.

## Install

```bash
pip install .          # installs the `aems` command; no third-party dependencies
aems scan <repo>       # same as: python -m aems scan <repo>
```

## Run it

```bash
python -m aems scan    <repo>  [--out aems-out] [--export] [--offline] [--window-days 180]
python -m aems portfolio <dir> --out <dir> [--export] [--offline]
python -m aems export  <repo>  [--out aems-out] [--keep-name] [--offline]
python -m aems scan    <repo>  --one-number [--offline]
python -m aems pack    <repo>  [--vendors vendors.json] [--out aems-out] [--offline]
                               [--keep-name] [--keep-vendor-names] [--allow-small-vendors]
python -m aems portfolio <dir> --out <dir> --pack [--vendors vendors.json] [--export]
```

`--one-number` is the free-scan teaser. It prints a single line, for example
`AEMS L1 (median L2) · VDR green` (overall weakest-link level, median level, VDR band), with no
repo name, path or ratio, and writes no files. It cannot be combined with `--export`.

| Output | File |
|---|---|
| Full local report | `<out>/<repo>.aems.html`, `<out>/<repo>.aems.json` |
| Portfolio | `<out>/portfolio.aems.html`, `<out>/portfolio.aems.json`, `<out>/repos/*` |
| Numbers-only export (schema `aems-export-4`) | `<out>/<repo-id>.export.json`, `<out>/portfolio.export.json`, `<out>/export/*` |

Tests use fixture repos built in temporary directories:

```bash
python3 -m pytest -q
```

## Method

AEMS rates an engineering system, not individual people. Each dimension sits on a ladder from
L0 to L5:

| Level | Name | In short |
|---|---|---|
| L0 | Ad hoc | agents used occasionally; nothing written down |
| L1 | Assisted | agents help individuals; instruction files and basic tests exist |
| L2 | Delegated | bounded tasks are handed to agents; review becomes the bottleneck |
| L3 | Harnessed | guides and sensors (tests, lint, CI, hooks) gate agent work, with outcome evidence |
| L4 | Orchestrated | several agents run in parallel lanes, with isolation and earned autonomy |
| L5 | Self-improving | the system measures itself and feeds the lessons back into its instructions and rules |

Evidence comes in four tiers. **T0** is the static contents of the repo: instruction files,
docs, test and CI configuration, governance files. **T1** is git and CI history. **T2** is
agent session logs. **T3** is a workshop plus production outcomes. This scanner reads T0 and
T1 only, so dimensions that need T2 are reported as *not assessed*.

The method rests on five design rules.

- **Evidence-graded.** Every level is a set of checks, and each check lists the path or command
  that produced its evidence. Nothing is inferred by a model.
- **Weakest link, not the average.** Gains in one stage do not pass through a slower one.
  Commits rose about 240% while releases rose about 30% (Demirer, Musolff & Yang, NBER w35275).
  So the overall score is the minimum across dimensions, shown with the median.
- **Outcome-anchored.** An artefact being present is not maturity. A level of 3 or above needs
  outcome evidence, such as low agent rework or green CI runs. Without it the level is capped at
  2 and labelled *presence, not maturity*. Instruction files can even hurt success rates
  ("Evaluating AGENTS.md", arXiv 2602.11988).
- **Verification is the bottleneck.** In high-AI teams, PR review time rose 91% and PR size 154%
  (Faros AI). For agents, review is where gains stall (Chen & Stratton 2026). The headline risk
  number is therefore the verification-debt ratio: agent change volume over verification
  capacity.
- **Dated advice.** Best practice in this field changes within months. Every recommendation
  cites a public source and carries a confidence and a review-by date.

## What it measures

There are nine dimensions (see [Method](#method)). Six are scored from tiers T0 and T1. The other three are
reported as **not assessed (needs T2 logs)**, with presence hints only.

| # | Dimension | Tier | Evidence the scanner reads |
|---|---|---|---|
| 1 | Context & instructions | T0 (+T1 for L5) | AGENTS.md, CLAUDE.md, GEMINI.md, `.cursorrules`, copilot-instructions; line counts (minimality); stale backtick path references; path-scoped rules; skills; MCP configs; instruction edits made in fix commits |
| 2 | Harness: guides | T0 + T1 | README and docs; plans and handovers; ADRs; specs, PRDs, OpenSpec and Spec-Kit artefacts; share of `feat` commits that touch a guide artefact; workflow skills; archived specs |
| 3 | Harness: sensors | T0 + T1 | test files; lint and type configs; CI workflows that invoke a test command; pre-commit, husky and agent hooks; mutation, property, architecture and fuzz tooling; share of fix commits that touch tests; **CI run conclusions** (`gh run list`) |
| 4 | Orchestration topology | hints | worktrees, subagent or crew definitions, loop scripts |
| 5 | Autonomy & review line | T1 | PR or merge share of first-parent changes; agent commits landed via PR; median PR or commit size; **PR review signals** (`gh pr list --state merged`, see below); autonomy-policy keywords; branch protection (`gh api`); CODEOWNERS |
| 6 | Verification & evals | hints | eval and golden directories, agent-reviewer configs |
| 7 | Memory & learning loops | hints | handover and memory files, retros, decision logs |
| 8 | Governance, security & cost | T0 | `.gitignore` covers `.env`; tracked secret-bearing files (by name); agent permission allow and deny lists; secret-scanning config; CODEOWNERS; attribution; secret-shaped string **counts** |
| 9 | Measurement | T1 | agent attribution; conventional-commit share; measurement artefacts and how often they are updated |

T1 proxies, all computed over a 180-day window by default:

- **Attribution.** An agent is identified from `Co-authored-by` trailers, bot authors (Claude,
  Devin, Copilot, Cursor, Codex, Jules, Gemini, Aider, Amp) or the "Generated with Claude Code"
  footer. Matching uses emails and bot logins, never display names. The result is a **lower
  bound**, because agent work committed without attribution cannot be seen.
- **Rework proxy.** An agent commit counts as reworked when a later
  fix/revert/hotfix commit touches one of the same *code* files within 30 days. Docs, manifests
  and lockfiles do not count as overlap. Only commits older than 30 days ("matured") enter the
  rate, and fewer than 5 matured commits is reported as `insufficient`. The human-only baseline
  is shown for context. It is biased low, because it contains unattributed agent work.
- **Review line.** First-parent changes are classified as merge commits, squash PRs (`(#N)`
  subject) or direct commits.
- **PR review signals** (dim 5 evidence and context for the VDR; read-only
  `gh pr list --state merged --limit 200 --json number,additions,deletions,createdAt,mergedAt,reviews,reviewDecision,author,comments`,
  filtered to PRs merged in the window):
  - *share of merged PRs with a formal review*: at least one review in state APPROVED,
    CHANGES_REQUESTED or COMMENTED by someone other than the PR author, or a reviewDecision of
    APPROVED / CHANGES_REQUESTED. A merged PR whose reviewDecision is `REVIEW_REQUIRED` was merged
    *without* the required approval, so it counts as unreviewed. DISMISSED and PENDING reviews do
    not count. Self-reviews are excluded after normalising `app/` and `[bot]` login spellings.
  - *PRs merged unreviewed*, and how many of those were agent-authored.
  - *median PR size* (additions + deletions; this is the PR size used for the batch-size check),
    *median time to merge* (hours, mergedAt − createdAt).
  - *review comments per PR* (mean): non-author conversation comments plus non-author review
    submissions, excluding non-agent bots. Inline diff comments are not in `gh pr list` output,
    so this is a lower bound.
  - PRs reviewed by a human vs. by an agent or review bot, and PR authors by class.
  PR authors and reviewers are reduced to classes (human / Claude / Devin / Copilot / Cursor /
  other agent / other bot / unknown) inside `aems/pr_review.py`; no login, name or comment text
  reaches the report or the export. With no GitHub remote, no `gh`, no auth, offline mode, a
  timeout or unparseable output, every PR signal reads **not observed** (never an error); a repo
  that is observed but merged no PRs reads **0 merged PRs**. The signals are evidence on the dim-5
  checks, plus one gate: with **at least 5 merged PRs** observed, dim 5 cannot reach L3 if any
  agent-authored PR was merged without a formal review (evidence: "agent PRs merged unreviewed:
  N of M", M = agent-authored merged PRs). With PR data not observed or fewer than 5 merged PRs
  the gate is not applied, so offline scans are not penalised. The VDR formula is unchanged: the
  share of merged-PR lines under a formal review is shown beside it as context, because adding it
  to capacity would double-count the PR-gated lines (G).
- **Batch size and churn.** Median and p90 lines per commit and per PR, the delete/add ratio,
  and the share of commits that touch a file changed in the previous 14 days.

## Query pack (`python -m aems pack`)

Three client-run, read-only, counts-only measures on top of the scan. `pack` writes the full
report (with a *Query pack* section) and the numbers-only export. It uses no LLM, only the
standard library, `git` and read-only `gh`. Thresholds live in the versioned
[`aems/data/pack_rules.json`](aems/data/pack_rules.json) (`pack-2026.10.1`), each with its
rationale and source.

Every figure is split by **author class**: *vendor* (matched by the local vendors file), then
*agent* (attributed agent work), then *human*. Non-agent bots are *other bot*. The order
matters: a vendor engineer's agent-assisted commit counts as *vendor*, so the vendor lens can
report that vendor's agent share.

**Q1 · Review timing.** Source: `gh pr list --state merged --json …,reviews,labels,mergeCommit`.
Each merged PR in the window gives:
- *open → first review*: the earliest formal non-author review (`submittedAt − createdAt`);
- *open → approval*: the earliest non-author APPROVED review;
- *approval per 100 changed lines*: approval hours ÷ (additions + deletions) × 100.

An approval is a **rubber stamp** when it came sooner than `max(60 s, lines ÷ 500 per hour)`.
The 500 lines-per-hour ceiling comes from the SmartBear/Cisco review study: defect detection
drops sharply beyond that rate
([case study](https://static1.smartbear.co/support/media/resources/cc/book/code-review-cisco-case-study.pdf),
[best practices](https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/)).
The 60-second floor is a design choice. Open → approval also includes waiting time, so the
rubber-stamp count is a lower bound. Medians and counts are reported by class.

**Q2 · Escaped-defect trace.** A *defect fix* is either of these:
- a commit whose subject is conventional `fix`/`hotfix`/`bugfix` or git's `Revert "…"`;
- the merge or squash commit of a merged PR linked to a bug, through a bug-like PR label, or
  through a closing issue with a bug label when the installed `gh` exposes
  `closingIssuesReferences`. Older `gh` falls back to labels, and the report says which was
  used.

For each fix, the scanner takes the lines the fix changed or removed (`git diff -U0`) and runs
`git blame` on the fix's parent to find the commits that last wrote them. Each fix counts as
one defect, split across those originating commits by share of blamed lines. The report gives:
- escaped defects within 30 and 90 days, and per 1K changed code lines, by originating class;
- the median escape age.

Only origins old enough to have had the full 30 or 90 days count, in both the numerator and
the denominator. Four kinds of fix are not counted as escapes:
- fixes that only add lines have nothing to blame and are reported as *untraceable*;
- a fix made on a branch to a commit from the same branch, before the merge, is *caught before
  merge*;
- a fix whose blamed origin is outside the window is reported in the totals only;
- fix subjects are a proxy, as for rework.

**Q3 · Vendor lens.** `--vendors vendors.json` is a client-local file:

```json
{"vendors": [{"label": "Acme Dev", "email_domains": ["acme.example"], "logins": ["^acme-"]}]}
```

Commits match on the author email domain or a GitHub noreply login. PRs match on the author
login, using a case-insensitive regex. For each vendor the lens reports:
- change volume (commits, code lines) and agent share;
- formal-review share and rubber-stamp rate of its PRs;
- 30-day rework rate;
- escaped defects per 1K lines within 30 and 90 days.

The mapping never leaves the client and is never written to a report. Vendor labels appear in
the client's own report. In the export they are salted hashes (set `AEMS_EXPORT_SALT`) unless
you pass `--keep-vendor-names`.

**Privacy.** The k = 5 rule applies, as everywhere else:
- A class breakdown with a human or vendor cell backed by 1–4 people is suppressed as a whole.
- Vendors with fewer than 5 people are pooled into one unlabelled row. If that pool still has
  fewer than 5 people, its numbers are suppressed, and so are the class breakdowns (otherwise
  the vendor-class total minus the visible vendor rows would reveal the pool).
- `--allow-small-vendors` lists every vendor by label. It prints a notice and records the
  override in the report and the export.

**Degrades gracefully.** If you are offline, have no `gh`, or have no GitHub remote, Q1 reads
*not observed* and Q2 runs from git alone (bug links *not observed*). With no vendors file, Q3
reads *not configured*.

## Scoring method

1. **Cumulative ladder.** A dimension sits at level *L* only when every check at levels 1..*L*
   is met. A gap stops the climb: a missing L2 check holds the dimension at L1 even if L3
   artefacts exist.
2. **Weakest link.** Overall = the **minimum** level across the six assessed dimensions, shown
   with the median. A team at L4 orchestration with L1 verification is in the autonomy trap and
   must not average to L2.5.
3. **Outcome cap.** A level of 3 or above needs outcome evidence. Without it, the level is
   capped at **2** and labelled *presence, not maturity*. The outcome evidence differs by
   dimension:
   - dims 1, 2, 5, 9: agent rework of 20% or less on at least 5 matured agent commits
   - dim 3: at least 5 decided CI runs in the window, with at least 70% success
   - dim 8: zero secret-shaped strings and zero secret-bearing files tracked
4. **Verification-debt ratio (VDR)** = A ÷ (T + G), measured in changed lines throughout.
   - A = non-test code lines changed by agent-attributed commits
   - T = test-file lines changed by any author
   - G = those A-lines that landed through a PR or merge while CI runs tests

   VDR ≤ 1 is green, ≤ 3 amber, > 3 red. When **fewer than 25% of commits are attributed**, A
   falls back to *total* change volume and the report says `low attribution coverage: X% of
   commits attributed`.

Thresholds such as 250 lines for "minimal", 20% rework, 70% CI success and 400-line batches are
design choices. They are named constants in the code and are restated in each report.

## Next three moves

[`aems/data/rules.json`](aems/data/rules.json) is a versioned and dated rule base
(`rules-2026.10.1`, dated 2026-10-26, quarterly review). Each rule has a condition, the move,
the rationale, the **public source** behind it, the expected effect, what *not* to do
yet, a confidence and a review-by date.

Selection works in four steps:
1. Headline rules go first. The VDR > 1 rule ("sensors before agents") is the only one.
2. The remaining rules are ordered weakest dimension first. Ties are broken by sensors →
   review line → measurement → context → governance → guides, because review is the
   bottleneck.
3. Within a dimension, a rule triggered by a condition (capped, stale references) comes before
   a rule triggered by level alone.
4. At most one move per dimension, and three moves in total.

## What it cannot see

- Agent work committed without attribution. Every AI share is a lower bound.
- Whether reviewers read diffs, and anything said in transcripts. Dims 4, 6 and 7 need T2 logs.
- Production incidents, usage and survival. These need a 90-day outcome join (T2/T3).
- Business value, team culture and fit to the use-case class (T3 workshop).
- Defects directly. Rework is inferred from commit intent and file overlap, so it is a proxy.
- Branch protection on private repos without the right plan or token scope. This is reported as
  "not visible", never as "absent".
- Inline diff review comments, PRs beyond the 200 most recently merged, and work that never went
  through a PR. A formal review proves a review was submitted, not that the diff was read.

## Data handling (zero-access design)

The client runs the scanner. Only derived numbers need to leave their environment.

- **No LLM or network calls on repository data.** Classification is rule-based: regexes on
  commit subjects (fix/revert/hotfix, conventional types), paths and trailers. It runs in
  memory and is never rendered. The only network calls are read-only `gh` metadata queries
  (`run list`, `pr list`, `issue list`, `repo view`, `api` GET). `--offline` disables them. The `gh` wrapper
  refuses any write flag (`-f`, `-F`, `-X`, `--input`).
- **No identities.** Author names and emails are used only to detect agents and bots. Reports
  show aggregated classes — *human*, an agent label such as Claude or Devin, and *other bot* —
  as counts.
- **k-anonymity (k = 5).** Any per-class or per-group breakdown with a cell backed by 1–4
  distinct *people* is replaced, as a whole, by `<5, suppressed`, in the full report and in the
  export. This covers commits by identity class and by agent tool, the human-only rework baseline,
  PR authors by class, and the human vs. agent reviewed split. A repo with one human author
  therefore never shows counts that describe that one person. The whole breakdown is suppressed,
  not just the small cell, because the total minus the visible cells would reveal it. Cells backed
  only by bots or agent apps (for example Devin-authored commits or PRs) describe no person and
  do not trigger suppression; agent-assisted commits authored by a person (a Claude co-author
  trailer) count that person. Repo-level totals stay: commits, agent commits, AI shares, agent
  rework, VDR and PR totals. Residual risk: the difference between two totals (for example commits
  minus agent commits) can still describe a small group. With the query pack and a vendors file, the
  same holds for the visible vendor rows: total PRs minus vendor and agent PRs is the in-house
  remainder, even when the human breakdown is suppressed. People are counted in memory with a
  per-run salted hash of the author email that is never stored, rendered or exported; scores and
  levels are computed from totals and are unaffected by suppression.
- **No contents.** Commit bodies are never loaded: the footer is detected with
  `git log --grep`, which returns hashes. Commit subjects are classified in memory and never
  rendered. File contents are never rendered. Files whose names mark them as secret-bearing
  (`.env*`, keys, credential and token stores, `settings.local.json`) are never opened. Secret
  detection counts pattern-family matches and never stores or prints a match.
- **Read-only on the scanned repo.** `GIT_OPTIONAL_LOCKS=0` is set on every git call, and the
  scanner only lists tracked files.
- **Two output levels.**
  - The full local HTML/JSON is for the client's own use. It may list file paths, which are the
    evidence behind each check.
  - The **export** (`python -m aems export` or `--export`) is built from an explicit allow-list
    of fields: levels, ratios, counts, status values, agent classes and rule ids. It has no
    paths, subjects, names, remote slugs, branch names or workflow names. The repo name is
    replaced by `sha256(salt + name)[:12]`; set `AEMS_EXPORT_SALT` so the id cannot be guessed,
    or pass `--keep-name` to keep the name.

## Sources

The rule base ([`aems/data/rules.json`](aems/data/rules.json)) and the query-pack thresholds
([`aems/data/pack_rules.json`](aems/data/pack_rules.json)) cite these public works. Each rule
names its own source.

- Demirer, Musolff & Yang, "Writing Code vs. Shipping Code", NBER Working Paper 35275 — <https://www.nber.org/papers/w35275>
- Faros AI, "The AI Productivity Paradox" (2025)
- Chen & Stratton, "Artificial Intelligence in the Firm: Bottlenecks in Software Production" (Harvard, 2026)
- METR, "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity" (2025)
- Stanford Software Engineering Productivity research — <https://softwareengineeringproductivity.stanford.edu>
- DORA, "State of AI-assisted Software Development 2025" and the AI Capabilities Model
- GitClear, "AI Copilot Code Quality" (2025) and follow-ups (2026)
- Thoughtworks Technology Radar (April 2026): harness engineering, feedback sensors, measuring collaboration quality
- GitLab, AI-Native Engineering Playbook (maturity ladder)
- "Evaluating AGENTS.md" — <https://arxiv.org/abs/2602.11988>
- "Agent READMEs" — <https://arxiv.org/abs/2511.12884>
- Tang et al., "Programming by Chat" (ASE 2026) — <https://arxiv.org/abs/2604.00436>
- Baumann et al., "SWE-chat: Coding Agent Interactions From Real Users in the Wild" — <https://arxiv.org/abs/2604.20779>
- Yu et al., "Habituation at the Gate" — <https://arxiv.org/abs/2606.22721>
- TraceProbe — <https://arxiv.org/abs/2607.06184>; "Beyond Resolution Rates" — <https://arxiv.org/abs/2604.02547>
- PRDBench — <https://arxiv.org/abs/2510.24358>
- "AI IDEs or Autonomous Agents?" — <https://arxiv.org/abs/2601.13597>
- GitHub Spec-Kit — <https://github.com/github/spec-kit>; OpenSpec
- SmartBear / Cisco code review case study (Cohen, *Best Kept Secrets of Peer Code Review*, 2006) — <https://static1.smartbear.co/support/media/resources/cc/book/code-review-cisco-case-study.pdf>
- SmartBear, "Best Practices for Code Review" — <https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/>

## Layout

| Module | Role |
|---|---|
| `aems/runner.py` | read-only `git`/`gh` subprocess wrappers with timeouts |
| `aems/history.py`, `aems/attribution.py` | commit loading, agent/bot/intent/path classification |
| `aems/metrics.py` | rework, VDR, flow, attribution, batch and churn (pure functions) |
| `aems/static_*.py`, `aems/t1_dims.py` | per-dimension checks and outcome checks |
| `aems/pr_review.py` | PR review signals and PR author classes (pure functions) |
| `aems/scoring.py` | ladder, cap, weakest link |
| `aems/recommend.py`, `aems/data/rules.json` | next-three-moves engine |
| `aems/render*.py`, `aems/portfolio.py`, `aems/export.py` | HTML, portfolio and numbers-only export |
| `aems/pack.py`, `aems/review_timing.py`, `aems/escapes.py`, `aems/escape_trace.py`, `aems/vendor_lens.py`, `aems/vendors.py`, `aems/pack_*.py`, `aems/data/pack_rules.json` | query pack (Q1-Q3) |

