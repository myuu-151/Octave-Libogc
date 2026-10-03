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
| Heap fragmentation (big blocks of repeating sizes) | `System/Dolphin/BigBlockCache_Dolphin.cpp` |

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

**Don't** use libogc's `guMtxConcat`. On the GameCube it is `ps_guMtxConcat`,
and in libogc 3.0.4 that routine is broken. It loads the 0 of its constant
`{0, 1}` with a `psq_l` off r13 through an `R_PPC_SDAREL16` relocation, but
`psq_l` has only 12 bits of offset. The linker writes 16, and the top bits land
in the instruction's W and I fields. So it loads one float (the 1 comes free)
from 608 bytes past r13, from whatever variable the link happens to put there.
Every matrix it makes then gets that float times the first matrix's
translation in its third column. That float is usually zero, so all looks well
until the variable changes. In Sonic Pipe Dream it sat inside a disc read
buffer: after the first read into it, every 3D object collapsed into "stripes
to a single point" for the rest of the run, while the 2D HUD was fine.
- Octave calls `c_guMtxConcat`, and its `GxUtils.h` points the name
  `guMtxConcat` at it.
- Game code that includes `gccore.h` itself must call `c_guMtxConcat`.
- To check a build: `powerpc-eabi-objdump -d -M gekko <game>.elf` should show
  no `psq_l`/`psq_st` off `r13` or `r2`, and no call to `ps_guMtxConcat`.

**Do** call `GX_InvVtxCache()` when a vertex array is made in memory that may
have held another one. BigBlockCache hands big blocks on, and the GPU's vertex
cache is keyed by address. Dolphin doesn't emulate that cache; the console
does.

---

## Memory (24 MB)

**Do** plan for fragmentation, not only the total. One game had 9.7 MB free but
no block bigger than 544 KB after three stage changes, and loads failed.
Reuse big blocks instead of freeing and allocating them again.
`BigBlockCache_Dolphin.cpp` helps, but only when the game links it with
`-Wl,--wrap=malloc,--wrap=free,--wrap=realloc,--wrap=calloc,--wrap=memalign`
(see `Standalone/Makefile_GCN`).

**Do** measure before linking the big block cache into a game that isn't
built on it. It suits big allocations that come back at the same sizes (a
sky's frames, the same stage pieces). Where they vary (each level's file,
textures of many sizes), it holds freed blocks for sizes that never return: in
one game it kept about 3 MB, and the biggest free piece while playing fell from
about 1 MB to under 250 KB. **Don't** find the biggest free piece by trying
`malloc` through the cache: a failed try empties it, and a successful big one
gets kept. Try `__real_malloc`.

**Don't** keep a table that only grows in a `std::vector`. Each time it
fills, it copies itself into one block twice the size, needing both at once,
late in a session when no piece that big is left. **Do** use a `std::deque`
(it grows in small pieces and never moves its elements), or reserve the
vector's final size at boot.

**Don't** let a Lua table grow for the whole of a session either. Lua keeps a
table's slots in one block and doubles it when it fills: past 8192 slots that
is 128 KB in one piece, plus the old 64 KB during the copy. A marathon kept its
track, a table per frame, in one table for the whole run. At the fourth zone
the heap had 2.5 MB free and no 128 KB piece, so the zone could not be joined.
It was built again and failed again every 1.7 s until the run ran off the end
of its track. **Do** take out what is passed and move the rest down
(`table.move`, then `nil` the tail) so the table stays a fixed size.

**Do** keep Lua's collector close behind a script that makes a lot of garbage:
`collectgarbage("setpause", 110)` and `collectgarbage("setstepmul", 1000)`.
At a stepmul of 400, Lua's heap rose a megabyte above what was live (2.8 to
4 MB) each time a zone was built. At the top of each rise, the engine's own
allocations failed.

**Do** reserve blocks, not only pin them, for anything streamed in and out at
one size: `System.PinBlocks(size, count, true)` takes them at boot, while the
heap is in one piece. Pinned only, a change of sky still had to find blocks in
the heap, and late in a run it found none. **Do** pin the size the allocation
really asks for: a 64 KB texture's block is 65,600 bytes with its header. A pin
of 65,536 reserves blocks too small for it.

**Do** release asset handles (`Asset:Release`) when a script replaces a whole
set of them. A dropped table's handles keep their assets loaded until Lua's
collector gets round to them, which on a busy heap can be many seconds.

**Don't** leave dead objects waiting for a cleanup that runs every N new ones.
Until it runs, up to N of them per owner are still using memory: a sweep every
1024 display nodes held about 540 KB. Keep N small, or free them when they die.

**Don't** read a file whole and then copy it (a temp buffer plus the final copy
is double the memory). **Do** read straight into where it will live:
`SYS_ReadFileRange` into the texture's own texels, as `Texture::ReloadPart`
does.

**Don't** let an STL container grow unbounded on the console. With no
exceptions, a failed `operator new` calls `abort()`, which spins forever in
libogc's `_exit`: a freeze with no crash screen. **Do** size buffers up front
and check allocations.

**Do** give any buffer that disc or DMA data passes through 32-byte alignment
(`memalign(32, ...)` or `__attribute__((aligned(32)))`). DMA writes, and cache
invalidates, work in whole 32-byte lines, so an unaligned buffer shares its
edge lines with its neighbours. (The "garbage over the 3D view" once blamed on
an unaligned buffer was really the broken `guMtxConcat` above: moving the
buffer only moved what that routine read.)

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

**Don't** read through a scratch buffer as big as the read. That needs the
data's size twice, in one piece. The disc reader did this for unaligned reads
until a 499 KB file failed to load late in a session with 680 KB in one piece.
**Do** read through a small fixed buffer, a piece at a time.

**Don't** touch nodes or widgets from any thread but the main one, and that
includes logging on screen. With `Logging=1`, the async loader's "Asset loaded"
lines used to rebuild the console's Text widgets while the main thread was part
way through them, whenever it slept waiting for the GPU or the disc. Nodes were
used after they had moved, and the heap was corrupted. Octave now queues console
lines and writes them in on the main thread (`FlushConsoleMessages`).

**Don't** read megabytes on the main thread while the game plays, even a piece
a frame. The SD card gives 0.3 to 0.7 MB/s, so a sky's 4 MB of star frames read
by `Texture::ReloadPart` held a zone change at 7 frames a second for half a
minute. **Do** read it in the background: `Texture::ReloadFromAsync` and
`IsReloading`, on `SYS_ReadFileRangeInBackground`. That thread sits below the
asset loader and rests as long as each piece took, so it takes about half the
card. Without the rest it starved the loader, and the sky's streamed frames
stopped coming.

**Don't** share one `FILE` on the ISO between reading threads. Each change of
reader is a seek, which throws away stdio's read-ahead and may walk the FAT
cluster chain. A streamed sky stuttered whenever anything else read. Octave now
gives each reading thread its own handle (`IsoFileForThread` in
`System_Dolphin.cpp`), so each thread's reads carry on forwards.

**Do** stash data that's needed at a moment's notice in ARAM when the card is
too slow to read it then: `Texture:StashFrom` reads a texture's texels into
ARAM in the background, and `ReloadFromStash` DMAs them in within a few
milliseconds. That's how a marathon's next sky is ready on the emerald.

**Don't** allocate a bounce buffer for each read. Under memory pressure the
`memalign` fails, and the read fails part way. The disc reader now uses one
static 64 KB buffer, under its mutex.

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

## A debug layout

Set this up before the first test run of a bug, and work down it in order.
Each step is cheap. Jumping straight to custom checks is what cost hours before.

**1. The setup**

- **Dolphin:** a scratch user folder (`-u <dir>`) with:
  - volume 0, background input off, pads unmapped;
  - DSP LLE.
- **Its log:** `<dir>/Config/Logger.ini`.
  - `[Options]`: `WriteToFile = True`, `Verbosity = 3`.
  - `[Logs]`: `OSREPORT`, `CP`, `GP`, `PI`, `PE` and `Video` all `True`.
  - The log lands in `<dir>/Logs/dolphin.log`. Close anything tailing it
    before the next run, or it can't be cleared.
- **A log build of the game:**
  - `Logging=1` in the project's `Config.ini`, and `OCT_DOLPHIN_EMU_LOG 1` in
    `System_Dolphin.cpp`: engine logs go on screen and into Dolphin's log.
  - `IsoLog_local.h` for `/octiso.log` on hardware.
  - Put all three back before committing.
- **Keep the `.elf` with the logs.** Addresses mean nothing without it.
- **Launch line:**
  `Dolphin.exe -u <dir> -C Dolphin.Core.FastDiscSpeed=True -C Dolphin.Core.EmulationSpeed=0 -b -e <game>.iso`.
  For gdb, add `-C Dolphin.General.GDBPort=2345 -C Dolphin.Interface.DebugModeEnabled=True`.
- **Screenshots on a timer**, not by hand, and a game-side test switch that
  plays the game by itself up to the bug (Sonic Pipe Dream's `GcTest.lua`).

**Hardware-true Dolphin.** The launch line above is tuned for fast repeats.
To chase a "console only" bug, or to confirm a fix before a hardware test, set
the scratch folder's config as close to the console as Dolphin goes. It runs
several times slower: the boot's loading bar alone takes over a minute.

`<dir>/Config/Dolphin.ini`:

```ini
[Core]
DSPHLE = False            ; the real audio microcode (HLE freezes libasnd games)
CPUThread = False         ; single core: CPU and GPU interleave the way the console's do
AccurateCPUCache = True   ; emulate the data cache: a missing DCFlushRange/DCInvalidateRange shows
Fastmem = False           ; no host-memory shortcut: every access takes the checked path
FPRF = True               ; float result flags, as the console sets them
AccurateNaNs = True
EmulationSpeed = 1        ; real speed: timing bugs need it (0, unlimited, is for fast repeats)
FastDiscSpeed = False     ; real disc timing (the console reads the SD card: see below)
OverclockEnable = False
RAMOverrideEnable = False ; 24 MB, as the console has
[DSP]
EnableJIT = True          ; the LLE microcode recompiled; the same results, faster
[Interface]
UsePanicHandlers = False  ; warnings go to the log, not a dialog that stalls a test run
```

**Don't** turn on `MMU = True`. libogc's start-up (`__CheckARGV`, straight
from `__app_start`) reads low memory at address `0x28`. Dolphin's MMU emulation
takes that as a crash, and the game never gets past a black screen. Without it,
these settings show one harmless "Invalid read from 0x00000028, PC =
0x80003100" warning at boot, and the game carries on.

`<dir>/Config/GFX.ini`:

```ini
[Hacks]
EFBAccessEnable = True          ; the CPU can read the framebuffer
EFBToTextureEnable = False      ; EFB copies really go to RAM
XFBToTextureEnable = False      ; so do XFB copies
DeferEFBCopies = False          ; ...when the GPU makes them, not later
ImmediateXFBEnable = False
SkipDuplicateXFBs = False
EFBEmulateFormatChanges = True
BBoxEnable = True
[Settings]
SafeTextureCacheColorSamples = 0 ; hash whole textures, so texels changed in RAM are seen
FastDepthCalc = False
```

What Dolphin can't match, however it is set:
- The GPU's **vertex cache**, and the texture cache going stale. A missing
  `GX_InvVtxCache` or `GX_InvalidateTexAll` draws correctly in Dolphin.
- The **SD card path**. The console reads the disc image from the SD card, and
  Dolphin reads it as a disc. Dolphin has no GameCube SD card adapter to put in
  a slot (checked in 2609-1: memory card, GCI folder, USB Gecko, the broadband
  and modem adapters, Advance Game Port, microphone; its SD card is the Wii's),
  so this path is console-only. `OCT_FORCE_SD 1` (`System_Dolphin.cpp`) only
  matters on hardware. Dolphin does emulate a USB Gecko, which helps the logs.
- The **write-gather pipe's** partial bursts, and the GPU's exact timing.
- For anything still in doubt, `CPUCore = 0` (the interpreter) is the reference
  CPU: slowest of all, but no JIT shortcuts.

**2. The first move, by symptom**

| Symptom | First move |
|---|---|
| All the 3D wrong, the 2D fine | Dolphin's GPU logs ("unknown opcode"?), then a per-draw check of the matrices sent |
| Garbage on some objects only | That mesh's display lists and vertex array (checksums), and how they are freed and rewritten (`GxDeferFree`, `GxWaitGpu`) |
| A freeze with no crash screen | gdb: attach, `bt`, and `addr2line` on the PC. `KThreadIdleMain` is only waiting for vsync |
| A crash screen (DSI, ISI) | `powerpc-eabi-addr2line -f -e <game>.elf` on SRR0 and LR. A DSI at a small address is a null pointer |
| Hangs at the same spot every run | Memory corruption (a stack too small, a buffer overrun), not a race |
| Fine in Dolphin, fails on the console | The SD card path (alignment, stack sizes, locks), the vertex cache, timing. Add the watchdog and read the SD log |
| Memory runs out late in a session | Replay a recorded session; compare what each `operator new` caller holds per level |
| A value looks overwritten | Dump it and disassemble what reads it; a canary for *when*; a gdb watchpoint for *who* (CPU stores only) |
| Game logic wrong | Reproduce it on the PC build first |

**3. The rules of the hunt**

- **Change one thing per run**, and compare each log with the last good one.
- **A fix that works but can't be explained isn't a fix.** A bug that depends
  on where the linker puts things "goes away" whenever anything moves. Three
  such false fixes hid the broken `guMtxConcat` across several sessions.
- **Mark every diagnostic `TEMP`** and take it all out at the end. Check the
  test switches are off (`GcTest = {}`, `Logging=0`) before committing.

---

## Logging and finding console bugs

**Don't** call `SYS_Report` (OSReport) on the console. It talks to the IPL's
EXI device, which can disturb the RTC or hang. **Do** use `OctLog`: it goes to
`/octiso.log` on the SD card through a low-priority writer thread, and to
Dolphin's log window when there is no card. The SD log only exists when
`Engine/Source/System/Dolphin/IsoLog_local.h` is present (copy it from
`IsoLog_local.h.off`; it is git-ignored). `OctLog` queues at most 32 lines:
a longer burst loses its end, and says only "N log lines dropped". Keep a
report under 32 lines.

**Don't** judge streaming with the SD log on. The log shares the card with
the game's reads, and each write holds the disc lock for 50 to 130 ms. The PERF
lines alone, every 3 s, were enough to make a streamed sky stall and lurch on
hardware, in every stage. Hours went into fixing "sky stalls" that were the log
itself. For anything card-bound (streaming, frame pacing, load times), build
without `IsoLog_local.h`. Use a log build to find failures, and don't trust its
timing.

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

**Do** look for `LUA ALLOC FAILED` and `C++ ALLOC FAILED` in the log when a
game runs out of memory. Lua's own "not enough memory" names no line, and a
failed `operator new` used to end the program without a word. The engine now
logs both (`OctLuaAlloc` and `OctNewFailed` in `Engine.cpp`):
- the size asked for;
- what the heap had free, and in how many holes;
- for Lua, the script lines that asked;
- for C++, the addresses that asked (name them with `powerpc-eabi-addr2line`).

A big request failing with megabytes free means the heap is in pieces. A
failure that repeats at a steady beat means something is retrying: in one game
it was a zone being built again every 1.7 s.

**Do**, for memory that runs out after a long session, replay a recorded
session in Dolphin rather than playing by hand. Count what each caller of
`operator new` holds, and at every level load list the callers that grew
most since the first level, not the biggest ones. The biggest are usually
fine. Name them with `powerpc-eabi-addr2line`. Before blaming the allocator,
check whether the growth is live data or waste.

**Do**, when all the 3D is wrong but the 2D HUD is fine, check the data before
the memory:
- Turn on Dolphin's `CP`, `GP`, `PI`, `PE` and `Video` logs. No "unknown
  opcode" means the command stream is intact, and the data in it is wrong.
- Check the matrices the renderer sends: a finite and range check per draw,
  logging the first bad one with its inputs. That found the broken
  `guMtxConcat` above in one run, after hours spent on GPU memory, display
  lists and the FIFO.

**Do**, when something looks overwritten, dump the memory itself before
hunting a writer, and disassemble the code that reads it. The value may be
intact and the reader wrong. To find *when* something goes wrong, use a canary:
a known computation checked at points through the frame. Log the first point
where it fails and the last point where it passed. One run narrows it to a
single call.

**Do**, for a silent freeze in Dolphin, attach Dolphin's GDB stub before
anything else (`[General] GDBPort`), and map the PC with
`powerpc-eabi-addr2line -f -e <game>.elf`. Also:
- Run Dolphin in debug mode for breakpoints and watchpoints:
  `-C Dolphin.General.GDBPort=2345 -C Dolphin.Interface.DebugModeEnabled=True`.
  Without it, the JIT silently ignored a code breakpoint that should have hit.
- Watchpoints catch only the CPU's own stores, not DMA.
- A PC in `KThreadIdleMain` is a healthy game waiting for vsync, not the
  freeze.
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
