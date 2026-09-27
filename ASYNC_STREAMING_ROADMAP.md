# Async Disc Streaming Roadmap (GameCube / libogc)

Roadmap B from the audio doc, generalized. Where the audio fix (Roadmap A) kept
one compressed track in RAM and decoded it on demand, this is the **general**
version: read *any* asset off the disc **asynchronously**, so the game can load
data — a texture, a mesh, a whole next area — **while it keeps running**, with no
load-screen stall.

This builds directly on the GCN ISO work already shipped (the FST reader in
`System_Dolphin.cpp` + the GCM builder in `ActionManager.cpp`). Those are base
camp: they already read assets off the disc FST — just synchronously, one
blocking read at a time. This turns that into a non-blocking, background system.

## What this is (and isn't)

- **One general layer, all asset types.** The read layer moves *bytes* off the
  disc; it doesn't care what they are. A single async-load API serves textures,
  meshes, scenes, audio — everything. That generality is the whole value.
- **The payoff is seamless loading:** load the next scene/area's assets in the
  background while the player is still in the current one, then swap when ready —
  no load screen, no freeze.
- **It is NOT** per-asset paging of data too big for RAM (streaming a single
  10 GB texture). That's a further, niche specialization. The general win is
  "load whole assets in the background without stalling."

## Target hardware note (GC Loader / ODE)

Because the target is a **GC Loader / flash ODE**, not a spinning optical disc,
two of the classically-hard GameCube streaming problems mostly evaporate:

- **Seek-aware disc layout — SKIP.** Ordering files on disc by access order
  exists to stop a physical read head thrashing (~100 ms/seek). Flash has ~no
  seek penalty, so the FST's default order is fine. (Would matter on real disc
  hardware; does not for an ODE.)
- **ARAM staging — OPTIONAL.** ARAM (the 16 MB aux RAM) is a staging buffer for
  when MEM1 is too full to hold in-flight reads. Unless memory-starved, DMA
  straight into MEM1. Add ARAM only if you actually run out of MEM1.

So for this setup, Roadmap B collapses to: **async DVD read thread + a
non-blocking asset pipeline.**

## What to build

### 1. Async DVD read (background I/O thread)
A dedicated LWP thread that pulls read requests off a queue and performs
FST-resolved `DVD_ReadPrio` (or `DVD_ReadAbsAsyncPrio`) **off the main thread**,
so the render frame never blocks on a disc read. On completion it signals the
requester (callback / future / flag). `DCInvalidateRange` each DMA'd buffer for
cache coherency before the CPU touches it.

Reference: Polyphase already has this exact scaffold (`StreamingIOThread` + a
FIFO in `AudioManager.cpp`) — written but parked, and pointed at SD `fopen`.
The move is to point that pattern at the FST reader (`DVD_ReadPrio`) instead.

### 2. Non-blocking asset-load API  *(the real work / the risk)*
`AssetManager::LoadAssetAsync(name) -> handle`, with a completion callback or a
pollable "ready" state. **This is the hard part**, because the entire engine
currently assumes `LoadAsset` returns *immediately* — scene loading, asset refs,
everything is synchronous. Introducing a "still loading" state and threading it
through the asset system (refs that resolve later, scenes that spawn once their
assets are ready) touches a lot of code. This, not the disc reads, is the
mountain.

### 3. First client: background area loading
"Load the next scene's assets while the player is in the current one, swap when
ready." This is the seamless-transition payoff and is fully general (works for
whatever assets a scene references). Build this on top of (1) + (2).

### Later clients (optional specializations)
- Audio: stream compressed audio off the disc async (vs Roadmap A's in-RAM
  decode) — only needed if compressed audio won't fit in RAM, which for music
  basically never happens.
- Texture mip streaming, giant-geometry paging — niche; only if a single asset
  exceeds RAM.

## The honest risks

- **Async-ifying the synchronous asset pipeline** (item 2) is broad and
  invasive. It's the bulk of the effort and the main source of subtle bugs.
- **Threading / interrupt / cache correctness** — background reads + cache
  invalidation + no data races with the main thread.
- **Only truly validated on hardware.** Dolphin will not reflect real GC Loader
  read timing or CPU cost. This needs the ODE to prove out.

## Staged plan

1. Async DVD read thread over the existing FST reader (item 1) — self-contained,
   testable in isolation (kick a background read, confirm data + no main-thread
   stall).
2. `LoadAssetAsync` in AssetManager with completion signalling (item 2) — the big
   lift; do it behind the existing synchronous API so nothing else breaks yet.
3. Background area/scene loading as the first real client (item 3).
4. Validate on the GC Loader (timing, no hitches, memory).

## Recommendation

Worth it **only if seamless, no-load-screen worlds are an actual goal.** If
level-based games with a fade between areas are fine, the shipped synchronous
FST loading is the finish line and this is effort with no payoff. If seamless is
the goal, this is the correct architecture — and the base (FST reader +
packaging) is already in place. Do items 1→2→3 in order, validate each on
hardware before the next.
