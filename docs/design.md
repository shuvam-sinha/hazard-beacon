## Design: fixed scene, locked exposure

The camera watches one unchanging scene, so "empty" looks nearly identical frame to frame and anything that differs is what matters. That makes the problem tractable on a microcontroller in a way general-purpose object detection is not — the model only has to separate *this* background from *this* background with a person in it.

That framing hides a subtle trap — and it's the reason the exposure is locked. If auto-exposure were left on, a person entering the frame would lower the average brightness, and the sensor would compensate by raising exposure and brightening the background. **Background brightness would then track the label**, handing the model an easy shortcut: judge the scene by how bright it is rather than by what's in it. Such a shortcut is brittle — it holds only while lighting stays constant and breaks the moment the light changes or something bright but harmless enters view. Locking exposure removes the shortcut, forcing the model to rely on the actual contents of the frame.

The fix is to lock exposure, gain, and white balance so the background renders identically every frame:

```cpp
sensor_t *s = esp_camera_sensor_get();
if (s) {
    const int AEC_VALUE = 300;      // fixed exposure — tune once to the scene
    const int AGC_GAIN  = 0;        // fixed gain (0 = lowest)
    s->set_exposure_ctrl(s, 0);     // disable auto exposure
    s->set_aec2(s, 0);
    s->set_aec_value(s, AEC_VALUE);
    s->set_gain_ctrl(s, 0);         // disable auto gain
    s->set_agc_gain(s, AGC_GAIN);
    s->set_whitebal(s, 0);          // disable auto white balance
}
```

Two rules follow: these calls must run **after** `esp_camera_init()` (settings applied earlier are discarded), and the **same `AEC_VALUE` is used for both data collection and deployment** — otherwise every deployed frame is out of distribution.
