# Adopted decoder scope: complete Harness comparison

Warm medians are **2.038725 s Nano, 2.115331 s kache and 24.127392 s direct Cargo**.
Nano is faster in **7/9 corresponding rounds**. Both warm wrappers are close;
all samples, including Nano's slower eighth run, are retained.

| Mode | Median | Mean | Range | Sample standard deviation |
| --- | ---: | ---: | ---: | ---: |
| Direct | 24.127392 s | 24.398527 s | 23.929590–25.467107 s | 0.541297 s |
| Nano | 2.038725 s | 2.074859 s | 2.009662–2.282645 s | 0.084649 s |
| kache | 2.115331 s | 2.118842 s | 2.047443–2.235144 s | 0.065918 s |

Same-round Nano-minus-kache differences have median −38.246 ms, mean
−43.983 ms and descriptive standard error 35.969 ms. These rotating rounds
share one host/session and are not independent machine trials. This does
not establish a robust or general warm advantage. Absolute comparisons
with earlier sessions cannot attribute a warm gain to the decoder change.
The [controlled before/after comparisons](decoder-scope-experiment.md)
establish the 21.6% and 22.7% cold-build reductions separately.

Cold remains slower for Nano: **31.715342 s Nano versus 28.085303 s kache**.
The direct prime takes 25.111636 s. All 27 warm builds match their own cold
Rust libraries, macro dylibs, build-script executables, native objects and
archives. Tracked Rust sources, manifests and lockfile remain unchanged.
Each Nano warm build has 167 Rust hits, 24 native hits, eight bypasses and
three failed compiler probes. Each kache warm build has 187 local hits and
three passthroughs. Scanner debug output and kache's path remapping prevent
claiming cross-mode byte equality.

Measured source revision: `bb55f9777db5ced3024e49a5d311f7bcda3e32a2`.
Installed executable SHA-256:
`ff22874cb5ac7ced96e67e076f75dc65581b921fa0307cf8f0b5018e8803f521`.
Host: Apple M3 Ultra, 28 logical CPUs, 256 GiB RAM, arm64 macOS 27.
Builds use Rust 1.97.1, four jobs, a 40 GiB sampled process-tree RSS cap,
locked offline release library mode and clean fixed target paths.
The runner starts and cleans up a private kache daemon, rotating three-way
order each round. Nano explicitly uses native Clang CAS, reported macro
inputs and experimental Apple macro/executable producers. Default-policy
results are separate and remain public.

```sh
env RUSTUP_TOOLCHAIN=1.97.1 python3 tests/project_comparison.py \
  zig-out/bin/nanocompile /Users/rachpradhan/harness \
  --kache /tmp/nanocompile-kache-bin/kache \
  --state /tmp/nanocompile-decoder-nine-way \
  --runs 9 --jobs 4 --proc-macros reported \
  --proc-macro-producers --executable-producers --native-clang \
  --output benchmarks/harness-decoder-nine-samples.json
```

[Full build report](../benchmarks/harness-decoder-nine-samples.json),
[all-sample analysis](../benchmarks/harness-decoder-nine-analysis.json) and
[summary script](../benchmarks/experiments/three_way_summary.py) retain the evidence.
Local adoption gates pass. At publication, the adopted revision's
[CI run](https://github.com/justrach/nanocompile/actions/runs/38007374944)
has passed Linux and macOS is queued; cross-platform validation is pending.

The [previous integrated-cc1 comparison](clang-integrated-nine-samples.md)
reported a larger warm gap with more kache variability. The earlier
nine-round ordering favoring kache is also retained. None establishes
a cross-machine advantage.
