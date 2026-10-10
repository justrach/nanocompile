# Current cold graph profile

The selected-resource implementation uses one decoder identity across 143 full compilation identities. A fresh diagnostic capture records 32 resolver queries, down from 264 in the prior schema-4 capture, while all 5,025 inspections remain. Full mutable-input hashing and selection validation remain enabled. Query counts support the reuse mechanism; elapsed diagnostic samples across sessions are not a controlled performance comparison.

| Component | Count / aggregate elapsed |
| --- | ---: |
| Collectors | 169 over 147 jobs; 6.154 s |
| Resolver queries | 32; 0.451 s |
| Toolchain queries | 21 |
| Disk memo hits | 3,451 |
| Fresh digests | 939; 0.549 s |
| Sysroot queries | 169; 2.429 s |
| Own artifact root queries | 169; 2.446 s |

The final Harness collector takes 0.133 s, including one resolver query and 0.083 s fresh hashing. Its previous 114-query tail is gone. The two sequential live compiler queries now dominate aggregate graph time. Concurrent Cargo timings overlap and cannot be added to predict elapsed build savings.

The isolated diagnostic patch applies cleanly to public revision `a21296b29e8d6da3995d22f234ff8999a726a166`. Stable Zig 0.17.0 unit tests and profiling-enabled real Rust/Zig integration pass. One cold capture and three warm builds match all 193 Rust, producer and native artifacts; warm builds each record 167 Rust hits and 24 native hits. Tracked Harness sources and manifests remain unchanged. Diagnostic elapsed times are 32.874 s cold and 2.067 / 2.138 / 2.136 s warm; these are not an A/B speedup result.

[Build provenance](../benchmarks/harness-selected-resource-profile-builds.json), [all cold phases](../benchmarks/harness-selected-resource-cold-phases.json), [all graph records](../benchmarks/harness-selected-resource-graph-profile.json), [identity memo analysis](../benchmarks/harness-selected-resource-identities.json), and [diagnostic patch](../benchmarks/experiments/decoder-graph-profile.patch) retain evidence. Installed production source is unchanged by the profiling patch.

A separate candidate overlaps the live sysroot query with artifact root decoding pinned to the fingerprint's validated selected root. The live result must agree with that root before metadata is accepted. Its tests and controlled benchmark determine whether adoption is warranted; the profile itself does not establish a speedup.
