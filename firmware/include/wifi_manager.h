#pragma once
#include <Arduino.h>

typedef void (*OledStatusCallback)(const char* title, const char* line1, const char* line2);

bool initWifi(uint32_t timeoutMs = 8000, OledStatusCallback cb = nullptr);
bool syncNtpTime(uint32_t timeoutMs = 5000, OledStatusCallback cb = nullptr);
bool isWifiConnected();
void maintainWifi();
String getWifiStatusString();
