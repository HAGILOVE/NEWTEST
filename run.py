"""Isolated Windows/macOS/Linux launcher. No third-party imports before setup."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv'
PYTHON = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def call(args):
    result = subprocess.run([str(x) for x in args], cwd=str(ROOT))
    if result.returncode:
        raise RuntimeError('Command failed (exit %s): %s' % (result.returncode, args))


def main():
    parser = argparse.ArgumentParser(description='Aether EM isolated launcher')
    parser.add_argument('--setup', action='store_true', help='Install/update this source in its isolated environment')
    parser.add_argument('--check', action='store_true', help='Verify imports and CAD kernel without opening the UI')
    args = parser.parse_args()
    if sys.version_info < (3, 9):
        raise RuntimeError('Python 3.9+ is required; use Python 3.12 on Windows.')
    first_run = not PYTHON.is_file()
    if first_run:
        print('Creating isolated .venv ...', flush=True)
        venv.EnvBuilder(with_pip=True).create(str(ENV))
    if first_run or args.setup:
        print('Installing application and CAD backend. First setup requires Internet access.', flush=True)
        call([PYTHON, '-m', 'pip', 'install', '-e', '.[mesh]'])
    # Fail clearly before opening a partly functional CAD workspace.
    check = 'import numpy, scipy, ezdxf, gmsh; gmsh.initialize(); gmsh.finalize(); import aether; print("Aether", aether.__version__, "- scientific stack and CAD kernel OK")'
    call([PYTHON, '-c', check])
    if not args.check and not args.setup:
        call([PYTHON, '-m', 'aether.cli', 'gui'])
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as exc:
        print('\nSTARTUP FAILED:', exc, file=sys.stderr)
        print('Run SETUP_WINDOWS.cmd to repair dependencies. On Linux the gmsh wheel also requires the system OpenGL/GLU libraries.', file=sys.stderr)
        raise SystemExit(1)
