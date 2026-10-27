#pragma once

// Conditionally include local device_config.h if present;
// otherwise fall back to safe compilation defaults from device_config.example.h.
#if __has_include("device_config.h")
#include "device_config.h"
#define VOICELOCK_HAS_LOCAL_CONFIG 1
#else
#include "device_config.example.h"
#define VOICELOCK_HAS_LOCAL_CONFIG 0
#endif
