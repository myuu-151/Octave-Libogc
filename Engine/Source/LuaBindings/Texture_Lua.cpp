#include "LuaBindings/Texture_Lua.h"
#include "LuaBindings/Asset_Lua.h"

#include "LuaBindings/Vector_Lua.h"

#if LUA_ENABLED

int Texture_Lua::IsMipmapped(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    bool ret = texture->IsMipmapped();

    lua_pushboolean(L, ret);
    return 1;
}

int Texture_Lua::IsRenderTarget(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    bool ret = texture->IsRenderTarget();

    lua_pushboolean(L, ret);
    return 1;
}

int Texture_Lua::ReloadFrom(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);
    const char* name = CHECK_STRING(L, 2);

    lua_pushboolean(L, texture->ReloadFrom(name));
    return 1;
}

// texture:ReloadPart(name, at, maxBytes) -> next, total: see Texture::ReloadPart. next is -1 when
// it cannot (not a GameCube, or a different size or format).
int Texture_Lua::ReloadPart(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);
    const char* name = CHECK_STRING(L, 2);
    uint32_t at = (uint32_t)CHECK_INTEGER(L, 3);
    uint32_t maxBytes = (uint32_t)CHECK_INTEGER(L, 4);

    uint32_t total = 0;
    int32_t next = texture->ReloadPart(name, at, maxBytes, total);
    lua_pushinteger(L, next);
    lua_pushinteger(L, total);
    return 2;
}

// texture:ReloadFromAsync(name) -> bool, and texture:IsReloading() -> bool: see Texture::ReloadFromAsync.
int Texture_Lua::ReloadFromAsync(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);
    const char* name = CHECK_STRING(L, 2);

    lua_pushboolean(L, texture->ReloadFromAsync(name));
    return 1;
}

// texture:StashFrom(name) -> bool, texture:IsStashed(name) -> bool, texture:ReloadFromStash() -> bool:
// see Texture::StashFrom (GameCube only; false elsewhere).
int Texture_Lua::StashFrom(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);
    const char* name = CHECK_STRING(L, 2);

    lua_pushboolean(L, texture->StashFrom(name));
    return 1;
}

int Texture_Lua::IsStashed(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);
    const char* name = CHECK_STRING(L, 2);

    lua_pushboolean(L, texture->IsStashed(name));
    return 1;
}

int Texture_Lua::IsStashing(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    lua_pushboolean(L, texture->IsStashing());
    return 1;
}

int Texture_Lua::FreeStash(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    texture->FreeStash();
    return 0;
}

int Texture_Lua::ReloadFromStash(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    lua_pushboolean(L, texture->ReloadFromStash());
    return 1;
}

int Texture_Lua::IsReloading(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    lua_pushboolean(L, texture->IsReloading());
    return 1;
}

int Texture_Lua::GetWidth(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    uint32_t ret = texture->GetWidth();

    lua_pushinteger(L, (int)ret);
    return 1;
}

int Texture_Lua::GetHeight(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    uint32_t ret = texture->GetHeight();

    lua_pushinteger(L, (int)ret);
    return 1;
}

int Texture_Lua::GetMipLevels(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    uint32_t ret = texture->GetMipLevels();

    lua_pushinteger(L, (int)ret);
    return 1;
}

int Texture_Lua::GetLayers(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    uint32_t ret = texture->GetLayers();

    lua_pushinteger(L, (int)ret);
    return 1;
}

int Texture_Lua::GetFormat(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    PixelFormat ret = texture->GetFormat();

    lua_pushinteger(L, (int)ret);
    return 1;
}

int Texture_Lua::GetFilterType(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    FilterType ret = texture->GetFilterType();

    lua_pushinteger(L, (int)ret);
    return 1;
}

int Texture_Lua::GetWrapMode(lua_State* L)
{
    Texture* texture = CHECK_TEXTURE(L, 1);

    WrapMode ret = texture->GetWrapMode();

    lua_pushinteger(L, (int)ret);
    return 1;
}

void Texture_Lua::Bind()
{
    lua_State* L = GetLua();
    int mtIndex = CreateClassMetatable(
        TEXTURE_LUA_NAME,
        TEXTURE_LUA_FLAG,
        ASSET_LUA_NAME);

    Asset_Lua::BindCommon(L, mtIndex);

    REGISTER_TABLE_FUNC(L, mtIndex, IsMipmapped);

    REGISTER_TABLE_FUNC(L, mtIndex, IsRenderTarget);

    REGISTER_TABLE_FUNC(L, mtIndex, ReloadFrom);

    REGISTER_TABLE_FUNC(L, mtIndex, ReloadPart);

    REGISTER_TABLE_FUNC(L, mtIndex, ReloadFromAsync);

    REGISTER_TABLE_FUNC(L, mtIndex, IsReloading);
    REGISTER_TABLE_FUNC(L, mtIndex, StashFrom);
    REGISTER_TABLE_FUNC(L, mtIndex, IsStashed);
    REGISTER_TABLE_FUNC(L, mtIndex, IsStashing);
    REGISTER_TABLE_FUNC(L, mtIndex, ReloadFromStash);
    REGISTER_TABLE_FUNC(L, mtIndex, FreeStash);

    REGISTER_TABLE_FUNC(L, mtIndex, GetWidth);

    REGISTER_TABLE_FUNC(L, mtIndex, GetHeight);

    REGISTER_TABLE_FUNC(L, mtIndex, GetMipLevels);

    REGISTER_TABLE_FUNC(L, mtIndex, GetLayers);

    REGISTER_TABLE_FUNC(L, mtIndex, GetFormat);

    REGISTER_TABLE_FUNC(L, mtIndex, GetFilterType);

    REGISTER_TABLE_FUNC(L, mtIndex, GetWrapMode);

    lua_pop(L, 1);
    OCT_ASSERT(lua_gettop(L) == 0);
}

#endif
