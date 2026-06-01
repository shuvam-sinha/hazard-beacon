#include <Arduino.h> //Core arduinoi framework
#include "esp_camera.h" //camera initialization

// ESP32-S3-EYE camera pin definition
#define PWDN_GPIO_NUM  -1 //power down (unused)
#define RESET_GPIO_NUM -1 //hardware reset (unsued)
#define XCLK_GPIO_NUM  15 //ESP32 clock
#define SIOD_GPIO_NUM  4 //SCCB data pin for camera
#define SIOC_GPIO_NUM  5 //SCCB clock for camera
#define Y9_GPIO_NUM    16 // MSB of pixel data bus
#define Y8_GPIO_NUM    17
#define Y7_GPIO_NUM    18
#define Y6_GPIO_NUM    12
#define Y5_GPIO_NUM    10
#define Y4_GPIO_NUM    8
#define Y3_GPIO_NUM    9
#define Y2_GPIO_NUM    11 //LSB of pixel data bus
#define VSYNC_GPIO_NUM 6 //Vertical sync pin - pulses once per complete frame to signal a new frame starting
#define HREF_GPIO_NUM  7 //Pulses once per row of pixels
#define PCLK_GPIO_NUM  13 //Pixel clock pin (pulses once per pixel so ESP32 knows when to read data bus)

void setup() {
  Serial.begin(115200); //baud data rate for laptop communication

  // Wait for up to 5 seconds for USB serial to connect
  uint32_t t = millis();
  while (!Serial && (millis() - t) < 5000) delay(10);
  delay(1000); //extra 1 second pause to let the serial monitor on laptop fully connect

  Serial.println("=== Hazard Beacon - Camera Init ===");

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
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
  config.xclk_freq_hz = 20000000; //20MHz - clock speed fed into the camera sensor
  config.pixel_format = PIXFORMAT_GRAYSCALE;
  config.frame_size   = FRAMESIZE_96X96;
  config.fb_count     = 2; //use 2 frame buffers in PSRAM so capture and processing can overlap
  config.grab_mode    = CAMERA_GRAB_LATEST; //grab most recent frame

  //initialize the camera
  esp_err_t err = esp_camera_init(&config); //pass the config struxt by reference and store the result
  if (err != ESP_OK) {
    Serial.printf("Camera init FAILED with error: 0x%x\n", err);
    Serial.println("Check camera pin definitions and connections.");
    return;
  }

  Serial.println("Camera initialized successfully!");
  Serial.println("Starting frame capture loop...");
}

void loop() {
  //ask the camera driver for a pointer to a captured frame buffer
  camera_fb_t *fb = esp_camera_fb_get();

  if (!fb) {
    Serial.println("ERROR: Frame capture failed");
    delay(1000);
    return;
  }

  // Send frame start marker so Python knows a new frame is coming
  Serial.println("FRAME_START");

  // Send raw pixel bytes directly over serial
  Serial.write(fb->buf, fb->len);

  // Send frame end marker so Python knows the frame is complete
  Serial.println("FRAME_END");

  esp_camera_fb_return(fb);
  delay(500);
}