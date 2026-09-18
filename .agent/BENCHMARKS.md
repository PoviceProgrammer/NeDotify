# Performance Benchmarks History

| Цикл | Baseline / Изменение | Backend Import (s) | Service Init (s) | Threads Init | Max RSS (MB) | DB 1000 Ins (s) | DB Search 50x (s) | Frontend JS (KB) | Unit Tests (s) |
|---|---|---|---|---|---|---|---|---|---|
| Baseline | Чистый старт до оптимизации | 0.1458s | 0.0051s | 4 | 331.82 MB | 0.1254s | 0.0234s | 922.10 KB | 1.38s |
| Цикл 1 | PERF-001 (SharedExecutor), PERF-002 (Particles leak fix), PERF-003 (Visualizer reflow fix) | 0.1464s | 0.0054s | 4 (без 25 eager потоков) | 352.74 MB | 0.1234s | 0.0241s | 921.91 KB (-192 B) | 1.40s |
| Цикл 2 | PERF-004 (Player DOM throttle), PERF-005 (Efficiency leak fix), PERF-006 (SQLite 2MB cache) | 0.1689s | 0.0058s | 4 | 362.85 MB | 0.1211s (-2%) | 0.0230s (-5%) | 922.74 KB | 8.04s (85 tests) |
| Цикл 3 | PERF-007 (main.py json hoisting), PERF-008 (proxy 64KB chunks), PERF-009 (contextmenu deduplication) | 0.1600s (-5%) | 0.0063s | 4 | 376.96 MB | 0.1226s | 0.0287s | 922.69 KB (-54 B) | 7.65s (85 tests, -5%) |
| Цикл 4 | PERF-010 (Artist profile rAF scroll), PERF-011 (Equalizer click dedup), PERF-012 (Artist bridge promise cleanup) | 0.1475s (-8%) | 0.0050s | 4 | 398.07 MB | 0.1235s | 0.0241s | 923.38 KB | 7.85s (85 tests + 3 node) |
| Цикл 5 | PERF-013 (Library rAF scroll & anim cancel), PERF-014 (Proxy LRU roots & 64KB stream chunks), PERF-015 (Waveform resize rAF throttle & hidden timer guard) | 0.1424s (-3.5%) | 0.0050s | 4 | 408.54 MB | 0.1266s | 0.0245s | 923.98 KB | 7.80s (85 tests + 3 node) |
| Цикл 6 | PERF-016 (Pages idempotent init), PERF-017 (Queue idempotent init), PERF-018 (Stream cache limit 500) | 0.1415s (-1%) | 0.0049s (-2%) | 4 | 408.66 MB | 0.1266s | 0.0230s (-6%) | 924.17 KB | 8.27s (85 tests + 3 node) |
| Цикл 7 | PERF-019 (Resolver regex & base64 hoisting), PERF-020 (Search dropdown click dedup & init guard) | 0.1423s | 0.0054s | 4 | 408.66 MB | 0.1280s | 0.0250s | 924.50 KB | 7.82s (85 tests + 3 node) |
| Цикл 8 | PERF-021 (Lyrics idempotent init), PERF-022 (Library idempotent init), PERF-023 (Settings idempotent init) | 0.1637s | 0.0055s | 4 | 427.38 MB | 0.1275s | 0.0232s (-7%) | 924.80 KB | 7.90s (85 tests + 3 node) |
| Цикл 9 | PERF-024 (CacheManager lazy executor), PERF-025 (LufsScanner lazy pool), PERF-026 (FileScanner extension lowering) | 0.1421s (-13%) | 0.0054s | 4 | 480.91 MB | 0.1287s | 0.0244s | 924.80 KB | 7.76s (94 tests + 3 node, -2%) |
