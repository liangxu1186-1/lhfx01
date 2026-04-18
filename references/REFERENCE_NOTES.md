# Reference Notes

## Scope

These repositories are local, read-only references for engineering guidance.

They are not the implementation base of this project.

Primary design source remains:

- [crypto-backtest-workbench-v1-implementation-design.md](/Users/liangxu/code/lhfx01/docs/crypto-backtest-workbench-v1-implementation-design.md)
- [REFERENCE_USAGE.md](/Users/liangxu/code/lhfx01/docs/REFERENCE_USAGE.md)

## Pinned References

### Freqtrade

- Path: `/Users/liangxu/code/lhfx01/references/freqtrade`
- Commit: `c1795c79f3fa8b762e98a7baee4daa5dd272e727`

Focus areas:

- project/module layout
- backtesting command flow
- strategy registration and strategy class shape
- configuration layering
- hyperopt workflow boundaries

Avoid importing into this project:

- bot lifecycle assumptions
- telegram / operational control layers
- live/dry trading semantics
- stop/limit logic outside this project's v1 boundary

### vectorbt

- Path: `/Users/liangxu/code/lhfx01/references/vectorbt`
- Commit: `993ceca7116fc8e55f4cd3a36fe43d83dab62b27`

Focus areas:

- portfolio / trades / drawdowns analysis objects
- parameter sweep organization
- vectorized experiment thinking
- result packaging for analytics

Avoid importing into this project:

- whole-framework inheritance
- license-sensitive code copying
- replacing local run manifest / feature artifact abstractions

## Practical Use Rules

When using Codex against these references:

1. Read references to learn structure, not to inherit framework identity.
2. Prefer small local re-implementations over copied code.
3. If a reference conflicts with local design, local design wins.
4. Keep this project's v1 boundary narrow:
   - no stop/tp
   - no limit order semantics
   - no live trading lifecycle
5. Use references mainly for:
   - naming
   - module boundaries
   - workflow decomposition
   - analytics object design

## Suggested First Look

### Freqtrade

- `freqtrade/optimize/`
- `freqtrade/strategy/`
- `freqtrade/data/`
- `freqtrade/commands/`

### vectorbt

- `vectorbt/portfolio/`
- `vectorbt/records/`
- `vectorbt/generic/`
- `examples/`

