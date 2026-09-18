# Performance Benchmarks History

| Цикл | Baseline / Изменение | Backend Import (s) | Service Init (s) | Threads Init | Max RSS (MB) | DB 1000 Ins (s) | DB Search 50x (s) | Frontend JS (KB) | Unit Tests (s) |
|---|---|---|---|---|---|---|---|---|---|
| Baseline | Чистый старт до оптимизации | 0.1458s | 0.0051s | 4 | 331.82 MB | 0.1254s | 0.0234s | 922.10 KB | 1.38s |
| Цикл 1 | PERF-001 (SharedExecutor), PERF-002 (Particles leak fix), PERF-003 (Visualizer reflow fix) | 0.1464s | 0.0054s | 4 (без 25 eager потоков) | 352.74 MB | 0.1234s | 0.0241s | 921.91 KB (-192 B) | 1.40s |
