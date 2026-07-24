# Security Review Findings Tracker

Status: Template. No independent security review or penetration test has been
commissioned or performed yet.

This document is scaffolding only. It exists so that when Phase 7 of
[REMAINING_TO_100_PERCENT_TASKLIST.md](REMAINING_TO_100_PERCENT_TASKLIST.md)
("Independent Security Review And Penetration Test") actually starts, there is
a ready-made place to triage, track, and close findings without having to
design a process under time pressure.

Do not treat any content below as evidence that a review has happened. The
findings table starts empty. The sign-off matrix starts blank. Phase 7 remains
fully open until a real external reviewer or pentest provider produces
findings, those findings are resolved or triaged here, and every sign-off row
is filled in with a real name, date, and decision.

## How To Use This Document

1. When an independent security review or penetration test is commissioned,
   record the engagement (vendor/reviewer, scope, start date, report date) in
   a short preamble above the findings table.
2. As findings arrive, add one row per finding to the table below. Do not
   summarize or merge findings across components.
3. Apply the severity-to-SLA mapping to decide whether a finding blocks
   release.
4. Keep the table current until every row is `Resolved`, `Accepted Risk`, or
   `Won't Fix` with a documented owner and rationale.
5. Only complete the sign-off matrix after the table has zero open
   critical/high findings and every medium/low finding has an owner and
   deadline.
6. Do not check off any Phase 7 item in
   `docs/REMAINING_TO_100_PERCENT_TASKLIST.md` based on this document alone.
   That file is owned separately; this tracker only supplies the evidence it
   would eventually point to.

## Findings Table

| ID | Title | Severity | Component/Surface | Status | Owner | Deadline | Evidence Link |
| --- | --- | --- | --- | --- | --- | --- | --- |
| _(none yet)_ | | | | | | | |

Column definitions:

- **ID**: Stable finding identifier from the reviewer's report (e.g.
  `PEN-2026-001`). Keep the reviewer's own numbering if they provide one.
- **Title**: Short finding name, matching the source report.
- **Severity**: One of `Critical`, `High`, `Medium`, `Low`, `Informational`.
- **Component/Surface**: One of `cloud API`, `admin portal`, `public portal`,
  `local API`, `MCP integration`, `extensions`, `sync`. Use the closest match;
  add a second surface in parentheses if a finding spans more than one.
- **Status**: One of `Open`, `In Progress`, `Resolved`, `Accepted Risk`,
  `Won't Fix`, `Duplicate`.
- **Owner**: Named individual accountable for resolution or triage decision.
  Never leave blank once a finding is past initial intake.
- **Deadline**: Target resolution or triage date. Required for every
  `Critical`/`High` finding immediately, and for `Medium`/`Low` findings once
  triaged.
- **Evidence Link**: Path or URL to the fix commit, PR, test, or documented
  risk-acceptance record that closes the finding.

## Severity-To-SLA Mapping

- **Critical / High**: Must block release. No `Critical` or `High` finding
  may remain `Open` or `In Progress` at the exit gate. Every `Critical`/`High`
  row must end as `Resolved` with an evidence link, or the release does not
  ship.
- **Medium / Low**: Must be triaged with a named owner and a deadline. Triage
  means an explicit decision (`Resolved`, `Accepted Risk`, `Won't Fix`, or a
  scheduled `In Progress` fix) is recorded; `Medium`/`Low` findings do not
  block release once triaged, but an untriaged `Medium`/`Low` finding (no
  owner, no deadline, no status) does block the Phase 7 exit gate.
- **Informational**: Logged for awareness only. No owner or deadline required
  unless it is later reclassified.

## Sign-Off Matrix

Final cross-functional sign-off, required once the findings table shows zero
open critical/high findings and every medium/low finding is triaged with an
owner and deadline. Every row below is currently blank pending a real review.

| Function | Name | Date | Decision |
| --- | --- | --- | --- |
| Engineering | | | |
| Security | | | |
| Operations | | | |
| Product | | | |
| Legal | | | |

`Decision` should be recorded as `Go`, `No-Go`, or `Go With Conditions` (list
the conditions in the Evidence Link column of the relevant findings, not
here).
