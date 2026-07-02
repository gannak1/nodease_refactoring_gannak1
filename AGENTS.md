# AGENTS.md

## Project Context

This repository contains the mbased project. Use the documentation under `docs/` for project-wide context and `docs/features/` for feature-level requirements, API contracts, UI/component behavior, and tests.

## Documentation Rules

- Keep product-wide decisions in `docs/`.
- Keep feature-specific details in `docs/features/<feature-name>/`.
- Do not redefine shared terms (e.g. Organization, Workflow, Agent, Knowledge) in feature docs; link to `docs/glossary.md` instead.
- Doc meta blocks carry `Status` only (plus `Related Features` in `requirements.md`). Do not add `Owner` or `Last Updated` lines; git history already answers who and when.
- Docs that make claims about code (`api_spec.md`, `component_spec.md`, `test_cases.md`, `docs/data_model.md`, `docs/architecture.md`) carry a `Verified Against: <branch> @ <commit>` line. Update it only after actually checking the doc against the code at that commit — never as a side effect of editing the doc. `TBD` means not yet verified.
- Update related feature docs when changing behavior, APIs, UI flows, permissions, or test expectations.
- Prefer concise, testable statements over broad descriptions.

