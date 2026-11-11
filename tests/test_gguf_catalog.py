import sys,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'agent'),str(Path(__file__).resolve().parents[1]/'tools')]
import gguf_catalog as catalog
from gguf_reader import GGUFFile

def string(s):
    b=s.encode();return struct.pack('<Q',len(b))+b

def fixture(path,mtp=False):
    kv=[('general.architecture',struct.pack('<I',8)+string('qwen35moe')),('qwen35moe.embedding_length',struct.pack('<II',4,128)),('tokenizer.ggml.tokens',struct.pack('<IIQ',9,8,3)+b''.join(string(x) for x in ['hello','world','猫']))]
    raw=struct.pack('<IIQQ',0x46554747,3,1,len(kv))+b''.join(string(k)+v for k,v in kv)
    raw+=string('mtp.weight' if mtp else 'test.weight')+struct.pack('<IQQIQ',2,64,2,1,0)
    path.write_bytes(raw+b'\0'*256)

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.file=self.root/'model.gguf';fixture(self.file)
        self.patch=patch.object(catalog,'DATA_ROOT',self.root);self.patch.start();catalog._memory.clear()
    def tearDown(self):self.patch.stop();self.tmp.cleanup();catalog._memory.clear()
    def test_skipped_vocabulary_preserves_tensor_table(self):
        full=GGUFFile(self.file);small=GGUFFile(self.file,skip_tokenizer=True)
        self.assertEqual(full.tensors,small.tensors);self.assertEqual(full.data_start,small.data_start)
        self.assertEqual(full.metadata['general.architecture'],small.metadata['general.architecture'])
        self.assertNotIn('tokenizer.ggml.tokens',small.metadata)
    def test_disk_cache_avoids_reopening_header(self):
        first=catalog.inspect(self.file);catalog._memory.clear()
        with patch.object(catalog,'GGUFFile',side_effect=AssertionError('Header re-opened')):self.assertEqual(catalog.inspect(self.file),first)
    def test_replaced_file_invalidates_capabilities(self):
        self.assertFalse(catalog.inspect(self.file)['head']);fixture(self.file,True)
        self.assertTrue(catalog.inspect(self.file)['head'])
    def test_corrupt_cache_recovers_from_file(self):
        catalog.inspect(self.file);catalog._memory.clear()
        next((self.root/'cache/gguf-catalog').glob('*.json')).write_text('{broken')
        self.assertEqual(catalog.inspect(self.file)['metadata']['general.architecture'],'qwen35moe')

if __name__=='__main__':unittest.main()
