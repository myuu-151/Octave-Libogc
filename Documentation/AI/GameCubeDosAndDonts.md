# GameCube: dos and don'ts

Read this before writing or changing GameCube code on Octave: engine code, or a
game's own code (renderers, loaders, threads, audio). It is written for AI
assistants, and holds for people too.

Every rule here comes from a bug that happened. Most of them **passed in
Dolphin and failed on the console**: a hang, a freeze, a green screen, or
something quietly missing. Dolphin is close to the hardware, but not exact, and
it reads the disc image as a disc where the console reads it from the SD card.
So "it works in Dolphin" proves little for this kind of code.

The one rule behind most of the others: **Octave already does the low-level
GameCube work, and its version has been through real hardware. Use it, or copy
its pattern. Don't write your own.** When the console and Dolphin disagree, look
first at wherever the game's code differs from Octave's.

---

## Where Octave does it

Paths under `Engine/Source/`. Read these before writing the same thing.

| What | Octave's code |
|---|---|
| Frames, waiting for the GPU, the retrace | `Graphics/GX/Graphics_GX.cpp` (`GFX_BeginFrame`, `GFX_EndFrame`), `GxWaitGpu` / `GxDeferFree` in `Graphics/GX/GxUtils.h` |
| Display lists | `Graphics/GX/GxUtils.cpp` |
| Textures (loading, freeing, refilling) | `Graphics/GX/Graphics_GX.cpp`, `Engine/Assets/Texture.cpp` (`ReloadPart`, `ReloadFrom`) |
| Disc and SD reads | `System/Dolphin/System_Dolphin.cpp` (`SYS_AcquireFileData`, `SYS_ReadFileRange`, `OctLockFileIo`) |
| Threads | `System/Dolphin/System_Dolphin.cpp` (`SYS_CreateThread`), `Audio/Dolphin/Audio_Dolphin.cpp` |
| Sound, ARAM, streamed music | `Audio/Dolphin/Audio_Dolphin.cpp` (`AramDma`, `AUD_*`) |
| Pads | `Input/Dolphin/Input_Dolphin.cpp` |
| Memory card | `System/Dolphin/System_Dolphin.cpp` |
| Logging | `OctLog` in `System/Dolphin/System_Dolphin.cpp` |
| Heap fragmentation | `System/Dolphin/BigBlockCache_Dolphin.cpp` |

Also read the `\bug` and `\note` lines in libogc's headers
(`devkitPro/libogc/include/ogc/*.h`) for any GX call you use in a new way.

---

## Graphics (GX)

**Don't** draw with no colour channel and no texture coordinate at once
(`GX_SetNumChans(0)` with `GX_SetNumTexGens(0)`). The console's GPU hung a
moment after it started drawing plain rectangles that way; Dolphin drew them.
**Do** draw solid colour with a small white texture, as Octave does
(`T_White`), or with a colour channel.

**Don't** `free()` anything the GPU reads (textures, vertex arrays, display
lists) straight away. Octave lets the GPU draw one frame while the CPU works on
the next, so the GPU can still be reading it. **Do** hand it to `GxDeferFree`.
A display list freed early is the worst case: `free()` writes its bookkeeping
into the list's first bytes, and the GPU runs them as commands.

**Don't** rewrite memory the GPU reads (texels, vertices) while it may still be
drawing. **Do** call `GxWaitGpu()` first.

**Do** call `GX_InvalidateTexAll()` after new texels arrive (a load, or a
refill in place). The texture cache is keyed by address, so a new texture where
an old one was cached can draw stale texels.

**Don't** size a display list's buffer to fit the list exactly. **Do** leave
64 bytes after it, as `GxUtils.cpp` does. When list plus flush filled the buffer
exactly, `GX_EndDispList` returned 67108864 (the FIFO wrap flag) on the console,
and those shapes never drew. Dolphin gave the right size.

**Don't** issue GX calls from any thread but the main one.
`GX_InitTexObj` is only a struct fill and is safe anywhere, but
`GX_InvalidateTexAll`, `GX_LoadTexObj` and drawing all go into the FIFO.

**Don't** draw masked content at exactly the depth the mask wrote and test for
equality. The console rounds the written and tested depths differently, so
parts went missing. **Do** offset it half a level and test `GX_GEQUAL`.

**Don't** pair one texture coordinate with textures of different sizes.
Normalised coordinates are scaled by each paired texture's own size. Video with
full-size Y and half-size chroma drew zoomed 2x on the console. Give each size
its own texcoord.

**Don't** trust devkitPro's `gxtexconv` for CMPR textures with alpha: it always
writes opaque DXT1. Octave encodes CMPR itself (`CmprEncoder.cpp`). If a
material shows only its last texture, suspect lost alpha first.

**Do** restore the GX state Octave's UI expects after custom drawing in a
widget: viewport, scissor, Z mode, alpha compare, and the colour channels.
`SetupLightingChannels` caches the channels it last set, so reset them from
`gGxContext.mLighting`.

**Don't** make meshes or textures smaller to gain frame rate. Look at how GX is
fed (strips, formats, draw order, the texture cache) and measure with the GX
performance counters first.

---

## Memory (24 MB)

**Do** plan for fragmentation, not only the total. One game had 9.7 MB free but
no block bigger than 544 KB after three stage changes, and loads failed.
Reuse big blocks instead of freeing and allocating them again.
`BigBlockCache_Dolphin.cpp` helps, but only when the game links it with
`-Wl,--wrap=malloc,--wrap=free,--wrap=realloc,--wrap=calloc,--wrap=memalign`
(see `Standalone/Makefile_GCN`).

**Don't** read a file whole and then copy it (a temp buffer plus the final copy
is double the memory). **Do** read straight into where it will live:
`SYS_ReadFileRange` into the texture's own texels, as `Texture::ReloadPart`
does.

**Don't** let an STL container grow unbounded on the console. With no
exceptions, a failed `operator new` calls `abort()`, which spins forever in
libogc's `_exit`: a freeze with no crash screen. **Do** size buffers up front
and check allocations.

**Do** give any buffer that disc or DMA data passes through 32-byte alignment
(`memalign(32, ...)` or `__attribute__((aligned(32)))`). An unaligned static
buffer flashed garbage over the 3D view for about 25 frames.

**Don't** read the `heap=` figure in the PERF log as "memory left". It is
`mallinfo().fordblks`, free space inside what malloc has already claimed. The
unclaimed arena (`SYS_GetArena1Hi() - SYS_GetArena1Lo()`) can be megabytes more.

**Do** look for assets the engine keeps loaded before cutting game data. The
splash texture alone was 1.3 MB.

---

## Threads, the SD card and the disc

**Do** give every thread that touches the SD card 64 KB of stack.
`fread` goes through libfat and the SD driver. 16 KB overflowed on the console
and hung at the same read every run: a hang at the same spot each time means
memory corruption, not a race.

**Do** keep reader threads below the main thread's priority (64). Octave's
loader is 40 and its audio thread is 50. SD PIO and the DVD reader busy-wait,
so a reader above the main thread freezes frames.

**Do** hold `OctLockFileIo()` / `OctUnlockFileIo()` around every SD card
access your code makes itself: reads, writes, logs, `stat()`. The SD driver
keeps shared state, and two threads in it at once hang the card. Octave's own
reads and `OctLog` already take this lock.

**Don't** add a thread when Octave reads on the main thread for the same job.
For a texture needed later, read it a piece a frame with `SYS_ReadFileRange`,
like `Texture::ReloadPart`.

**Don't** assume every file access goes through the disc image. `stat()`,
`fopen()` and directory scans go to the SD card's FAT unless they use Octave's
functions, which look in the image first.

**Do**, when a disc build shows a green screen with no log, suspect the SD
mount first. A game that couldn't find its `.iso` on the first-mounted card
fell back to the empty disc drive and busy-waited there.

---

## Audio

**Do** use Octave's audio (`Audio_Dolphin.cpp`) and its ARAM path for sound
effects. That frees main memory, and it already handles libasnd's traps:
- a voice with a callback never reports finished;
- `ASND_TestVoiceBufferReady` is also true for an empty voice;
- `ASND_AddVoice` fails until the mixer takes the previous buffer, so remove
  data from your queue only after it succeeds.

**Do** read streamed music's data off the main thread, or keep the reads small.
Main-thread refills queued behind a loader's big reads caused 100 ms stutters.

---

## Logging and finding console bugs

**Don't** call `SYS_Report` (OSReport) on the console. It talks to the IPL's
EXI device, which can disturb the RTC or hang. **Do** use `OctLog`: it goes to
`/octiso.log` on the SD card through a low-priority writer thread, and to
Dolphin's log window when there is no card. The SD log only exists when
`Engine/Source/System/Dolphin/IsoLog_local.h` is present (copy it from
`IsoLog_local.h.off`; it is git-ignored).

**Do** add a watchdog to any game about to be tested on hardware: a thread
above every other (priority 100, 64 KB stack) that logs where the main thread
was when updates and frames stop for 3 seconds. Mark the main thread's position
with a cheap `volatile const char*`. Its line reaches the card whenever the
main thread is blocked. That's how a hang was traced to the GPU (main stuck
in `GFX_BeginFrame`'s `GX_WaitDrawDone`) instead of the game code.

**Do** read the whole log from a hardware run, and compare it with the last
good run before building the next test. The PERF lines' worst-frame breakdown
usually names the cause. Guessing cost many round trips on earlier bugs.

**Do** reproduce game-logic bugs on the PC build first. Only code that is
GameCube-specific needs the console.

**Do**, for a silent freeze in Dolphin, attach Dolphin's GDB stub before
anything else (`[General] GDBPort`), and map the PC with
`powerpc-eabi-addr2line -f -e <game>.elf`. Also:
- a PC in `KThreadIdleMain` is a healthy game waiting for vsync, not the
  freeze;
- Dolphin with DSP HLE freezes libasnd games that read the disc while music
  plays, so test with DSP LLE.

**Do** use blue and yellow, or solid and flashing, for on-screen
diagnostics. Never red against green: the owner of this repo is colour-blind.

---

## Building and testing

**Do** build GameCube targets from PowerShell, with
`C:\devkitPro\devkitPPC\bin;C:\devkitPro\tools\bin;C:\devkitPro\msys2\usr\bin`
on PATH. From Git Bash the compiler can't write its temp files. Package with
the repo-root `Octave.exe -headless -project <game>.octp -build GameCube`:
the copy under `Standalone/Build` silently skips the disc image.

**Do** rebuild the Windows editor after changing texture cooking
(`Texture.cpp`, the CMPR encoder): cooking runs on the PC, not the console.

**Do** run automated Dolphin tests in a scratch user directory (`-u <dir>`),
with:
- its volume at 0;
- `[Input] BackgroundInput = False`, and its pads unmapped (the user's typing
  otherwise drives the test);
- DSP LLE.

**Do** build test images from a scratch copy, never over the disc image the
user may be playing.

**Do** check a copy onto the SD card byte for byte (hash both). A half-written
image boots and then fails in odd ways.

**Do** keep a test build's `.elf` with its logs: failed allocations log code
addresses that only that build can name.

---

## Octave engine gotchas

- A `Widget` subclass must override `GetDrawData`, or its `Render` never runs.
- `Primitive3D` bodies that were simulated once keep their mass and inertia
  when physics is switched on again (`SetMass` skips an unchanged value). Warm
  up the solver with throwaway bodies, never ones the game will use.
- On the GameCube, the `Text` widget drew with a null texture and crashed. A
  game that needs text on the console draws its own bitmap font.
- Lua on the console: errors don't reach the Dolphin log (show them on screen),
  a syntax error silently falls back to other scripts, and
  `Set-Content -Encoding utf8` adds a BOM that the engine's Lua rejects.
- libogc's `CARD_Write` with more than one sector writes only the first and
  still returns success: write one sector at a time.
