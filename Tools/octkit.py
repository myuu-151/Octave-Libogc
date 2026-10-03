"""octkit: Octave assets written from code -- no editor.

A project's Raw/ folder holds the source files (PNG, JPG, BMP, TGA, WAV, OGG, MP3, FLAC, and models: GLB, glTF, OBJ,
and Blender's .blend through Blender itself; videos and fonts go through Octave's own importer, run headless); octkit
turns each into
the .oct asset the editor would have made of it, in Assets/ (the same sub-folders), and Octave's packager then
cooks them for the console as it does any asset (a texture's GameCube format is chosen there, from its alpha).
Sonic Pipe Dream's way (its native/*.py wrote its stages, sounds and sky this way), made general.

    python Tools/octkit.py convert <project folder>     the new and changed files; events as JSON lines
    python Tools/octkit.py status  <project folder>     every file, its asset and whether it's up to date: JSON

    import octkit                                        from a project's own build.py:
    octkit.write_texture(path, name, w, h, rgba, ...)    a texture from RGBA8 pixels
    octkit.write_sound(path, name, pcm, rate, ...)       a sound from 16-bit PCM
    octkit.write_music(path, name, source, ...)          a streamed music track (Vorbis) from any audio file
    octkit.write_material(path, name, ...)               a material (MaterialLite): a colour, a texture, lit or not
    octkit.write_mesh(path, name, vertices, indices, ...) a static mesh from (x y z u v nx ny nz) vertices
    octkit.read_model(path)                              a GLB / glTF / OBJ / .blend's meshes, materials, images

Each file's settings live in Raw/assets.json, keyed by its path in Raw/ (DolphinWorks edits them):
    textures  name, filter (linear | nearest), wrap (repeat | clamp | mirror), mipmaps, force_hq, downsample
    sounds    name, mode (effect | music), rate, volume, pitch, max_instances, quality (music: Vorbis -q)
    videos    name, preset (custom | ntsc | pal), width, height (0: keep the aspect), fps, quality (JPEG, 2 best - 31
              smallest), audio_channels (1 | 2), sample_rate (Hz), native_resolution, native_fps, native_audio
              (Octave cooks them)
    models    name, scale, lit, cull (back | none), filter (its textures)
A model becomes a mesh for each of its materials (SM_<Name>, or SM_<Name>_<Material>; split at the consoles'
65535 vertices), a material each (M_...), and a texture for each picture in it (T_...): its scene baked flat.
and its uuid, made once and kept, so what refers to the asset keeps finding it. Missing settings are the
defaults: what Octave's editor gives a new asset, and for sounds, mono 22 kHz effects and stereo 32 kHz music
streamed from the disc (as Sonic Pipe Dream's).

Only Python's standard library; images and audio are read with Octave's own ffmpeg (External/ffmpeg/bin).
"""
import hashlib
import json
import os
import random
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]                      # Octave-libogc
FFMPEG = ROOT / 'External' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
FFPROBE = ROOT / 'External' / 'ffmpeg' / 'bin' / 'ffprobe.exe'
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

# Engine/Source/Engine/Asset.h, and the types' ids (TypeIds of their class names)
ASSET_MAGIC, ASSET_VERSION = 0x4F435421, 15
TYPE_TEXTURE, TYPE_SOUNDWAVE = 3451640368, 2590661312
TYPE_STATICMESH, TYPE_MATERIALLITE = 3558673693, 2750237807
MAX_VERTICES = 65535                                            # a mesh's on the consoles (16-bit indices)
FILTERS = {'nearest': 0, 'linear': 1}
WRAPS = {'clamp': 0, 'repeat': 1, 'mirror': 2}
PIXEL_RGBA8 = 2

IMAGES = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.webp'}
AUDIO = {'.wav', '.ogg', '.mp3', '.flac', '.aif', '.aiff'}
MODELS = {'.glb', '.gltf', '.obj', '.blend'}
VIDEOS = {'.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v'}
FONTS = {'.ttf'}
OCTAVE_EXE = ROOT / "Octave.exe"
SETTINGS = 'assets.json'


# --- writing ------------------------------------------------------------------------------------

def _header(type_id, uuid, name):
    raw = name.encode('ascii')
    return struct.pack('<IIIBQ', ASSET_MAGIC, ASSET_VERSION, type_id, 0, uuid) + struct.pack('<I', len(raw)) + raw


def new_uuid():
    return random.getrandbits(63) | 1


def write_texture(path, name, width, height, rgba, uuid=None, filter='linear', wrap='repeat', mipmaps=True,
                  srgb=True, force_hq=False, downsample=1):
    """A texture asset from RGBA8 pixels (width * height * 4 bytes, rows top down), as the editor saves one
    (Texture::SaveStream): the packager cooks it for the console."""
    if len(rgba) != width * height * 4:
        raise ValueError(f'{name}: {len(rgba)} bytes of pixels for {width} x {height}')
    levels = (int(max(width, height)).bit_length()) if mipmaps else 1      # floor(log2(max)) + 1
    d = _header(TYPE_TEXTURE, uuid or new_uuid(), name)
    d += struct.pack('<IIIIIII', width, height, levels, 1, PIXEL_RGBA8, FILTERS[filter], WRAPS[wrap])
    d += struct.pack('<???', bool(mipmaps), False, bool(srgb))
    d += struct.pack('<?B', bool(force_hq), max(1, min(int(downsample), 8)))
    d += bytes(rgba)
    _write(path, d)


def _sound_properties(volume, pitch, compress, stream, max_instances):
    return (struct.pack('<ffb', float(volume), float(pitch), 0)
            + struct.pack('<???B', compress, compress, stream, max(0, min(int(max_instances), 255))))


def write_sound(path, name, pcm, rate, channels=1, uuid=None, volume=1.0, pitch=1.0, max_instances=0):
    """A sound effect asset from 16-bit PCM (interleaved if stereo), kept as PCM: it starts the moment it's
    asked for. As SoundWave::SaveStream writes one."""
    frames = len(pcm) // (2 * channels)
    d = _header(TYPE_SOUNDWAVE, uuid or new_uuid(), name)
    d += _sound_properties(volume, pitch, False, False, max_instances)
    d += struct.pack('<IIIIII', channels, 16, rate, frames * channels, 2 * channels, rate * channels * 2)
    d += struct.pack('<?I', False, len(pcm)) + bytes(pcm)
    _write(path, d)


def write_music(path, name, source, uuid=None, rate=32000, channels=2, quality=4, volume=1.0):
    """A music asset from any audio file: Vorbis, made here at a proper quality (the engine's own cook
    encodes at a much lower one), stored compressed and STREAMED from the disc as it plays, so a track costs
    next to no memory. Sonic Pipe Dream's music, made this way."""
    ogg = _ffmpeg(['-i', str(source), '-vn', '-ac', str(channels), '-ar', str(rate), '-c:a', 'libvorbis',
                   '-q:a', str(quality), '-f', 'ogg', '-'])
    frames = int(round(_duration(source) * rate))
    d = _header(TYPE_SOUNDWAVE, uuid or new_uuid(), name)
    d += _sound_properties(volume, 1.0, True, True, 1)
    d += struct.pack('<IIIIII', channels, 16, rate, frames, 2 * channels, rate * channels * 2)
    d += struct.pack('<?I', True, len(ogg)) + ogg
    _write(path, d)


def _ref(uuid, name):
    raw = (name or '').encode('ascii')
    return struct.pack('<BQI', 1, uuid or 0, len(raw)) + raw          # (a null reference: uuid 0, no name)


def write_material(path, name, uuid=None, texture=None, color=(1.0, 1.0, 1.0, 1.0), lit=True, blend='opaque',
                   cull='back', vertex_color=False, specular=0.0, shininess=32.0, emission=0.0):
    """A MaterialLite asset: a colour, and a texture ((uuid, name) of a texture asset) or none. As the editor
    saves one (MaterialLite::SaveStream); the defaults are a new material's."""
    blends = {'opaque': 0, 'masked': 1, 'translucent': 2, 'additive': 3}
    culls = {'none': 0, 'back': 1, 'front': 2}
    d = _header(TYPE_MATERIALLITE, uuid or new_uuid(), name)
    d += struct.pack('<I', 0)                                            # no shader parameters
    d += struct.pack('<III', 1 if lit else 0, blends[blend], 1 if vertex_color else 0)
    d += struct.pack('<I', 1)                                            # textures in use
    slots = [texture] + [None] * 3
    for i, slot in enumerate(slots):
        d += _ref(*(slot or (0, ''))) + struct.pack('<BB', 0, 0 if i == 0 else 1)   # uv map 0; Replace, then Modulate
    d += struct.pack('<4f', 0, 0, 1, 1) * 2                              # uv offset and scale, two maps
    d += struct.pack('<4f', *color) + struct.pack('<4f', 1, 0, 0, 0)       # colour; fresnel colour
    d += struct.pack('<4f', 1.0, emission, 0.0, specular)               # fresnel power, emission, wrap lighting, specular
    d += struct.pack('<I3fi', 2, 1.0, 0.5, shininess, 0)                # toon steps, opacity, mask cutoff, shininess, sort
    d += struct.pack('<???B', False, False, True, culls[cull])          # depth test on, no fresnel, fog, culling
    _write(path, d)


def write_mesh(path, name, vertices, indices, material=None, uuid=None):
    """A StaticMesh asset: vertices as (x, y, z, u, v, nx, ny, nz) -- Octave's axes (Y up), UVs from the top --
    and triangle indices; its material ((uuid, name)) or none. As StaticMesh::SaveStream writes one (floats: the
    packager quantizes it for the consoles if the project asks)."""
    if len(vertices) > MAX_VERTICES:
        raise ValueError(f'{name}: {len(vertices)} vertices: the consoles take {MAX_VERTICES} a mesh (split it)')
    d = _header(TYPE_STATICMESH, uuid or new_uuid(), name)
    d += struct.pack('<III', len(vertices), len(indices), 1)
    d += _ref(*(material or (0, '')))
    d += struct.pack('<??', False, False)                               # no triangle collision, no vertex colours
    vb = bytearray()
    for x, y, z, u, v, nx, ny, nz in vertices:
        vb += struct.pack('<10f', x, y, z, u, v, 0.0, 0.0, nx, ny, nz)
    d += bytes(vb) + struct.pack(f'<{len(indices)}I', *indices)
    d += struct.pack('<?I', False, 0)                                   # no collision shapes
    lo = [min(v[i] for v in vertices) for i in range(3)] if vertices else [0, 0, 0]
    hi = [max(v[i] for v in vertices) for i in range(3)] if vertices else [0, 0, 0]
    centre = [(a + b) / 2 for a, b in zip(lo, hi)]
    radius = max((sum((v[i] - centre[i]) ** 2 for i in range(3)) ** 0.5 for v in vertices), default=0.0)
    d += struct.pack('<4f', *centre, radius)
    _write(path, d)


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + '.part')
    part.write_bytes(data)
    part.replace(path)


# --- reading sources (Octave's ffmpeg) ------------------------------------------------------------

def _ffmpeg(args):
    if not FFMPEG.exists():
        raise RuntimeError(f'No ffmpeg in {FFMPEG.parent}: the Engine page builds it (ffmpeg).')
    out = subprocess.run([str(FFMPEG), '-v', 'error', '-nostdin', *args], capture_output=True, creationflags=NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode('utf-8', 'replace').strip() or 'ffmpeg failed')
    return out.stdout


def _probe(path, entries):
    out = subprocess.run([str(FFPROBE), '-v', 'error', '-show_entries', entries, '-of', 'json', str(path)],
                         capture_output=True, creationflags=NO_WINDOW)
    return json.loads(out.stdout or b'{}')


def _duration(path):
    info = _probe(path, 'format=duration')
    return float(info.get('format', {}).get('duration') or 0)


def read_image(path):
    """(width, height, RGBA8 bytes) of any image ffmpeg reads."""
    streams = _probe(path, 'stream=width,height').get('streams') or [{}]
    w, h = int(streams[0].get('width', 0)), int(streams[0].get('height', 0))
    if not w or not h:
        raise RuntimeError(f'{Path(path).name}: not an image ffmpeg can read')
    rgba = _ffmpeg(['-i', str(path), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'])
    return w, h, rgba


def read_pcm(path, rate, channels):
    """16-bit little-endian PCM of any audio file, at this rate and channel count."""
    return _ffmpeg(['-i', str(path), '-vn', '-ac', str(channels), '-ar', str(rate), '-f', 's16le', '-'])


# --- models: GLB / glTF / OBJ, and .blend through Blender -------------------------------------------

def _mat_mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _trs(node):
    if 'matrix' in node:
        m = node['matrix']                                           # column major
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    tx, ty, tz = node.get('translation', [0, 0, 0])
    qx, qy, qz, qw = node.get('rotation', [0, 0, 0, 1])
    sx, sy, sz = node.get('scale', [1, 1, 1])
    r = [[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
         [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
         [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]]
    return [[r[0][0] * sx, r[0][1] * sy, r[0][2] * sz, tx], [r[1][0] * sx, r[1][1] * sy, r[1][2] * sz, ty],
            [r[2][0] * sx, r[2][1] * sy, r[2][2] * sz, tz], [0, 0, 0, 1]]


def _normal_matrix(m):
    """The inverse transpose of a matrix's 3 x 3: how its normals turn."""
    a = [row[:3] for row in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < 1e-12:
        return a
    inv = [[(a[(c + 1) % 3][(r + 1) % 3] * a[(c + 2) % 3][(r + 2) % 3] - a[(c + 1) % 3][(r + 2) % 3] * a[(c + 2) % 3][(r + 1) % 3]) / det
            for c in range(3)] for r in range(3)]
    return [[inv[c][r] for c in range(3)] for r in range(3)]


def _norm(x, y, z):
    n = (x * x + y * y + z * z) ** 0.5 or 1.0
    return x / n, y / n, z / n


def _smooth_normals(positions, indices):
    acc = [[0.0, 0.0, 0.0] for _ in positions]
    for t in range(0, len(indices) - 2, 3):
        a, b, c = indices[t:t + 3]
        pa, pb, pc = positions[a], positions[b], positions[c]
        e1 = [pb[i] - pa[i] for i in range(3)]
        e2 = [pc[i] - pa[i] for i in range(3)]
        n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
        for k in (a, b, c):
            for i in range(3):
                acc[k][i] += n[i]
    return [_norm(*n) for n in acc]


class Model:
    """A model's triangles, by material, baked to one space: groups[material index] = (vertices, indices) with
    vertices (x y z u v nx ny nz); materials [{name, color, image}]; images [(name, bytes)]."""

    def __init__(self):
        self.groups, self.materials, self.images = {}, [], []

    def add(self, material, positions, normals, uvs, indices, matrix=None):
        nm = _normal_matrix(matrix) if matrix else None
        verts, base = self.groups.setdefault(material, ([], []))[0], None
        group = self.groups[material]
        base = len(group[0])
        for i, (x, y, z) in enumerate(positions):
            if matrix:
                x, y, z = (matrix[r][0] * x + matrix[r][1] * y + matrix[r][2] * z + matrix[r][3] for r in range(3))
            nx, ny, nz = normals[i]
            if nm:
                nx, ny, nz = _norm(*(nm[r][0] * nx + nm[r][1] * ny + nm[r][2] * nz for r in range(3)))
            u, v = uvs[i] if uvs else (0.0, 0.0)
            group[0].append((x, y, z, u, v, nx, ny, nz))
        group[1].extend(base + k for k in indices)


def _gltf_accessor(doc, buffers, index):
    acc = doc['accessors'][index]
    view = doc['bufferViews'][acc['bufferView']]
    data = buffers[view['buffer']]
    comps = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[acc['type']]
    fmt, size = {5126: ('f', 4), 5125: ('I', 4), 5123: ('H', 2), 5121: ('B', 1), 5122: ('h', 2), 5120: ('b', 1)}[acc['componentType']]
    stride = view.get('byteStride') or comps * size
    start = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
    out = []
    unpack = struct.Struct('<' + fmt * comps).unpack_from
    for i in range(acc['count']):
        values = unpack(data, start + i * stride)
        if acc.get('normalized') and fmt != 'f':
            top = {'B': 255, 'H': 65535, 'b': 127, 'h': 32767}[fmt]
            values = tuple(max(v / top, -1.0) for v in values)
        out.append(values if comps > 1 else values[0])
    return out


def read_gltf(path):
    path = Path(path)
    raw = path.read_bytes()
    if raw[:4] == b'glTF':                                           # GLB: a JSON chunk, then a binary one
        doc, buffers, at = None, [], 12
        while at < len(raw):
            length, kind = struct.unpack_from('<II', raw, at)
            chunk = raw[at + 8:at + 8 + length]
            if kind == 0x4E4F534A:
                doc = json.loads(chunk)
            elif kind == 0x004E4942:
                buffers.append(chunk)
            at += 8 + length
    else:
        doc, buffers = json.loads(raw), []
    for i, b in enumerate(doc.get('buffers', [])):
        uri = b.get('uri')
        if uri is None:
            continue                                                 # (the GLB's own chunk)
        if uri.startswith('data:'):
            import base64
            data = base64.b64decode(uri.split(',', 1)[1])
        else:
            data = (path.parent / urllib_unquote(uri)).read_bytes()
        if i < len(buffers):
            buffers[i] = data
        else:
            buffers.append(data)
    model = Model()
    for i, img in enumerate(doc.get('images', [])):
        if 'bufferView' in img:
            view = doc['bufferViews'][img['bufferView']]
            data = buffers[view['buffer']][view.get('byteOffset', 0):view.get('byteOffset', 0) + view['byteLength']]
        else:
            data = (path.parent / urllib_unquote(img['uri'])).read_bytes()
        model.images.append((img.get('name') or f'Image{i}', data))
    for i, mat in enumerate(doc.get('materials', [])):
        pbr = mat.get('pbrMetallicRoughness', {})
        tex = pbr.get('baseColorTexture')
        image = doc['textures'][tex['index']].get('source') if tex is not None else None
        model.materials.append({'name': mat.get('name') or f'Material{i}', 'color': tuple(pbr.get('baseColorFactor', [1, 1, 1, 1])),
                                'image': image, 'blend': {'BLEND': 'translucent', 'MASK': 'masked'}.get(mat.get('alphaMode'), 'opaque'),
                                'two_sided': bool(mat.get('doubleSided'))})

    def visit(index, parent):
        node = doc['nodes'][index]
        m = _mat_mul(parent, _trs(node))
        if 'mesh' in node:
            for prim in doc['meshes'][node['mesh']]['primitives']:
                if prim.get('mode', 4) != 4:
                    continue                                         # (triangles only)
                at = prim['attributes']
                pos = _gltf_accessor(doc, buffers, at['POSITION'])
                idx = _gltf_accessor(doc, buffers, prim['indices']) if 'indices' in prim else list(range(len(pos)))
                nrm = _gltf_accessor(doc, buffers, at['NORMAL']) if 'NORMAL' in at else _smooth_normals(pos, idx)
                uvs = _gltf_accessor(doc, buffers, at['TEXCOORD_0']) if 'TEXCOORD_0' in at else None
                model.add(prim.get('material', -1), pos, nrm, uvs, idx, m)
        for child in node.get('children', []):
            visit(child, m)
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    scene = doc.get('scenes', [{}])[doc.get('scene', 0)] if doc.get('scenes') else {'nodes': list(range(len(doc.get('nodes', []))))}
    for root in scene.get('nodes', []):
        visit(root, identity)
    return model


def urllib_unquote(s):
    from urllib.parse import unquote
    return unquote(s)


def read_obj(path):
    """An OBJ (and its .mtl: colours, map_Kd textures). UVs flipped to start at the top, as Octave's."""
    path = Path(path)
    model = Model()
    mats, current = {}, None
    pos, uvs, nrm = [], [], []
    faces = {}                                                        # material name -> [(p, t, n) * 3]
    for line in path.read_text(errors='replace').splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == 'v':
            pos.append(tuple(float(x) for x in parts[1:4]))
        elif tag == 'vt':
            uvs.append((float(parts[1]), 1.0 - float(parts[2]) if len(parts) > 2 else 0.0))
        elif tag == 'vn':
            nrm.append(tuple(float(x) for x in parts[1:4]))
        elif tag == 'usemtl':
            current = parts[1] if len(parts) > 1 else None
        elif tag == 'mtllib':
            mtl = path.parent / ' '.join(parts[1:])
            name = None
            if mtl.exists():
                for m in mtl.read_text(errors='replace').splitlines():
                    mp = m.split()
                    if not mp:
                        continue
                    if mp[0] == 'newmtl':
                        name = mp[1] if len(mp) > 1 else 'Material'
                        mats[name] = {'name': name, 'color': (1.0, 1.0, 1.0, 1.0), 'image': None, 'blend': 'opaque', 'two_sided': False}
                    elif name and mp[0] == 'Kd':
                        mats[name]['color'] = (float(mp[1]), float(mp[2]), float(mp[3]), 1.0)
                    elif name and mp[0] == 'd' and float(mp[1]) < 1.0:
                        mats[name]['color'] = mats[name]['color'][:3] + (float(mp[1]),)
                        mats[name]['blend'] = 'translucent'
                    elif name and mp[0] == 'map_Kd':
                        img = path.parent / ' '.join(mp[1:])
                        if img.exists():
                            model.images.append((img.stem, img.read_bytes()))
                            mats[name]['image'] = len(model.images) - 1
        elif tag == 'f':
            corners = []
            for c in parts[1:]:
                ids = (c.split('/') + ['', ''])[:3]
                fix = lambda s, n: (int(s) - 1 if int(s) > 0 else n + int(s)) if s else None
                corners.append((fix(ids[0], len(pos)), fix(ids[1], len(uvs)), fix(ids[2], len(nrm))))
            for k in range(1, len(corners) - 1):                     # (a polygon: a fan of triangles)
                faces.setdefault(current, []).append((corners[0], corners[k], corners[k + 1]))
    names = list(mats)
    for matname, tris in faces.items():
        index = names.index(matname) if matname in names else -1
        positions, normals, texcoords, indices, seen = [], [], [], [], {}
        smooth_needed = any(c[2] is None for t in tris for c in t)
        for tri in tris:
            for c in tri:
                if c not in seen:
                    seen[c] = len(positions)
                    positions.append(pos[c[0]])
                    texcoords.append(uvs[c[1]] if c[1] is not None else (0.0, 0.0))
                    normals.append(nrm[c[2]] if c[2] is not None else (0.0, 1.0, 0.0))
                indices.append(seen[c])
        if smooth_needed:
            normals = _smooth_normals(positions, indices)
        model.add(index, positions, normals, texcoords, indices)
    model.materials = [mats[n] for n in names]
    return model


def find_blender():
    for root in (Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Blender Foundation',
                 Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Blender Foundation'):
        found = sorted(root.glob('*/blender.exe')) if root.is_dir() else []
        if found:
            return found[-1]                                         # (the newest)
    return None


def read_blend(path, work):
    """A .blend, exported by Blender itself (headless) to GLB, then read as one."""
    blender = find_blender()
    if not blender:
        raise RuntimeError('No Blender found (blender.org): it reads .blend files. Or export a .glb from Blender.')
    out = Path(work) / (Path(path).stem + '.glb')
    out.parent.mkdir(parents=True, exist_ok=True)
    script = ('import bpy, sys; bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format="GLB", '
              'export_apply=True, export_yup=True)')
    run = subprocess.run([str(blender), '-b', str(path), '--python-expr', script, '--', str(out)],
                         capture_output=True, creationflags=NO_WINDOW, timeout=600)
    if not out.exists():
        raise RuntimeError('Blender did not export it: ' + run.stdout.decode('utf-8', 'replace')[-400:])
    return read_gltf(out)


def read_model(path, work=None):
    ext = Path(path).suffix.lower()
    if ext in ('.glb', '.gltf'):
        return read_gltf(path)
    if ext == '.obj':
        return read_obj(path)
    if ext == '.blend':
        return read_blend(path, work or Path(path).parent)
    raise ValueError(f'Not a model: {path}')


VIDEO_OPTIONS = {'preset': 'videoPreset', 'width': 'videoWidth', 'height': 'videoHeight', 'fps': 'videoFps',
                 'quality': 'videoQuality', 'audio_channels': 'videoAudioChannels', 'sample_rate': 'videoSampleRate',
                 'native_resolution': 'videoNativeResolution',
                 'native_fps': 'videoNativeFrameRate', 'native_audio': 'videoNativeSampleRate'}
PRESETS = {'custom': 0, 'ntsc': 1, 'pal': 2}


def octave_import(project_folder, source, name, folder, options=None):
    """A file imported by Octave's own importer (the editor's Import Asset), headless: Octave.exe -headless -project
    <project> -import <file> <folder>. What only Octave makes: a cooked video (JPEG frames and audio, its own
    format), a font. The asset is named after the file, so the source goes in under the asset's name."""
    octp = next(Path(project_folder).glob('*.octp'), None)
    if not octp:
        raise RuntimeError('no .octp in the project folder')
    if not OCTAVE_EXE.exists():
        raise RuntimeError(f'No Octave.exe in {ROOT}: the Engine page builds it (the editor).')
    work = Path(project_folder) / 'Intermediate' / 'octkit'
    work.mkdir(parents=True, exist_ok=True)
    copy = work / (name + Path(source).suffix.lower())
    copy.write_bytes(Path(source).read_bytes())
    (Path(project_folder) / 'Assets' / folder).mkdir(parents=True, exist_ok=True)
    sets = []
    for key, value in (options or {}).items():
        sets += ['-importset', f'{key}={int(value)}']
    run = subprocess.run([str(OCTAVE_EXE), '-headless', '-project', octp.as_posix(), *sets, '-import', str(copy), folder],
                         cwd=str(ROOT), capture_output=True, creationflags=NO_WINDOW, timeout=3600)
    out = run.stdout.decode('utf-8', 'replace') + run.stderr.decode('utf-8', 'replace')
    if 'Headless import:' not in out:
        lines = [l for l in out.splitlines() if re.search(r'error|fail', l, re.I) and 'socket' not in l]
        raise RuntimeError('Octave did not import it: ' + ('; '.join(lines[-3:]) or out[-300:].strip()))
    what = next((l.split(': ', 1)[1] for l in out.splitlines() if 'cooked' in l), 'imported by Octave')
    what = re.sub(r',?\s*[\d.]+ MB\.?\s*$', '', what)                   # (the size is said after)
    return Path(project_folder) / 'Assets' / folder / (name + '.oct'), what


def _split(vertices, indices):
    """(vertices, indices) pieces of at most MAX_VERTICES vertices each, by whole triangles."""
    if len(vertices) <= MAX_VERTICES:
        return [(vertices, indices)]
    pieces, verts, idx, remap = [], [], [], {}
    for t in range(0, len(indices), 3):
        tri = indices[t:t + 3]
        if len(verts) + sum(1 for k in tri if k not in remap) > MAX_VERTICES:
            pieces.append((verts, idx))
            verts, idx, remap = [], [], {}
        for k in tri:
            if k not in remap:
                remap[k] = len(verts)
                verts.append(vertices[k])
            idx.append(remap[k])
    pieces.append((verts, idx))
    return pieces


def _clean(name):
    return re.sub(r'[^A-Za-z0-9]+', ' ', str(name)).title().replace(' ', '') or 'Part'


def convert_model(source, folder, base, settings, uuids, work):
    """A model's assets into folder: its textures, materials and meshes. uuids: a dict kept per output name (so
    each keeps its uuid). Returns [(path, what)]."""
    model = read_model(source, work)
    stem = base[3:] if base.startswith('SM_') else base
    scale = float(settings.get('scale', 1.0))
    out = []
    uuid_of = lambda name: int(uuids.setdefault(name, hex(new_uuid())), 16)
    textures = {}
    for i, (img_name, data) in enumerate(model.images):
        used = any(m.get('image') == i for m in model.materials)
        if not used:
            continue
        tmp = Path(work) / f'{stem}_{i}.img'
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        w, h, rgba = read_image(tmp)
        tname = f'T_{stem}_{_clean(img_name)}'
        write_texture(Path(folder) / f'{tname}.oct', tname, w, h, rgba, uuid_of(tname), settings.get('filter', 'linear'))
        textures[i] = (uuid_of(tname), tname)
        out.append((Path(folder) / f'{tname}.oct', f'texture {w} x {h}'))
    groups = sorted(model.groups.items(), key=lambda kv: kv[0])
    for mi, (verts, idx) in groups:
        mat = model.materials[mi] if 0 <= mi < len(model.materials) else {'name': 'Default', 'color': (1, 1, 1, 1), 'image': None,
                                                                            'blend': 'opaque', 'two_sided': False}
        part = '' if len(groups) == 1 else '_' + _clean(mat['name'])
        mname = f'M_{stem}{part}'
        write_material(Path(folder) / f'{mname}.oct', mname, uuid_of(mname), textures.get(mat.get('image')),
                       tuple(mat['color']), bool(settings.get('lit', True)), mat.get('blend', 'opaque'),
                       'none' if mat.get('two_sided') or settings.get('cull') == 'none' else 'back')
        out.append((Path(folder) / f'{mname}.oct', 'material'))
        if scale != 1.0:
            verts = [(x * scale, y * scale, z * scale, u, v, nx, ny, nz) for x, y, z, u, v, nx, ny, nz in verts]
        pieces = _split(verts, idx)
        for k, (pv, pi) in enumerate(pieces):
            sname = f'SM_{stem}{part}' + (f'_{k + 1}' if len(pieces) > 1 else '')
            write_mesh(Path(folder) / f'{sname}.oct', sname, pv, pi, (uuid_of(mname), mname), uuid_of(sname))
            out.append((Path(folder) / f'{sname}.oct', f'mesh, {len(pv)} vertices, {len(pi) // 3} triangles'))
    if not out:
        raise RuntimeError('no triangles in it')
    return out


# --- a project's Raw/ folder ----------------------------------------------------------------------

PREFIX = {'texture': 'T_', 'sound': 'SW_', 'mesh': 'SM_', 'video': 'V_', 'font': 'F_'}


def kind_of(path):
    ext = Path(path).suffix.lower()
    return ('texture' if ext in IMAGES else 'sound' if ext in AUDIO else 'mesh' if ext in MODELS else
            'video' if ext in VIDEOS else 'font' if ext in FONTS else None)


def default_name(rel, kind):
    stem = re.sub(r'[^A-Za-z0-9]+', ' ', Path(rel).stem).title().replace(' ', '') or 'Asset'
    return PREFIX[kind] + stem


def defaults(rel, kind, source):
    if kind == 'video':                         # VideoClip's own defaults (its cook: Engine/Source/Engine/Assets/VideoClip.h)
        return {'name': default_name(rel, kind), 'preset': 'custom', 'width': 320, 'height': 0, 'fps': 24, 'quality': 5,
                'audio_channels': 2, 'sample_rate': 44100, 'native_resolution': False, 'native_fps': False, 'native_audio': False}
    if kind == 'font':
        return {'name': default_name(rel, kind)}
    if kind == 'mesh':
        return {'name': default_name(rel, kind), 'scale': 1.0, 'lit': True, 'cull': 'back', 'filter': 'linear'}
    if kind == 'texture':
        return {'name': default_name(rel, kind), 'filter': 'linear', 'wrap': 'repeat', 'mipmaps': True,
                'force_hq': False, 'downsample': 1}
    music = Path(rel).suffix.lower() in ('.ogg', '.mp3') or _duration(source) > 15.0
    return {'name': default_name(rel, kind), 'mode': 'music' if music else 'effect',
            'rate': 32000 if music else 22050, 'volume': 1.0, 'pitch': 1.0, 'max_instances': 0, 'quality': 4}


class Project:
    """A project folder's Raw/ sources, their settings (Raw/assets.json) and what's been made of them
    (Intermediate/octkit.json: each source's size, time and settings when its asset was written)."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.raw = self.folder / 'Raw'
        self.assets = self.folder / 'Assets'
        self.settings_file = self.raw / SETTINGS
        self.made_file = self.folder / 'Intermediate' / 'octkit.json'
        self.settings = self._load(self.settings_file).get('assets', {})
        self.made = self._load(self.made_file)

    @staticmethod
    def _load(path):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def sources(self):
        if not self.raw.is_dir():
            return []
        return sorted(p for p in self.raw.rglob('*') if p.is_file() and kind_of(p) and '.part' not in p.suffixes)

    def entry(self, source):
        """The settings for a source (its defaults filled in, and a uuid made once)."""
        rel = source.relative_to(self.raw).as_posix()
        kind = kind_of(source)
        stored = self.settings.get(rel, {})
        entry = {**defaults(rel, kind, source), **stored, 'kind': kind}
        if 'uuid' not in stored:
            entry['uuid'] = hex(new_uuid())
            self.settings[rel] = {**stored, 'uuid': entry['uuid']}
        return rel, entry

    def output(self, rel, entry):
        return self.assets / Path(rel).parent / (entry['name'] + '.oct')

    def stamp(self, source, entry):
        st = source.stat()
        settings = json.dumps({k: v for k, v in entry.items() if k != 'uuid'}, sort_keys=True)
        return f'{st.st_size}:{int(st.st_mtime)}:{hashlib.sha1(settings.encode()).hexdigest()[:12]}'

    def status(self):
        out = []
        for source in self.sources():
            rel, entry = self.entry(source)
            target = self.output(rel, entry)
            if entry['kind'] == 'mesh':
                paths = self.made.get(rel + '#paths') or []
                meshes = [Path(x) for x in paths if Path(x).name.startswith('SM_')]
                target = meshes[0] if meshes else target
            made = self.made.get(rel)
            state = 'new' if not made or not target.exists() else 'ready' if made == self.stamp(source, entry) else 'changed'
            outputs = [Path(x).stem for x in self.made.get(rel + '#paths', [])] if entry['kind'] == 'mesh' else None
            out.append({'source': rel, 'asset': target.stem if entry['kind'] == 'mesh' and target.exists() else entry['name'],
                        'kind': entry['kind'], 'settings': entry, 'outputs': outputs,
                        'state': state, 'path': str(target), 'size': target.stat().st_size if target.exists() else None,
                        'source_size': source.stat().st_size})
        return out

    def convert(self, emit=lambda kind, **data: None, everything=False):
        """Writes the asset of every new or changed source. Returns (made, failed)."""
        made = failed = 0
        for source in self.sources():
            rel, entry = self.entry(source)
            target = self.output(rel, entry)
            stamp = self.stamp(source, entry)
            made_paths = self.made.get(rel + '#paths') if entry['kind'] == 'mesh' else None   # (a model: all its parts)
            there = all(Path(x).exists() for x in made_paths) if made_paths else target.exists()
            if not everything and self.made.get(rel) == stamp and there:
                continue
            uuid = int(entry['uuid'], 16)
            try:
                if entry['kind'] in ('video', 'font'):
                    folder = Path(rel).parent.as_posix()
                    options = None
                    if entry['kind'] == 'video':
                        options = {VIDEO_OPTIONS[k]: (PRESETS.get(entry[k], 0) if k == 'preset' else entry[k]) for k in VIDEO_OPTIONS}
                    target, what = octave_import(self.folder, source, entry['name'], '' if folder == '.' else folder, options)
                    old = self.made.get(rel + '#path')
                    if old and Path(old) != target and Path(old).exists():
                        Path(old).unlink()
                    self.made[rel] = stamp
                    self.made[rel + '#path'] = str(target)
                    made += 1
                    emit('line', text=f'{rel} -> {entry["name"]} ({what}, {target.stat().st_size / 1048576:.1f} MB)', level='info')
                    continue
                if entry['kind'] == 'mesh':
                    uuids = self.settings.setdefault(rel, {}).setdefault('uuids', {})
                    written = convert_model(source, target.parent, entry['name'], entry, uuids,
                                            self.folder / 'Intermediate' / 'octkit')
                    for old in self.made.get(rel + '#paths', []):           # (parts it no longer has)
                        if Path(old) not in [w for w, _ in written] and Path(old).exists():
                            Path(old).unlink()
                    self.made[rel + '#paths'] = [str(w) for w, _ in written]
                    self.made[rel] = stamp
                    made += 1
                    for w, what in written:
                        emit('line', text=f'{rel} -> {w.stem} ({what}, {w.stat().st_size / 1024:.0f} KB)', level='info')
                    continue
                if entry['kind'] == 'texture':
                    w, h, rgba = read_image(source)
                    write_texture(target, entry['name'], w, h, rgba, uuid, entry['filter'], entry['wrap'],
                                  entry['mipmaps'], True, entry['force_hq'], entry['downsample'])
                    what = f'texture {w} x {h}'
                elif entry['mode'] == 'music':
                    write_music(target, entry['name'], source, uuid, int(entry['rate']), 2, entry['quality'],
                                entry['volume'])
                    what = f'music, streamed, {int(entry["rate"]) // 1000} kHz'
                else:
                    pcm = read_pcm(source, int(entry['rate']), 1)
                    write_sound(target, entry['name'], pcm, int(entry['rate']), 1, uuid, entry['volume'],
                                entry['pitch'], entry['max_instances'])
                    what = f'sound effect, {len(pcm) / 2 / int(entry["rate"]):.2f} s'
            except (RuntimeError, ValueError, OSError, KeyError, IndexError, struct.error, subprocess.SubprocessError) as e:
                failed += 1
                emit('line', text=f'{rel}: {e}', level='error')
                continue
            # a renamed asset: the old file goes
            old = self.made.get(rel + '#path')
            if old and Path(old) != target and Path(old).exists():
                Path(old).unlink()
            self.made[rel] = stamp
            self.made[rel + '#path'] = str(target)
            made += 1
            emit('line', text=f'{rel} -> {entry["name"]} ({what}, {target.stat().st_size / 1024:.0f} KB)', level='info')
        self.save()
        return made, failed

    def save(self):
        self.raw.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(json.dumps({'assets': self.settings}, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        self.made_file.parent.mkdir(parents=True, exist_ok=True)
        self.made_file.write_text(json.dumps(self.made, indent=1, sort_keys=True), encoding='utf-8')


def main(argv):
    if len(argv) < 3 or argv[1] not in ('convert', 'status'):
        print(__doc__)
        return 2
    project = Project(argv[2])
    if argv[1] == 'status':
        print(json.dumps(project.status()))
        project.save()
        return 0
    emit = lambda kind, **data: print(json.dumps({'kind': kind, **data}), flush=True)
    start = time.time()
    made, failed = project.convert(emit, everything='--all' in argv)
    emit('done', made=made, failed=failed, seconds=round(time.time() - start, 1))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
