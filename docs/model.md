## Model (Edge Impulse)

**Target:** Espressif ESP-EYE

### How Edge Impulse works

Edge Impulse is a platform for building TinyML models — collecting data, training in the cloud, and exporting something small enough to run on a microcontroller. Its central concept is an **impulse**: a pipeline of an input block, a signal-processing (DSP) block, and a learning block. For this project the impulse is:

```
96×96 image  →  Image DSP block (RGB)  →  transfer learning (MobileNetV2 0.35)  →  2 classes
```

The **DSP block** (short for digital signal processing — a name inherited from audio projects) is the preprocessing stage between the raw input and the model. It doesn't *learn* anything; it deterministically turns each raw image into the numeric feature vector the network consumes, and it runs **identically during training and on-device inference** — which is the whole point, since the model only works if live camera frames are turned into features the same way the training images were. For images that means applying the color mode, normalising the pixel values, and flattening the result. This project's block is set to **RGB**, producing 96×96×3 = **27,648 features** — even though the camera is grayscale — because the pretrained MobileNetV2 base expects three channels. That single choice is why the firmware packs each grey byte into all three channels (see [Signal callback](#signal-callback)): the pipeline must see the same format at inference time that it saw in training.

You upload labelled images, design the impulse in the browser, train, check accuracy on a held-out set, then export. Rather than ship the model as a `.tflite` file that a generic interpreter reads at runtime, this project uses Edge Impulse's **EON Compiler**, which compiles the model's operator graph directly into C++ source. There is no interpreter to store or step through — which is why the deployment page reports it using ~18% less RAM and ~21% less flash than the standard TFLite Micro path, at the same accuracy.

### Impulse configuration

- **Input:** 96×96 image, resize mode **Squash** (avoids the padding artifacts fit/crop introduce)
- **Processing:** Image block, RGB — 27,648 features (96×96×3)
- **Learning:** Transfer learning, MobileNetV2 0.35, 20 cycles, lr = 0.0005, augmentation enabled
- **Output classes:** `ambient_noise`, `hazard_detected`
- **Quantization:** int8 post-training

The DSP block is configured for **RGB** even though the camera is grayscale; the firmware packs each grey byte into all three channels — see [Signal callback](#signal-callback).

### Results

Edge Impulse validation set. The **int8** model is what runs on the device; float32 is included for reference.

| Model | Accuracy | `ambient_noise` recall | `hazard_detected` recall | Weighted F1 |
|---|---|---|---|---|
| **int8 (deployed)** | **97.8%** | 100% | 95.6% | 0.98 |
| float32 (reference) | 99.8% | 100% | 99.6% | 1.00 |

On-device performance (int8, ESP32-S3 @ 240 MHz, Edge Impulse estimate):

| Metric | Value |
|---|---|
| Inference latency | ~1.5 s |
| Peak RAM | 248.7 KB |
| Flash | 531.9 KB |

### What gets exported

The "Arduino library" export is a self-contained C++ library, `hazard_beacon_inferencing/`, holding three things:

- **The model** — `tflite-model/tflite_learn_*_compiled.cpp`: the weights and the EON-compiled graph, as code.
- **Model parameters** — `model-parameters/model_metadata.h` and `model_variables.h`: input dimensions, class labels, thresholds, and quantization parameters.
- **The runtime SDK** — `edge-impulse-sdk/`: the DSP blocks, the CMSIS-NN kernels that do the actual math, and a **porting layer** that abstracts memory, timing, and printing per target.

The API surface is small: fill a `signal_t` (how many values, plus a callback that supplies them), call `run_classifier()`, and read the scores out of `ei_impulse_result_t.classification[]`.

### Adapting it to the ESP32-S3

The export is generic; making it run on this board took three things:

1. **Feed it the camera.** `run_classifier()` doesn't read the image — it calls back for pixels. The `get_signal_data` callback bridges the camera frame to the model, packing each grayscale byte into RGB (see [Signal callback](#signal-callback)).
2. **Put the model's memory in PSRAM.** The stock allocators assume the model fits in internal RAM; it doesn't. The porting layer was patched to allocate from PSRAM with correct alignment — see [Memory](#memory-internal-sram-vs-psram) and [SDK patches](#sdk-patches-do-not-revert).
3. **Keep the watchdog fed** across the multi-second inference call so the chip doesn't reset mid-classification.
