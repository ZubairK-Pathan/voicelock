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
    secureClient.setTimeout(timeoutMs);

    HTTPClient https;
    char url[256];
    snprintf(url, sizeof(url), "https://%s:%u/challenge", host, port);

    if (!https.begin(secureClient, url)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Failed to init HTTPS connection");
        return res;
    }

    https.setConnectTimeout(timeoutMs);
    https.setTimeout(timeoutMs);
    https.addHeader("X-Device-ID", deviceId);
    https.addHeader("X-Device-Timestamp", tsStr);
    https.addHeader("X-Device-Nonce", nonceStr);
    https.addHeader("X-Device-Signature", sigHex);
    https.addHeader("Content-Type", "application/json");

    int httpCode = https.POST(reinterpret_cast<uint8_t*>(body), bodyLen);
    res.httpCode = httpCode;

    if (httpCode <= 0) {
        char errBuf[128] = {0};
        secureClient.lastError(errBuf, sizeof(errBuf));
        snprintf(res.errorMessage, sizeof(res.errorMessage), "TLS/Connect error (%d): %s", httpCode, errBuf);
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

// Helper to ensure every byte of a buffer is fully transmitted over WiFiClientSecure
static bool writeAll(WiFiClientSecure& client, const uint8_t* data, size_t length, uint32_t timeoutMs = 8000) {
    if (data == nullptr || length == 0) return true;
    size_t totalWritten = 0;
    uint32_t lastProgressMs = millis();

    while (totalWritten < length) {
        if (!client.connected()) {
            return false;
        }
        size_t toWrite = length - totalWritten;
        if (toWrite > 4096) toWrite = 4096;

        size_t written = client.write(data + totalWritten, toWrite);
        if (written > 0) {
            totalWritten += written;
            lastProgressMs = millis();
        } else {
            if (millis() - lastProgressMs > timeoutMs) {
                return false;
            }
            delay(10);
        }
    }
    return (totalWritten == length);
}

// Structured HTTP response representation with bounded memory
struct HttpResponse {
    int httpCode = 0;
    bool success = false;
    char body[4096] = {0};
    size_t bodyLen = 0;
    char error[96] = {0};
};

// Bounded HTTP response parser supporting Content-Length and Transfer-Encoding: chunked
static HttpResponse readBoundedHttpResponse(WiFiClientSecure& client, uint32_t timeoutMs = 12000) {
    HttpResponse resp;
    resp.httpCode = 0;
    resp.success = false;
    resp.bodyLen = 0;
    resp.body[0] = '\0';
    resp.error[0] = '\0';

    uint32_t startMs = millis();
    while (client.available() == 0 && (millis() - startMs < timeoutMs)) {
        if (!client.connected()) break;
        delay(10);
    }

    if (client.available() == 0) {
        snprintf(resp.error, sizeof(resp.error), "Response timeout from server");
        return resp;
    }

    // 1. Read status line
    client.setTimeout(timeoutMs);
    String statusLine = client.readStringUntil('\n');
    statusLine.trim();
    if (!statusLine.startsWith("HTTP/1.")) {
        snprintf(resp.error, sizeof(resp.error), "Invalid HTTP status line");
        return resp;
    }

    int firstSpace = statusLine.indexOf(' ');
    if (firstSpace > 0 && firstSpace + 4 <= (int)statusLine.length()) {
        resp.httpCode = statusLine.substring(firstSpace + 1, firstSpace + 4).toInt();
    } else {
        snprintf(resp.error, sizeof(resp.error), "Malformed HTTP code in status line");
        return resp;
    }

    // 2. Read headers and parse framing
    int contentLength = -1;
    bool isChunked = false;
    uint32_t headerReadStart = millis();

    while (client.connected() || client.available() > 0) {
        if (millis() - headerReadStart > timeoutMs) {
            snprintf(resp.error, sizeof(resp.error), "Header read timeout");
            return resp;
        }

        String headerLine = client.readStringUntil('\n');
        headerLine.trim();
        if (headerLine.length() == 0) {
            break; // Empty line separates headers from body
        }

        String lowerHeader = headerLine;
        lowerHeader.toLowerCase();

        if (lowerHeader.startsWith("content-length:")) {
            int colon = lowerHeader.indexOf(':');
            if (colon > 0) {
                contentLength = lowerHeader.substring(colon + 1).toInt();
            }
        } else if (lowerHeader.startsWith("transfer-encoding:") && lowerHeader.indexOf("chunked") != -1) {
            isChunked = true;
        }
    }

    // 3. Read body according to framing
    constexpr size_t MAX_RESP_BODY = sizeof(resp.body) - 1; // 4095 bytes

    if (isChunked) {
        size_t totalRead = 0;
        uint32_t chunkStart = millis();

        while (true) {
            if (millis() - chunkStart > timeoutMs) {
                snprintf(resp.error, sizeof(resp.error), "Chunked body read timeout");
                return resp;
            }

            String lenLine = client.readStringUntil('\n');
            lenLine.trim();
            if (lenLine.length() == 0) continue;

            long chunkLen = strtol(lenLine.c_str(), nullptr, 16);
            if (chunkLen < 0 || chunkLen > 65536) {
                snprintf(resp.error, sizeof(resp.error), "Invalid chunk length: %ld", chunkLen);
                return resp;
            }

            if (chunkLen == 0) {
                // Final 0-chunk: read any trailer headers
                while (client.connected() || client.available() > 0) {
                    String trailer = client.readStringUntil('\n');
                    trailer.trim();
                    if (trailer.length() == 0) break;
                }
                break;
            }

            if (totalRead + chunkLen > MAX_RESP_BODY) {
                snprintf(resp.error, sizeof(resp.error), "Response body exceeded %u bytes", (unsigned int)MAX_RESP_BODY);
                return resp;
            }

            size_t chunkBytesRead = 0;
            while (chunkBytesRead < (size_t)chunkLen) {
                if (millis() - chunkStart > timeoutMs) {
                    snprintf(resp.error, sizeof(resp.error), "Chunk data read timeout");
                    return resp;
                }
                if (!client.connected() && client.available() == 0) {
                    snprintf(resp.error, sizeof(resp.error), "Connection dropped during chunk read");
                    return resp;
                }
                size_t needed = (size_t)chunkLen - chunkBytesRead;
                size_t got = client.readBytes(reinterpret_cast<uint8_t*>(resp.body + totalRead), needed);
                if (got > 0) {
                    totalRead += got;
                    chunkBytesRead += got;
                    chunkStart = millis();
                } else {
                    delay(5);
                }
            }

            client.readStringUntil('\n'); // Consume trailing \r\n
        }

        resp.body[totalRead] = '\0';
        resp.bodyLen = totalRead;
        resp.success = true;
    } else if (contentLength >= 0) {
        if ((size_t)contentLength > MAX_RESP_BODY) {
            snprintf(resp.error, sizeof(resp.error), "Content-Length %d exceeds buffer (%u)", contentLength, (unsigned int)MAX_RESP_BODY);
            return resp;
        }

        size_t totalRead = 0;
        uint32_t bodyStart = millis();

        while (totalRead < (size_t)contentLength) {
            if (millis() - bodyStart > timeoutMs) {
                snprintf(resp.error, sizeof(resp.error), "Body read timeout");
                return resp;
            }
            if (!client.connected() && client.available() == 0) {
                snprintf(resp.error, sizeof(resp.error), "Connection dropped: read %u of %d bytes", (unsigned int)totalRead, contentLength);
                return resp;
            }

            size_t needed = (size_t)contentLength - totalRead;
            size_t got = client.readBytes(reinterpret_cast<uint8_t*>(resp.body + totalRead), needed);
            if (got > 0) {
                totalRead += got;
                bodyStart = millis();
            } else {
                delay(5);
            }
        }

        resp.body[totalRead] = '\0';
        resp.bodyLen = totalRead;
        resp.success = true;
    } else {
        // Read until connection closed, bounded by buffer
        size_t totalRead = 0;
        uint32_t bodyStart = millis();

        while ((client.connected() || client.available() > 0) && totalRead < MAX_RESP_BODY) {
            if (millis() - bodyStart > timeoutMs) {
                break;
            }
            size_t avail = client.available();
            if (avail > 0) {
                size_t toRead = (avail < (MAX_RESP_BODY - totalRead)) ? avail : (MAX_RESP_BODY - totalRead);
                size_t got = client.readBytes(reinterpret_cast<uint8_t*>(resp.body + totalRead), toRead);
                if (got > 0) {
                    totalRead += got;
                    bodyStart = millis();
                }
            } else {
                delay(5);
            }
        }

        resp.body[totalRead] = '\0';
        resp.bodyLen = totalRead;
        resp.success = (totalRead > 0);
    }

    return resp;
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
    secureClient.setTimeout(timeoutMs);

    if (!secureClient.connect(host, port)) {
        char errBuf[128] = {0};
        secureClient.lastError(errBuf, sizeof(errBuf));
        snprintf(res.errorMessage, sizeof(res.errorMessage), "TLS connect failed to %s: %s", host, errBuf);
        return res;
    }

    // 8. Format HTTP request headers
    char reqHeaderBuf[512];
    int headerLen = snprintf(reqHeaderBuf, sizeof(reqHeaderBuf),
        "POST /verify HTTP/1.1\r\n"
        "Host: %s:%u\r\n"
        "User-Agent: ESP32-VoiceLock\r\n"
        "X-Device-ID: %s\r\n"
        "X-Device-Timestamp: %s\r\n"
        "X-Device-Nonce: %s\r\n"
        "X-Device-Signature: %s\r\n"
        "Content-Type: multipart/form-data; boundary=%s\r\n"
        "Content-Length: %u\r\n"
        "Connection: close\r\n\r\n",
        host, port, deviceId, tsStr, nonceStr, sigHex, boundary, (unsigned int)totalBodyLength
    );

    if (headerLen <= 0 || (size_t)headerLen >= sizeof(reqHeaderBuf)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Header buffer overflow");
        secureClient.stop();
        return res;
    }

    // Send HTTP headers using writeAll
    if (!writeAll(secureClient, reinterpret_cast<const uint8_t*>(reqHeaderBuf), headerLen, 5000)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Failed to transmit HTTP headers");
        secureClient.stop();
        return res;
    }

    // 9. Send multipart prefix using writeAll
    if (!writeAll(secureClient, reinterpret_cast<const uint8_t*>(part1), part1Len, 5000)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Failed to transmit multipart prefix");
        secureClient.stop();
        return res;
    }

    // 10. Send 44-byte WAV header using writeAll
    if (!writeAll(secureClient, wavHeader, sizeof(wavHeader), 5000)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Failed to transmit WAV header");
        secureClient.stop();
        return res;
    }

    // 11. Stream PCM samples in bounded chunks with writeAll
    const uint8_t* pcmRaw = reinterpret_cast<const uint8_t*>(pcmData);
    size_t sent = 0;
    constexpr size_t CHUNK_SIZE = 4096;
    while (sent < pcmBytes) {
        size_t toSend = (pcmBytes - sent < CHUNK_SIZE) ? (pcmBytes - sent) : CHUNK_SIZE;
        if (!writeAll(secureClient, pcmRaw + sent, toSend, 5000)) {
            snprintf(res.errorMessage, sizeof(res.errorMessage), "Failed to stream PCM chunk at %u bytes", (unsigned int)sent);
            secureClient.stop();
            return res; // Abort immediately on incomplete transmission
        }
        sent += toSend;
    }

    // 12. Send closing boundary using writeAll
    if (!writeAll(secureClient, reinterpret_cast<const uint8_t*>(partTail), tailLen, 5000)) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "Failed to transmit closing boundary");
        secureClient.stop();
        return res;
    }
    secureClient.flush();

    // 13. Read bounded HTTP response (handles Content-Length and Transfer-Encoding: chunked)
    HttpResponse httpResp = readBoundedHttpResponse(secureClient, timeoutMs);
    secureClient.stop();

    res.httpCode = httpResp.httpCode;
    if (!httpResp.success) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "%s (HTTP %d)", httpResp.error, httpResp.httpCode);
        return res;
    }

    if (httpResp.httpCode != 200) {
        snprintf(res.errorMessage, sizeof(res.errorMessage), "HTTP %d: %s", httpResp.httpCode, httpResp.body);
        res.errorMessage[sizeof(res.errorMessage) - 1] = '\0';
        return res;
    }

    // 14. Parse JSON response safely
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, httpResp.body);
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

