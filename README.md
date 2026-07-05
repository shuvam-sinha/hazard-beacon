# Hazard Beacon

Nighttime wildlife and person detection system running on an ESP32-S3-EYE camera module. Uses an IR illuminator to light the scene, captures 96×96 grayscale frames, and runs a MobileNetV2 0.35 int8 classifier on-device via Edge Impulse's EON compiler. A yellow LED lights when the hazard confidence score exceeds 60%.

Binary classification: **hazard_present** vs **ambient_noise**.

---

## Hardware

| Component | Detail |
|---|---|
| MCU + Camera | ESP32-S3-EYE (OV2640, 8MB OPI PSRAM, 8MB Flash) |
| IR illuminator | Auto-activates in darkness |
| Alert LED | GPIO 21, yellow, HIGH on hazard |
| Framework | PlatformIO + Arduino |
| Board config | `esp32s3camlcd`, `qio_opi` memory type, 8MB partition table |

Camera pins (OV2640 on ESP32-S3-EYE — these differ from the board variant defaults and must be overridden):

```
XCLK=15  SIOD=4   SIOC=5
Y9=16    Y8=17    Y7=18    Y6=12
Y5=10    Y4=8     Y3=9     Y2=11
VSYNC=6  HREF=7   PCLK=13
PWDN=-1  RESET=-1
```

---

## Repository Structure

```
hazard_beacon/
├── dataset/
│   ├── raw/
│   │   ├── test_captures/     # ESP32 frames captured for pipeline testing
│   │   ├── iwildcam/          # iWildCam 2020 annotations JSON
│   │   ├── nightowls/         # NightOwls annotations
│   │   └── wellington/        # Wellington Camera Traps CSV
│   ├── processed/
│   │   ├── hazard_present/    # ~2,178 images (96×96 grayscale PNG)
│   │   ├── ambient_noise/     # ~2,178 images (96×96 grayscale PNG)
│   │   └── hazard_review/     # Frames awaiting manual review
│   └── processed_backup/      # Backup before augmentation
├── firmware/
│   └── hazard_beacon/
│       ├── src/main.cpp
│       ├── platformio.ini
│       └── lib/
│           └── hazard_beacon_inferencing/   # Edge Impulse exported C++ library
│               └── src/
│                   ├── tflite-model/        # EON-compiled model
│                   └── edge-impulse-sdk/    # EI SDK (patched — see below)
├── scripts/
│   ├── receive_frames.py
│   ├── filter_wellington.py
│   ├── filter_iwildcam.py
│   ├── filter_nightowls.py
│   ├── download_iwildcam.py
│   ├── augment_dataset.py
│   ├── process_dataset.py
│   ├── test_eim_model.py        # macOS host-side model validation (edge_impulse_linux)
│   └── test_exported_model.py   # ESP32 serial-based inference test (deprecated)
└── model/                     # Edge Impulse exports
```

---

## Dataset Pipeline

### Step 1 — Capture frames from device

`scripts/receive_frames.py` opens the serial port, reads frames sent by the ESP32 framing protocol (`FRAME_START:<len>\n` followed by raw bytes), prompts the user to label each frame (1 = hazard_present, 2 = ambient_noise), and saves them into `dataset/processed/`.

### Step 2 — Filter external nighttime datasets

Three external sources were filtered down to nighttime-only images:

- **Wellington Camera Traps** — `filter_wellington.py` reads the CSV and filters by time-of-day column
- **iWildCam 2020** — `filter_iwildcam.py` reads `iwildcam2020_train_annotations.json` and keeps images captured between 19:00–06:00
- **NightOwls** — `filter_nightowls.py` reads NightOwls annotations (dataset is entirely nighttime, so this script is mainly for format conversion)

iWildCam download hit a Kaggle API rate limit after ~642 images, so the iWildCam contribution to the dataset is partial.

### Step 3 — Process to uniform format

`scripts/process_dataset.py` converts all images in `dataset/processed/` to 96×96 grayscale PNG in-place. This matches the Edge Impulse impulse input size.

### Step 4 — Augment ESP32 captures

`scripts/augment_dataset.py` applies 5× augmentation to ESP32-captured frames only (not external dataset images, which are already varied). Augmentations: ±20% brightness, horizontal flip, Gaussian noise, random crop.

### Dataset status (as of Week 5)

- **hazard_present**: ~2,178 images
- **ambient_noise**: ~2,178 images (balanced)

> **Important caveat:** The current dataset is daytime captures. The deployment environment is nighttime IR-illuminated. This dataset validates the pipeline only — accuracy will be poor until a HIL rig is used to collect real nighttime IR data and the model is retrained (planned Week 6).

---

## Model Training (Edge Impulse)

**Project:** hazard_beacon (Edge Impulse Studio)  
**Target:** Espressif ESP-EYE  
**Upload:** 4,356 items, 80/20 train/test split  

### Impulse configuration

- Input: 96×96 Image block, resize mode: **Squash** (not fit/crop — Squash avoids padding artifacts)
- Processing: Image block (grayscale)
- Learning: Classification (MobileNetV2 0.35, 60 epochs, lr=0.001)
- Quantization: int8 post-training quantization

### Export

Exported as **C++ library** (Arduino format). Place the extracted folder in `firmware/hazard_beacon/lib/` as `hazard_beacon_inferencing/`.

The EON compiler path (`EI_CLASSIFIER_COMPILED=1`) is used, not the standard TFLite Micro interpreter path. This means `tflite_eon.h` calls `graph_config->model_init(ei_aligned_calloc)` at runtime, and the compiled model file (`tflite_learn_*_compiled.cpp`) handles its own tensor arena allocation and operator dispatch.

---

## Model Validation (macOS host-side)

After exporting from Edge Impulse, the model was validated on macOS using the `.eim` binary (Edge Impulse Linux SDK). This is a **host-side sanity check only** — the `.eim` is a macOS ARM64 executable and cannot run on the ESP32. The ESP32 uses the C++ library export (`lib/hazard_beacon_inferencing/`).

### How it works

`scripts/test_eim_model.py` loads labelled images from `dataset/processed/`, runs them through the `.eim` model via `ImageImpulseRunner`, and reports per-class accuracy. Images are passed as OpenCV numpy arrays (not file paths) to `runner.get_features_from_image()`.

### Running

```bash
pip install edge_impulse_linux opencv-python
python scripts/test_eim_model.py --samples 200
# --eim flag overrides the default path if your .eim is elsewhere
```

Default `.eim` path: `~/Downloads/hazard_beacon-mac-arm64-v4-impulse-#1.eim`

### Results (Week 5, model 1043721)

Tested on 200 randomly sampled images (100 per class) from `dataset/processed/`:

| Class | Correct | Accuracy |
|---|---|---|
| ambient_noise | 98/100 | 98.0% |
| hazard_present | 92/100 | 92.0% |
| **Overall** | **190/200** | **95.0%** |

Edge Impulse's own validation set reported 95.9% (98.5% ambient / 90.9% hazard), so the exported model is behaving as trained.

> **Note:** This test samples from the full dataset including training images, so accuracy may be slightly inflated compared to Edge Impulse's held-out test set figure.

---

## Firmware

### platformio.ini

```ini
[env:esp32s3eye]
platform = espressif32
board = esp32s3camlcd
framework = arduino
monitor_speed = 115200
board_build.arduino.memory_type = qio_opi
board_upload.flash_size = 8MB
board_build.partitions = default_8MB.csv
lib_deps =
    espressif/esp32-camera
build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DEI_MAX_OVERFLOW_BUFFER_COUNT=30   # redundant (porting header overrides to 100), harmless
```

### Inference loop (main.cpp)

1. `esp_camera_fb_get()` — capture frame into DMA buffer
2. Build `signal_t` with `get_signal_data` callback that normalises `uint8 → float [0,1]`
3. `run_classifier(&signal, &result, false)` — runs EON-compiled MobileNetV2
4. `esp_camera_fb_return(fb)` — release frame buffer immediately after inference
5. Parse `result.classification[]` for `hazard_present` and `ambient_noise` scores
6. `digitalWrite(LED_PIN, hazard_score > 0.6f ? HIGH : LOW)`
7. Print `[Inference] hazard=X.XX  ambient=X.XX  → clear/HAZARD DETECTED`
8. `delay(2000)`

### Low-light sensor tuning

Commented out in main.cpp for daytime testing. Uncomment when deploying with IR illuminator:

```cpp
sensor_t *s = esp_camera_sensor_get();
s->set_gainceiling(s, GAINCEILING_16X);
s->set_exposure_ctrl(s, 1);
s->set_gain_ctrl(s, 1);
s->set_aec2(s, 1);
s->set_bpc(s, 1);
s->set_wpc(s, 1);
```

### Serial monitoring

```
~/.platformio/penv/bin/platformio device monitor --baud 115200 --project-dir ~/Documents/hazard_beacon/firmware/hazard_beacon
```

Expected output:
```
=== Hazard Beacon - Inference Mode ===
PSRAM total: 8386279 bytes  free: 8386275 bytes
Camera initialized. Running inference every 2 seconds...
[Inference] hazard=0.12  ambient=0.88  → clear
```

---

## SDK Patches (DO NOT REVERT)

Two files in the Edge Impulse library have been patched. These patches are required for the model to run on ESP32-S3 and will need to be re-applied if you update the library from Edge Impulse.

### Patch 1 — PSRAM allocator alignment fix

**File:** `lib/hazard_beacon_inferencing/src/edge-impulse-sdk/porting/espressif/ei_classifier_porting.cpp`

**Problem:** The default `ei_malloc` and `ei_calloc` used `heap_caps_malloc`/`heap_caps_calloc` with `MALLOC_CAP_SPIRAM`, which returns 8-byte aligned memory. CMSIS-NN SIMD operations require 16-byte alignment. Additionally, the EON compiled model's `AllocatePersistentBufferImpl` calculates alignment padding when checking whether a scratch buffer fits in the tensor arena, but when it overflows to `ei_calloc(bytes, 1)`, it only allocates exactly `bytes` — not `bytes + padding`. CMSIS-NN then writes up to the next 16-byte boundary, stomping the ESP-IDF heap poisoning canary and triggering:

```
CORRUPT HEAP: Bad tail at 0x3da25537. Expected 0xbaad5678 got 0x4dc7cf51
assert failed: multi_heap_free multi_heap_poisoning.c:259 (head != NULL)
```

**Fix:** Use `heap_caps_aligned_alloc(16, rounded_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)` where `rounded_size = (requested + 15) & ~15`. This guarantees both pointer alignment and sufficient allocation size.

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

__attribute__((weak)) void *ei_calloc(size_t nitems, size_t size) {
#if defined(CONFIG_IDF_TARGET_ESP32S3)
    size_t total = ((nitems * size) + 15) & ~15u;
    void *ptr = heap_caps_aligned_alloc(16, total, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (ptr) { memset(ptr, 0, total); return ptr; }
    ptr = heap_caps_aligned_alloc(16, total, MALLOC_CAP_DEFAULT);
    if (ptr) { memset(ptr, 0, total); return ptr; }
    return NULL;
#endif
    return calloc(nitems, size);
}

__attribute__((weak)) void ei_free(void *ptr) {
    heap_caps_free(ptr);  // works for both internal RAM and PSRAM pointers
}
```

### Patch 2 — Overflow buffer count

**File:** `lib/hazard_beacon_inferencing/src/edge-impulse-sdk/porting/ei_classifier_porting.h`

**Problem:** MobileNetV2 0.35 with CMSIS-NN generates more scratch buffers than fit in the 246KB tensor arena. When these overflow to `ei_calloc`, they are tracked in a static array of size `EI_MAX_OVERFLOW_BUFFER_COUNT`. The default for ESP32-S3 was 30, which was not enough, causing:

```
ERR: Failed to allocate persistent buffer of size N, does not fit in tensor arena
and reached EI_MAX_OVERFLOW_BUFFER_COUNT
```

**Fix:** Raise `EI_MAX_OVERFLOW_BUFFER_COUNT` to 100 for ESP32-S3. This is the **authoritative** definition location — the compiled model file has a `#ifndef` fallback that is overridden by this header.

```c
#if defined(CONFIG_IDF_TARGET_ESP32S3)
#define EI_MAX_OVERFLOW_BUFFER_COUNT    100
#endif
```

> **Note on porting layer selection:** When `CONFIG_IDF_TARGET_ESP32S3` is defined (which PlatformIO sets automatically via the board target), `ei_classifier_porting.h` forces `EI_PORTING_ESPRESSIF=1` and `EI_PORTING_ARDUINO=0`, even though the framework is Arduino. This means the Espressif porting layer (`porting/espressif/ei_classifier_porting.cpp`) is the active allocator, not the Arduino one. Any allocator patches must go in the Espressif file.

---

## Debugging Log — Week 5 Crash Cascade

This section records every crash encountered getting the EON model running, in the order they appeared.

### Crash 1 — `extern "C"` linkage conflict (compile error)

**Symptom:** Compiler error about conflicting C/C++ linkage on `ei_malloc`, `ei_calloc`, `ei_free`.

**Cause:** Initial attempt was to override the allocators in `main.cpp` using `extern "C"` blocks, but the functions are declared with C++ linkage in the porting header.

**Fix:** Removed `extern "C"` wrappers from `main.cpp`. Attempted plain C++ overrides instead (led to next crash).

---

### Crash 2 — Core 0 panic before `setup()` ran

**Symptom:**
```
Guru Meditation Error: Core 0 panic'd (LoadProhibited)
EXCVADDR: 0x00000000
```
Device rebooted before any serial output from `setup()`.

**Cause:** Defining `ei_malloc`/`ei_calloc`/`ei_free` in `main.cpp` conflicted with the Espressif porting layer's initialization, which runs on Core 0 before `setup()`. The weak-symbol overrides in `main.cpp` were being selected by the linker but called before the PSRAM was initialised.

**Fix:** Removed all allocator overrides from `main.cpp`. Instead, patched the Espressif porting layer directly (`porting/espressif/ei_classifier_porting.cpp`), which is the correct and intentional override point.

---

### Crash 3 — Overflow buffer count exceeded

**Symptom:**
```
ERR: Failed to allocate persistent buffer of size 692224, does not fit in tensor arena
and reached EI_MAX_OVERFLOW_BUFFER_COUNT
Core 1 panic'd (LoadProhibited)
```

**Cause:** MobileNetV2 0.35 with CMSIS-NN requires more scratch buffers than fit in the 246KB tensor arena. These overflow to heap via `ei_calloc`. The overflow tracking array was capped at 10 (compiled model default) then 30 (build flag), neither of which was sufficient.

**Investigation:** Discovered that `ei_classifier_porting.h` defines `EI_MAX_OVERFLOW_BUFFER_COUNT` for `CONFIG_IDF_TARGET_ESP32S3` unconditionally (not guarded by `#ifndef`), so it always overwrites whatever the compiled model file or build flag sets. The porting header is the authoritative location.

**Fix:** Changed the porting header definition from 30 to 100.

---

### Crash 4 — Heap corruption (CORRUPT HEAP: Bad tail)

**Symptom:**
```
CORRUPT HEAP: Bad tail at 0x3da25537. Expected 0xbaad5678 got 0x4dc7cf51
assert failed: multi_heap_free multi_heap_poisoning.c:259 (head != NULL)
```

Camera initialised successfully, crash occurred during first call to `run_classifier()`.

**Cause:** Two related issues in `AllocatePersistentBufferImpl` (the EON model's arena allocator):

1. **Alignment:** When a scratch buffer fits in the tensor arena, the arena path aligns the pointer to 16 bytes and accounts for padding. When it overflows to `ei_calloc`, it calls `ei_calloc(bytes, 1)` — no alignment, no padding. `heap_caps_calloc` returns 8-byte aligned PSRAM. CMSIS-NN SIMD code writes 16-byte chunks from the (8-byte aligned) pointer and overruns the allocation by up to 8 bytes.

2. **Size:** The arena check subtracts `bytes + align_bytes` to see if the buffer fits, but the overflow path only allocates `bytes`. The missing `align_bytes` are the bytes CMSIS-NN will write past the end.

The corrupted address `0x3da25537` is in the PSRAM virtual address range (`0x3D000000–0x3DFFFFFF`), confirming the stomped canary is on a PSRAM heap allocation.

**Fix:** `ei_calloc` and `ei_malloc` now use `heap_caps_aligned_alloc(16, rounded, MALLOC_CAP_SPIRAM)` where `rounded = (size + 15) & ~15`. This fixes both the pointer alignment and ensures the allocation covers the padding CMSIS-NN assumes is there.

---

### PlatformIO build cache issues

When patching library files inside `.pio/`, PlatformIO sometimes uses cached `.a` archives and does not recompile. Symptoms: ELF SHA256 unchanged after an apparently successful build+upload.

**Fix:** Delete the entire `.pio` directory before rebuilding:

```
rm -rf ~/Documents/hazard_beacon/firmware/hazard_beacon/.pio
~/.platformio/penv/bin/platformio run --target upload
```

Also: do not run `platformio run` from two terminals simultaneously (the Bash tool and a terminal). The `.sconsign` dependency tracking file gets corrupted.

---

## Build and Flash

```bash
# Full clean rebuild + upload
rm -rf ~/Documents/hazard_beacon/firmware/hazard_beacon/.pio
cd ~/Documents/hazard_beacon/firmware/hazard_beacon
~/.platformio/penv/bin/platformio run --target upload

# Monitor
~/.platformio/penv/bin/platformio device monitor --baud 115200 \
    --project-dir ~/Documents/hazard_beacon/firmware/hazard_beacon
```

---

## Known Limitations

- **Domain gap:** Model trained on daytime captures, deployed at night under IR illumination. Scores are meaningless until the model is retrained on nighttime IR data.
- **iWildCam partial download:** Kaggle API rate limit cut the download at ~642 images out of the intended set.
- **No FreeRTOS dual-core split yet:** Camera capture and inference run serially on Core 1. Week 6 will move capture to Core 0.
- **LED not wired yet:** GPIO 21 is defined in firmware but the physical wire has not been run.
- **`EI_MAX_OVERFLOW_BUFFER_COUNT=30` in platformio.ini:** This build flag is now redundant (the porting header overrides it to 100) but is harmless — produces a warning during compilation.

---

## Week 6 Plan

1. **HIL rig** — mount ESP32-S3-EYE + IR illuminator, collect nighttime IR frames of both classes
2. **Retrain** — upload nighttime frames to Edge Impulse, retrain MobileNetV2, re-export C++ library
3. **FreeRTOS** — camera on Core 0, inference queue on Core 1
4. **LED wiring** — run wire from GPIO 21 to yellow LED + resistor
5. **Threshold tuning** — adjust 0.6 threshold based on real-world precision/recall tradeoff
