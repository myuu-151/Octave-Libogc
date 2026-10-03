// OctTemplate: an Octave game in C++, made without the editor.
//
// The engine calls these hooks: OctPreInitialize before it starts (the window size, and on GameCube the
// assets and scripts packaged into the program), OctPostInitialize once it has (make the game here), then
// OctPreUpdate / OctPostUpdate every frame. Lua runs beside it: the project's Scripts/Startup.lua, if there
// is one, runs at startup too.

#include <stdint.h>
#include <stdio.h>

#undef min
#undef max

#include "Engine.h"
#include "World.h"
#include "InputDevices.h"
#include "Log.h"
#include "Nodes/Widgets/Canvas.h"
#include "Nodes/Widgets/Text.h"

#define EMBEDDED_ENABLED (PLATFORM_DOLPHIN || PLATFORM_3DS)

#if EMBEDDED_ENABLED && __has_include("../Generated/EmbeddedAssets.h")
#include "../Generated/EmbeddedAssets.h"
#include "../Generated/EmbeddedScripts.h"
#define EMBEDDED_FILES 1
#endif

#if PLATFORM_DOLPHIN && OCT_GDB
#include <debug.h>
#include <ogc/usbgecko.h>
#elif PLATFORM_DOLPHIN && OCT_GECKO_LOG
bool OctGeckoLogEnable();               // the engine (System_Dolphin.cpp): the log over the USB Gecko
#endif

static Text* sText = nullptr;
static int32_t sPresses = 0;

static void ShowText()
{
    char line[64];
    snprintf(line, sizeof(line), "Hello, GameCube!\nPress A  (%d)", (int)sPresses);
    sText->SetText(line);
}

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

#if EMBEDDED_FILES
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
    // The game's first node: a canvas the size of the screen, with a line of text in its middle.
    Canvas* canvas = GetWorld(0)->SpawnNode<Canvas>();
    canvas->SetName("Game");
    // the whole screen: stretched to its parent, no margins (a canvas with no parent: the screen)
    canvas->SetAnchorMode(AnchorMode::FullStretch);
    canvas->SetMargins(0.0f, 0.0f, 0.0f, 0.0f);
    sText = (Text*)canvas->CreateChild(Text::GetStaticType());
    sText->SetAnchorMode(AnchorMode::FullStretch);
    sText->SetMargins(0.0f, 0.0f, 0.0f, 0.0f);
    sText->SetHorizontalJustification(Justification::Center);
    sText->SetVerticalJustification(Justification::Center);
    sText->SetTextSize(36.0f);
    ShowText();
    LogDebug("OctTemplate: started");
}

void OctPreUpdate()
{
}

void OctPostUpdate()
{
    if (IsGamepadButtonJustDown(GAMEPAD_A, 0))
    {
        ++sPresses;
        ShowText();
    }
}

void OctPreShutdown()
{
}

void OctPostShutdown()
{
}
