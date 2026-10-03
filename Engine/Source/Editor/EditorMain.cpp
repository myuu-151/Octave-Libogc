#if EDITOR

#include <stdint.h>
#include <stdio.h>

#if PLATFORM_WINDOWS
#include <Windows.h>
#endif

#undef min
#undef max

#include "Engine.h"
#include "World.h"
#include "Renderer.h"
#include "Log.h"

#include "Nodes/Widgets/Quad.h"
#include "Nodes/Widgets/Text.h"
#include "Nodes/Widgets/Canvas.h"

#include "Nodes/3D/StaticMesh3d.h"
#include "Nodes/3D/PointLight3d.h"
#include "Nodes/3D/TestSpinner.h"

#include "ActionManager.h"
#include "AssetManager.h"
#include "AssetDir.h"
#include "InputManager.h"
#include "Preferences/PreferencesManager.h"
#include "Grid.h"
#include "Assets/StaticMesh.h"
#include "Assets/Font.h"
#include "EditorState.h"
#include "EditorImgui.h"
#include "Utilities.h"
#include "System/System.h"

#include <string>

void OctPreInitialize(EngineConfig& config);

void EditorMain(int32_t argc, char** argv)
{
    GetEngineState()->mArgC = argc;
    GetEngineState()->mArgV = argv;

#if PLATFORM_WINDOWS
    // Anchor the working directory to the exe's own folder so engine resources
    // (fonts, default assets, shaders) resolve no matter how the editor was
    // launched. Without this, double-clicking a .octp sets the working directory
    // to the project folder, and the editor can't find Engine/Assets -> crash.
    {
        std::string exePath = SYS_GetExecutablePath();
        size_t slash = exePath.find_last_of("\\/");
        if (slash != std::string::npos)
        {
            SetWorkingDirectory(exePath.substr(0, slash));
        }
    }
#endif

    ReadCommandLineArgs(argc, argv);

    {
        EngineConfig* mutableConfig = GetMutableEngineConfig();
        OctPreInitialize(*mutableConfig);
    }

    ReadEngineConfig();

    Initialize();

    const EngineConfig* engineConfig = GetEngineConfig();

    // Headless build mode - minimal initialization, run build, and exit
    if (IsHeadless())
    {
        LogDebug("Headless mode: Starting");
        LogDebug("Headless mode: Project path = %s", engineConfig->mProjectPath.c_str());
        LogDebug("Headless mode: Build platform = %d", (int)engineConfig->mBuildPlatform);

        ActionManager::Create();

        // Load project directly without editor state
        if (engineConfig->mProjectPath != "")
        {
            LoadProject(engineConfig->mProjectPath);

            // Check and auto-upgrade assets to new UUID format
            if (ActionManager::Get()->CheckProjectNeedsUpgrade())
            {
                LogDebug("Headless mode: Auto-upgrading assets to new UUID format...");
                ActionManager::Get()->UpgradeProject();
            }
        }

        // -import: files imported as the editor's Import Asset would, each into its folder in Assets/ (made in the
        // asset tree as needed; the folder on disk must be there). How a project made without the editor gets
        // what only Octave's importers make, a cooked video above all (octkit, DolphinWorks).
        for (size_t i = 0; i + 1 < engineConfig->mImportPaths.size(); i += 2)
        {
            const std::string& file = engineConfig->mImportPaths[i];
            const std::string& folder = engineConfig->mImportPaths[i + 1];
            AssetDir* dir = AssetManager::Get()->FindProjectDirectory();
            size_t start = 0;
            while (dir != nullptr && start < folder.size())
            {
                size_t slash = folder.find_first_of("/\\", start);
                std::string part = folder.substr(start, slash == std::string::npos ? std::string::npos : slash - start);
                if (part != "")
                {
                    AssetDir* sub = dir->GetSubdirectory(part);
                    dir = (sub != nullptr) ? sub : dir->CreateSubdirectory(part);
                }
                start = (slash == std::string::npos) ? folder.size() : slash + 1;
            }
            if (dir == nullptr)
            {
                LogError("Headless import: no project to import %s into", file.c_str());
                continue;
            }
            GetEditorState()->SetAssetDirectory(dir, false);
            Asset* asset = ActionManager::Get()->ImportAsset(file);
            if (asset != nullptr)
            {
                LogDebug("Headless import: %s -> %s%s.oct", file.c_str(), dir->mPath.c_str(), asset->GetName().c_str());
            }
            else
            {
                LogError("Headless import failed: %s", file.c_str());
            }
        }

        if (engineConfig->mBuildPlatform != Platform::Count)
        {
            LogDebug("Headless mode: Building for %s (embedded=%d)",
                     GetPlatformString(engineConfig->mBuildPlatform),
                     engineConfig->mBuildEmbedded ? 1 : 0);

            ActionManager::Get()->BuildData(engineConfig->mBuildPlatform, engineConfig->mBuildEmbedded);

            LogDebug("Headless mode: Build complete");
        }
        else if (engineConfig->mImportPaths.empty())
        {
            LogError("Headless mode: No build platform specified. Use -build <platform>");
        }

        // Cleanup and exit
        ActionManager::Destroy();
        Shutdown();
        return;
    }

    // Normal editor initialization
    GetEditorState()->Init();

    ActionManager::Create();
    InputManager::Create();
    PreferencesManager::Create();

    InitializeGrid();

    if (engineConfig->mProjectPath != "")
    {
        // Clear the project path so we don't overwrite the EditorProject.sav file with default data.
        // This would have been set earlier in Initialize() to ensure that shader cache is loaded correctly.
        // TODO: Seems like we don't need to be storing shader cache in project folder when running the editor?
        GetEngineState()->mProjectName = "";
        GetEngineState()->mProjectPath = "";
        GetEngineState()->mProjectDirectory = "";

        ActionManager::Get()->OpenProject(engineConfig->mProjectPath.c_str());
    }

    // Spawn starting scene if a default wasn't loaded, with no project open. A project with no scene (a game
    // made in code) keeps what its Scripts/Startup.lua built while it loaded, as opening it from File does: an
    // empty scene opened here would clear that, and the spinning demo isn't the project's.
    if (GetEditorState()->GetEditScene() == nullptr && GetEngineState()->mProjectPath == "")
    {
        GetEditorState()->OpenEditScene(nullptr);
        GetWorld(0)->SpawnNode<TestSpinner>();
    }

    Renderer::Get()->EnableConsole(true);
    Renderer::Get()->EnableStatsOverlay(false);

    bool ret = true;

    while (ret)
    {
        InputManager::Get()->Update();
        ActionManager::Get()->Update();

        bool playInEditor = GetEditorState()->mPlayInEditor;

        if (playInEditor)
        {
            OctPreUpdate();
        }

        ret = Update();

        if (GetEditorState()->mEndPieAtEndOfFrame)
        {
            GetEditorState()->EndPlayInEditor();
        }

        // We are trying to quit, and haven't done the shutdown check yet
        if (!ret && !GetEditorState()->mShutdownUnsavedCheck)
        {
            GetEditorState()->mShutdownUnsavedCheck = true;
            std::vector<AssetStub*> unsavedAssets = AssetManager::Get()->GatherDirtyAssets();

            if (unsavedAssets.size() > 0)
            {
                // Need to wait on user response.
                ret = true;
                GetEngineState()->mQuit = false;

                // Have the imgui callbacks set / clear the Quit and Shutdown check flags as appropriate.
                EditorShowUnsavedAssetsModal(unsavedAssets);
            }
        }

        if (playInEditor)
        {
            OctPostUpdate();
        }
    }

    PreferencesManager::Destroy();
    GetEditorState()->Shutdown();
    Shutdown();
}

#endif
