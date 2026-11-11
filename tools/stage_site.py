"""Create a new static-only publication directory, never copy the repository."""
from pathlib import Path
import shutil
import sys

PUBLIC_FILES = tuple('caitian-ai/' + name for name in (
    'caitian-config.js', 'caitian-session.js', 'caitian-questionnaire.js',
    'caitian-questionnaire.css', 'index.html'))


def stage(source, destination):
    source, destination = Path(source), Path(destination)
    for name in PUBLIC_FILES:
        if not (source / name).is_file() or (source / name).is_symlink():
            raise ValueError(f'Missing or unsafe public file: {name}')
    destination.mkdir(parents=True, exist_ok=False)
    for name in PUBLIC_FILES:
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination / name)
    return list(PUBLIC_FILES)


if __name__ == '__main__':
    print('\n'.join(stage(Path(__file__).resolve().parents[1],
                          sys.argv[1] if len(sys.argv) > 1 else 'build/site')))
