# Security policy

## Reporting a vulnerability

Please report vulnerabilities **privately**, through GitHub's private vulnerability reporting:
open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a
public issue, pull request or discussion for a suspected vulnerability.

Include the affected version or commit, a description, and the smallest reproduction you can
(for example a fixture repository built in a temporary directory). Please do not send real
repository data, credentials or personal data.

We aim to acknowledge a report within 5 working days and to agree a fix and disclosure date
with you. Credit is given in the advisory unless you prefer otherwise.

## Supported versions

Only the latest release receives security fixes.

## What counts

The scanner runs on a client's machine against their repositories. Its safety properties are
part of its contract. A way to break any of them is in scope:

- **Read-only.** It never writes to the scanned repository and never runs a program that the
  repository's own git configuration names (fsmonitor, hooks, external diff, textconv, pager).
- **Read-only GitHub access.** `gh` is only called with read verbs; write flags are refused.
- **No contents, no identities.** File contents, commit messages, line contents, names,
  emails, logins and vendor mappings never appear in a report or the export.
- **k-anonymity.** No breakdown cell backed by 1 to 4 people is shown.
- **Allow-listed export.** The numbers-only export holds only allow-listed fields.
- **Safe outputs.** Output is never written through a symlink.

Running the scanner on a repository you do not trust is supported. Running it with a
`vendors.json` you do not trust is not: login patterns in that file are regular expressions.
