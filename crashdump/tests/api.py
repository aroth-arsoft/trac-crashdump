#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import shutil
import tempfile
import unittest

from trac.core import Component, implements
from trac.db.api import DatabaseManager
#from trac.db.schema import Table, Column, Index
from trac.test import EnvironmentStub

from crashdump.api import CrashDumpSystem


class CrashDumpSystemEnvOkTestCase(unittest.TestCase):
    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*', 'crashdump.*'])
        self.env.path = tempfile.mkdtemp()
        self.db_mgr = DatabaseManager(self.env)
        #self.db = self.env.get_db_cnx()
        self.crashdump_sys = CrashDumpSystem(self.env)

    def tearDown(self):
        #self.db.close()
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    def test_fields(self):

        def assert_field_exists(self, fields, name):
            exists = False
            for f in fields:
                if f['name'] == name:
                    exists = True
                    break
            self.assertTrue(exists, msg='Field with name %s does not exists' % name)

        fields = self.crashdump_sys.fields
        assert_field_exists(self, fields, 'reporter')
        assert_field_exists(self, fields, 'applicationname')

        assert_field_exists(self, fields, 'coredumpfile')
        assert_field_exists(self, fields, 'coredumpreportxmlfile')
        assert_field_exists(self, fields, 'coredumpreporthtmlfile')
        assert_field_exists(self, fields, 'coredumpreporttextfile')

        assert_field_exists(self, fields, 'minidumpfile')
        assert_field_exists(self, fields, 'minidumpreportxmlfile')
        assert_field_exists(self, fields, 'minidumpreporthtmlfile')
        assert_field_exists(self, fields, 'minidumpreporttextfile')


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(CrashDumpSystemEnvOkTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')

