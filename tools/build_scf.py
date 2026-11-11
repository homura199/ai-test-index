"""Package only function sources and a freshly installed Linux dependency directory."""
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

FUNCTION_FILES = ('index.py', 'profiles/__init__.py', 'profiles/coze.py',
                  'profiles/scoring.py', 'profiles/service.py', 'profiles/storage.py')


def package(source, vendor, output):
    source, vendor, output = Path(source), Path(vendor), Path(output)
    if not (vendor / 'qcloud_cos' / '__init__.py').is_file():
        raise ValueError('Install backend/requirements.txt into a fresh vendor directory on Linux first')
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'x', ZIP_DEFLATED) as archive:
        for name in FUNCTION_FILES:
            archive.write(source / name, name)
        for path in sorted(vendor.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                if path.is_symlink(): raise ValueError('Symlinks are not supported')
                archive.write(path, path.relative_to(vendor).as_posix())


if __name__ == '__main__':
    package(Path(__file__).resolve().parents[1] / 'backend', sys.argv[1], sys.argv[2])
    print('SCF package created; configuration and credentials are not included.')
