#ifndef FIXTURE_ANDROID_LOG_H
#define FIXTURE_ANDROID_LOG_H
enum { ANDROID_LOG_INFO = 4, ANDROID_LOG_WARN = 5 };
int __android_log_print(int priority, const char *tag, const char *format, ...);
#endif
