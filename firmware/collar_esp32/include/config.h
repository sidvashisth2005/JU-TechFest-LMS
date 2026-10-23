// Pulls in lms_config.h (or the example) and fills in anything an older config lacks.
#pragma once

#if __has_include("lms_config.h")
#include "lms_config.h"
#else
#include "lms_config.example.h"
#define LMS_USING_EXAMPLE_CONFIG
#endif

#ifndef PPG_DEFAULT
#define PPG_DEFAULT -1
#endif
#ifndef HAVE_BATTERY
#define HAVE_BATTERY 0
#endif
#ifndef PIN_PULSE_ANALOG
#define PIN_PULSE_ANALOG 34
#endif
#ifndef REPORT_SECONDS
#define REPORT_SECONDS 5
#endif
