#include <Arduino.h>
#include "esp_camera.h"
#include <hazard_beacon_inferencing.h>  // Edge Impulse generated Arduino library (model + SDK)

// ── Camera pin definitions for ESP32-S3-EYE ──────────────────────────────────
// The board variant (esp32s3camlcd) defines different pin numbers so we
// undef first to avoid redefinition warnings, then set the correct values.
#undef PWDN_GPIO_NUM
#undef RESET_GPIO_NUM
#undef XCLK_GPIO_NUM
#undef SIOD_GPIO_NUM
#undef SIOC_GPIO_NUM
#undef Y9_GPIO_NUM
#undef Y8_GPIO_NUM
#undef Y7_GPIO_NUM
#undef Y6_GPIO_NUM
#undef Y5_GPIO_NUM
#undef Y4_GPIO_NUM
#undef Y3_GPIO_NUM
#undef Y2_GPIO_NUM
#undef VSYNC_GPIO_NUM
#undef HREF_GPIO_NUM
#undef PCLK_GPIO_NUM

#define PWDN_GPIO_NUM  -1  // Power down — not used on this board
#define RESET_GPIO_NUM -1  // Hardware reset — not used on this board
#define XCLK_GPIO_NUM  15  // Clock signal fed into the camera sensor
#define SIOD_GPIO_NUM  4   // SCCB data pin (camera's I2C-like config bus)
#define SIOC_GPIO_NUM  5   // SCCB clock pin
#define Y9_GPIO_NUM    16  // Pixel data bus MSB
#define Y8_GPIO_NUM    17
#define Y7_GPIO_NUM    18
#define Y6_GPIO_NUM    12
#define Y5_GPIO_NUM    10
#define Y4_GPIO_NUM    8
#define Y3_GPIO_NUM    9
#define Y2_GPIO_NUM    11  // Pixel data bus LSB
#define VSYNC_GPIO_NUM 6   // Pulses once per complete frame
#define HREF_GPIO_NUM  7   // Pulses once per row of pixels
#define PCLK_GPIO_NUM  13  // Pixel clock — pulses once per pixel

#define LED_PIN        21  // Yellow alert LED — HIGH when hazard detected

// ── Global frame buffer pointer ───────────────────────────────────────────────
// Shared between loop() and the Edge Impulse get_data callback
static uint8_t *frame_buf_ptr = nullptr;

// ── Edge Impulse signal callback ──────────────────────────────────────────────
// Called by the classifier to read pixel values one chunk at a time.
// Converts raw uint8 pixel (0-255) to float (0.0-1.0) as the model expects.
static int get_signal_data(size_t offset, size_t length, float *out_ptr) {
    for (size_t i = 0; i < length; i++) {
        out_ptr[i] = (float)frame_buf_ptr[offset + i] / 255.0f;
    }
    return EIDSP_OK;
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    // Wait up to 5 seconds for USB serial to connect before continuing
    uint32_t t = millis();
    while (!Serial && (millis() - t) < 5000) delay(10);
    delay(1000);

    // Initialize LED pin — starts OFF (no hazard)
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    Serial.println("=== Hazard Beacon - Inference Mode ===");
    Serial.printf("PSRAM total: %u bytes  free: %u bytes\n",
                  ESP.getPsramSize(), ESP.getFreePsram());

    // ── Camera configuration ──────────────────────────────────────────────────
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;  // LEDC peripheral used to generate XCLK
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = Y2_GPIO_NUM;
    config.pin_d1       = Y3_GPIO_NUM;
    config.pin_d2       = Y4_GPIO_NUM;
    config.pin_d3       = Y5_GPIO_NUM;
    config.pin_d4       = Y6_GPIO_NUM;
    config.pin_d5       = Y7_GPIO_NUM;
    config.pin_d6       = Y8_GPIO_NUM;
    config.pin_d7       = Y9_GPIO_NUM;
    config.pin_xclk     = XCLK_GPIO_NUM;
    config.pin_pclk     = PCLK_GPIO_NUM;
    config.pin_vsync    = VSYNC_GPIO_NUM;
    config.pin_href     = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn     = PWDN_GPIO_NUM;
    config.pin_reset    = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;        // 20MHz clock to camera sensor
    config.pixel_format = PIXFORMAT_GRAYSCALE; // Single channel — matches training data
    config.frame_size   = FRAMESIZE_96X96; // Must match EI_CLASSIFIER_INPUT_WIDTH/HEIGHT
    config.fb_count     = 2;              // Two frame buffers so capture and inference overlap
    config.grab_mode    = CAMERA_GRAB_LATEST; // Always use the most recent frame

    // ── Low-light sensor tuning (disabled for daytime) ───────────────────────
    // Uncomment when deploying with IR illuminator at night
    // sensor_t *s = esp_camera_sensor_get();
    // s->set_gainceiling(s, GAINCEILING_16X); // Boost sensor gain for low light
    // s->set_exposure_ctrl(s, 1);             // Enable auto exposure
    // s->set_gain_ctrl(s, 1);                 // Enable auto gain
    // s->set_aec2(s, 1);                      // Enable AEC2 for better exposure
    // s->set_bpc(s, 1);                       // Black pixel correction
    // s->set_wpc(s, 1);                       // White pixel correction
    // ── End low-light sensor tuning ───────────────────────────────────────────

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init FAILED: 0x%x\n", err);
        return;
    }

    Serial.println("Camera initialized. Running inference every 2 seconds...");
}

// ── Main loop ─────────────────────────────────────────────────────────────────
void loop() {
    // Capture a single frame from the camera into a frame buffer
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("ERROR: Frame capture failed");
        delay(1000);
        return;
    }

    // Point the global buffer pointer at this frame's pixel data
    // so the get_signal_data callback can read from it
    frame_buf_ptr = fb->buf;

    // Build the Edge Impulse signal descriptor
    // total_length = 96*96 = 9216 pixels
    signal_t signal;
    signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
    signal.get_data     = &get_signal_data;

    // Run the ML classifier on the captured frame
    ei_impulse_result_t result = { 0 };
    EI_IMPULSE_ERROR ei_err = run_classifier(&signal, &result, false);

    // Return the frame buffer back to the camera driver immediately after inference
    esp_camera_fb_return(fb);

    if (ei_err != EI_IMPULSE_OK) {
        Serial.printf("Classifier error: %d\n", ei_err);
        return;
    }

    // Extract confidence scores for each class from the result
    float hazard_score  = 0.0f;
    float ambient_score = 0.0f;
    for (size_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
        String label = result.classification[i].label;
        float  value = result.classification[i].value;
        if (label == "hazard_present") hazard_score  = value;
        if (label == "ambient_noise")  ambient_score = value;
    }

    // Trigger LED if hazard confidence exceeds 60% threshold
    bool hazard_detected = hazard_score > 0.6f;
    digitalWrite(LED_PIN, hazard_detected ? HIGH : LOW);

    // Print result to serial for monitoring
    Serial.printf("[Inference] hazard=%.2f  ambient=%.2f  → %s\n",
        hazard_score, ambient_score,
        hazard_detected ? "HAZARD DETECTED" : "clear");

    delay(2000); // Wait 2 seconds before next inference
}
