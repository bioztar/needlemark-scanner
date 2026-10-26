"""Dimensions 2 (guides, feed-forward) and 3 (sensors, feedback)."""
from __future__ import annotations

import json
import re

from .attribution import is_fix_intent, is_test_path
from .model import Check, Commit, Evidence
from .repo_files import RepoFiles

PLAN_RE = (r"(^|/)(plans?|briefs|missions|roadmap|tasks)/|(^|/)(PLAN|PLANS|ROADMAP|TODO|TASKS|HANDOVER)[^/]*\.md$"
           r"|(^|/)docs/(plans?|design)/")
ADR_RE = r"(^|/)(adr|adrs|decisions)/|(^|/)docs/(adr|decisions)/"
SPEC_RE = (r"(^|/)(specs?|openspec|\.specify|prd|prds|rfcs?)/|(^|/)[^/]*\.spec\.md$|(^|/)(PRD|SPEC)[^/]*\.md$"
           r"|(^|/)(constitution|principles)\.md$")
SPEC_ARCHIVE_RE = r"(^|/)openspec/changes/archive/|(^|/)specs?/archive/|(^|/)(missions|plans)/(archive|done)/"
WORKFLOW_SKILL_RE = r"(^|/)\.?(claude|agents|codex|cursor)/(skills|commands|agents)/|(^|/)skills/[^/]+/SKILL\.md$"
GUIDE_TOUCH_RE = re.compile("|".join((PLAN_RE, ADR_RE, SPEC_RE)), re.I)

LINT_TYPE_RE = (r"(^|/)(\.eslintrc[^/]*|eslint\.config\.[cm]?[jt]s|biome\.jsonc?|\.prettierrc[^/]*|tsconfig[^/]*\.json"
                r"|\.flake8|ruff\.toml|\.ruff\.toml|mypy\.ini|\.mypy\.ini|pyrightconfig\.json|\.pylintrc|setup\.cfg"
                r"|\.golangci\.ya?ml|clippy\.toml|rustfmt\.toml|\.rubocop\.yml|\.stylelintrc[^/]*|deno\.jsonc?)$")
HOOK_RE = (r"(^|/)\.pre-commit-config\.ya?ml$|(^|/)\.husky/|(^|/)lefthook\.ya?ml$|(^|/)\.githooks/"
           r"|(^|/)\.lintstagedrc[^/]*$")
WORKFLOW_RE = r"^\.github/workflows/[^/]+\.ya?ml$|^\.gitlab-ci\.yml$|^\.circleci/config\.yml$|^Jenkinsfile$|^\.buildkite/"
TEST_CMD_RE = re.compile(
    r"\b(pytest|unittest|tox|nox|jest|vitest|mocha|playwright|cypress|go test|cargo test|"
    r"npm (run )?test|pnpm (run )?test|yarn test|bun test|make test|rspec|phpunit|dotnet test|"
    r"node --test|deno test|scripts/test)", re.I)
FITNESS_RE = re.compile(
    r"\b(stryker|mutmut|cosmic-ray|pitest|mutation|hypothesis|fast-check|proptest|quickcheck|"
    r"dependency-cruiser|import-linter|archunit|eslint-plugin-boundaries|madge|atheris|go-fuzz|cargo-fuzz|"
    r"jsfuzz|promptfoo|deepeval|evals?/)", re.I)
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "Cargo.toml",
             "go.mod", "Makefile", "setup.cfg", "tox.ini", "noxfile.py")


def _ev(label, items, source) -> Evidence:
    items = tuple(items)
    shown = ", ".join(items[:6]) + (f" (+{len(items) - 6})" if len(items) > 6 else "")
    return Evidence(label, f"{len(items)}" + (f": {shown}" if items else ""), source)


def guide_checks(files: RepoFiles, commits: tuple[Commit, ...]) -> tuple[Check, ...]:
    readme = files.matching_re(r"^README[^/]*$|^docs/")
    plans, adrs = files.matching_re(PLAN_RE), files.matching_re(ADR_RE)
    specs, archive = files.matching_re(SPEC_RE), files.matching_re(SPEC_ARCHIVE_RE)
    skills = files.matching_re(WORKFLOW_SKILL_RE)
    feats = tuple(c for c in commits if not c.is_merge and c.subject.lower().startswith("feat"))
    with_guide = sum(1 for c in feats if any(GUIDE_TOUCH_RE.search(p) for p in c.paths))
    share = with_guide / len(feats) if feats else 0.0
    return (
        Check(1, "README or docs present", bool(readme), (_ev("README/docs files", readme, "git ls-files"),)),
        Check(2, "Planning artefacts or ADRs checked in", bool(plans or adrs),
              (_ev("plan/handover files", plans, PLAN_RE), _ev("ADR/decision files", adrs, ADR_RE))),
        Check(3, "Spec-driven artefacts present", bool(specs), (_ev("spec/PRD/constitution files", specs, SPEC_RE),)),
        Check(3, "Spec or plan touched in >= 20% of feature commits", bool(feats) and share >= 0.20,
              (Evidence("feature commits with a guide artefact", f"{with_guide}/{len(feats)}",
                        "git log --numstat, subjects starting 'feat'"),)),
        Check(4, "Workflow skills/commands/agents defined", bool(skills), (_ev("skill/command/agent files", skills, WORKFLOW_SKILL_RE),)),
        Check(5, "Specs archived after apply (closed loop)", bool(archive), (_ev("archived change/spec files", archive, SPEC_ARCHIVE_RE),)),
    )


def _claude_hooks(files: RepoFiles) -> int:
    count = 0
    for rel in files.matching_re(r"(^|/)\.claude/settings\.json$"):
        text = files.read_text(rel)
        try:
            hooks = json.loads(text or "{}").get("hooks", {})
        except (json.JSONDecodeError, AttributeError):
            continue
        count += sum(len(v) for v in hooks.values()) if isinstance(hooks, dict) else 0
    return count


def ci_runs_tests(files: RepoFiles) -> tuple[bool, tuple[str, ...]]:
    flows = files.matching_re(WORKFLOW_RE)
    hits = tuple(w for w in flows if TEST_CMD_RE.search(files.read_text(w) or ""))
    return bool(hits), hits


def _text_hits(files: RepoFiles, paths: tuple[str, ...], rx: re.Pattern) -> tuple[str, ...]:
    return tuple(p for p in paths if rx.search(files.read_text(p) or ""))


def sensor_checks(files: RepoFiles, commits: tuple[Commit, ...]) -> tuple[Check, ...]:
    tests = tuple(p for p in files.paths if is_test_path(p))
    lint = files.matching_re(LINT_TYPE_RE)
    manifests = tuple(m for m in MANIFESTS if files.exists(m))
    lint_in_manifest = _text_hits(files, manifests, re.compile(r"\b(ruff|eslint|mypy|pyright|biome|prettier|black|flake8|tsc|golangci|clippy)\b", re.I))
    ci_tests, ci_files = ci_runs_tests(files)
    hooks = files.matching_re(HOOK_RE)
    agent_hooks = _claude_hooks(files)
    fitness = _text_hits(files, manifests + files.matching_re(WORKFLOW_RE), FITNESS_RE) + files.matching_re(r"(^|/)(evals?|golden|fuzz)/")
    fixes = tuple(c for c in commits if not c.is_merge and is_fix_intent(c.subject))
    fixes_with_tests = sum(1 for c in fixes if any(is_test_path(p) for p in c.paths))
    return (
        Check(1, "Tests or lint/type config present", bool(tests or lint or lint_in_manifest),
              (_ev("test files", tests, "path classifier"), _ev("lint/type configs", lint + lint_in_manifest, LINT_TYPE_RE))),
        Check(2, "Tests present", bool(tests), (_ev("test files", tests, "path classifier"),)),
        Check(2, "Lint, format or type checker configured", bool(lint or lint_in_manifest),
              (_ev("lint/type configs or manifest entries", lint + lint_in_manifest, LINT_TYPE_RE + " | manifests"),)),
        Check(3, "CI workflow runs tests", ci_tests, (_ev("CI workflows invoking a test command", ci_files, WORKFLOW_RE),)),
        Check(3, "Gate wired into the loop (pre-commit or agent hooks)", bool(hooks) or agent_hooks > 0,
              (_ev("pre-commit/husky/lefthook files", hooks, HOOK_RE),
               Evidence("agent hook entries", str(agent_hooks), ".claude/settings.json 'hooks' (tracked)"))),
        Check(4, "Fitness sensors: mutation/property/architecture/fuzz/evals", bool(fitness),
              (_ev("fitness sensor references", tuple(dict.fromkeys(fitness)), "manifests + workflows + eval dirs"),)),
        Check(5, "Regression discipline: >= 50% of fix commits add/touch tests (n >= 4)",
              len(fixes) >= 4 and fixes_with_tests / len(fixes) >= 0.5,
              (Evidence("fix commits touching tests", f"{fixes_with_tests}/{len(fixes)}", "git log --numstat"),)),
    )
