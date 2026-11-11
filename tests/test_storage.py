import sys
import types
import unittest
from unittest.mock import Mock, patch
from backend.profiles.storage import CosStore

class ServiceError(Exception):
    def __init__(self, code): self.code = code
    def get_status_code(self): return self.code

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.get_bucket_versioning.return_value = {}
        self.store = CosStore(lambda: self.client, 'private-test-bucket')
        module = types.ModuleType('qcloud_cos.cos_exception')
        module.CosServiceError = ServiceError
        self.mock = patch.dict(sys.modules, {'qcloud_cos.cos_exception': module})
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_duplicate_submission_uses_cos_atomic_no_overwrite(self):
        self.assertTrue(self.store.create('submissions', 'a' * 64, {'answers': 'private'}))
        self.assertEqual(self.client.put_object.call_args.kwargs['ForbidOverwrite'], 'true')
        self.assertEqual(self.client.put_object.call_args.kwargs['ServerSideEncryption'], 'AES256')
        self.client.put_object.side_effect = ServiceError(409)
        self.assertFalse(self.store.create('submissions', 'a' * 64, {'answers': 'replacement'}))

    def test_versioning_and_storage_errors_cannot_silently_overwrite(self):
        for status in ('Enabled', 'Suspended'):
            self.client.get_bucket_versioning.return_value = {'Status': status}
            with self.assertRaises(RuntimeError): self.store.create('submissions', 'a' * 64, {})
        self.client.put_object.assert_not_called()
        self.client.get_bucket_versioning.return_value = {}
        self.client.put_object.side_effect = ServiceError(403)
        with self.assertRaises(ServiceError): self.store.create('submissions', 'a' * 64, {})
