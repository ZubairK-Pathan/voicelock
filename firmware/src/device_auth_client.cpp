#include "device_auth_client.h"
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <mbedtls/sha256.h>
#include <mbedtls/md.h>
#include <time.h>
#include "root_ca.h"

void computeSha256Hex(const uint8_t* data, size_t len, char* outHex65) {
    uint8_t hash[32];
    mbedtls_sha256(data, len, hash, 0);
    for (int i = 0; i < 32; i++) {
        sprintf(outHex65 + (i * 2), "%02x", hash[i]);
    }
    outHex65[64] = '\0';
}

bool computeHmacSha256Hex(const char* secret, const char* message, char* outHex65) {
    const mbedtls_md_info_t* md = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (!md) return false;
    uint8_t hmac[32];
    int ret = mbedtls_md_hmac(md, (const uint8_t*)secret, strlen(secret), (const uint8_t*)message, strlen(message), hmac);
    if (ret != 0) return false;
    for (int i = 0; i < 32; i++) {
        sprintf(outHex65 + (i * 2), "%02x", hmac[i]);
    }
    outHex65[64] = '\0';
    return true;
}

ChallengeResult requestLivenessChallenge(
    const char* host,
    uint16_t port,
    const char* deviceId,
    const char* secret,
    const char* claimedIdentity,
    uint32_t timeoutMs
) {
    ChallengeResult res = {};
    res.success = false;
    res.httpCode = 0;

    if (!host || strlen(host) == 0 || !deviceId || strlen(deviceId) == 0 || !secret || strlen(secret) == 0) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Unconfigured device credentials");
        return res;
    }

    // 1. Build JSON request body
    char body[128];
    snprintf(body, sizeof(body), "{\"claimed_identity\":\"%s\"}", claimedIdentity ? claimedIdentity : "Zubair");
    size_t bodyLen = strlen(body);

    // 2. Compute SHA256 hex digest of wire body
    char bodySha256[65];
    computeSha256Hex(reinterpret_cast<const uint8_t*>(body), bodyLen, bodySha256);

    // 3. Obtain current timestamp (requires synchronized SNTP clock)
    time_t now = time(nullptr);
    if (now < 1700000000) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Clock uncalibrated (NTP required)");
        return res;
    }

    char tsStr[24];
    snprintf(tsStr, sizeof(tsStr), "%lu", static_cast<unsigned long>(now));

    // 4. Generate 16-hex CSPRNG nonce
    char nonceStr[32];
    snprintf(nonceStr, sizeof(nonceStr), "%08x%08x", esp_random(), esp_random());

    // 5. Construct canonical string: METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256
    char canonical[256];
    snprintf(canonical, sizeof(canonical), "POST\n/challenge\n%s\n%s\n%s", tsStr, nonceStr, bodySha256);

    // 6. Compute HMAC-SHA256 signature
    char sigHex[65];
    if (!computeHmacSha256Hex(secret, canonical, sigHex)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "HMAC computation failed");
        return res;
    }

    // 7. Configure WiFiClientSecure with Root CA
    WiFiClientSecure secureClient;
    secureClient.setCACert(AZURE_ROOT_CA_CERT);
    secureClient.setTimeout(timeoutMs / 1000);

    HTTPClient https;
    char url[256];
    snprintf(url, sizeof(url), "https://%s:%u/challenge", host, port);

    if (!https.begin(secureClient, url)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Failed to init HTTPS connection");
        return res;
    }

    https.setTimeout(timeoutMs);
    https.addHeader("X-Device-ID", deviceId);
    https.addHeader("X-Device-Timestamp", tsStr);
    https.addHeader("X-Device-Nonce", nonceStr);
    https.addHeader("X-Device-Signature", sigHex);
    https.addHeader("Content-Type", "application/json");

    int httpCode = https.POST(reinterpret_cast<uint8_t*>(body), bodyLen);
    res.httpCode = httpCode;

    if (httpCode <= 0) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "TLS/Connect error (%d)", httpCode);
        https.end();
        return res;
    }

    String responsePayload = https.getString();
    https.end();

    if (httpCode != 200) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Server HTTP %d: %s", httpCode, responsePayload.substring(0, 32).c_str());
        return res;
    }

    // 8. Parse JSON response
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, responsePayload);
    if (err) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "JSON Parse error: %s", err.c_str());
        return res;
    }

    const char* chId = doc["challenge_id"];
    if (chId) {
        strncpy(res.challengeId, chId, sizeof(res.challengeId) - 1);
    }

    JsonArray digitsArr = doc["digits"].as<JsonArray>();
    int dIdx = 0;
    for (JsonVariant v : digitsArr) {
        if (dIdx < 7) {
            String s = v.as<String>();
            if (s.length() > 0) {
                res.digits[dIdx++] = s[0];
            }
        }
    }
    res.digits[dIdx] = '\0';

    const char* disp = doc["display"];
    if (disp) {
        strncpy(res.display, disp, sizeof(res.display) - 1);
    } else {
        snprintf(res.display, sizeof(res.display), "%c  %c  %c", res.digits[0], res.digits[1], res.digits[2]);
    }

    res.expiresInSeconds = doc["expires_in_seconds"] | 60;
    res.success = true;
    return res;
}
