# Template: an Octave game made in code

A project to start from without the editor. DolphinWorks' **New project** makes one from this folder (renaming
`OctTemplate`); by hand, copy it and replace `OctTemplate` with your game's name in the `.octp`, `Config.ini`
and `Makefile_GCN`.

It comes two ways:

- **Lua**: `OctTemplate.octp`, `Config.ini`, `Assets/`, and `Scripts/`. `Scripts/Startup.lua` runs when the game
  starts and makes its first node (a canvas the size of the screen) with `Scripts/Game.lua` on it: `Game:Create`
  runs once, `Game:Tick` every frame. No scene needed. Packaging builds it with Octave's Standalone program.
- **C++**: the same, without the Lua game, plus `Source/Main.cpp` (the engine's hooks: `OctPreInitialize`,
  `OctPostInitialize`, `OctPreUpdate`, `OctPostUpdate`; the game starts in `OctPostInitialize`) and
  `Makefile_GCN`, which links the prebuilt engine library (`Engine/Build/GCN/libEngine.a`). Lua runs beside it:
  a `Scripts/Startup.lua` runs at startup in a C++ game too.

Either one shows "Hello, GameCube!" in the middle of the screen and counts presses of A.

**Assets without the editor:** put pictures, sounds and models (PNG, WAV, OGG, MP3, GLB, glTF, OBJ, and .blend
through Blender) in a `Raw/` folder; `Tools/octkit.py convert <project>` (DolphinWorks does it on every Build) makes
them Octave assets in `Assets/`, settings per file in `Raw/assets.json`, and the game loads them by name
(`LoadAsset("T_Logo")`). **A build step of its own:** `build.py` (copy this one in) runs after that, before packaging,
with `octkit` to import: for what the game makes for itself, as Sonic Pipe Dream's scripts did.

Build it for GameCube with `Octave.exe -headless -project <path>/<Name>.octp -build GameCube` (DolphinWorks'
Build runs that), which writes `Packaged/GameCube/<Name>.iso`. A C++ project finds the engine through the
`OCTAVE` environment variable (DolphinWorks sets it), else `Makefile_GCN`'s default. `GECKOLOG=1` or `GDB=1` in
the environment build it with the USB Gecko log or GDB's debug stub.

(`Makefile_3DS`, `Makefile_Wii`, `Makefile_Linux_*` and `OctTemplate.vcxproj` are upstream Octave's, for its
other platforms; they aren't kept up to date in this fork.)
