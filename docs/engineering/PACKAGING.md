# Observa Packaging & Distribution

## Goal

The intended end-user experience is a `pip install` of **this project's**
published package.

> ⚠️ **Namespace warning (open decision):** the public PyPI distribution name
> `observa` is already occupied by an unrelated project. Until a unique public
> namespace is chosen, the private MVP is installed from a built wheel
> (`pip install observa-0.1.0-<tag>.whl`), never via the bare `pip install
> observa`. The public distribution namespace must be unique before any PyPI
> release.

The engine is Rust but end users must never need to install Rust manually.

## Historical state

The original roadmap placed pip packaging in v1.0 and identified maturin + GitHub Actions as the expected path.

## Current product proposal

Because installation friction directly affects whether a new user can try the MVP, engineering leadership proposes moving pip packaging into MVP.

## Expected responsibilities

- Python packaging metadata.
- Maturin integration for the Rust/Python extension.
- Platform-compatible wheel builds.
- GitHub Actions release pipeline.
- Clean-environment installation tests.
- Versioning and changelog generation.

## Release rule

No package should be described as supported until installation has been verified on the intended support matrix.

## Important limitation

The exact supported operating systems, Python versions, architectures, and wheel strategy were not finalized in the source knowledge base. Those are release-engineering decisions still to be researched and approved.
