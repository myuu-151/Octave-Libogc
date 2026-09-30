// BigBlockCache_Dolphin.cpp -- GameCube only.
//
// WHY. A GameCube has 24 MB, and a game that streams assets in and out (a stage's pipe, a sky's
// star frames, the menus) frees and allocates blocks of hundreds of kilobytes all session long.
// With newlib's malloc that cuts the heap to pieces: small allocations made in between (Lua
// tables, nodes, strings) land in the holes the big blocks leave, and a few stages later a
// 512 KB star frame has nowhere to go with 9.7 MB free -- measured in Sonic2Special3D-GC: the
// largest block fell from 6.5 MB at boot to 544 KB by the third stage, and loads failed.
//
// WHAT. Freed blocks of BIG_BLOCK bytes or more are kept here instead of going back to the heap,
// and an allocation of (about) the same size takes one back. The big allocations a game repeats
// are the same sizes every time -- every sky's star frames are one size, a drop piece is the same
// size in every stage's palette, the file buffers match the files -- so they go on reusing the
// same blocks, and the small allocations never get into them.
//
// NOTHING STARVES. Whenever any allocation fails, big or small, the cache gives its blocks back
// to the heap one at a time and the allocation is tried again after each: first the smallest
// block big enough for it alone, else the biggest (see GiveBackOne). The cache can only ever hold
// memory nothing else could get at that moment -- except PINNED sizes (System.PinBlocks), which a
// game asks to keep for good.
//
// HOW. The link wraps malloc, free, realloc, calloc and memalign (Standalone/Makefile_GCN:
// -Wl,--wrap=...): every call in the game, the engine, Lua and libstdc++ (operator new) comes
// here. newlib's own internal allocations (_malloc_r) do not, which is fine: their blocks are
// small, and freeing one through free() still arrives here.

#if PLATFORM_GAMECUBE

#include <malloc.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <sys/reent.h>

extern "C"
{
void* __real_malloc(size_t size);
void __real_free(void* ptr);
void* __real_realloc(void* ptr, size_t size);
void* __real_calloc(size_t count, size_t size);
void* __real_memalign(size_t align, size_t size);

void __malloc_lock(struct _reent* r);
void __malloc_unlock(struct _reent* r);
}


namespace
{
    const size_t BIG_BLOCK = 32 * 1024;     // blocks this size and up are kept
    const uint32_t MAX_KEPT = 96;           // at most this many at once

    struct Kept
    {
        void* mPtr;
        size_t mSize;                       // malloc_usable_size
    };

    Kept sKept[MAX_KEPT];
    uint32_t sNumKept = 0;

    // PINNED: blocks of a size a game needs again and again (a sky's frames, a stage's biggest
    // meshes) are never given back to the heap, so the next of them always finds one here -- given
    // back, the heap's small allocations cut them up: with megabytes free not one 64 KB block was
    // left for a sky frame, nor one of 156 KB for a stage's rise piece, whose last one had gone
    // back for the next stage's script and sky. Each pinned size keeps up to its own count; the
    // rest of that size go back like any other.
    struct Pin
    {
        size_t mLo;
        size_t mHi;                         // a block's usable size: the size asked for, a little over
        uint32_t mMax;                      // at most this many kept at once
    };
    const uint32_t MAX_PINS = 8;
    Pin sPins[MAX_PINS];
    uint32_t sNumPins = 0;

    // The pin a block of `size` bytes comes under, or -1.
    int32_t PinOf(size_t size)
    {
        for (uint32_t i = 0; i < sNumPins; ++i)
        {
            if (size >= sPins[i].mLo && size <= sPins[i].mHi)
            {
                return int32_t(i);
            }
        }
        return -1;
    }

    struct Lock
    {
        Lock() { __malloc_lock(_REENT); }
        ~Lock() { __malloc_unlock(_REENT); }
    };

    // A kept block for a request of `size` aligned to `align` (1 for plain malloc): the
    // smallest that fits and wastes no more than an eighth. A pinned block goes only to its own
    // size: handed to anything within an eighth of it, the corners' reserved blocks went to other
    // allocations of 70-79 KB, and the corners then looked for theirs in the heap after all.
    // nullptr if there is none.
    void* Take(size_t size, size_t align)
    {
        if (size < BIG_BLOCK)
        {
            return nullptr;
        }

        Lock lock;
        const int32_t sizePin = PinOf(size);
        int32_t best = -1;
        for (uint32_t i = 0; i < sNumKept; ++i)
        {
            const Kept& k = sKept[i];
            const int32_t pin = PinOf(k.mSize);
            if (pin >= 0 && pin != sizePin)
            {
                continue;
            }
            if (k.mSize >= size && k.mSize <= size + size / 8 &&
                ((uintptr_t)k.mPtr & (align - 1)) == 0 &&
                (best < 0 || k.mSize < sKept[best].mSize))
            {
                best = int32_t(i);
            }
        }

        if (best < 0)
        {
            return nullptr;
        }

        void* ptr = sKept[best].mPtr;
        sKept[best] = sKept[--sNumKept];
        return ptr;
    }

    // Give a kept block back to the heap, for an allocation of `forSize` bytes that failed: the
    // smallest that is big enough for it alone, or, when none is, the biggest (the likeliest to
    // join free space beside it into a piece that is). Always the biggest, as this was, a 2 KB
    // allocation took a 156 KB block, and the small ones after it cut the rest up. Pinned blocks
    // stay, up to their pin's count. False when none may go.
    bool GiveBackOne(size_t forSize)
    {
        void* ptr = nullptr;
        {
            Lock lock;
            uint32_t pinned[MAX_PINS] = {};
            for (uint32_t i = 0; i < sNumKept; ++i)
            {
                const int32_t pin = PinOf(sKept[i].mSize);
                if (pin >= 0) pinned[pin]++;
            }
            int32_t fit = -1;
            int32_t biggest = -1;
            for (uint32_t i = 0; i < sNumKept; ++i)
            {
                const size_t size = sKept[i].mSize;
                const int32_t pin = PinOf(size);
                if (pin >= 0 && pinned[pin] <= sPins[pin].mMax)
                {
                    continue;               // pinned, and within its count: it stays
                }
                if (size >= forSize && (fit < 0 || size < sKept[fit].mSize))
                {
                    fit = int32_t(i);
                }
                if (biggest < 0 || size > sKept[biggest].mSize)
                {
                    biggest = int32_t(i);
                }
            }
            const int32_t which = (fit >= 0) ? fit : biggest;
            if (which < 0)
            {
                return false;               // nothing, or only pinned blocks: they stay
            }

            ptr = sKept[which].mPtr;
            sKept[which] = sKept[--sNumKept];
        }

        __real_free(ptr);
        return true;
    }
}

// Blocks of `size` bytes, up to `count` of them, are kept for good once freed (see Pin). Each call
// pins one more size (the same size again changes its count), up to MAX_PINS; 0 unpins them all.
void BigBlockCachePin(size_t size, uint32_t count)
{
    Lock lock;
    if (size == 0)
    {
        sNumPins = 0;
        return;
    }
    for (uint32_t i = 0; i < sNumPins; ++i)
    {
        if (sPins[i].mLo == size)
        {
            sPins[i].mMax = count;
            return;
        }
    }
    if (sNumPins < MAX_PINS)
    {
        // a block's usable size: what was asked for and malloc's rounding, or memalign's
        sPins[sNumPins++] = { size, size + 256, count };
    }
}

// Pins `size` for `count` blocks, and puts that many in the cache now, from the heap as it is (at
// boot, in one piece): the first of them is then as sure to be there as the rest. Pinned only, a
// size still had to find its first block in the heap, and a stage's first rise piece, three stages
// into a session, found none. 32-byte aligned, so memalign(32, ...) can have them too.
void BigBlockCacheReserve(size_t size, uint32_t count)
{
    BigBlockCachePin(size, count);
    for (uint32_t i = 0; i < count; ++i)
    {
        {
            Lock lock;
            if (sNumKept >= MAX_KEPT)
            {
                return;
            }
        }
        void* ptr = __real_memalign(32, size);
        if (ptr == nullptr)
        {
            return;
        }
        Lock lock;
        sKept[sNumKept].mPtr = ptr;
        sKept[sNumKept].mSize = malloc_usable_size(ptr);
        sNumKept++;
    }
}

// What the cache holds: free memory as far as the game is concerned (System.GetFreeMemory).
size_t BigBlockCacheBytes()
{
    Lock lock;
    size_t total = 0;
    for (uint32_t i = 0; i < sNumKept; ++i)
    {
        total += sKept[i].mSize;
    }

    return total;
}

extern "C"
{

void* __wrap_malloc(size_t size)
{
    void* ptr = Take(size, 1);
    if (ptr != nullptr)
    {
        return ptr;
    }

    ptr = __real_malloc(size);
    while (ptr == nullptr && GiveBackOne(size))
    {
        ptr = __real_malloc(size);
    }

    return ptr;
}

void* __wrap_memalign(size_t align, size_t size)
{
    if (align > 0 && (align & (align - 1)) == 0)
    {
        void* ptr = Take(size, align);
        if (ptr != nullptr)
        {
            return ptr;
        }
    }

    void* ptr = __real_memalign(align, size);
    while (ptr == nullptr && GiveBackOne(size))
    {
        ptr = __real_memalign(align, size);
    }

    return ptr;
}

void __wrap_free(void* ptr)
{
    if (ptr == nullptr)
    {
        return;
    }

    size_t size = malloc_usable_size(ptr);
    if (size >= BIG_BLOCK)
    {
        Lock lock;
        if (sNumKept < MAX_KEPT)
        {
            sKept[sNumKept].mPtr = ptr;
            sKept[sNumKept].mSize = size;
            sNumKept++;
            return;
        }
    }

    __real_free(ptr);
}

void* __wrap_realloc(void* ptr, size_t size)
{
    void* out = __real_realloc(ptr, size);
    if (out == nullptr && ptr != nullptr && size >= BIG_BLOCK)
    {
        // grown into a kept block of its new size, if there is one (a Lua array doubling)
        void* kept = Take(size, 1);
        if (kept != nullptr)
        {
            size_t old = malloc_usable_size(ptr);
            memcpy(kept, ptr, old < size ? old : size);
            __wrap_free(ptr);
            return kept;
        }
    }
    while (out == nullptr && size > 0 && GiveBackOne(size))
    {
        out = __real_realloc(ptr, size);
    }

    return out;
}

void* __wrap_calloc(size_t count, size_t size)
{
    void* ptr = __real_calloc(count, size);
    while (ptr == nullptr && count > 0 && size > 0 && GiveBackOne(count * size))
    {
        ptr = __real_calloc(count, size);
    }

    return ptr;
}

}

#endif
