#include "wifi_manager.h"
#include "device_config_loader.h"
#include <WiFi.h>
#include <esp_sntp.h>
#include <time.h>

static uint32_t lastReconnectAttempt = 0;
constexpr uint32_t RECONNECT_INTERVAL_MS = 15000;

static bool isPlaceholderSsid(const char *ssid) {
  if (!ssid || strlen(ssid) == 0)
    return true;
  if (strcmp(ssid, "YOUR_WIFI_SSID") == 0)
    return true;
  if (strcmp(ssid, "CONFIGURE_IN_DEVICE_CONFIG_H") == 0)
    return true;
  return false;
}

bool initWifi(uint32_t timeoutMs, OledStatusCallback cb) {
  if (isPlaceholderSsid(WIFI_SSID)) {
    Serial.println("WIFI_UNCONFIGURED");
    if (cb) {
      cb("WIFI UNCONFIGURED", "Edit device_config.h", "Serial mode active");
    }
    return false;
  }

  if (cb) {
    cb("WIFI SETUP", "Connecting to:", WIFI_SSID);
  }

  WiFi.persistent(false);
  WiFi.disconnect(true);
  delay(50);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t startMs = millis();
  int dots = 0;
  while (WiFi.status() != WL_CONNECTED && (millis() - startMs < timeoutMs)) {
    delay(250);
    dots = (dots + 1) % 4;
    char line2[32];
    snprintf(line2, sizeof(line2), "Connecting%.*s", dots, "...");
    if (cb) {
      cb("WIFI SETUP", WIFI_SSID, line2);
    }
  }

  if (WiFi.status() == WL_CONNECTED) {
    String ipStr = WiFi.localIP().toString();
    Serial.print("WIFI_CONNECTED:");
    Serial.println(ipStr);
    if (cb) {
      cb("WIFI CONNECTED", WIFI_SSID, ipStr.c_str());
    }
    return true;
  }

  Serial.println("WIFI_CONNECT_TIMEOUT");
  if (cb) {
    cb("WIFI TIMEOUT", "Connection failed", "Serial mode active");
  }
  return false;
}

bool syncNtpTime(uint32_t timeoutMs, OledStatusCallback cb) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }

  if (cb) {
    cb("TIME SYNC", "Querying NTP...", "pool.ntp.org");
  }

  configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");

  uint32_t startMs = millis();
  time_t now = 0;
  while ((now < 1700000000) && (millis() - startMs < timeoutMs)) {
    delay(150);
    time(&now);
  }

  if (now >= 1700000000) {
    char buf[32];
    struct tm timeinfo;
    gmtime_r(&now, &timeinfo);
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M", &timeinfo);
    Serial.print("NTP_SYNCED:");
    Serial.println(buf);
    if (cb) {
      cb("TIME SYNCHRONIZED", buf, "UTC Verified");
    }
    return true;
  }

  Serial.println("NTP_SYNC_TIMEOUT");
  if (cb) {
    cb("NTP TIMEOUT", "Clock uncalibrated", "Using local timer");
  }
  return false;
}

bool isWifiConnected() { return WiFi.status() == WL_CONNECTED; }

static bool wasConnected = false;

void maintainWifi() {
  if (isPlaceholderSsid(WIFI_SSID)) {
    return;
  }

  uint32_t now = millis();
  bool currentlyConnected = (WiFi.status() == WL_CONNECTED);

  if (currentlyConnected && !wasConnected) {
    // Transitioned from offline to online: resynchronize NTP clock before
    // authenticated requests
    Serial.println("WIFI_RECONNECTED_RESYNCING_NTP");
    syncNtpTime(5000, nullptr);
  }
  wasConnected = currentlyConnected;

  if (!currentlyConnected &&
      (now - lastReconnectAttempt >= RECONNECT_INTERVAL_MS)) {
    lastReconnectAttempt = now;
    Serial.println("WIFI_RECONNECTING");
    WiFi.reconnect();
  }
}

String getWifiStatusString() {
  if (WiFi.status() == WL_CONNECTED) {
    return WiFi.localIP().toString();
  }
  if (isPlaceholderSsid(WIFI_SSID)) {
    return "Offline (Unconfigured)";
  }
  return "Offline (Connecting)";
}
