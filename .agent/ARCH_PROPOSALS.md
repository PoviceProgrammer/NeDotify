# Architecture & Visual Trade-Off Proposals (Pending User Review)

> **IMPORTANT**: According to Rule 2 & 3, changes from this file are NOT implemented automatically. They require architectural shifts or visual trade-offs.

| ID | Category | Component | Proposal Description | Trade-Off / Impact |
|---|---|---|---|---|
| ARCH-001 | VISUAL/GPU | `ui/web_new/js/particles.js` | Reduce default particle count from 30 to 15 on lower-end systems | Reduces GPU rasterization load, but slightly changes particle density visually. |
| ARCH-002 | VISUAL/GPU | `ui/web_new/css/style.css` | Disable `backdrop-filter: blur(...)` permanently on all glass cards | Drastically reduces GPU composition cost on integrated graphics, but alters the glassmorphism aesthetic. |
| ARCH-003 | ARCH/CORE | `main.py` / `core/` | Migrate from `pywebview` with WebKitGTK to Qt WebEngine or custom Rust/C++ UI bridge | Requires complete packaging and build system rewrite. |
| ARCH-004 | VISUAL/CPU | `ui/web_new/js/visualizer.js` | Reduce `BAR_COUNT` in audio visualizer from 48 to 24 bars | Decreases per-frame loop computations and canvas draw calls by 50%, but lowers visual bar resolution. |
