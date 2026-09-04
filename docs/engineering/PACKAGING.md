# Observa Packaging & Distribution

## Goal

The intended end-user experience is:

```bash
pip install observa
```

without requiring users to install Rust manually.

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
