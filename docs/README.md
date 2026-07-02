# Nodease Documentation

Status: Draft
Authority: Documentation Index
Source of Truth: Yes

This directory is the active documentation root for Nodease. When active docs conflict with `docs_old/`, use this `docs/` tree as the higher-authority documentation source.

## Core Documents

| Area | Document |
| --- | --- |
| Product requirements | [PRD.md](PRD.md) |
| Architecture and service boundaries | [architecture.md](architecture.md) |
| Data model and RBAC policy | [data_model.md](data_model.md) |
| Shared terminology | [glossary.md](glossary.md) |
| Design decisions | [decisions/](decisions/) |
| Feature requirements, API, components, tests | [features/](features/) |

## Authority Order

When documents conflict, use this order unless a newer accepted ADR or current code comparison explicitly overrides it:

1. Accepted ADRs in [decisions/](decisions/)
2. [PRD.md](PRD.md)
3. [architecture.md](architecture.md)
4. [data_model.md](data_model.md)
5. Feature `requirements.md`
6. Feature `api_spec.md`
7. Feature `component_spec.md`
8. Feature `test_cases.md`
9. `docs_old/` historical reference material

## Archive Boundary

`docs_old/` is a historical archive only. It may contain preserved metadata such as `Source of Truth: Yes` from before the documentation restructure, but that metadata is not current authority.
