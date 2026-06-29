#include <Arduino.h>
#include "esp_camera.h"
#include <hazard_beacon_inferencing.h>  // Edge Impulse generated Arduino library (model + SDK)
#include <WiFi.h>           // ESP32 WiFi driver — handles connecting to a network
#include <WiFiClientSecure.h> // TLS-capable TCP client — required for HTTPS connections
#include <HTTPClient.h>     // High-level HTTP library — builds and sends GET/POST requests
#include <ArduinoJson.h>    // JSON serialisation — builds the {"chat_id":...,"text":...} payload
#include "credentials.h"    // WiFi SSID/password and Telegram token/chat ID (gitignored)

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

// ── Telegram alert cooldown ───────────────────────────────────────────────────
// millis() returns milliseconds since boot. We compare it against the timestamp
// of the last alert to enforce a minimum gap between notifications.
static const uint32_t ALERT_COOLDOWN_MS = 30000; // 30 seconds between alerts
static uint32_t last_alert_ms = 0;                // timestamp of the last alert sent

// ── Send Telegram notification ────────────────────────────────────────────────
static void sendTelegramAlert(float score) {
    // Don't attempt if WiFi dropped — avoids a long blocking timeout
    if (WiFi.status() != WL_CONNECTED) return;

    // WiFiClientSecure handles the TLS handshake that HTTPS requires.
    // setInsecure() skips certificate verification — acceptable on a private
    // embedded device but would be a security risk in a public-facing server.
    WiFiClientSecure client;
    client.setInsecure();

    HTTPClient https;

    // The Telegram Bot API endpoint for sending a message.
    // Format: https://api.telegram.org/bot<TOKEN>/sendMessage
    String url = String("https://api.telegram.org/bot") + TELEGRAM_BOT_TOKEN + "/sendMessage";

    // Open a TCP+TLS connection to api.telegram.org
    if (!https.begin(client, url)) return;

    // Tell the server the body we're sending is JSON, not a form
    https.addHeader("Content-Type", "application/json");

    // Build the JSON payload Telegram expects:
    // { "chat_id": "...", "text": "..." }
    // ArduinoJson serialises this into a compact string automatically.
    JsonDocument doc;
    doc["chat_id"] = TELEGRAM_CHAT_ID;
    doc["text"]    = String("Hazard detected! Confidence: ") + String(score * 100, 0) + "%";

    String body;
    serializeJson(doc, body); // converts the JSON object → String

    // POST sends the request and returns the HTTP status code.
    // 200 = success, anything else means Telegram rejected it.
    int code = https.POST(body);
    Serial.printf("[Telegram] response code: %d\n", code);

    // Always close the connection — HTTPClient holds a socket open otherwise
    https.end();
}

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

    // ── WiFi connection ───────────────────────────────────────────────────────
    // WiFi.begin() starts the connection process in the background.
    // The while loop polls every 500ms until the ESP32 gets an IP address
    // from the router (WL_CONNECTED), or we give up after 15 seconds.
    // If WiFi fails, the rest of the firmware still runs — alerts just won't send.
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("Connecting to WiFi");
    uint32_t wifi_start = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - wifi_start) < 15000) {
        delay(500);
        Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
        // localIP() prints the IP the router assigned to the ESP32 (e.g. 192.168.1.42)
        Serial.printf("\nWiFi connected: %s\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("\nWiFi failed — continuing without notifications");
    }

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

    if (ei_err != EI_IMPULSE_OK) {
        esp_camera_fb_return(fb);
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

    // Send a Telegram alert every 30 seconds regardless of detection result.
    // This lets us verify the WiFi + Telegram integration works independently
    // of the ML model. Once the model is retrained on nighttime IR data and
    // detection is reliable, change this condition to: hazard_detected && ...
    if (millis() - last_alert_ms > ALERT_COOLDOWN_MS) {
        sendTelegramAlert(hazard_score);
        last_alert_ms = millis();
    }

    // Print result to serial for monitoring
    Serial.printf("[Inference] hazard=%.2f  ambient=%.2f  → %s\n",
        hazard_score, ambient_score,
        hazard_detected ? "HAZARD DETECTED" : "clear");

    // Send raw frame bytes so the laptop can save them as PNGs.
    // Header line: FRAME_START:<bytes>:<label>:<score>
    const char *label_str = hazard_detected ? "hazard" : "ambient";
    Serial.printf("FRAME_START:%u:%s:%.2f\n", fb->len, label_str,
        hazard_detected ? hazard_score : ambient_score);
    Serial.write(fb->buf, fb->len);

    // Return the frame buffer back to the camera driver
    esp_camera_fb_return(fb);
}
