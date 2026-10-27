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

void createWavHeader(uint8_t header[44], uint32_t pcmBytes, uint32_t sampleRate, uint16_t numChannels, uint16_t bitsPerSample) {
    uint32_t byteRate = sampleRate * numChannels * (bitsPerSample / 8);
    uint16_t blockAlign = numChannels * (bitsPerSample / 8);
    uint32_t chunkSize = 36 + pcmBytes;

    // RIFF chunk descriptor
    header[0] = 'R'; header[1] = 'I'; header[2] = 'F'; header[3] = 'F';
    header[4] = (uint8_t)(chunkSize & 0xFF);
    header[5] = (uint8_t)((chunkSize >> 8) & 0xFF);
    header[6] = (uint8_t)((chunkSize >> 16) & 0xFF);
    header[7] = (uint8_t)((chunkSize >> 24) & 0xFF);
    header[8] = 'W'; header[9] = 'A'; header[10] = 'V'; header[11] = 'E';

    // "fmt " subchunk
    header[12] = 'f'; header[13] = 'm'; header[14] = 't'; header[15] = ' ';
    header[16] = 16; header[17] = 0; header[18] = 0; header[19] = 0; // Subchunk1Size = 16 for PCM
    header[20] = 1; header[21] = 0;                                  // AudioFormat = 1 (Linear PCM)
    header[22] = (uint8_t)(numChannels & 0xFF);
    header[23] = (uint8_t)((numChannels >> 8) & 0xFF);
    header[24] = (uint8_t)(sampleRate & 0xFF);
    header[25] = (uint8_t)((sampleRate >> 8) & 0xFF);
    header[26] = (uint8_t)((sampleRate >> 16) & 0xFF);
    header[27] = (uint8_t)((sampleRate >> 24) & 0xFF);
    header[28] = (uint8_t)(byteRate & 0xFF);
    header[29] = (uint8_t)((byteRate >> 8) & 0xFF);
    header[30] = (uint8_t)((byteRate >> 16) & 0xFF);
    header[31] = (uint8_t)((byteRate >> 24) & 0xFF);
    header[32] = (uint8_t)(blockAlign & 0xFF);
    header[33] = (uint8_t)((blockAlign >> 8) & 0xFF);
    header[34] = (uint8_t)(bitsPerSample & 0xFF);
    header[35] = (uint8_t)((bitsPerSample >> 8) & 0xFF);

    // "data" subchunk
    header[36] = 'd'; header[37] = 'a'; header[38] = 't'; header[39] = 'a';
    header[40] = (uint8_t)(pcmBytes & 0xFF);
    header[41] = (uint8_t)((pcmBytes >> 8) & 0xFF);
    header[42] = (uint8_t)((pcmBytes >> 16) & 0xFF);
    header[43] = (uint8_t)((pcmBytes >> 24) & 0xFF);
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

    // 1. Validate claimed identity formatting (strict alphanumeric, _, -)
    const char* ident = (claimedIdentity && strlen(claimedIdentity) > 0) ? claimedIdentity : "Zubair";
    size_t identLen = strlen(ident);
    if (identLen > 32) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "claimed_identity too long (>32 chars)");
        return res;
    }
    for (size_t i = 0; i < identLen; i++) {
        char c = ident[i];
        if (!isalnum(c) && c != '_' && c != '-') {
            snprintf(res.errorMessage, sizeof(res.errorMessage), "Invalid claimed_identity characters");
            return res;
        }
    }

    // 2. Build JSON request body
    char body[128];
    snprintf(body, sizeof(body), "{\"claimed_identity\":\"%s\"}", ident);
    size_t bodyLen = strlen(body);

    // 3. Compute SHA256 hex digest of wire body
    char bodySha256[65];
    computeSha256Hex(reinterpret_cast<const uint8_t*>(body), bodyLen, bodySha256);

    // 4. Obtain current timestamp (requires synchronized SNTP clock)
    time_t now = time(nullptr);
    if (now < 1700000000) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Clock uncalibrated (NTP required)");
        return res;
    }

    char tsStr[24];
    snprintf(tsStr, sizeof(tsStr), "%lu", static_cast<unsigned long>(now));

    // 5. Generate 16-hex CSPRNG nonce
    char nonceStr[32];
    snprintf(nonceStr, sizeof(nonceStr), "%08lx%08lx", 
             static_cast<unsigned long>(esp_random()), 
             static_cast<unsigned long>(esp_random()));

    // 6. Construct canonical string: METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256
    char canonical[256];
    snprintf(canonical, sizeof(canonical), "POST\n/challenge\n%s\n%s\n%s", tsStr, nonceStr, bodySha256);

    // 7. Compute HMAC-SHA256 signature
    char sigHex[65];
    if (!computeHmacSha256Hex(secret, canonical, sigHex)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "HMAC computation failed");
        return res;
    }

    // 8. Configure WiFiClientSecure with Root CA
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

    // 9. Parse JSON response
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, responsePayload);
    if (err) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "JSON Parse error: %s", err.c_str());
        return res;
    }

    const char* chId = doc["challenge_id"];
    if (chId) {
        strncpy(res.challengeId, chId, sizeof(res.challengeId) - 1);
        res.challengeId[sizeof(res.challengeId) - 1] = '\0';
    }

    const char* sess = doc["session_id"];
    if (sess) {
        strncpy(res.sessionId, sess, sizeof(res.sessionId) - 1);
        res.sessionId[sizeof(res.sessionId) - 1] = '\0';
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
        res.display[sizeof(res.display) - 1] = '\0';
    } else {
        int pos = 0;
        for (int i = 0; i < dIdx && pos < (int)sizeof(res.display) - 2; i++) {
            res.display[pos++] = res.digits[i];
            if (i < dIdx - 1 && pos < (int)sizeof(res.display) - 2) {
                res.display[pos++] = ' ';
                res.display[pos++] = ' ';
            }
        }
        res.display[pos] = '\0';
    }

    res.expiresInSeconds = doc["expires_in_seconds"] | 60;
    res.success = true;
    return res;
}

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
    uint32_t timeoutMs
) {
    VerifyResult res = {};
    res.success = false;
    res.httpCode = 0;
    res.accepted = false;
    res.isUnlock = false;
    res.livenessPassed = false;
    res.similarity = 0.0f;
    res.errorMessage[0] = '\0';
    res.reason[0] = '\0';

    if (!host || !deviceId || !secret || !challengeId || !sessionId || !pcmData || pcmBytes == 0) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Missing required verification parameters");
        return res;
    }

    const char* ident = (claimedIdentity && strlen(claimedIdentity) > 0) ? claimedIdentity : "Zubair";
    strncpy(res.claimedIdentity, ident, sizeof(res.claimedIdentity) - 1);

    // 1. Prepare 44-byte WAV header
    uint8_t wavHeader[44];
    createWavHeader(wavHeader, pcmBytes, 16000, 1, 16);

    // 2. Format multipart/form-data boundary & parts
    const char* boundary = "----VoiceLockFormBoundary7MA4YWxkTrZu0gW";

    char part1[512];
    int part1Len = snprintf(
        part1, sizeof(part1),
        "--%s\r\nContent-Disposition: form-data; name=\"claimed_identity\"\r\n\r\n%s\r\n"
        "--%s\r\nContent-Disposition: form-data; name=\"challenge_id\"\r\n\r\n%s\r\n"
        "--%s\r\nContent-Disposition: form-data; name=\"session_id\"\r\n\r\n%s\r\n"
        "--%s\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"voice.wav\"\r\nContent-Type: audio/wav\r\n\r\n",
        boundary, ident,
        boundary, challengeId,
        boundary, sessionId,
        boundary
    );

    char partTail[64];
    int tailLen = snprintf(partTail, sizeof(partTail), "\r\n--%s--\r\n", boundary);

    size_t totalBodyLength = part1Len + sizeof(wavHeader) + pcmBytes + tailLen;

    // 3. Compute SHA256 of entire multipart body
    mbedtls_sha256_context shaCtx;
    mbedtls_sha256_init(&shaCtx);
    mbedtls_sha256_starts(&shaCtx, 0);
    mbedtls_sha256_update(&shaCtx, reinterpret_cast<const uint8_t*>(part1), part1Len);
    mbedtls_sha256_update(&shaCtx, wavHeader, sizeof(wavHeader));
    mbedtls_sha256_update(&shaCtx, reinterpret_cast<const uint8_t*>(pcmData), pcmBytes);
    mbedtls_sha256_update(&shaCtx, reinterpret_cast<const uint8_t*>(partTail), tailLen);
    uint8_t bodyHash[32];
    mbedtls_sha256_finish(&shaCtx, bodyHash);
    mbedtls_sha256_free(&shaCtx);

    char bodySha256[65];
    for (int i = 0; i < 32; i++) {
        sprintf(bodySha256 + (i * 2), "%02x", bodyHash[i]);
    }
    bodySha256[64] = '\0';

    // 4. Timestamp & Nonce
    time_t now = time(nullptr);
    if (now < 1700000000) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Clock uncalibrated (NTP required)");
        return res;
    }
    char tsStr[24];
    snprintf(tsStr, sizeof(tsStr), "%lu", static_cast<unsigned long>(now));

    char nonceStr[32];
    snprintf(nonceStr, sizeof(nonceStr), "%08lx%08lx", 
             static_cast<unsigned long>(esp_random()), 
             static_cast<unsigned long>(esp_random()));

    // 5. Canonical signing string: METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256
    char canonical[256];
    snprintf(canonical, sizeof(canonical), "POST\n/verify\n%s\n%s\n%s", tsStr, nonceStr, bodySha256);

    // 6. Compute HMAC-SHA256 signature
    char sigHex[65];
    if (!computeHmacSha256Hex(secret, canonical, sigHex)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "HMAC computation failed");
        return res;
    }

    // 7. Connect via WiFiClientSecure with strict Root CA validation
    WiFiClientSecure secureClient;
    secureClient.setCACert(AZURE_ROOT_CA_CERT);
    secureClient.setTimeout(timeoutMs / 1000);

    if (!secureClient.connect(host, port)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "TLS connect failed to %s", host);
        return res;
    }

    // 8. Send HTTP request headers
    secureClient.printf("POST /verify HTTP/1.1\r\n");
    secureClient.printf("Host: %s:%u\r\n", host, port);
    secureClient.printf("User-Agent: ESP32-VoiceLock\r\n");
    secureClient.printf("X-Device-ID: %s\r\n", deviceId);
    secureClient.printf("X-Device-Timestamp: %s\r\n", tsStr);
    secureClient.printf("X-Device-Nonce: %s\r\n", nonceStr);
    secureClient.printf("X-Device-Signature: %s\r\n", sigHex);
    secureClient.printf("Content-Type: multipart/form-data; boundary=%s\r\n", boundary);
    secureClient.printf("Content-Length: %u\r\n", (unsigned int)totalBodyLength);
    secureClient.printf("Connection: close\r\n\r\n");

    // 9. Stream multipart body
    secureClient.write(reinterpret_cast<const uint8_t*>(part1), part1Len);
    secureClient.write(wavHeader, sizeof(wavHeader));

    const uint8_t* pcmRaw = reinterpret_cast<const uint8_t*>(pcmData);
    size_t sent = 0;
    constexpr size_t CHUNK_SIZE = 4096;
    while (sent < pcmBytes && secureClient.connected()) {
        size_t toSend = (pcmBytes - sent < CHUNK_SIZE) ? (pcmBytes - sent) : CHUNK_SIZE;
        size_t written = secureClient.write(pcmRaw + sent, toSend);
        if (written == 0) break;
        sent += written;
    }
    secureClient.write(reinterpret_cast<const uint8_t*>(partTail), tailLen);
    secureClient.flush();

    // 10. Read HTTP response
    uint32_t respStart = millis();
    while (secureClient.available() == 0 && (millis() - respStart < timeoutMs)) {
        delay(10);
        if (!secureClient.connected()) break;
    }

    if (secureClient.available() == 0) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Server response timeout");
        secureClient.stop();
        return res;
    }

    String statusLine = secureClient.readStringUntil('\n');
    statusLine.trim();
    int httpCode = 0;
    if (statusLine.startsWith("HTTP/1.")) {
        int firstSpace = statusLine.indexOf(' ');
        if (firstSpace > 0) {
            httpCode = statusLine.substring(firstSpace + 1, firstSpace + 4).toInt();
        }
    }
    res.httpCode = httpCode;

    // Skip response headers
    while (secureClient.connected()) {
        String headerLine = secureClient.readStringUntil('\n');
        headerLine.trim();
        if (headerLine.length() == 0) {
            break; // Empty line separates headers from body
        }
    }

    String responseBody = secureClient.readString();
    secureClient.stop();

    if (httpCode != 200) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "HTTP %d: %s", httpCode, responseBody.substring(0, 48).c_str());
        return res;
    }

    // 11. Parse JSON response
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, responseBody);
    if (err) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "JSON Parse error: %s", err.c_str());
        return res;
    }

    res.accepted = doc["accepted"] | false;
    const char* act = doc["action"];
    res.isUnlock = (res.httpCode == 200 && res.accepted && act != nullptr && strcmp(act, "UNLOCK") == 0);
    res.livenessPassed = doc["liveness_passed"] | false;
    res.similarity = doc["similarity"] | 0.0f;

    const char* rsn = doc["reason"];
    if (rsn) {
        strncpy(res.reason, rsn, sizeof(res.reason) - 1);
        res.reason[sizeof(res.reason) - 1] = '\0';
    }

    res.success = true;
    return res;
}
