# Wayfinder Local Tracker

This repo has no external issue tracker, so the wayfinder map and its tickets live here as Markdown files, alongside the code they plan. (The repo does have a GitHub remote — `xueyouchao/mlops-demo`. Keeping the map in-repo is deliberate, matching the sibling WellPlannerEye effort; moving to GitHub issues later means re-creating the map as an issue labelled `wayfinder:map` and wiring native blocking.) The conventions below define how the wayfinder operations map onto this layout. Refer to every ticket **by its title** (linked), never by a bare id, in anything the human reads.

## Layout

- `MAP.md` — the wayfinder map (label `wayfinder:map`). The single canonical index; decisions live in tickets, the map only gists and links.
- `tickets/TNN-<slug>.md` — one ticket per file, a child of the map. The `TNN` id is the ticket's identity.

## Ticket frontmatter

```yaml
---
id: TNN                      # stable id, used for blocking references
title: <human-readable name> # the ticket's name — link it by this
labels: [wayfinder:<type>]   # research | prototype | grilling | task
status: open                 # open | closed
assignee: ""                 # empty = unclaimed; setting it IS the claim
blocked-by: []               # ticket ids; unblocked when all are closed
---
```

Because tickets are files rather than tracker records, blocking can be written in the same pass that creates them — the reference's "second pass" exists only because issue trackers need ids before they can reference each other.

## Semantics

- **Frontier**: tickets that are `open`, have every `blocked-by` id closed, and an empty `assignee`. The takeable edge of the known.
- **Claim first**: set `assignee` before any work on a ticket, so concurrent sessions skip it.
- **Resolve**: append a `## Resolution` section to the ticket body (the answer plus links to any assets), set `status: closed`, then append one gist line to the map's `## Decisions so far`, linking the ticket by name.
- **Research findings** are never pasted into tickets or the map. They live as a single Markdown file on a throwaway `research/<slug>` branch; the ticket's resolution points at the branch and path (read with `git show research/<slug>:<path>`). Local convention for the path is `docs/research/<slug>.md`. Research branches are throwaway — never merged, never pushed.
- **Fog graduation**: when a resolution makes a `## Not yet specified` item specifiable, create the ticket, wire its blocking edges, and remove the item from the map's fog section. Work ruled beyond the destination is recorded under `## Out of scope` instead — close the ticket, leave one line there.
- **Concurrency**: other sessions may edit this tracker concurrently. Commit small and often; claim before work; never resolve more than one ticket per session (research tickets excepted).

## Ticket types

- `research` (AFK) — resolved by a background research agent; findings on a throwaway branch.
- `prototype` (HITL) — a cheap, rough artifact for the human to react to; deliberately throwaway.
- `grilling` (HITL) — one-question-at-a-time conversation with the human, via `/grilling` + `/domain-modeling`.
- `task` (HITL or AFK) — manual work that unblocks a decision; resolved when the work is done.
