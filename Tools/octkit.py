"""octkit: Octave assets written from code -- no editor.

A project's Raw/ folder holds the source files (PNG, JPG, BMP, TGA, WAV, OGG, MP3, FLAC); octkit turns each into
the .oct asset the editor would have made of it, in Assets/ (the same sub-folders), and Octave's packager then
cooks them for the console as it does any asset (a texture's GameCube format is chosen there, from its alpha).
Sonic Pipe Dream's way (its native/*.py wrote its stages, sounds and sky this way), made general.

    python Tools/octkit.py convert <project folder>     the new and changed files; events as JSON lines
    python Tools/octkit.py status  <project folder>     every file, its asset and whether it's up to date: JSON

    import octkit                                        from a project's own build.py:
    octkit.write_texture(path, name, w, h, rgba, ...)    a texture from RGBA8 pixels
    octkit.write_sound(path, name, pcm, rate, ...)       a sound from 16-bit PCM
    octkit.write_music(path, name, source, ...)          a streamed music track (Vorbis) from any audio file

Each file's settings live in Raw/assets.json, keyed by its path in Raw/ (DolphinWorks edits them):
    textures  name, filter (linear | nearest), wrap (repeat | clamp | mirror), mipmaps, force_hq, downsample
    sounds    name, mode (effect | music), rate, volume, pitch, max_instances, quality (music: Vorbis -q)
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
FILTERS = {'nearest': 0, 'linear': 1}
WRAPS = {'clamp': 0, 'repeat': 1, 'mirror': 2}
PIXEL_RGBA8 = 2

IMAGES = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.webp'}
AUDIO = {'.wav', '.ogg', '.mp3', '.flac', '.aif', '.aiff'}
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


# --- a project's Raw/ folder ----------------------------------------------------------------------

PREFIX = {'texture': 'T_', 'sound': 'SW_'}


def kind_of(path):
    ext = Path(path).suffix.lower()
    return 'texture' if ext in IMAGES else 'sound' if ext in AUDIO else None


def default_name(rel, kind):
    stem = re.sub(r'[^A-Za-z0-9]+', ' ', Path(rel).stem).title().replace(' ', '') or 'Asset'
    return PREFIX[kind] + stem


def defaults(rel, kind, source):
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
            made = self.made.get(rel)
            state = 'new' if not made or not target.exists() else 'ready' if made == self.stamp(source, entry) else 'changed'
            out.append({'source': rel, 'asset': entry['name'], 'kind': entry['kind'], 'settings': entry,
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
            if not everything and self.made.get(rel) == stamp and target.exists():
                continue
            uuid = int(entry['uuid'], 16)
            try:
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
            except (RuntimeError, ValueError, OSError) as e:
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
