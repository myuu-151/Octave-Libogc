#include <stdint.h>

#undef min
#undef max

#include "Engine.h"
#include "World.h"
#include "Renderer.h"
#include "InputDevices.h"
#include "Log.h"
#include "Assets/Scene.h"
#include "AssetManager.h"

#include "Nodes/Widgets/StatsOverlay.h"

#define EMBEDDED_ENABLED (PLATFORM_DOLPHIN || PLATFORM_3DS)

#if EMBEDDED_ENABLED
#include "../Generated/EmbeddedAssets.h"
#include "../Generated/EmbeddedScripts.h"
extern uint32_t gNumEmbeddedAssets;
#endif

#if PLATFORM_DOLPHIN && OCT_GDB
#include <debug.h>
#include <ogc/usbgecko.h>
#elif PLATFORM_DOLPHIN && OCT_GECKO_LOG
bool OctGeckoLogEnable();               // the engine (System_Dolphin.cpp): the log over the USB Gecko
#endif

void OctPreInitialize(EngineConfig& config)
{
#if PLATFORM_DOLPHIN && OCT_GDB
    // built as Debug (GDB): libogc's debug stub on the USB Gecko (slot A, else B). Waits here for GDB
    // (DolphinWorks' Start GDB; the screen stays black till then); "continue" in GDB runs the game.
    DEBUG_Init(GDBSTUB_DEVICE_USB, usb_isgeckoalive(EXI_CHANNEL_0) ? EXI_CHANNEL_0 : EXI_CHANNEL_1);
    _break();
#elif PLATFORM_DOLPHIN && OCT_GECKO_LOG
    OctGeckoLogEnable();                 // built with GECKOLOG=1: the log, live over the USB Gecko
#endif
    GetEngineState()->mStandalone = true;

#if !EDITOR

    if (config.mWindowWidth == 0)
        config.mWindowWidth = 1280;

    if (config.mWindowHeight == 0)
        config.mWindowHeight = 720;

#if EMBEDDED_ENABLED
    config.mEmbeddedAssetCount = gNumEmbeddedAssets;
    config.mEmbeddedAssets = gEmbeddedAssets;
    config.mEmbeddedScriptCount = gNumEmbeddedScripts;
    config.mEmbeddedScripts = gEmbeddedScripts;
    config.mEmbeddedConfig = gEmbeddedConfig_Data;
    config.mEmbeddedConfigSize = gEmbeddedConfig_Size;
#endif

#endif
}

void OctPostInitialize()
{

}

void OctPreUpdate()
{

}

void OctPostUpdate()
{

}

void OctPreShutdown()
{

}

void OctPostShutdown()
{

}
