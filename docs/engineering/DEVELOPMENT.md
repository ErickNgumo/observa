# Observa Development

## Coding philosophy

### Rust

- Explicit over implicit.
- `Result<T, E>` and `thiserror` for recoverable errors.
- No production panics unless there is a justified exception.
- Keep public APIs minimal.
- Public structs/functions should have documentation.
- Tests live close to the implementation where practical.

### Python strategies

- Plain dict-based API.
- No external strategy dependencies for the MVP contract.
- Class-based strategy interface.
- Use position tickets for targeted closes.

### JavaScript

The historical project uses vanilla JavaScript with no npm build step and a dependency-sensitive script load order. TradingView v5 APIs are used.

## Workflow

1. Define the problem in plain language.
2. Decide whether it belongs in MVP.
3. Define the contract and acceptance criteria.
4. Design the smallest implementation consistent with architecture.
5. Implement with tests.
6. Review architectural and financial implications.
7. Run the complete applicable test suite.
8. Update affected documentation.
9. Commit a coherent milestone.

## Bug rule

Every bug should first become a reproducible test or fixture, then be fixed, then remain covered by regression testing.

## Documentation authority

Code is runtime ground truth. Documentation must never knowingly describe interfaces that no longer exist.
