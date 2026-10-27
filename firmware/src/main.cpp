#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <ESP_I2S.h>
#include <math.h>

#include "device_config_loader.h"
#include "wifi_manager.h"
#include "device_auth_client.h"

// ==================== PIN DEFINITIONS (LOCKED) ====================

constexpr int I2S_BCLK      = 4;
constexpr int I2S_WS        = 5;
constexpr int I2S_DIN       = 6;

constexpr int OLED_SDA      = 41;
constexpr int OLED_SCL      = 40;

constexpr int BUTTON_START  = 16;
constexpr int BUTTON_CANCEL = 15;

constexpr int LED_GREEN     = 17;
constexpr int LED_RED       = 18;
constexpr int BUZZER_PIN    = 21;

// ==================== AUDIO SPECIFICATIONS ====================

constexpr uint32_t SAMPLE_RATE     = 16000;
constexpr uint32_t RECORD_SECONDS  = 5;
constexpr size_t   TOTAL_SAMPLES   = SAMPLE_RATE * RECORD_SECONDS; // 80,000 samples
constexpr size_t   PCM_BYTES       = TOTAL_SAMPLES * sizeof(int16_t); // 160,000 bytes
constexpr uint32_t CAPTURE_TIMEOUT_MS = 8000;

// ==================== PERIPHERALS & BUFFERS ====================

U8G2_SH1106_128X64_NONAME_F_HW_I2C display(
    U8G2_R0,
    U8X8_PIN_NONE,
    OLED_SCL,
    OLED_SDA
);

bool oledReady = false;
uint8_t detectedOledAddress = 0;

I2SClass i2s;
bool microphoneReady = false;

int16_t* pcmBuffer = nullptr;
size_t samplesCaptured = 0;

// Read stereo frames (Left + Right 32-bit slots = 256 int32_t values = 128 stereo frames)
constexpr size_t STEREO_FRAMES_PER_READ = 128;
int32_t i2sStereoRaw[STEREO_FRAMES_PER_READ * 2];

// DC-Blocker state: y[n] = x[n] - x[n-1] + R * y[n-1], R = 255/256 (~10 Hz cutoff at 16 kHz)
int32_t dcPrevX = 0;
int32_t dcPrevY = 0;
int activeChannelOffset = 0; // 0 = Left (even index), 1 = Right (odd index)

// Challenge state
ChallengeResult activeChallenge = {};

// ==================== STATE MACHINE ====================

enum DeviceState {
    STATE_STARTING,
    STATE_READY,
    STATE_CHALLENGE_REQUESTING,
    STATE_CHALLENGE_DISPLAY,
    STATE_RECORDING,
    STATE_TRANSMITTING,
    STATE_COMPLETE,
    STATE_CANCELLED,
    STATE_ERROR
};

DeviceState state = STATE_STARTING;

uint32_t stateEnteredAt = 0;
uint32_t lastDisplayUpdate = 0;

bool previousStart = HIGH;
bool previousCancel = HIGH;
uint32_t lastButtonChange = 0;
constexpr uint32_t DEBOUNCE_MS = 35;

// ==================== BUZZER & LEDS ====================

void beep(uint32_t frequency, uint32_t durationMs) {
    if (!ledcAttach(BUZZER_PIN, frequency, 8)) {
        return;
    }
    ledcWriteTone(BUZZER_PIN, frequency);
    delay(durationMs);
    ledcWriteTone(BUZZER_PIN, 0);
    ledcDetach(BUZZER_PIN);
}

void successTone() {
    beep(1500, 80);
    delay(40);
    beep(2200, 100);
}

void errorTone() {
    beep(500, 180);
}

// ==================== OLED DISPLAY ====================

void showScreen(const char* title, const char* line1, const char* line2) {
    if (!oledReady) return;

    display.clearBuffer();
    display.setFont(u8g2_font_6x12_tf);
    display.drawStr(0, 10, "VOICELOCK ENTERPRISE");
    display.drawHLine(0, 12, 128);

    display.setFont(u8g2_font_ncenB08_tr);
    display.drawStr(0, 28, title);

    display.setFont(u8g2_font_6x12_tf);
    display.drawStr(0, 44, line1);
    display.drawStr(0, 59, line2);
    display.sendBuffer();
}

void showChallengeScreen(const char* displayDigits, uint32_t remainingSecs) {
    if (!oledReady) return;

    display.clearBuffer();
    display.setFont(u8g2_font_6x12_tf);
    display.drawStr(0, 10, "LIVENESS CHALLENGE");
    display.drawHLine(0, 12, 128);

    display.setFont(u8g2_font_6x12_tf);
    display.drawStr(0, 24, "Speak Digits Clearly:");

    // Prominent digit font
    display.setFont(u8g2_font_logisoso16_tr);
    display.drawStr(24, 46, displayDigits ? displayDigits : "---");

    display.setFont(u8g2_font_6x12_tf);
    char expBuf[32];
    snprintf(expBuf, sizeof(expBuf), "Expires in: %lu s", (unsigned long)remainingSecs);
    display.drawStr(0, 60, expBuf);
    display.sendBuffer();
}

void updateDisplay() {
    char line2Buf[32];

    switch (state) {
        case STATE_STARTING:
            showScreen("Starting", "Init mic & PSRAM", "");
            break;

        case STATE_READY:
            if (isWifiConnected()) {
                String ip = getWifiStatusString();
                showScreen("Ready (Connected)", "Press START: Challenge", ip.c_str());
            } else {
                showScreen("Ready (Offline)", "Press START: Capture", "Serial mode active");
            }
            break;

        case STATE_CHALLENGE_REQUESTING:
            showScreen("Requesting...", "Contacting Azure", "POST /challenge");
            break;

        case STATE_CHALLENGE_DISPLAY: {
            uint32_t elapsedSecs = (millis() - stateEnteredAt) / 1000;
            uint32_t remaining = (activeChallenge.expiresInSeconds > elapsedSecs) 
                ? (activeChallenge.expiresInSeconds - elapsedSecs) : 0;
            showChallengeScreen(activeChallenge.display, remaining);
            break;
        }

        case STATE_RECORDING: {
            uint32_t pct = (samplesCaptured * 100) / TOTAL_SAMPLES;
            snprintf(line2Buf, sizeof(line2Buf), "Captured: %lu%%", (unsigned long)pct);
            showScreen("Recording 5s", "Speak clearly now", line2Buf);
            break;
        }

        case STATE_TRANSMITTING:
            showScreen("Sending PCM", "160,000 bytes", "Do not unplug USB");
            break;

        case STATE_COMPLETE:
            showScreen("Test Complete", "WAV sent to Mac", "Check Python output");
            break;

        case STATE_CANCELLED:
            showScreen("Cancelled", "Action aborted", "Returning to READY");
            break;

        case STATE_ERROR:
            showScreen("System Error", "See Serial output", "Press CANCEL");
            break;
    }
}

void setState(DeviceState newState) {
    state = newState;
    stateEnteredAt = millis();
    updateDisplay();
}

// ==================== BUFFER & I2S INITIALIZATION ====================

bool allocatePcmBuffer() {
    if (psramFound()) {
        pcmBuffer = static_cast<int16_t*>(ps_malloc(PCM_BYTES));
    } else {
        pcmBuffer = static_cast<int16_t*>(malloc(PCM_BYTES));
    }
    return (pcmBuffer != nullptr);
}

void detectActiveI2SChannel() {
    for (int flush = 0; flush < 15; flush++) {
        i2s.readBytes(reinterpret_cast<char*>(i2sStereoRaw), sizeof(i2sStereoRaw));
    }

    size_t bytesRead = i2s.readBytes(reinterpret_cast<char*>(i2sStereoRaw), sizeof(i2sStereoRaw));
    size_t frames = bytesRead / (2 * sizeof(int32_t));
    if (frames < 8) {
        activeChannelOffset = 0;
        return;
    }

    int64_t nonZeroEven = 0;
    int64_t nonZeroOdd  = 0;

    for (size_t i = 0; i < frames; i++) {
        int32_t sEven = i2sStereoRaw[i * 2] >> 8;
        int32_t sOdd  = i2sStereoRaw[i * 2 + 1] >> 8;
        if (sEven != 0) nonZeroEven += abs(sEven);
        if (sOdd != 0)  nonZeroOdd  += abs(sOdd);
    }

    activeChannelOffset = (nonZeroOdd > nonZeroEven * 4) ? 1 : 0;
}

bool initializeMicrophone() {
    i2s.setPins(I2S_BCLK, I2S_WS, -1, I2S_DIN, -1);

    bool ok = i2s.begin(
        I2S_MODE_STD,
        SAMPLE_RATE,
        I2S_DATA_BIT_WIDTH_32BIT,
        I2S_SLOT_MODE_STEREO
    );

    if (ok) {
        detectActiveI2SChannel();
    }
    return ok;
}

// ==================== SAMPLE CONVERSION ====================

inline int16_t convertI2SSlotToPcm16(int32_t rawSlot32) {
    int32_t sample24 = rawSlot32 >> 8;

    int32_t diff = sample24 - dcPrevX;
    dcPrevX = sample24;
    int32_t filtered24 = diff + ((dcPrevY * 255) >> 8);
    dcPrevY = filtered24;

    int32_t pcm32 = filtered24 >> 6;

    if (pcm32 > 32767)  pcm32 = 32767;
    if (pcm32 < -32768) pcm32 = -32768;

    return static_cast<int16_t>(pcm32);
}

// ==================== RECORDING & PROTOCOL FLOW ====================

void beginRecording() {
    if (state == STATE_ERROR || pcmBuffer == nullptr || !microphoneReady) {
        return;
    }

    for (int i = 0; i < 4; i++) {
        size_t b = i2s.readBytes(reinterpret_cast<char*>(i2sStereoRaw), sizeof(i2sStereoRaw));
        size_t frames = b / (2 * sizeof(int32_t));
        if (frames > 0) {
            dcPrevX = i2sStereoRaw[(frames - 1) * 2 + activeChannelOffset] >> 8;
            dcPrevY = 0;
        }
    }

    samplesCaptured = 0;
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);
    beep(1800, 70);

    Serial.print("STARTING\n");
    Serial.flush();

    setState(STATE_RECORDING);
}

void cancelAction() {
    if (state == STATE_RECORDING || state == STATE_CHALLENGE_DISPLAY || state == STATE_CHALLENGE_REQUESTING) {
        samplesCaptured = 0;
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, HIGH);
        errorTone();

        Serial.print("CANCELLED\n");
        Serial.flush();

        setState(STATE_CANCELLED);
    }
}

void captureStep() {
    if (millis() - stateEnteredAt > CAPTURE_TIMEOUT_MS) {
        digitalWrite(LED_RED, HIGH);
        errorTone();
        Serial.print("ERROR_I2S_TIMEOUT\n");
        setState(STATE_ERROR);
        return;
    }

    size_t remaining = TOTAL_SAMPLES - samplesCaptured;
    if (remaining == 0) {
        setState(STATE_TRANSMITTING);
        return;
    }

    size_t framesToRequest = (remaining < STEREO_FRAMES_PER_READ) ? remaining : STEREO_FRAMES_PER_READ;
    size_t bytesRequested = framesToRequest * 2 * sizeof(int32_t);

    size_t bytesRead = i2s.readBytes(reinterpret_cast<char*>(i2sStereoRaw), bytesRequested);
    size_t framesRead = bytesRead / (2 * sizeof(int32_t));

    for (size_t i = 0; i < framesRead && samplesCaptured < TOTAL_SAMPLES; i++) {
        int32_t rawSlot = i2sStereoRaw[i * 2 + activeChannelOffset];
        pcmBuffer[samplesCaptured++] = convertI2SSlotToPcm16(rawSlot);
    }

    if (samplesCaptured >= TOTAL_SAMPLES) {
        setState(STATE_TRANSMITTING);
    }
}

void transmitAudioPayload() {
    Serial.print("AUDIO_BEGIN\n");
    Serial.flush();

    const uint8_t* bytePtr = reinterpret_cast<const uint8_t*>(pcmBuffer);
    size_t bytesRemaining = PCM_BYTES;
    constexpr size_t TX_CHUNK_SIZE = 4096;

    while (bytesRemaining > 0) {
        size_t toWrite = (bytesRemaining < TX_CHUNK_SIZE) ? bytesRemaining : TX_CHUNK_SIZE;
        size_t written = Serial.write(bytePtr, toWrite);
        bytePtr += written;
        bytesRemaining -= written;
    }
    Serial.flush();

    Serial.print("AUDIO_END\n");
    Serial.flush();

    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);
    beep(1800, 60);

    setState(STATE_COMPLETE);
    setState(STATE_READY);
    Serial.print("READY\n");
    Serial.flush();
}

// ==================== CHALLENGE REQUEST FLOW ====================

void startChallengeRequest() {
    if (!isWifiConnected()) {
        showScreen("No Wi-Fi", "Wi-Fi is offline", "Cannot request API");
        errorTone();
        delay(1500);
        setState(STATE_READY);
        return;
    }

    setState(STATE_CHALLENGE_REQUESTING);
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);
    beep(1600, 50);

    Serial.print("CHALLENGE_REQUESTING\n");
    Serial.flush();

    activeChallenge = requestLivenessChallenge(
        VOICELOCK_BACKEND_HOST,
        VOICELOCK_BACKEND_PORT,
        DEVICE_ID,
        DEVICE_SECRET,
        DEFAULT_CLAIMED_IDENTITY,
        8000
    );

    if (activeChallenge.success) {
        // Neutral prompt indication: digits received and displayed on OLED screen.
        // Green LED is strictly prohibited from illuminating until server authorization (Milestone 3).
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, LOW);
        beep(2000, 40);

        Serial.printf("CHALLENGE_RECEIVED:{\"id\":\"%s\",\"digits\":\"%s\",\"display\":\"%s\"}\n",
                      activeChallenge.challengeId, activeChallenge.digits, activeChallenge.display);
        Serial.flush();

        setState(STATE_CHALLENGE_DISPLAY);
    } else {
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, HIGH);
        errorTone();

        Serial.printf("CHALLENGE_ERROR:%s (HTTP %d)\n", activeChallenge.errorMessage, activeChallenge.httpCode);
        Serial.flush();

        showScreen("Auth Failed", activeChallenge.errorMessage, "Returning to READY");
        delay(2500);
        setState(STATE_READY);
        Serial.print("READY\n");
        Serial.flush();
    }
}

// ==================== BUTTON POLLING ====================

void pollButtons() {
    bool startNow = digitalRead(BUTTON_START);
    bool cancelNow = digitalRead(BUTTON_CANCEL);
    uint32_t now = millis();

    if (startNow != previousStart) {
        previousStart = startNow;
        if (startNow == LOW && (now - lastButtonChange >= DEBOUNCE_MS)) {
            lastButtonChange = now;
            if (state == STATE_READY || state == STATE_CANCELLED || state == STATE_COMPLETE) {
                if (isWifiConnected()) {
                    startChallengeRequest();
                } else {
                    beginRecording();
                }
            }
        }
    }

    if (cancelNow != previousCancel) {
        previousCancel = cancelNow;
        if (cancelNow == LOW && (now - lastButtonChange >= DEBOUNCE_MS)) {
            lastButtonChange = now;
            cancelAction();
        }
    }
}

// ==================== SETUP & LOOP ====================

void setup() {
    Serial.begin(115200);

    uint32_t waitStart = millis();
    while (!Serial && (millis() - waitStart < 3000)) {
        delay(10);
    }
    delay(200);

    pinMode(BUTTON_START, INPUT_PULLUP);
    pinMode(BUTTON_CANCEL, INPUT_PULLUP);
    pinMode(LED_GREEN, OUTPUT);
    pinMode(LED_RED, OUTPUT);
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);

    // Initialize OLED on SDA=41, SCL=40
    Wire.begin(OLED_SDA, OLED_SCL);
    Wire.setClock(100000);

    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0 && (addr == 0x3C || addr == 0x3D)) {
            detectedOledAddress = addr;
        }
    }
    if (detectedOledAddress != 0) {
        display.setI2CAddress(detectedOledAddress << 1);
    }
    oledReady = display.begin();
    Wire.setClock(100000);

    setState(STATE_STARTING);

    bool ramOk = allocatePcmBuffer();
    microphoneReady = initializeMicrophone();

    if (!ramOk || !microphoneReady) {
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, HIGH);
        errorTone();
        setState(STATE_ERROR);
        Serial.print("ERROR_INIT_FAILED\n");
        Serial.flush();
        return;
    }

    // Step 2: Wi-Fi and SNTP Initialization
    bool wifiOk = initWifi(8000, showScreen);
    if (wifiOk) {
        syncNtpTime(5000, showScreen);
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, LOW);
        beep(1800, 60);
    } else {
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, HIGH);
        beep(800, 100);
        delay(1500);
        digitalWrite(LED_RED, LOW);
    }

    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);
    setState(STATE_READY);
    Serial.print("READY\n");
    Serial.flush();
}

void loop() {
    pollButtons();

    if (state == STATE_READY) {
        maintainWifi();

        static uint32_t lastReadyPing = 0;
        if (millis() - lastReadyPing >= 2000) {
            lastReadyPing = millis();
            Serial.print("READY\n");
            Serial.flush();
        }

        while (Serial.available() > 0) {
            char c = static_cast<char>(Serial.read());
            if (c == 'R') {
                beginRecording();
                break;
            } else if (c == 'C') {
                startChallengeRequest();
                break;
            }
        }
    }

    switch (state) {
        case STATE_CHALLENGE_DISPLAY: {
            uint32_t displayDurationMs = (activeChallenge.expiresInSeconds > 0)
                ? min((uint32_t)(activeChallenge.expiresInSeconds * 1000), (uint32_t)25000)
                : 20000;
            if (millis() - stateEnteredAt >= displayDurationMs) {
                setState(STATE_READY);
                Serial.print("READY\n");
                Serial.flush();
            } else if (millis() - lastDisplayUpdate >= 500) {
                lastDisplayUpdate = millis();
                updateDisplay();
            }
            break;
        }

        case STATE_RECORDING:
            captureStep();
            if (millis() - lastDisplayUpdate >= 250) {
                lastDisplayUpdate = millis();
                updateDisplay();
            }
            break;

        case STATE_TRANSMITTING:
            transmitAudioPayload();
            break;

        case STATE_CANCELLED:
            if (millis() - stateEnteredAt >= 1500) {
                digitalWrite(LED_GREEN, LOW);
                digitalWrite(LED_RED, LOW);
                setState(STATE_READY);
                Serial.print("READY\n");
                Serial.flush();
            }
            break;

        default:
            break;
    }
}
