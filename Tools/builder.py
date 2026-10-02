"""Octave-libogc Builder: what the release ships, built from this checkout, in a window.

    Double-click "Build Octave.bat" (or: python Tools/builder.py)

Each part is a tick box, and the window checks what the ticked parts need (Visual Studio with
C++, the Vulkan SDK, devkitPro) and says how to fix what's missing:

- ffmpeg and ffprobe (External/ffmpeg/bin), which packaging uses for video and sound: in git
  zipped (each is over GitHub's 100 MB a file), unzipped here;
- the shaders (Engine/Shaders/GLSL/bin), compiled with the Vulkan SDK's glslc;
- the editor, Octave.exe at the root (Standalone, ReleaseEditor|x64), which also packages games;
- the GameCube engine library (Engine/Build/GCN/libEngine.a, Bullet's with it), for GameCube games;
- the Windows game program (Standalone, Release|x64), which packaging a Windows game copies in.

Visual Studio builds two projects at a time (MSBuild /m:2, CL_MPCount=2) and make two files at a
time, everything below normal priority, so the machine stays usable. Every step runs without a
window of its own; the window shows each step's progress, and of the output only the steps and
errors ("Show every line" for the rest). All of it is in builder.log at the root.
"""
import io
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / 'builder.log'
SHADERS = ROOT / 'Engine' / 'Shaders' / 'GLSL'
EDITOR_BUILT = ROOT / 'Standalone' / 'Build' / 'Windows' / 'x64' / 'ReleaseEditor' / 'Octave.exe'
RUNTIME_BUILT = ROOT / 'Standalone' / 'Build' / 'Windows' / 'x64' / 'Release' / 'Octave.exe'
GCN_LIB = ROOT / 'Engine' / 'Build' / 'GCN' / 'libEngine.a'
FFMPEG = ROOT / 'External' / 'ffmpeg' / 'bin'
LOW_PRIORITY = 0x4000 | 0x08000000  # below normal, no console window (Windows)
SOURCE_LINE = re.compile(r'^\s*[\w.+-]+\.(?:cpp|c|cc)$')
# Only real errors: gcc's "error:", MSVC's "error C2065:" or "error LNK2019:", make's "Error 2", the
# linkers' -- not source lines quoted under a warning that happen to say "error" or "failed".
IMPORTANT = re.compile(r'\berror(?: [A-Z]+\d+)?:|fatal error|\bError \d+\b|undefined reference|unresolved external|'
                       r'No rule to make|ld returned|Traceback')
# Files Visual Studio compiles for a whole build of each (measured from a fresh clone): MSBuild's
# own count isn't knowable beforehand (the editor's sources come in through the configuration).
FULL_BUILD = {'ReleaseEditor': 711, 'Release': 526}


def find_devkitpro():
    for candidate in (os.environ.get('DEVKITPRO_WIN'), os.environ.get('DEVKITPRO'), r'C:\devkitPro'):
        if not candidate:
            continue
        if candidate.startswith('/') and len(candidate) > 2 and candidate[2] == '/':
            candidate = f'{candidate[1].upper()}:{candidate[2:]}'  # /c/devkitPro
        elif candidate.startswith('/opt/devkitpro'):
            candidate = r'C:\devkitPro'
        if (Path(candidate) / 'devkitPPC' / 'bin' / 'powerpc-eabi-gcc.exe').exists():
            return Path(candidate)
    return None


def msys(path):
    """C:\\devkitPro -> /c/devkitPro, as devkitPro's makefiles want it."""
    p = Path(path).as_posix()
    return f'/{p[0].lower()}{p[2:]}' if len(p) > 1 and p[1] == ':' else p


def find_msbuild():
    """Visual Studio's MSBuild, with the C++ tools (vswhere: Visual Studio's own, or the copy here)."""
    installer = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio' / 'Installer' / 'vswhere.exe'
    tool = installer if installer.exists() else ROOT / 'External' / 'vswhere' / 'vswhere.exe'
    if not tool.exists():
        return None
    try:
        out = subprocess.run([str(tool), '-latest', '-products', '*', '-requires',
                              'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-find',
                              r'MSBuild\**\Bin\MSBuild.exe'], capture_output=True, text=True,
                             creationflags=0x08000000 if os.name == 'nt' else 0).stdout.strip().splitlines()
    except OSError:
        return None
    return Path(out[0]) if out and Path(out[0]).exists() else None


def find_vulkan():
    sdk = os.environ.get('VULKAN_SDK')
    if sdk and (Path(sdk) / 'Bin' / 'glslc.exe').exists():
        return Path(sdk)
    return None


def msbuild_total(configuration):
    """How many files a build of this configuration will compile: all of them (FULL_BUILD) when
    it hasn't been built before; otherwise unknown (0), as it depends on what changed."""
    objects = ROOT / 'Engine' / 'Intermediate' / 'Windows' / 'x64' / configuration
    if objects.is_dir() and any(objects.rglob('*.obj')):
        return 0
    return FULL_BUILD.get(configuration, 0)


def program_sources():
    """The source files of Standalone and what it references (the engine, its libraries): what
    MSBuild could compile, for its progress."""
    seen, total, todo = set(), 0, [ROOT / 'Standalone' / 'Standalone.vcxproj']
    while todo:
        project = todo.pop().resolve()
        if project in seen or not project.exists():
            continue
        seen.add(project)
        try:
            tree = ET.parse(project).getroot()
        except ET.ParseError:
            continue
        for item in tree.iter():
            tag = item.tag.split('}')[-1]
            if tag == 'ClCompile' and item.get('Include'):
                total += 1
            elif tag == 'ProjectReference' and item.get('Include'):
                todo.append(project.parent / item.get('Include'))
    return total


# ffmpeg's two exes are over GitHub's 100 MB a file, so git has them zipped (External/ffmpeg/
# ffmpeg.zip, ffprobe.zip). Without those, they're read out of the latest release's zip -- only
# its two files, by ranges -- or, failing that, from BtbN's builds, where they come from.
RELEASES = 'https://api.github.com/repos/myuu-151/Octave-Libogc/releases/latest'
FFMPEG_URL = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip'


FFMPEG_ZIPS = (FFMPEG.parent / 'ffmpeg.zip', FFMPEG.parent / 'ffprobe.zip')


def ffmpeg_there():
    return (FFMPEG / 'ffmpeg.exe').exists() and (FFMPEG / 'ffprobe.exe').exists()


class RemoteFile(io.RawIOBase):
    """A file on the web, read by byte ranges (enough for zipfile to take a few members out of a big
    zip). counted: the bytes read so far."""

    def __init__(self, url):
        import urllib.request
        self.request = urllib.request
        with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=60) as r:
            self.url, self.size = r.geturl(), int(r.headers['Content-Length'])
        self.pos = self.counted = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, buffer):
        if self.pos >= self.size:
            return 0
        end = min(self.size, self.pos + len(buffer)) - 1
        request = self.request.Request(self.url, headers={'Range': f'bytes={self.pos}-{end}'})
        with self.request.urlopen(request, timeout=60) as r:
            data = r.read()
        buffer[:len(data)] = data
        self.pos += len(data)
        self.counted += len(data)
        return len(data)


def makefile_sources(makefile):
    """A devkitPro makefile's SOURCES folders' .c and .cpp files, and its BUILD folder."""
    text = makefile.read_text(encoding='utf-8', errors='replace').replace('\\\n', ' ')
    sources = re.search(r'^SOURCES\s*:=\s*(.*)$', text, re.MULTILINE)
    build = re.search(r'^BUILD\s*:=\s*(\S+)', text, re.MULTILINE)
    folders = sources.group(1).split() if sources else []
    files = [f for d in folders for pattern in ('*.c', '*.cpp') for f in (makefile.parent / d).glob(pattern)]
    return files, makefile.parent / (build.group(1) if build else 'Intermediate/GCN')


def gcn_to_compile():
    """(the files make will compile for the GameCube library, all of them): an object missing or
    older than its source. A changed header makes more; the count grows then."""
    stale = everything = 0
    for makefile in (ROOT / 'External' / 'Bullet' / 'Makefile_GCN', ROOT / 'Engine' / 'Makefile_GCN'):
        files, objects = makefile_sources(makefile)
        everything += len(files)
        for f in files:
            o = objects / (f.stem + '.o')
            stale += not o.exists() or o.stat().st_mtime < f.stat().st_mtime
    return stale, everything


class Builder:
    PARTS = (('ffmpeg', 'ffmpeg and ffprobe (External/ffmpeg/bin), unzipped: packaging needs them'),
             ('shaders', 'The shaders (Engine/Shaders/GLSL/bin)'),
             ('editor', 'The editor (Octave.exe), which also packages games'),
             ('gcn', 'The GameCube engine library (libEngine.a)'),
             ('runtime', 'The Windows game program (for packaging Windows games)'))

    def __init__(self, root):
        self.root = root
        self.lines = queue.Queue()
        self.busy = False
        self.ready = False
        root.title('Octave-libogc Builder')
        root.minsize(660, 560)
        self.verbose = tk.BooleanVar(value=False)
        self.entries = []  # every line of output: (text, shown without "Show every line")
        self.phase = ''
        self.step = ''

        pad = {'padx': 10, 'pady': 4}
        ttk.Label(root, text='Octave-libogc, from source', font=('Segoe UI', 14, 'bold')).pack(anchor='w', **pad)

        what = ttk.LabelFrame(root, text='What to build')
        what.pack(fill='x', **pad)
        self.parts = {}
        for key, title in self.PARTS:
            # ffmpeg ticked when it isn't there (a download, not a build: once is enough)
            var = tk.BooleanVar(value=not ffmpeg_there() if key == 'ffmpeg' else True)
            ttk.Checkbutton(what, text=title, variable=var, command=self.check).pack(anchor='w', padx=6, pady=1)
            self.parts[key] = var

        checks = ttk.LabelFrame(root, text='What that needs')
        checks.pack(fill='x', **pad)
        self.rows = {}
        for key, title in (('vs', 'Visual Studio (C++)'), ('vulkan', 'Vulkan SDK'), ('devkitpro', 'devkitPro (devkitPPC)'),
                           ('ffmpeg', 'ffmpeg')):
            row = ttk.Frame(checks)
            row.pack(fill='x', padx=6, pady=2)
            mark = ttk.Label(row, width=3, font=('Segoe UI', 11, 'bold'))
            mark.pack(side='left')
            ttk.Label(row, text=title, width=24).pack(side='left')
            note = ttk.Label(row, foreground='#555')
            note.pack(side='left', fill='x', expand=True)
            self.rows[key] = (mark, note)

        buttons = ttk.Frame(root)
        buttons.pack(fill='x', **pad)
        self.build_button = ttk.Button(buttons, text='Build', command=self.build)
        self.build_button.pack(side='left')
        self.progress = ttk.Progressbar(buttons, mode='indeterminate', length=240, maximum=100)  # while building

        self.status = ttk.Label(root, text='')
        self.status.pack(anchor='w', **pad)

        ttk.Checkbutton(root, text='Show every line', variable=self.verbose,
                        command=self.show_log).pack(anchor='w', padx=10)
        frame = ttk.Frame(root)
        frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(frame, height=12, wrap='none', font=('Consolas', 9), state='disabled')
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)

        self.msbuild, self.vulkan, self.devkitpro = find_msbuild(), find_vulkan(), find_devkitpro()
        self.check()
        root.after(100, self.pump)

    # --- what the build needs -------------------------------------------------

    def set_row(self, key, state, note):
        """state: True (there), False (missing and needed), None (missing, not needed now)."""
        mark, label = self.rows[key]
        text, colour = {True: ('OK', '#1a7f37'), False: ('X', '#c62828'), None: ('-', '#888')}[state]
        mark.configure(text=text, foreground=colour)
        label.configure(text=note)

    def check(self):
        want = {k: v.get() for k, v in self.parts.items()}
        ok = any(want.values())
        if self.busy:
            return ok
        need_vs = want['editor'] or want['runtime']
        need_vulkan = want['shaders'] or need_vs          # the Windows build includes Vulkan's headers too
        if self.msbuild:
            self.set_row('vs', True, str(self.msbuild.parents[3]))
        else:
            self.set_row('vs', False if need_vs else None, 'install Visual Studio with "Desktop development with C++"')
            ok = ok and not need_vs
        if self.vulkan:
            self.set_row('vulkan', True, str(self.vulkan))
        else:
            self.set_row('vulkan', False if need_vulkan else None, 'install the Vulkan SDK (vulkan.lunarg.com)')
            ok = ok and not need_vulkan
        if self.devkitpro:
            self.set_row('devkitpro', True, str(self.devkitpro))
        else:
            self.set_row('devkitpro', False if want['gcn'] else None, 'install devkitPro with devkitPPC (devkitpro.org)')
            ok = ok and not want['gcn']
        if ffmpeg_there():
            self.set_row('ffmpeg', True, str(FFMPEG))
        elif want['ffmpeg']:
            self.set_row('ffmpeg', None, 'unzipped from External/ffmpeg when building' if all(z.exists() for z in FFMPEG_ZIPS)
                         else "taken from the latest release's zip when building (about 110 MB)")
        else:
            self.set_row('ffmpeg', False, 'not there: tick it above (packaging uses it for video and sound)')
            ok = False
        self.ready = ok
        self.build_button.configure(state='normal' if ok and not self.busy else 'disabled')
        if not self.busy:
            self.status.configure(text='Ready to build.' if ok else
                                  ('Tick something to build.' if not any(want.values()) else 'Fix the X items above, then build.'))
        return ok

    # --- the window's log and progress -------------------------------------

    def write(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text)
        self.log.see('end')
        self.log.configure(state='disabled')

    def show_log(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.insert('end', ''.join(text + '\n' for text, shown in self.entries if shown or self.verbose.get()))
        self.log.see('end')
        self.log.configure(state='disabled')

    def pump(self):
        try:
            while True:
                kind, *rest = self.lines.get_nowait()
                if kind == 'line':
                    text, shown = rest
                    self.entries.append((text, shown))
                    if shown or self.verbose.get():
                        self.write(text + '\n')
                elif kind == 'phase':
                    self.phase = rest[0]
                    self.show_step('starting')
                elif kind == 'step':
                    self.show_step(rest[0])
                elif kind == 'progress':
                    self.show_progress(*rest)
                elif kind == 'count':
                    self.status.configure(text=f'{self.phase}: {self.step}, {rest[0]} files compiled')
                elif kind == 'done':
                    self.finished(*rest)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def show_step(self, step):
        self.step = step
        self.progress.stop()
        self.progress.configure(mode='indeterminate')
        self.progress.start(12)
        self.status.configure(text=f'{self.phase}: {step}...')

    def show_progress(self, done, total):
        if str(self.progress.cget('mode')) != 'determinate':
            self.progress.stop()
            self.progress.configure(mode='determinate')
        percent = 100 * done // max(total, 1)
        self.progress.configure(value=percent)
        self.status.configure(text=f'{self.phase}: {self.step}, {done} of {total} ({percent}%)')

    def say(self, text):
        self.lines.put(('line', text, True))
        with open(LOG_FILE, 'a', encoding='utf-8') as log:
            log.write(text + '\n')

    # --- building ---------------------------------------------------------

    def build(self):
        if self.busy or not self.check():
            return
        self.busy = True
        self.build_button.configure(state='disabled')
        self.progress.pack(side='right')
        self.status.configure(foreground='')
        self.entries = []
        self.show_log()
        LOG_FILE.write_text('', encoding='utf-8')
        threading.Thread(target=self.run_build, args=({k: v.get() for k, v in self.parts.items()},), daemon=True).start()

    def run(self, args, cwd, env, watch):
        """Runs a step hidden, in the background at low priority (what it starts inherits that);
        each line of its output to the log file, and to watch, which says whether the window shows
        it. True if it succeeded."""
        startup = None
        if os.name == 'nt':
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0  # SW_HIDE
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, startupinfo=startup,
                                creationflags=LOW_PRIORITY if os.name == 'nt' else 0)
        with open(LOG_FILE, 'a', encoding='utf-8') as log:
            for raw in proc.stdout:
                text = raw.decode('utf-8', 'replace').rstrip('\r\n').split('\r')[-1].rstrip()
                if not text:
                    continue
                log.write(text + '\n')
                self.lines.put(('line', text, watch(text)))
        return proc.wait() == 0

    def counting(self, total):
        """A watch that counts the source files compiled against total and shows only errors."""
        count = {'done': 0}

        def watch(text):
            if SOURCE_LINE.match(text):
                count['done'] += 1
                if total:
                    self.lines.put(('progress', count['done'], max(total, count['done'])))
                else:
                    self.lines.put(('count', count['done']))
                return False
            return bool(IMPORTANT.search(text)) and 'warning' not in text.lower()
        return watch

    def ffmpeg(self):
        """ffmpeg.exe and ffprobe.exe into External/ffmpeg/bin: unzipped from External/ffmpeg's
        zips (in git); without them, the ones the latest release ships, read out of its zip; failing
        that, BtbN's LGPL build."""
        if all(z.exists() for z in FFMPEG_ZIPS):
            return self.ffmpeg_from_repo()
        try:
            return self.ffmpeg_from_release()
        except (OSError, ValueError, KeyError) as e:
            self.say(f"couldn't take ffmpeg from the release ({e}): downloading BtbN's build instead")
            return self.ffmpeg_from_btbn()

    def ffmpeg_from_repo(self):
        import zipfile
        self.lines.put(('step', 'unpacking ffmpeg'))
        FFMPEG.mkdir(parents=True, exist_ok=True)
        for n, path in enumerate(FFMPEG_ZIPS, 1):
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    part = FFMPEG / (info.filename + '.part')
                    with z.open(info) as src, open(part, 'wb') as out:
                        shutil.copyfileobj(src, out, 1 << 20)
                    part.replace(FFMPEG / info.filename)
            self.lines.put(('progress', n, len(FFMPEG_ZIPS)))
        if not ffmpeg_there():
            self.say("External/ffmpeg's zips had no ffmpeg.exe and ffprobe.exe in them")
            return False
        self.say(f'ffmpeg: {FFMPEG.relative_to(ROOT).as_posix()} (unzipped)')
        return True

    def ffmpeg_from_release(self):
        import json
        import urllib.request
        import zipfile
        self.lines.put(('step', 'finding the latest release'))
        with urllib.request.urlopen(RELEASES, timeout=60) as r:
            release = json.load(r)
        asset = next(a for a in release['assets'] if a['name'].endswith('.zip'))
        remote = RemoteFile(asset['browser_download_url'])
        with zipfile.ZipFile(io.BufferedReader(remote, buffer_size=1 << 20)) as z:
            members = [i for i in z.infolist() if i.filename.startswith('External/ffmpeg/bin/')
                       and i.filename.rsplit('/', 1)[-1] in ('ffmpeg.exe', 'ffprobe.exe')]
            if len(members) != 2:
                raise ValueError(f"{asset['name']} has no ffmpeg in it")
            total = sum(i.compress_size for i in members) >> 20
            self.lines.put(('step', f"downloading ffmpeg from {release['tag_name']} (MB)"))
            FFMPEG.mkdir(parents=True, exist_ok=True)
            start = remote.counted
            for info in members:
                part = FFMPEG / (info.filename.rsplit('/', 1)[-1] + '.part')
                with z.open(info) as src, open(part, 'wb') as out:
                    while True:
                        block = src.read(1 << 20)
                        if not block:
                            break
                        out.write(block)
                        self.lines.put(('progress', min((remote.counted - start) >> 20, total), total))
                part.replace(FFMPEG / info.filename.rsplit('/', 1)[-1])
        if not ffmpeg_there():
            return False
        self.say(f"ffmpeg: {FFMPEG.relative_to(ROOT).as_posix()} (from {release['tag_name']})")
        return True

    def ffmpeg_from_btbn(self):
        """BtbN's LGPL ffmpeg build: its ffmpeg.exe, ffprobe.exe and licence."""
        import urllib.request
        import zipfile
        self.lines.put(('step', 'downloading ffmpeg (MB)'))
        FFMPEG.mkdir(parents=True, exist_ok=True)
        part = FFMPEG.parent / 'ffmpeg-download.zip'
        with urllib.request.urlopen(FFMPEG_URL, timeout=60) as response, open(part, 'wb') as out:
            total = int(response.headers.get('Content-Length') or 0)
            done = 0
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if total:
                    self.lines.put(('progress', done >> 20, total >> 20))
        self.lines.put(('step', 'unpacking ffmpeg'))
        wanted = {'ffmpeg.exe': 'ffmpeg.exe', 'ffprobe.exe': 'ffprobe.exe', 'LICENSE.txt': 'LICENSE.txt'}
        with zipfile.ZipFile(part) as z:
            for info in z.infolist():
                name = info.filename.rsplit('/', 1)[-1]
                in_bin = '/bin/' in info.filename
                if name in wanted and (in_bin or name == 'LICENSE.txt'):
                    (FFMPEG / wanted[name]).write_bytes(z.read(info))
        part.unlink()
        if not ffmpeg_there():
            self.say('the download had no ffmpeg.exe and ffprobe.exe in it')
            return False
        self.say(f'ffmpeg: {FFMPEG.relative_to(ROOT).as_posix()}')
        return True

    def shaders(self):
        """Each shader in Engine/Shaders/GLSL/src (not the .glsl ones, which they include) compiled
        with glslc, as compile.bat does."""
        sources = sorted(f for f in (SHADERS / 'src').iterdir() if f.is_file() and f.suffix != '.glsl')
        (SHADERS / 'bin').mkdir(exist_ok=True)
        glslc = self.vulkan / 'Bin' / 'glslc.exe'
        self.lines.put(('step', 'compiling the shaders'))
        for n, f in enumerate(sources, 1):
            ok = self.run([str(glslc), str(f), '-O', '-g', '-fpreserve-bindings', '-o', str(SHADERS / 'bin' / f.name)],
                          SHADERS, dict(os.environ), lambda text: True)
            if not ok:
                self.say(f'{f.name} did not compile')
                return False
            self.lines.put(('progress', n, len(sources)))
        self.say(f'shaders: {len(sources)} compiled')
        return True

    def msbuild_standalone(self, configuration, step):
        self.lines.put(('step', step))
        env = dict(os.environ, CL_MPCount='2', VULKAN_SDK=str(self.vulkan))
        return self.run([str(self.msbuild), 'Octave.sln', '/t:Standalone', f'/p:Configuration={configuration}',
                         '/p:Platform=x64', '/m:2', '/v:m', '/nologo'], ROOT, env, self.counting(msbuild_total(configuration)))

    def editor(self):
        if not self.msbuild_standalone('ReleaseEditor', 'compiling the editor'):
            return False
        try:
            shutil.copy2(EDITOR_BUILT, ROOT / 'Octave.exe')
        except OSError as e:
            self.say(f'could not copy the editor to Octave.exe ({e}): is it open? Close it and build again.')
            return False
        self.say('editor: Octave.exe')
        return True

    def gcn(self):
        dkp = self.devkitpro
        env = dict(os.environ)
        env['PATH'] = os.pathsep.join([str(dkp / 'devkitPPC' / 'bin'), str(dkp / 'tools' / 'bin'),
                                       str(dkp / 'msys2' / 'usr' / 'bin'), env.get('PATH', '')])
        env['DEVKITPRO'] = msys(dkp)
        env['DEVKITPPC'] = msys(dkp / 'devkitPPC')
        stale, everything = gcn_to_compile()
        self.lines.put(('step', 'compiling the GameCube engine library'))
        ok = self.run([str(dkp / 'msys2' / 'usr' / 'bin' / 'make.exe'), '-f', 'Makefile_GCN', '-j2'],
                      ROOT / 'Engine', env, self.counting(stale or everything))
        if ok and GCN_LIB.exists():
            self.say(f'GameCube engine library: {GCN_LIB.relative_to(ROOT).as_posix()}')
        return ok and GCN_LIB.exists()

    def runtime(self):
        if not self.msbuild_standalone('Release', 'compiling the Windows game program'):
            return False
        self.say(f'Windows game program: {RUNTIME_BUILT.relative_to(ROOT).as_posix()}')
        return RUNTIME_BUILT.exists()

    def run_build(self, want):
        steps = [('ffmpeg', 'ffmpeg', self.ffmpeg), ('shaders', 'The shaders', self.shaders), ('editor', 'The editor', self.editor),
                 ('gcn', 'The GameCube library', self.gcn), ('runtime', 'The Windows game program', self.runtime)]
        ok = True
        for key, phase, step in steps:
            if not want[key]:
                continue
            self.say(f'== {phase}')
            self.lines.put(('phase', phase))
            try:
                ok = step()
            except OSError as e:
                self.say(f'{phase} failed: {e}')
                ok = False
            if not ok:
                break
        self.lines.put(('done', ok))

    def finished(self, ok):
        self.busy = False
        self.progress.stop()
        self.progress.configure(mode='determinate', value=0)
        self.progress.pack_forget()
        self.build_button.configure(state='normal' if self.ready else 'disabled')
        if ok:
            self.status.configure(text='Done.', foreground='#1a7f37')
            self.entries.append(('== Done', True))
            self.write('== Done\n')
        else:
            self.status.configure(text=f'The build failed: the log says why (all of it: {LOG_FILE}).',
                                  foreground='#c62828')
            if not self.verbose.get():
                hidden = [text for text, shown in self.entries if not shown][-25:]
                if hidden:
                    self.write('\n-- the last lines of output:\n' + ''.join(text + '\n' for text in hidden))


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use('vista')
    except tk.TclError:
        pass
    Builder(root)
    root.mainloop()


if __name__ == '__main__':
    main()
