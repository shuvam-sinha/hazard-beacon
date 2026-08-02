## Debugging log — the crash cascade

The sequence of crashes hit while getting the EON model running on-device, kept because the failure modes are non-obvious and recur after library updates.

**Crash 1 — linkage conflict (compile error).** Overriding the allocators in `main.cpp` inside `extern "C"` blocks conflicted with their C++ linkage in the porting header.

**Crash 2 — Core 0 panic before `setup()`.** Defining the allocators in `main.cpp` won weak-symbol resolution, so they ran during Core 0 init — before PSRAM was up. Fix: patch the Espressif porting layer instead, the intended override point.

**Crash 3 — overflow buffer count exceeded.** Scratch buffers overflowed a tracking array capped at 30. The porting header defines the cap unconditionally for ESP32-S3, overriding the build flag; raised it to 100 (Patch 2).

**Crash 4 — heap corruption.** Camera initialised fine; the crash landed on the first `run_classifier()`. Two compounding causes — 8-byte-aligned PSRAM handed to 16-byte SIMD code, and an overflow allocation short by exactly the alignment padding. The corrupted address sat in the PSRAM range (`0x3D000000–0x3DFFFFFF`), confirming a PSRAM allocation. Fixed by Patch 1.
