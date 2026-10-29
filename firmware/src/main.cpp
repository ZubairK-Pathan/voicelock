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
constexpr int BUZZER_PIN_POS = 21; // Connect BOTH buzzer (+) legs here
constexpr int BUZZER_PIN_NEG = 14; // Connect BOTH buzzer (-) legs here

// ==================== AUDIO SPECIFICATIONS ====================

constexpr uint32_t SAMPLE_RATE     = 16000;
constexpr uint32_t RECORD_SECONDS  = 5;
constexpr size_t   TOTAL_SAMPLES   = SAMPLE_RATE * RECORD_SECONDS; // 80,000 samples
constexpr size_t   PCM_BYTES       = TOTAL_SAMPLES * sizeof(int16_t); // 160,000 bytes
constexpr uint32_t CAPTURE_TIMEOUT_MS = 8000;

// ==================== PERIPHERALS & BUFFERS ====================

// Use _SW_I2C to bypass ESP32-S3 hardware I2C peripheral lockups on GPIO 40/41
U8G2_SH1106_128X64_NONAME_F_SW_I2C display(
    U8G2_R0,
    OLED_SCL,
    OLED_SDA,
    U8X8_PIN_NONE
);

// Override Arduino loopTask stack size from default 8192 to 16384 bytes
// to prevent stack overflow during TLS handshake and multipart audio upload
size_t getArduinoLoopTaskStackSize(void) {
    return 16384;
}

bool oledReady = false;
uint8_t detectedOledAddress = 0;

I2SClass i2s;
bool microphoneReady = false;

int16_t* pcmBuffer = nullptr;
size_t samplesCaptured = 0;
size_t captureZeroReads = 0;
size_t captureLastReadBytes = 0;

// Read stereo frames (Left + Right 32-bit slots = 256 int32_t values = 128 stereo frames)
constexpr size_t STEREO_FRAMES_PER_READ = 128;
int32_t i2sStereoRaw[STEREO_FRAMES_PER_READ * 2];

// DC-Blocker state: y[n] = x[n] - x[n-1] + R * y[n-1], R = 255/256 (~10 Hz cutoff at 16 kHz)
int32_t dcPrevX = 0;
int32_t dcPrevY = 0;
int activeChannelOffset = 0; // 0 = Left (even index), 1 = Right (odd index)

// Challenge & Verification states
ChallengeResult activeChallenge = {};
VerifyResult activeVerifyResult = {};
bool isVerificationFlow = false;
uint32_t resultDisplayHoldMs = 2500;

// ==================== STATE MACHINE ====================

enum DeviceState {
    STATE_STARTING,
    STATE_READY,
    STATE_CHALLENGE_REQUESTING,
    STATE_CHALLENGE_DISPLAY,
    STATE_RECORDING,
    STATE_UPLOADING,
    STATE_RESULT,
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
    if (frequency == 0 || durationMs == 0) return;

    pinMode(BUZZER_PIN_POS, OUTPUT);
    pinMode(BUZZER_PIN_NEG, OUTPUT);

    uint32_t halfPeriodUs = 500000UL / frequency;
    uint32_t startMs = millis();

    while (millis() - startMs < durationMs) {
        // Push (+3.3V across piezo)
        digitalWrite(BUZZER_PIN_POS, HIGH);
        digitalWrite(BUZZER_PIN_NEG, LOW);
        delayMicroseconds(halfPeriodUs);

        // Pull (-3.3V across piezo = 6.6V peak-to-peak swing!)
        digitalWrite(BUZZER_PIN_POS, LOW);
        digitalWrite(BUZZER_PIN_NEG, HIGH);
        delayMicroseconds(halfPeriodUs);
    }

    // Set both LOW so zero current flows when idle
    digitalWrite(BUZZER_PIN_POS, LOW);
    digitalWrite(BUZZER_PIN_NEG, LOW);
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
    display.setFont(u8g2_font_6x10_tf);
    display.drawStr(4, 10, "VOICELOCK ENTERPRISE");
    display.drawHLine(0, 13, 128);

    display.setFont(u8g2_font_7x14B_tf);
    if (title && title[0]) {
        char tBuf[20];
        strncpy(tBuf, title, 18);
        tBuf[18] = '\0';
        display.drawStr(4, 28, tBuf);
    }

    display.setFont(u8g2_font_6x10_tf);
    if (line1 && line1[0]) {
        char l1Buf[22];
        strncpy(l1Buf, line1, 20);
        l1Buf[20] = '\0';
        display.drawStr(4, 43, l1Buf);
    }
    if (line2 && line2[0]) {
        char l2Buf[22];
        strncpy(l2Buf, line2, 20);
        l2Buf[20] = '\0';
        display.drawStr(4, 57, l2Buf);
    }
    display.sendBuffer();
}

constexpr uint32_t CHALLENGE_PREP_MS = 3500;

void showChallengeScreen(const char* displayDigits, uint32_t elapsedMs = 0, uint32_t totalMs = CHALLENGE_PREP_MS) {
    if (!oledReady) return;

    display.clearBuffer();
    display.setFont(u8g2_font_6x10_tf);
    display.drawStr(4, 10, "LIVENESS CHALLENGE");
    display.drawHLine(0, 13, 128);

    display.setFont(u8g2_font_6x10_tf);
    display.drawStr(4, 24, "Get Ready to Speak:");

    const char* digits = displayDigits ? displayDigits : "---";
    display.setFont(u8g2_font_fub14_tr);
    int w = display.getStrWidth(digits);
    int x = (128 - w) / 2;
    if (x < 4) x = 4;
    display.drawStr(x, 42, digits);

    display.setFont(u8g2_font_6x10_tf);
    uint32_t remainingSec = (totalMs > elapsedMs) ? ((totalMs - elapsedMs + 999) / 1000) : 0;
    char hintBuf[32];
    snprintf(hintBuf, sizeof(hintBuf), "Recording in %lus...", (unsigned long)remainingSec);
    display.drawStr(4, 58, hintBuf);
    display.sendBuffer();
}

void showRecordingScreen(const char* displayDigits, uint32_t currentSamples, uint32_t totalSamples) {
    if (!oledReady) return;

    display.clearBuffer();
    display.setFont(u8g2_font_6x10_tf);
    display.drawStr(4, 10, "SPEAK DIGITS CLEARLY");
    display.drawHLine(0, 13, 128);

    const char* digits = displayDigits ? displayDigits : "---";
    display.setFont(u8g2_font_fub14_tr);
    int w = display.getStrWidth(digits);
    int x = (128 - w) / 2;
    if (x < 4) x = 4;
    display.drawStr(x, 28, digits);

    uint32_t pct = (totalSamples > 0) ? (currentSamples * 100) / totalSamples : 0;
    if (pct > 100) pct = 100;
    int barX = 14;
    int barY = 34;
    int barW = 100;
    int barH = 8;
    display.drawFrame(barX, barY, barW, barH);
    int fillW = (pct * (barW - 4)) / 100;
    if (fillW > 0) {
        display.drawBox(barX + 2, barY + 2, fillW, barH - 4);
    }

    char progressStr[32];
    snprintf(progressStr, sizeof(progressStr), "Recording: %lu%%", (unsigned long)pct);
    display.setFont(u8g2_font_6x10_tf);
    int pw = display.getStrWidth(progressStr);
    display.drawStr((128 - pw) / 2, 57, progressStr);
    display.sendBuffer();
}

void showResultScreen(const VerifyResult& res) {
    if (!oledReady) return;

    display.clearBuffer();
    display.setFont(u8g2_font_6x10_tf);
    display.drawStr(4, 10, "VOICELOCK VERIFICATION");
    display.drawHLine(0, 13, 128);

    if (res.isUnlock) {
        display.setFont(u8g2_font_7x14B_tf);
        display.drawStr(4, 28, "ACCESS GRANTED");
        display.setFont(u8g2_font_6x10_tf);
        char sBuf[80];
        snprintf(sBuf, sizeof(sBuf), "User: %s", res.claimedIdentity);
        display.drawStr(4, 43, sBuf);
        char scoreBuf[32];
        snprintf(scoreBuf, sizeof(scoreBuf), "Similarity: %.4f", res.similarity);
        display.drawStr(4, 57, scoreBuf);
    } else if (res.httpCode == 200) {
        display.setFont(u8g2_font_7x14B_tf);
        display.drawStr(4, 28, "ACCESS DENIED");
        display.setFont(u8g2_font_6x10_tf);

        if (res.reason[0] != '\0') {
            char rBuf[22];
            strncpy(rBuf, res.reason, 20);
            rBuf[20] = '\0';
            display.drawStr(4, 43, rBuf);
        } else if (!res.livenessPassed) {
            display.drawStr(4, 43, "Liveness Failed");
        } else {
            display.drawStr(4, 43, "Voice Mismatch");
        }

        char scoreBuf[32];
        if (res.similarity > 0.0f) {
            snprintf(scoreBuf, sizeof(scoreBuf), "Score: %.4f (min 0.25)", res.similarity);
        } else {
            snprintf(scoreBuf, sizeof(scoreBuf), "Liveness: %s", res.livenessPassed ? "Pass" : "Fail");
        }
        display.drawStr(4, 57, scoreBuf);
    } else {
        display.setFont(u8g2_font_7x14B_tf);
        display.drawStr(4, 28, "AUTH / HTTP ERROR");
        display.setFont(u8g2_font_6x10_tf);
        char hBuf[32];
        snprintf(hBuf, sizeof(hBuf), "HTTP Status: %d", res.httpCode);
        display.drawStr(4, 43, hBuf);
        char errBuf[22];
        strncpy(errBuf, res.errorMessage[0] ? res.errorMessage : "Failed", 20);
        errBuf[20] = '\0';
        display.drawStr(4, 57, errBuf);
    }
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
                showScreen("Ready (Connected)", "Press START: Verify", ip.c_str());
            } else {
                showScreen("Ready (Offline)", "Press START: Capture", "Serial mode active");
            }
            break;

        case STATE_CHALLENGE_REQUESTING:
            showScreen("Requesting...", "Contacting Azure", "POST /challenge");
            break;

        case STATE_CHALLENGE_DISPLAY: {
            uint32_t elapsed = millis() - stateEnteredAt;
            showChallengeScreen(activeChallenge.display, elapsed, CHALLENGE_PREP_MS);
            break;
        }

        case STATE_RECORDING:
            if (isVerificationFlow) {
                showRecordingScreen(activeChallenge.display, samplesCaptured, TOTAL_SAMPLES);
            } else {
                uint32_t pct = (samplesCaptured * 100) / TOTAL_SAMPLES;
                snprintf(line2Buf, sizeof(line2Buf), "Captured: %lu%%", (unsigned long)pct);
                showScreen("Recording 5s", "Speak clearly now", line2Buf);
            }
            break;

        case STATE_UPLOADING:
            showScreen("Verifying", "Uploading audio...", "POST /verify");
            break;

        case STATE_RESULT:
            showResultScreen(activeVerifyResult);
            break;

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
    bool hasPsram = psramFound();
    if (hasPsram) {
        pcmBuffer = static_cast<int16_t*>(ps_malloc(PCM_BYTES));
        Serial.printf("PCM_BUFFER_ALLOCATED:PSRAM (free_psram=%lu, free_heap=%lu)\n",
                      (unsigned long)ESP.getFreePsram(), (unsigned long)ESP.getFreeHeap());
    } else {
        pcmBuffer = static_cast<int16_t*>(malloc(PCM_BYTES));
        Serial.printf("PCM_BUFFER_ALLOCATED:INTERNAL_HEAP (free_heap=%lu)\n",
                      (unsigned long)ESP.getFreeHeap());
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

    // In ICS-43434 with LR=GND, the microphone transmits data on the Left slot (WS=0, even index)
    // Default strictly to Left channel (slot 0)
    activeChannelOffset = 0;
    if (nonZeroOdd > nonZeroEven * 4 && nonZeroOdd > 1000) {
        activeChannelOffset = 1;
    }
    Serial.printf("I2S_CHANNEL_SELECT:{\"active\":%d,\"left_mag\":%lld,\"right_mag\":%lld}\n",
                  activeChannelOffset, (long long)nonZeroEven, (long long)nonZeroOdd);
    Serial.flush();
}

void runI2SDiagnostic(uint32_t durationMs = 1000) {
    if (!microphoneReady) {
        Serial.println("I2S_DIAG_ERROR:Microphone not initialized");
        return;
    }

    Serial.println("I2S_DIAG_START:Sampling stereo frames (1s)");
    int64_t sumSqEven = 0;
    int64_t sumSqOdd = 0;
    int32_t minEven = 2147483647, maxEven = -2147483648;
    int32_t minOdd = 2147483647, maxOdd = -2147483648;
    size_t totalFrames = 0;

    uint32_t startMs = millis();
    while (millis() - startMs < durationMs) {
        size_t bytesRead = i2s.readBytes(reinterpret_cast<char*>(i2sStereoRaw), sizeof(i2sStereoRaw));
        size_t frames = bytesRead / (2 * sizeof(int32_t));
        for (size_t i = 0; i < frames; i++) {
            int32_t sEven = i2sStereoRaw[i * 2] >> 8;
            int32_t sOdd = i2sStereoRaw[i * 2 + 1] >> 8;

            sumSqEven += (int64_t)sEven * sEven;
            sumSqOdd += (int64_t)sOdd * sOdd;

            if (sEven < minEven) minEven = sEven;
            if (sEven > maxEven) maxEven = sEven;
            if (sOdd < minOdd) minOdd = sOdd;
            if (sOdd > maxOdd) maxOdd = sOdd;

            totalFrames++;
        }
    }

    if (totalFrames == 0) {
        Serial.println("I2S_DIAG_ERROR:Zero frames read from DMA");
        return;
    }

    double rmsEven = sqrt((double)sumSqEven / totalFrames);
    double rmsOdd = sqrt((double)sumSqOdd / totalFrames);

    Serial.printf("I2S_DIAG:{\"frames\":%u,\"ch0_left_rms\":%.1f,\"ch0_min\":%ld,\"ch0_max\":%ld,\"ch1_right_rms\":%.1f,\"ch1_min\":%ld,\"ch1_max\":%ld,\"active_channel\":%d}\n",
                  (unsigned int)totalFrames, rmsEven, (long)minEven, (long)maxEven, rmsOdd, (long)minOdd, (long)maxOdd, activeChannelOffset);
    Serial.flush();
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

void beginRecording(bool forVerification = false) {
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

    isVerificationFlow = forVerification;
    samplesCaptured = 0;
    captureZeroReads = 0;
    captureLastReadBytes = 0;
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);
    beep(1800, 70);

    Serial.print("STARTING\n");
    Serial.flush();

    setState(STATE_RECORDING);
}

void cancelAction() {
    if (state == STATE_RECORDING || state == STATE_CHALLENGE_DISPLAY || state == STATE_CHALLENGE_REQUESTING || state == STATE_UPLOADING) {
        samplesCaptured = 0;
        captureZeroReads = 0;
        captureLastReadBytes = 0;
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, HIGH);
        errorTone();

        Serial.print("CANCELLED\n");
        Serial.flush();

        setState(STATE_CANCELLED);
    }
}

void dispatchVerificationUpload() {
    if (state == STATE_CANCELLED) {
        return;
    }
    setState(STATE_UPLOADING);
    Serial.print("UPLOADING_VERIFICATION\n");
    Serial.flush();

    activeVerifyResult = uploadAudioVerification(
        VOICELOCK_BACKEND_HOST,
        VOICELOCK_BACKEND_PORT,
        DEVICE_ID,
        DEVICE_SECRET,
        DEFAULT_CLAIMED_IDENTITY,
        activeChallenge.challengeId,
        activeChallenge.sessionId,
        pcmBuffer,
        PCM_BYTES,
        15000
    );

    // If cancellation was invoked during upload, discard response
    if (state == STATE_CANCELLED) {
        digitalWrite(LED_GREEN, LOW);
        return;
    }

    if (activeVerifyResult.isUnlock) {
        // Explicit backend authorization: activate green LED and chime
        digitalWrite(LED_GREEN, HIGH);
        digitalWrite(LED_RED, LOW);
        successTone();
        resultDisplayHoldMs = 3500;
        Serial.printf("VERIFY_GRANTED:{\"identity\":\"%s\",\"similarity\":%.4f}\n",
                      activeVerifyResult.claimedIdentity, activeVerifyResult.similarity);
    } else if (activeVerifyResult.httpCode == 200) {
        // Explicit biometric denial or liveness failure: red LED and error tone
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, HIGH);
        errorTone();
        resultDisplayHoldMs = 2500;
        Serial.printf("VERIFY_DENIED:{\"liveness\":%s,\"similarity\":%.4f,\"reason\":\"%s\"}\n",
                      activeVerifyResult.livenessPassed ? "true" : "false",
                      activeVerifyResult.similarity,
                      activeVerifyResult.reason);
    } else {
        // HTTP or network error: red LED and error tone, green LED strictly OFF
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, HIGH);
        errorTone();
        resultDisplayHoldMs = 2500;
        Serial.printf("VERIFY_ERROR:{\"http\":%d,\"error\":\"%s\"}\n",
                      activeVerifyResult.httpCode, activeVerifyResult.errorMessage);
    }
    Serial.flush();
    setState(STATE_RESULT);
}

void captureStep() {
    if (millis() - stateEnteredAt > CAPTURE_TIMEOUT_MS) {
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, HIGH);
        errorTone();
        uint32_t elapsedMs = millis() - stateEnteredAt;
        Serial.printf("ERROR_I2S_TIMEOUT:{\"captured\":%u,\"target\":%u,\"elapsed_ms\":%lu,\"zero_reads\":%u,\"last_read_bytes\":%u}\n",
                      (unsigned int)samplesCaptured,
                      (unsigned int)TOTAL_SAMPLES,
                      (unsigned long)elapsedMs,
                      (unsigned int)captureZeroReads,
                      (unsigned int)captureLastReadBytes);
        Serial.flush();
        setState(STATE_ERROR);
        return;
    }

    size_t remaining = TOTAL_SAMPLES - samplesCaptured;
    if (remaining == 0) {
        if (isVerificationFlow) {
            setState(STATE_UPLOADING);
        } else {
            setState(STATE_TRANSMITTING);
        }
        return;
    }

    size_t framesToRequest = (remaining < STEREO_FRAMES_PER_READ) ? remaining : STEREO_FRAMES_PER_READ;
    size_t bytesRequested = framesToRequest * 2 * sizeof(int32_t);

    size_t bytesRead = i2s.readBytes(reinterpret_cast<char*>(i2sStereoRaw), bytesRequested);
    captureLastReadBytes = bytesRead;
    if (bytesRead == 0) {
        captureZeroReads++;
    }
    size_t framesRead = bytesRead / (2 * sizeof(int32_t));

    for (size_t i = 0; i < framesRead && samplesCaptured < TOTAL_SAMPLES; i++) {
        int32_t rawSlot = i2sStereoRaw[i * 2 + activeChannelOffset];
        pcmBuffer[samplesCaptured++] = convertI2SSlotToPcm16(rawSlot);
    }

    if (samplesCaptured >= TOTAL_SAMPLES) {
        if (isVerificationFlow) {
            setState(STATE_UPLOADING);
        } else {
            setState(STATE_TRANSMITTING);
        }
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

    time_t curTime = time(nullptr);
    if (curTime < 1700000000) {
        Serial.println("NTP_RESYNCING_FOR_CHALLENGE");
        showScreen("TIME SYNC", "Resyncing NTP...", "Please wait");
        syncNtpTime(8000, showScreen);
        curTime = time(nullptr);
        if (curTime < 1700000000) {
            showScreen("Time Not Set", "NTP sync required", "Press START again");
            errorTone();
            delay(2000);
            setState(STATE_READY);
            return;
        }
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
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, LOW);
        beep(2000, 40);

        // Sanitize serial output: log challenge digits for UI validation without dumping raw session tokens
        Serial.printf("CHALLENGE_RECEIVED:{\"digits\":\"%s\",\"display\":\"%s\"}\n",
                      activeChallenge.digits, activeChallenge.display);
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
            if (state == STATE_READY || state == STATE_CANCELLED || state == STATE_COMPLETE || state == STATE_RESULT) {
                if (isWifiConnected()) {
                    startChallengeRequest();
                } else {
                    beginRecording(false);
                }
            } else if (state == STATE_CHALLENGE_DISPLAY) {
                // User is ready to speak immediately, skip remaining countdown
                beginRecording(true);
            }
        }
    }

    if (cancelNow != previousCancel) {
        previousCancel = cancelNow;
        if (cancelNow == LOW && (now - lastButtonChange >= DEBOUNCE_MS)) {
            lastButtonChange = now;
            if (state == STATE_RECORDING || state == STATE_CHALLENGE_DISPLAY || state == STATE_CHALLENGE_REQUESTING || state == STATE_UPLOADING) {
                cancelAction();
            }
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
    // Boot visual self-test: flash both LEDs briefly (250ms) to verify physical wiring
    digitalWrite(LED_GREEN, HIGH);
    digitalWrite(LED_RED, HIGH);
    delay(250);
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);

    pinMode(BUZZER_PIN_POS, OUTPUT);
    pinMode(BUZZER_PIN_NEG, OUTPUT);
    digitalWrite(BUZZER_PIN_POS, LOW);
    digitalWrite(BUZZER_PIN_NEG, LOW);

    // Give SH1106 controller time to stabilize power rail
    delay(150);

    // Diagnostic check using Wire first to verify physical wiring on 41/40
    pinMode(OLED_SDA, INPUT_PULLUP);
    pinMode(OLED_SCL, INPUT_PULLUP);
    delay(5);
    Serial.printf("OLED pin levels before init: SDA(%d)=%d, SCL(%d)=%d\n",
                  OLED_SDA, digitalRead(OLED_SDA),
                  OLED_SCL, digitalRead(OLED_SCL));

    Wire.begin(OLED_SDA, OLED_SCL, 100000);
    detectedOledAddress = 0;

    for (uint8_t address = 1; address < 127; address++) {
        Wire.beginTransmission(address);
        uint8_t err = Wire.endTransmission();
        if (err == 0) {
            Serial.printf("I2C device found at 0x%02X (SDA=%d, SCL=%d)\n", address, OLED_SDA, OLED_SCL);
            if (address == 0x3C || address == 0x3D) {
                detectedOledAddress = address;
            }
        }
    }
    Wire.end(); // Release hardware I2C peripheral so U8G2_SW_I2C owns GPIO 40/41 cleanly

    if (detectedOledAddress != 0) {
        display.setI2CAddress(detectedOledAddress << 1);
        Serial.printf("OLED: DETECTED at 0x%02X\n", detectedOledAddress);
    } else {
        display.setI2CAddress(0x3C << 1);
        Serial.println("OLED: No ACK on hardware scan (check 3V3/GND/SDA=41/SCL=40 wires!), trying SW_I2C init at 0x3C...");
    }

    oledReady = display.begin();
    display.setBusClock(100000);

    if (oledReady) {
        display.setPowerSave(0);
        display.setContrast(255);
        showScreen("VOICELOCK", "Starting...", "");
    }

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
        bool ntpOk = false;
        constexpr int MAX_NTP_ATTEMPTS = 5;
        for (int attempt = 1; attempt <= MAX_NTP_ATTEMPTS && !ntpOk; attempt++) {
            char line2Buf[32];
            snprintf(line2Buf, sizeof(line2Buf), "Querying NTP (%d/%d)...", attempt, MAX_NTP_ATTEMPTS);
            showScreen("TIME SYNC", line2Buf, "pool.ntp.org");
            ntpOk = syncNtpTime(6000, showScreen);
            if (!ntpOk && attempt < MAX_NTP_ATTEMPTS) {
                delay(1000);
            }
        }

        if (ntpOk) {
            digitalWrite(LED_GREEN, LOW);
            digitalWrite(LED_RED, LOW);
            beep(1800, 60);
        } else {
            showScreen("NTP FAILED", "Clock uncalibrated", "Serial mode active");
            digitalWrite(LED_RED, HIGH);
            errorTone();
            delay(2000);
            digitalWrite(LED_RED, LOW);
        }
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

        // Refresh OLED periodically (every 1000ms) to ensure display never stays blank
        if (millis() - lastDisplayUpdate >= 1000) {
            lastDisplayUpdate = millis();
            updateDisplay();
        }

        static uint32_t lastReadyPing = 0;
        if (millis() - lastReadyPing >= 2000) {
            lastReadyPing = millis();
            Serial.print("READY\n");
            Serial.flush();
        }

        while (Serial.available() > 0) {
            char c = static_cast<char>(Serial.read());
            if (c == 'R' || c == 'r') {
                beginRecording(false);
                break;
            } else if (c == 'C' || c == 'c' || c == 'V' || c == 'v') {
                startChallengeRequest();
                break;
            } else if (c == 'D' || c == 'd') {
                runI2SDiagnostic(1000);
                break;
            }
        }
    }

    switch (state) {
        case STATE_CHALLENGE_DISPLAY:
            if (millis() - stateEnteredAt >= CHALLENGE_PREP_MS) {
                beginRecording(true);
            } else if (millis() - lastDisplayUpdate >= 200) {
                lastDisplayUpdate = millis();
                updateDisplay();
            }
            break;

        case STATE_RECORDING:
            captureStep();
            break;

        case STATE_UPLOADING:
            dispatchVerificationUpload();
            break;

        case STATE_RESULT:
            if (millis() - stateEnteredAt >= resultDisplayHoldMs) {
                digitalWrite(LED_GREEN, LOW);
                digitalWrite(LED_RED, LOW);
                setState(STATE_READY);
                Serial.print("READY\n");
                Serial.flush();
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

