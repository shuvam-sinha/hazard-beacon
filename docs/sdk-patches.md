## SDK patches (DO NOT REVERT)

Two files in the Edge Impulse library are patched; both are required for the model to run on ESP32-S3. A fresh export overwrites them, so they must be reapplied after any library update.

### Patch 1 — PSRAM allocator alignment

**File:** `lib/hazard_beacon_inferencing/src/edge-impulse-sdk/porting/espressif/ei_classifier_porting.cpp`

The default `ei_malloc`/`ei_calloc` return 8-byte aligned memory, but CMSIS-NN SIMD operations require 16-byte alignment. Worse, the EON model accounts for alignment padding when checking whether a scratch buffer fits the tensor arena, but its overflow path calls `ei_calloc(bytes, 1)` — no padding. CMSIS-NN then writes up to the next 16-byte boundary, past the end of the allocation, corrupting the ESP-IDF heap canary:

```
CORRUPT HEAP: Bad tail at 0x3da25537. Expected 0xbaad5678 got 0x4dc7cf51
```

**Fix:** allocate from PSRAM with explicit 16-byte alignment and round every request up to a 16-byte multiple.

```cpp
__attribute__((weak)) void *ei_malloc(size_t size) {
#if defined(CONFIG_IDF_TARGET_ESP32S3)
    size_t rounded = (size + 15) & ~15u;
    void *ptr = heap_caps_aligned_alloc(16, rounded, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (ptr) return ptr;
    return heap_caps_aligned_alloc(16, rounded, MALLOC_CAP_DEFAULT);
#endif
    return malloc(size);
}
```

`ei_calloc` applies the same rounding, and `ei_free` uses `heap_caps_free` so it works for both internal RAM and PSRAM pointers.

### Patch 2 — Overflow buffer count

**File:** `lib/hazard_beacon_inferencing/src/edge-impulse-sdk/porting/ei_classifier_porting.h`

MobileNetV2 0.35 with CMSIS-NN generates more scratch buffers than fit the tensor arena. Overflow buffers are tracked in a static array sized by `EI_MAX_OVERFLOW_BUFFER_COUNT`, whose ESP32-S3 default of 30 is too small. Raising it to 100 fixes it — and this header is the **authoritative** definition, overriding both the compiled model's fallback and any build flag.

```c
#if defined(CONFIG_IDF_TARGET_ESP32S3)
#define EI_MAX_OVERFLOW_BUFFER_COUNT    100
#endif
```

> When `CONFIG_IDF_TARGET_ESP32S3` is defined, the SDK forces the **Espressif** porting layer active even though the framework is Arduino — so allocator patches must go in the Espressif file, not the Arduino one.
