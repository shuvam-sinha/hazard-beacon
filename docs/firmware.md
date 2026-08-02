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
    bblanchon/ArduinoJson@^7.0.0
build_flags =
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
```

### Inference loop

Each pass captures one live frame and classifies it, roughly every ~2 seconds. The three memory regions work together throughout — the block each step touches is called out in **bold** (see [Memory](#memory-internal-sram-vs-psram) for what each one is):

1. `esp_camera_fb_get()` — capture a frame. The camera's DMA latches pixels through small **internal SRAM** buffers (DMA can only reach on-chip RAM) and assembles the 96×96 frame into a frame buffer in **PSRAM**.
2. Point `frame_buf_ptr` at the pixel data — the frame stays in **PSRAM**; only a pointer is set, on the **SRAM** stack. Nothing is copied.
3. Build `signal_t` with the `get_signal_data` callback (a small descriptor on the **SRAM** stack).
4. `run_classifier_init()`, then `esp_task_wdt_reset()` to feed the watchdog before the multi-second inference call.
5. `run_classifier()` — EON-compiled MobileNetV2. The model's **weights are read from flash** (streamed through cache, never copied to RAM); its **tensor arena and CMSIS-NN scratch buffers live in PSRAM**; and the **CPU drives the math from SRAM**. The DSP block runs first, pulling each pixel from the **PSRAM** frame via the callback (packing grayscale into RGB) and writing the feature vector into the **PSRAM** arena, which the network layers then compute through.
6. Read `hazard_detected` / `ambient_noise` scores — a few numbers in the `result` struct on the **SRAM** stack — apply the 0.6 threshold, set the LED, and print the result over serial.
7. On a sustained streak (5 consecutive hazard frames), POST the frame to the server — the raw bytes are read back out of the **PSRAM** frame buffer and sent over WiFi.
8. `esp_camera_fb_return(fb)` — release the **PSRAM** frame buffer so the next capture can reuse it.

In short: the frame lands in **PSRAM**, the model reads its weights from **flash** and does its scratch work in **PSRAM**, while **SRAM** runs the code and holds the DMA buffers and the final scores.

### Class label

The model's positive class is **`hazard_detected`**, matched by exact string:

```cpp
if (strcmp(label, "hazard_detected") == 0) hazard_score  = value;
if (strcmp(label, "ambient_noise")   == 0) ambient_score = value;
```

If a retrain assigns a different class name, this comparison silently fails and every frame reads as clear with no error anywhere. **Verify the class names on the Edge Impulse deployment page against these strings after every retrain.**

### Signal callback

Edge Impulse pulls pixels through a callback. Because the DSP block is RGB, each grayscale byte is packed into all three channels:

```cpp
static int get_signal_data(size_t offset, size_t length, float *out_ptr) {
    for (size_t i = 0; i < length; i++) {
        uint8_t gray = frame_buf_ptr[offset + i];
        out_ptr[i] = (float)((gray << 16) | (gray << 8) | gray);   // 0xRRGGBB
    }
    return EIDSP_OK;
}
```

### Frame streaming

A compile-time flag controls whether each classified frame is streamed over serial for the capture scripts:

```cpp
#define DUMP_FRAMES    1
```

At `1`, the firmware emits `FRAME_START:<len>:<decision>:<hazard>:<ambient>` followed by the raw pixel bytes — required by `receive_frames.py` and `capture_classified_frames.py`. At `0`, serial is clean text only and the capture scripts receive nothing. (At `1`, a plain serial monitor renders the pixel bytes as garbled text; that's expected — read the stream through one of the scripts.)
