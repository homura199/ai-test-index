from pathlib import Path
import tempfile
import unittest
from tools.stage_site import PUBLIC_FILES, stage


class PublicationTests(unittest.TestCase):
    def test_private_files_never_enter_site(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in PUBLIC_FILES:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text('public', encoding='utf-8')
            (root / 'private-survey.xlsx').write_bytes(b'sensitive')
            (root / '.env').write_text('TOKEN=private', encoding='utf-8')
            (root / 'backend').mkdir()
            (root / 'backend' / 'private.py').write_text('private', encoding='utf-8')
            output = root / 'site'
            stage(root, output)
            self.assertEqual({item.relative_to(output).as_posix() for item in output.rglob('*') if item.is_file()}, set(PUBLIC_FILES))

    def test_existing_output_is_rejected_to_avoid_uploading_stale_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in PUBLIC_FILES:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text('public', encoding='utf-8')
            output = root / 'site'
            output.mkdir()
            (output / 'student.xlsx').write_bytes(b'private')
            with self.assertRaises(FileExistsError):
                stage(root, output)
