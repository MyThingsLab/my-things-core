# mythings-core — agent instructions

You are developing **mythings-core**, the SDK every MyThingsLab tool imports —
**not** a My[X] tool itself. It provides the five contracts (`ledger`, `policy`,
`engine`, `github`, `isolation`) and build tooling (`_devledger`, `_harness`).

The build harness lives here canonically: the agent checklist is
[`src/mythings/harness.md`](src/mythings/harness.md) and the rationale +
enforcement map is [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md). Obey them.

Core-specific rules:
- Keep the runtime package **dependency-free**.
- The public API (`__all__`) is **contracts only**. `_devledger` and `_harness`
  are build tooling — never add them to `__all__`.
- No docstrings; the *why* lives in `docs/ARCHITECTURE.md`, `docs/CONVENTIONS.md`,
  and `docs/PROVENANCE.md`.
- Editing `src/mythings/harness.md` changes **every** tool: update it here, then
  re-vendor the `HARNESS.md` copy in each tool. A drift-check test in each tool
  fails CI if they diverge.
