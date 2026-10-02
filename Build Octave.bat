@echo off
rem Octave-libogc Builder: the editor, the shaders, the GameCube engine library and the Windows game program, from source.
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 Tools\builder.py & exit /b)
where pythonw >nul 2>nul && (start "" pythonw Tools\builder.py & exit /b)
echo Python 3 is needed: https://www.python.org/downloads/
pause
