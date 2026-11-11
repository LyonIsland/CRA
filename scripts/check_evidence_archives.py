"""Exercise split archive restoration and hostile path/hash rejection."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from archive_project_evidence import pack,AuditedReader
from restore_project_evidence import process_group,verify_part


class Checks(unittest.TestCase):
    def test_split_roundtrip_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.write_bytes(bytes(range(256))*400)
            archives=root/'archives';archives.mkdir()
            manifest=pack(archives,'test',[(source,'project/test.dat')],128)
            self.assertGreater(len(manifest['parts']),1)
            out=(root/'restored').resolve();out.mkdir()
            result=process_group(archives,manifest,out)
            self.assertEqual(result['verified_files'],1)
            self.assertEqual((out/'project/test.dat').read_bytes(),source.read_bytes())
            changed=dict(manifest['parts'][0]);changed['sha256']='0'*64
            with self.assertRaises(ValueError):verify_part(archives/changed['name'],changed)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.write_text('evidence')
            manifest=pack(root,'escape',[(source,'../outside')],1024)
            with self.assertRaises(ValueError):process_group(root,manifest)

    def test_secret_pattern_across_read_boundary(self):
        import io
        reader=AuditedReader(io.BytesIO(('ghp_'+'a'*40).encode()),Path('example'))
        reader.read(12)
        with self.assertRaises(ValueError):reader.read()


if __name__=='__main__':unittest.main()
