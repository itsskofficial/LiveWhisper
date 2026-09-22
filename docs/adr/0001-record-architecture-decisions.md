# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

LiveWhisper's behaviour rests on many measured choices - which model for which
language, what the formatter may change, what is never pasted. They were
recorded in code comments, commit messages and a long conversation, which is
where a new contributor cannot find them and where they cannot be superseded
cleanly.

## Decision

Significant decisions are recorded here as Architecture Decision Records, one
file each, numbered, in the format of [0000-template.md](0000-template.md). A
decision that changes is not edited away: a new record supersedes it, and the
old one's status says so. Every record names the evidence it rests on.

## Consequences

The why of the system is in one place and survives refactors. Code comments
still carry local detail and point here for the larger picture.
