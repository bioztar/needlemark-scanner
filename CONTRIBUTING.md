# Contributing

Thanks for helping. A few rules keep the scanner small, auditable and safe to run on client
code.

- **Standard library only.** No runtime dependencies. `pytest` is the only test dependency.
- **Tests first.** Write the failing test first, then make it pass. Build fixture repositories
  in temporary directories (see `tests/conftest.py`) and use made-up names and data. Never
  commit real repository data, logs, reports or personal data.
- **Keep the privacy invariants.** Never render identities, contents or commit subjects. Add a
  new export field only to the explicit allow-list in `aems/export.py` /
  `aems/pack_export.py`. Respect k = 5 for any new breakdown (`aems/privacy.py`). Call
  `gh` with read verbs only.
- **Cite thresholds.** A new rule or threshold goes in `aems/data/*.json` with a rationale, a
  public source, a confidence and a review-by date. Mark design choices as design choices.
- **Small pieces.** Prefer small, pure functions and immutable data, and keep files under 400
  lines.
- **Conventional commits**, for example `feat: …`, `fix: …`, `docs: …`, `test: …`.

Run the suite before you open a pull request:

```bash
python -m pip install ".[test]"
python -m pytest -q
```

Report security issues privately. See [SECURITY.md](SECURITY.md).
