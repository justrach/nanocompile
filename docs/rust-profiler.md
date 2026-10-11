# Rust build profiler

`tools/rust_profile.py` turns Cargo `--timings` reports into a critical path and a what-if schedule. Use it to rank changes by **estimated wall-time effect** instead of by summed request intervals, which overlap and cannot be added.

## Capture

```sh
# Any benchmark run can keep its Cargo timing reports (small report-writing overhead):
python3 tests/project_comparison.py ... --cargo-timings
python3 tests/project_pair_comparison.py ... --cargo-timings
python3 tests/harness_full_source_edits.py ... --cargo-timings

# Full dependency graph for the same command (stable toolchains; no build is run):
python3 tools/rust_profile.py unit-graph --cwd /path/to/project --output graph.json -- \
  cargo build --release --locked --offline --bin harness -p harness -j 8
```

Cargo numbers units the same way in `--timings` and `--unit-graph` for one resolved build. The profiler checks unit count, features and mode before joining them. Without a graph it falls back to Cargo's "unblocked" edges, which record only the last dependency to finish. That is enough for an observed critical path but makes what-if estimates optimistic.

## Commands

| Command | Answers |
| --- | --- |
| `path TIMING` | Which chain of units ends the build, and how much of it was waiting for a job slot? |
| `simulate TIMING --scale REGEX=FACTOR` | What would the wall time be if these units (or a category such as `build-script-run`) were faster? |
| `diff BASELINE CANDIDATE` | Which unit categories and units explain the wall-time gap between two builds? |
| `phases CAPTURE...` | Which Nano request kinds and compiler/script phases use the most wrapper time and CPU? For the slowest requests: context switches, page-ins, block reads, free jobserver tokens, and the frontend/codegen split. |
| `study REPORT --state DIR` | For a whole benchmark run kept with `--cargo-timings`: median wall time and slot time per category for each implementation and phase, plus the median simulated wall effect per category across all Nano/competitor pairs. |
| `trace TIMING --output trace.json [--simulated]` | A Chrome/Perfetto trace of the observed or simulated schedule, one lane per job slot, with critical-path units tagged. |

The simulator replays Cargo's list scheduling on `--jobs` slots. A unit becomes ready when every dependency has finished, or, for pipelined library dependencies, has emitted metadata. The ready unit with the most transitive dependents runs first. Cargo's pre-build resolution offset is taken from the report. `--spawn auto` (the default) calibrates a fixed per-unit spawn latency so the simulated baseline matches its observed wall time. The candidate's error under that calibration is printed as a model check.

`diff` substitutes the candidate's durations into the baseline's graph, one category or unit at a time, and re-simulates. Positive numbers mean the candidate is faster. The output also shows each category's summed unit delta, so you can see when a large summed difference has little wall effect.

## Validation

`python3 tests/rust_profile_test.py` checks pipelined scheduling, slot priority, inferred and observed critical paths, diff attribution, calibration and graph mismatch rejection on synthetic builds.

On nine real full Harness builds from the matched warm profile (three ~180 s cold builds and six 6.5–9.3 s warm builds), the uncalibrated model is within 0.2–0.6% on cold builds and 1.4–4.3% on warm builds. Calibration fits 0.9–1.9 ms of per-unit spawn latency. Simulating kache's warm build with spawn latency calibrated on Nano's warm build lands within 1.0% of kache's observed wall time.

## What it showed for Harness warm builds

The first diff of a Nano warm build (7.77 s) against a kache warm build (6.53 s) showed that warm builds are **throughput-bound**: 6.35 s of the 7.77 s critical path is waiting for one of eight job slots. No single request decides the result. Nano used 52.1 s of slot time against kache's 42.4 s:

| Category (units) | Summed unit delta | Estimated wall effect |
| --- | ---: | ---: |
| build-script runs (138) | +4.53 s | +0.57 s |
| libraries (991) | +3.26 s | +0.46 s |
| final binary (1) | +0.28 s | +0.28 s |
| build-script compiles (107) | +1.57 s | +0.20 s |

`phases` on the same captures attributed the overhead to repeated full input and output re-hashing (`restore.input_validation`, 8.5 s across 1,099 hits) and four live process spawns per linking request for Apple tool selection (`producer.apple_selection`, about 23 ms × 154). Nano also used 25 s of CPU on Rust requests against kache's 12 s. Those findings motivated the [digest and selection memos](digest-memo.md).

## Hill-climbing loop

1. Run the comparison with `--cargo-timings`.
2. Use `study` to find the category with the largest positive wall effect for the competitor.
3. Use `diff` on one representative pair to find the units behind it.
4. Use `phases` on a traced capture to find the Nano stage inside those units.
5. Use `simulate --scale` to estimate the payoff of a fix before building it.
6. Implement the fix, then rerun step 1.

Each round of this loop on Harness produced the next change: build-script runs, then Apple selection, then installed-tree memos, then contract parsing. The same loop also explained the source-edit result. `diff` placed kache's whole shared-edit lead on one `harness-ui` compile. `phases` on a traced reproduction showed Nano's own work adding only 0.26 s to it. The [wait diagnostics](#wait-diagnostics) then located the rest: a frontend stall waiting for the system's assessment of freshly restored proc-macro dylibs (see [the results](nano-vs-kache-memo-results.md#why-the-shared-edit-was-a-loss)).

## Wait diagnostics

Captured requests (`tools/build_capture.c`) also record:

- the child's page-ins, block reads and writes, and voluntary and involuntary context switches
- the jobserver tokens left free in Cargo's pipe or FIFO, sampled every 50 ms without consuming any
- when each output stream chunk arrived

`phases` uses the arrival of the compiler's `rmeta` artifact notification to split a compile into frontend (until metadata) and codegen. A request whose wall time grows while its CPU time, faults and free tokens stay the same is waiting on something outside the compiler. The frontend/codegen split shows where that wait sits.

This is how the shared-edit loss was found. The slow `harness-ui`, `harness-preview` and `harness-adapters` compiles each had a fixed 2–4 s added to the frontend, while codegen time, CPU, faults and free tokens were unchanged. That matched the system's serialized first-load assessment of restored proc-macro dylibs (see [code assessment](code-assessment.md)).

## Limits

The model ignores jobserver tokens used inside rustc, variance in process spawn time, filesystem cache state and host contention. Treat estimates as a way to rank and pre-screen ideas. Every claimed win still needs repeated untraced alternating builds.
