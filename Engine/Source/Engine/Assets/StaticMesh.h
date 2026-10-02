#pragma once

#include <string>

#include "Assets/Material.h"
#include "Asset.h"
#include "Vertex.h"

#include "Graphics/GraphicsTypes.h"

#define CREATE_CONVEX_COLLISION_MESH (PLATFORM_WINDOWS || PLATFORM_LINUX)

#if EDITOR
#include <assimp/scene.h>
#endif

class StaticMesh : public Asset
{
public:

    DECLARE_ASSET(StaticMesh, Asset);

    StaticMesh();
    ~StaticMesh();

    void CreateRaw(
        uint32_t numVertices,
        Vertex* vertices,
        uint32_t numIndices,
        IndexType* indices);

    StaticMeshResource* GetResource();

    // Asset Interface
    virtual void LoadStream(Stream& stream, Platform platform) override;
    virtual bool CanLoadWindowed() const override { return true; }
    virtual void SaveStream(Stream& stream, Platform platform) override;
    virtual void Create() override;
    virtual void Destroy() override;
    virtual bool Import(const std::string& path, ImportOptions* options) override;
    virtual void GatherProperties(std::vector<Property>& outProps) override;
    virtual glm::vec4 GetTypeColor() override;
    virtual const char* GetTypeName() override;
    virtual const char* GetTypeImportExt() override;

    class Material* GetMaterial();
    void SetMaterial(class Material* newMaterial);

    uint32_t GetNumIndices() const;
    uint32_t GetNumFaces() const;
    uint32_t GetNumVertices() const;
    bool HasVertexColor() const;

    Vertex* GetVertices();
    VertexColor* GetColorVertices();
    IndexType* GetIndices();

    Bounds GetBounds() const;

    btBvhTriangleMeshShape* GetTriangleCollisionShape();
    btCollisionShape* GetCollisionShape();
    void SetCollisionShape(btCollisionShape* shape);
    void SetCollisionShapes(uint32_t numCollisionShapes, btCollisionShape** collisionShapes, btTransform* transforms, bool compound);

    void SetGenerateTriangleCollisionMesh(bool generate);
    bool IsTriangleCollisionMeshEnabled() const;
    // GX: the mesh was made compact (GFX_SetCompactUnlitMeshes) and needs its full arrays no more.
    void ReleaseSourceArrays();
    // GX: the vertices were read straight into the compact form (position, colour: 16 bytes).
    bool HasCompactVertices() const { return mCompactVertices; }
    // Hands the vertex array over (the compact renderer keeps it) and forgets it.
    void* TakeVertexArray();
    // GX: the vertices were read already quantized (cooked so: SaveStream, CookQuantizedMeshes),
    // 14 bytes each, with these fraction bits. The renderer takes the array.
    bool HasQuantData() const { return mQuantData != nullptr; }
    void* TakeQuantData() { void* q = mQuantData; mQuantData = nullptr; return q; }
    uint8_t GetQuantPosFrac() const { return mQuantPosFrac; }
    uint8_t GetQuantUvFrac() const { return mQuantUvFrac; }
    // Fraction bits that keep a mesh's extent in 16 bits (false: too coarse, or a second UV set
    // of its own, so not quantized). Shared by the cook and the GX renderer.
    static bool QuantizeFracs(const Vertex* vertices, uint32_t numVertices, int& posFrac, int& uvFrac);
    glm::vec3 GetVertexPosition(uint32_t index);

    // Console only (GX), for a COMPACT mesh: take another mesh asset's vertex colours -- the same
    // mesh painted differently, same vertices in the same order -- without loading it. Staged a
    // piece at a time (up to maxVertices from vertex `at`; returns the next vertex, outTotal when
    // done, or -1), then applied all at once, so the change shows in one frame. Call it once with
    // maxVertices 0 while nothing is being drawn: that allocates the staging buffer, kept after.
    int32_t StageColorsFrom(const std::string& assetName, uint32_t at, uint32_t maxVertices, uint32_t& outTotal);
    bool ApplyStagedColors();

    // Console only (GX), for a COMPACT mesh: its colours from a table of the colours it has in
    // each of several palettes, at once and without reading anything. `indices` is 2 bytes a
    // vertex -- which combination of colours the vertex has, high byte first and plus 32 --
    // and `table` every combination's colour in each of `palettes` palettes, 4 bytes each,
    // little-endian (as a mesh file holds its colours), palette 0 first. See Sonic Pipe Dream's
    // native/make_pipe_palettes.py. False (and nothing changed) if the data does not fit the mesh.
    bool SetPaletteColors(const uint8_t* indices, uint32_t indexBytes, const uint8_t* table, uint32_t tableBytes,
                          uint32_t palettes, uint32_t palette);

    // Every vertex's position and colour, set anew (a mesh with vertex colours, the same number of
    // vertices): a shape drawn afresh each frame, such as a trail traced behind something. xyz is
    // 3 floats a vertex; rgba 1 packed colour a vertex (r | g << 8 | b << 16 | a << 24, as the
    // mesh files store them). The bounds follow. On GX the arrays the display list reads are
    // written in place; elsewhere the GPU buffers are made again (they are small).
    bool SetVertexData(const float* xyz, const uint32_t* rgba, uint32_t count);
    uint32_t GetVertexSize() const;

    static bool HandlePropChange(Datum* datum, uint32_t index, const void* newValue);

#if EDITOR
    // Bake a scale into the geometry itself, so a node can carry it at scale 1 without changing
    // size. Rewrites vertex positions and normals, rescales the collision shapes and bounds, and
    // re-uploads the mesh. Editor-only: it modifies the asset, which then needs saving.
    void ApplyScale(glm::vec3 scale);
#endif

private:

    bool ShouldGenerateTriangleCollision() const;

    void CreateTriangleCollisionShape();
    void DestroyTriangleCollisionShape();

    void ResizeVertexArray(uint32_t newSize);
    void ResizeIndexArray(uint32_t newSize);

    void ComputeBounds();

    MaterialRef mMaterial;
    uint32_t mNumVertices;
    uint32_t mNumIndices;
    uint32_t mNumUvMaps;

    void* mVertices;
    IndexType* mIndices;

    Bounds mBounds;

    btCollisionShape* mCollisionShape;
    btBvhTriangleMeshShape* mTriangleCollisionShape;
    btTriangleIndexVertexArray* mTriangleIndexVertexArray;
    btTriangleInfoMap* mTriangleInfoMap;
    bool mGenerateTriangleCollisionMesh;
    bool mHasVertexColor;
    bool mCompactVertices = false;
    void* mQuantData = nullptr;         // see HasQuantData
    uint8_t mQuantPosFrac = 0;
    uint8_t mQuantUvFrac = 0;
    bool mQuantOnDisc = false;          // read quantized: the bounds are the file's (no floats to measure)

    // StageColorsFrom: the colours read so far, whose asset, and where its vertices start
    std::vector<uint32_t> mStagedColors;
    std::string mStagedFrom;
    uint32_t mStagedDataAt = 0;

    // Graphics Resource
    StaticMeshResource mResource;

#if EDITOR
public:
    void Create(
        const aiScene* scene,
        const aiMesh& meshData,
        uint32_t numCollisionMeshes,
        const aiMesh** collisionMeshes);
protected:
    std::vector<uint32_t> mPureVertexColors;
#endif

#if CREATE_CONVEX_COLLISION_MESH
public:
    void CreateCollisionMesh(btCollisionShape* collisionShape);
    std::vector<StaticMesh*> mCollisionMeshes;
#endif // EDITOR
};