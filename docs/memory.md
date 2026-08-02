## Memory: internal SRAM vs PSRAM

The ESP32-S3 exposes two kinds of general-purpose RAM, and the split is the whole reason this project needed allocator patches.

- **Internal SRAM — 512 KB, on-chip, fast.** Runs at CPU speed, but it is shared by everything and only a few hundred KB is realistically free.
  *Stored here:* the Arduino/FreeRTOS runtime and task stacks, and the camera driver's DMA buffers (DMA hardware can only reach internal RAM).
- **PSRAM (a.k.a. SPIRAM) — 8 MB, external, slower.** A separate memory chip wired over an octal-SPI bus and memory-mapped into the CPU's address space (the `0x3C000000–0x3DFFFFFF` region). Far larger, but every access goes through the bus and cache, so it is slower than internal SRAM. It must be enabled (`-DBOARD_HAS_PSRAM`, `qio_opi` memory type) and explicitly requested with `heap_caps_malloc(..., MALLOC_CAP_SPIRAM)` — a plain `malloc` never touches it.
  *Stored here:* the model's tensor arena and the CMSIS-NN scratch / overflow buffers (the bulk of the ~249 KB peak), plus the two camera frame buffers.
- **Flash — 8 MB, non-volatile.** Storage, not RAM.
  *Stored here:* the compiled firmware, the EON-compiled model weights (read-only constants streamed through cache at runtime), and the partition table.

MobileNetV2's tensor arena and its CMSIS-NN scratch buffers need more contiguous memory than internal SRAM can spare alongside the camera's frame buffers, so the model's working memory has to live in PSRAM. That is exactly what the SDK patches force: every model allocation is routed to `MALLOC_CAP_SPIRAM`. It is also why the crash address in the [debugging log](#debugging-log--the-crash-cascade) (`0x3d…`) was the clue — that range is PSRAM, so the heap overrun had to be on a PSRAM buffer, not internal RAM.
