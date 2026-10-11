# Producer postcompile digest-sharing investigation

The [initial full-Harness cold profile](../benchmarks/harness-full-app-source-edit-initial-cold-profile.json)
verified 4,997 captured files, 1,145 compiler requests and 1,237 Cargo units.
The final executable producer spends 66.419639s executing the compiler,
3.184994s in postcompile storage, 0.230052s staging input snapshots and
0.068585s collecting linked inputs. Its total is 69.946907s. These nested
observations cannot be added to project time or turned into a promised saving.
The full traced source-edit sequence remains running, and its fresh-output and
revert gates are pending.

`compiler.save` collects each direct Rust dependency root separately. Every call
creates a fresh metadata resolver seeded with the directly validated inputs;
additional transitive digests discovered in one root walk are discarded before
the next. This is a candidate source of repeated work, not a measured attribution
of all 3.184994s.

A private prototype shares only those fresh digest/file-state maps across root
walks within the same successful entry construction. Each reuse still validates
file state, each root retains its own metadata classification and directory
guards, and the maps are discarded after that entry. It is default-off and
unbuilt; production is unchanged. Initial build/unit/executable smoke validation
is queued after the current diagnostic sequence. That validation alone will not
justify adoption.

Require an actual multi-root shared-transitive-input fixture, mutation/revert and
preserved-mtime replacement checks, failures/corruption/concurrency gates, and an
isolated replay of the captured final request. Compare both controls using the
same binary and flags with the experimental setting toggled, ensuring real
postcompile misses and identical dependency/output manifests. Then run repeated
alternating full-Harness comparisons against frozen Nano and kache, followed by
independent confirmation. Reject unknown coverage, changed outputs or repeatable
regressions. The shared-edit loss still has no established cause.
