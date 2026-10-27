#pragma once
#include <Arduino.h>

struct ChallengeResult {
    bool success;
    int httpCode;
    char challengeId[64];
    char digits[8];
    char display[16];
    uint32_t expiresInSeconds;
    char errorMessage[64];
};

void computeSha256Hex(const uint8_t* data, size_t len, char* outHex65);
bool computeHmacSha256Hex(const char* secret, const char* message, char* outHex65);

ChallengeResult requestLivenessChallenge(
    const char* host,
    uint16_t port,
    const char* deviceId,
    const char* secret,
    const char* claimedIdentity,
    uint32_t timeoutMs = 8000
);
