#include "Log.h"
#include "Renderer.h"
#include "Nodes/Widgets/Console.h"

#include "System/System.h"

#include "EngineTypes.h"

static bool sInitialized = false;
static MutexObject* sMutex = nullptr;
static bool sLoggingEnabled = false;

static void OpenLogFile()
{
    EngineState* engineState = GetEngineState();

    if (engineState->mLogFile == nullptr)
    {
        std::string projName = engineState->mProjectName;
        if (projName == "")
        {
            projName = "Octave";
        }
        std::string logName = projName + ".log";
        engineState->mLogFile = fopen(logName.c_str(), "w");
    }
}

static void CloseLogFile()
{
    EngineState* engineState = GetEngineState();
    if (engineState->mLogFile != nullptr)
    {
        fclose(engineState->mLogFile);
        engineState->mLogFile = nullptr;
    }
}

void InitializeLog()
{
    if (!sInitialized)
    {
        sMutex = SYS_CreateMutex();

        if (GetEngineConfig()->mLogToFile)
        {
            OpenLogFile();
        }

        sInitialized = true;
    }

#if LOGGING_ENABLED
    sLoggingEnabled = GetEngineConfig()->mLogging;
#else
    sLoggingEnabled = false;
#endif

}

void ShutdownLog()
{
    if (sInitialized)
    {
        sInitialized = false;

        SYS_DestroyMutex(sMutex);
        sMutex = nullptr;

        CloseLogFile();
    }
}

void LogToFile(const char* format, va_list arg)
{
    FILE* logFile = GetEngineState()->mLogFile;
    if (logFile)
    {
        vfprintf(logFile, format, arg);
        fprintf(logFile, "\n");
    }
}

#define LOG_TO_FILE() \
    if (GetEngineConfig()->mLogToFile) \
    { \
        va_list argptr; \
        va_start(argptr, format); \
        LogToFile(format, argptr); \
        va_end(argptr); \
    }

void EnableLog(bool enable)
{
#if LOGGING_ENABLED
    sLoggingEnabled = enable;
#endif
}

bool IsLogEnabled()
{
    return sLoggingEnabled;
}

void LockLog()
{
    if (!sInitialized)
    {
        InitializeLog();
    }

    SYS_LockMutex(sMutex);
}

void UnlockLog()
{
    OCT_ASSERT(sInitialized);
    SYS_UnlockMutex(sMutex);
}

#if CONSOLE_ENABLED
// THE CONSOLE'S LINES ARE QUEUED, and the main thread writes them in (FlushConsoleMessages). A
// line can be logged from any thread -- the async loader logs every asset it loads -- but the
// console's Text widgets are the main thread's: it ticks them, gathers them to draw, and draws
// them. Written in straight from the loader thread, a line took a widget out of the console and
// put it back, and changed its text, while the main thread was part way through the same widgets
// (asleep in the middle of a frame, waiting for the GPU or for the disc). Nodes were used after
// they had moved, the heap was corrupted, and on a GameCube the whole 3D picture went to stripes
// to a single point until the game crashed -- in any build with Logging=1.
namespace
{
    struct PendingConsoleLine
    {
        char mText[128];
        glm::vec4 mColor;
    };

    const uint32_t kMaxPendingConsoleLines = 16;       // more than that in a frame: the oldest go
    PendingConsoleLine sPendingConsole[kMaxPendingConsoleLines];
    uint32_t sPendingConsoleHead = 0;                  // the oldest line not yet written in
    uint32_t sPendingConsoleCount = 0;
}
#endif

// (the log mutex is held: every caller locks it)
void WriteConsoleMessage(glm::vec4 color, const char* format, va_list args)
{
#if CONSOLE_ENABLED
    if (sPendingConsoleCount == kMaxPendingConsoleLines)
    {
        sPendingConsoleHead = (sPendingConsoleHead + 1) % kMaxPendingConsoleLines;
        sPendingConsoleCount--;
    }

    PendingConsoleLine& line = sPendingConsole[(sPendingConsoleHead + sPendingConsoleCount) % kMaxPendingConsoleLines];
    vsnprintf(line.mText, sizeof(line.mText), format, args);
    line.mColor = color;
    sPendingConsoleCount++;
#endif
}

void FlushConsoleMessages()
{
#if CONSOLE_ENABLED
    if (!sInitialized)
    {
        return;
    }

    PendingConsoleLine lines[kMaxPendingConsoleLines];
    uint32_t numLines = 0;

    LockLog();
    while (sPendingConsoleCount > 0)
    {
        lines[numLines++] = sPendingConsole[sPendingConsoleHead];
        sPendingConsoleHead = (sPendingConsoleHead + 1) % kMaxPendingConsoleLines;
        sPendingConsoleCount--;
    }
    UnlockLog();

    Renderer* renderer = Renderer::Get();
    Console* console = renderer ? renderer->GetConsoleWidget() : nullptr;

    for (uint32_t i = 0; i < numLines && console != nullptr; ++i)
    {
        console->WriteOutput(lines[i].mText, lines[i].mColor);
    }
#endif
}


void LogDebug(const char* format, ...)
{
#if LOGGING_ENABLED

    if (!sLoggingEnabled)
        return;

    LockLog();

    {
        va_list argptr;
        va_start(argptr, format);

        // Pass to SYS interface
        SYS_Log(LogSeverity::Debug, format, argptr);
        va_end(argptr);
    }

    {
        va_list argptr;
        va_start(argptr, format);

        // Write to in-game console
        WriteConsoleMessage({0.5f, 1.0f, 0.5f, 1.0f}, format, argptr);

        va_end(argptr);
    }

    LOG_TO_FILE();

    UnlockLog();
#endif
}


void LogWarning(const char* format, ...)
{
#if LOGGING_ENABLED

    if (!sLoggingEnabled)
    {
#if PLATFORM_DOLPHIN
        // Logging off is no log ON SCREEN; a console's warnings and errors still go to its SD
        // log (SYS_Log: nothing where there is no card log), the one place a hardware test can
        // say what went wrong.
        va_list argptr;
        va_start(argptr, format);
        SYS_Log(LogSeverity::Warning, format, argptr);
        va_end(argptr);
#endif
        return;
    }

    LockLog();

    {
        va_list argptr;
        va_start(argptr, format);

        // Pass to SYS interface
        SYS_Log(LogSeverity::Warning, format, argptr);
        va_end(argptr);
    }

    {
        va_list argptr;
        va_start(argptr, format);

        // Write to in-game console
        WriteConsoleMessage({1.0f, 1.0f, 0.5f, 1.0f}, format, argptr);

        va_end(argptr);
    }

    LOG_TO_FILE();

    UnlockLog();
#endif
}

void LogError(const char* format, ...)
{
#if LOGGING_ENABLED

    if (!sLoggingEnabled)
    {
#if PLATFORM_DOLPHIN
        // Logging off is no log ON SCREEN; a console's warnings and errors still go to its SD
        // log (SYS_Log: nothing where there is no card log), the one place a hardware test can
        // say what went wrong.
        va_list argptr;
        va_start(argptr, format);
        SYS_Log(LogSeverity::Error, format, argptr);
        va_end(argptr);
#endif
        return;
    }

    LockLog();

    {
        va_list argptr;
        va_start(argptr, format);

        // Pass to SYS interface
        SYS_Log(LogSeverity::Error, format, argptr);
        va_end(argptr);
    }

    {
        va_list argptr;
        va_start(argptr, format);

        // Write to in-game console
        WriteConsoleMessage({1.0f, 0.5f, 0.5f, 1.0f}, format, argptr);

        va_end(argptr);
    }

    LOG_TO_FILE();

    UnlockLog();

#endif
}

void LogConsole(glm::vec4 color, const char* format, ...)
{
#if LOGGING_ENABLED

    if (!sLoggingEnabled)
        return;

    LockLog();

    va_list argptr;
    va_start(argptr, format);

    // Write to in-game console
    WriteConsoleMessage(color, format, argptr);

    va_end(argptr);

    UnlockLog();

#endif
}
