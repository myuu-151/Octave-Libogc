"""OctTemplate's own build step: DolphinWorks runs this on every Build, after it has converted Raw/ into assets and
before Octave packages the game -- for what the game makes for itself (data as Lua tables, pictures cut or
recoloured, levels from a file...). Sonic Pipe Dream's native/*.py scripts did this kind of work.

    PROJECT   this project's folder (also the working folder)
    OCTAVE    Octave-libogc's folder: octkit (Tools/octkit.py) imports from it

A failure (an exception, or a non-zero exit) stops the build, with its output in the log. By hand:
    set PROJECT=<this folder> & set PYTHONPATH=<Octave>\\Tools & python build.py
"""
import os
from pathlib import Path

import octkit           # Octave's asset writers: write_texture, write_sound, write_music, write_material, write_mesh

PROJECT = Path(os.environ.get('PROJECT', Path(__file__).resolve().parent))


def lua(value, indent=0):
    """A Python value as Lua source: dicts, lists, numbers, strings, booleans."""
    pad = '    ' * (indent + 1)
    if isinstance(value, dict):
        return '{\n' + ''.join(f'{pad}{k} = {lua(v, indent + 1)},\n' for k, v in value.items()) + '    ' * indent + '}'
    if isinstance(value, (list, tuple)):
        return '{ ' + ', '.join(lua(v, indent + 1) for v in value) + ' }'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, str):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return repr(value)


# An example: game data written as a Lua table the scripts read (Script.Require("Levels") gives Levels).
levels = {'count': 3, 'speeds': [1.0, 1.5, 2.0]}
(PROJECT / 'Scripts' / 'Levels.lua').write_text('-- Made by build.py: change it there.\nLevels = ' + lua(levels) + '\n')
print('build.py: wrote Scripts/Levels.lua')
