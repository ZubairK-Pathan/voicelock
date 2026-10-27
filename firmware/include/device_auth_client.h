#pragma once
#include <Arduino.h>

struct ChallengeResult {
    bool success;
    int httpCode;
    char challengeId[64];
    char sessionId[64];
    char digits[8];
    char display[16];
    uint32_t expiresInSeconds;
    char errorMessage[64];
};

struct VerifyResult {
    bool success;
    int httpCode;
    bool accepted;
    bool isUnlock;
    bool livenessPassed;
    float similarity;
    char claimedIdentity[64];
    char reason[128];
    char errorMessage[128];
};

void computeSha256Hex(const uint8_t* data, size_t len, char* outHex65);
bool computeHmacSha256Hex(const char* secret, const char* message, char* outHex65);
void createWavHeader(uint8_t header[44], uint32_t pcmBytes, uint32_t sampleRate = 16000, uint16_t numChannels = 1, uint16_t bitsPerSample = 16);

ChallengeResult requestLivenessChallenge(
    const char* host,
    uint16_t port,
    const char* deviceId,
    const char* secret,
    const char* claimedIdentity,
    uint32_t timeoutMs = 8000
);

VerifyResult uploadAudioVerification(
    const char* host,
    uint16_t port,
    const char* deviceId,
    const char* secret,
    const char* claimedIdentity,
    const char* challengeId,
    const char* sessionId,
    const int16_t* pcmData,
    size_t pcmBytes,
    uint32_t timeoutMs = 12000
);
