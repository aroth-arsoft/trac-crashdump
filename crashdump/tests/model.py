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
from trac.resource import ResourceNotFound

from crashdump.web_ui import CrashDumpModule
from crashdump.model import CrashDump


class CrashDumpModelTestCase(unittest.TestCase):
    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*', 'crashdump.*'])
        self.env.path = tempfile.mkdtemp()
        self.db_mgr = DatabaseManager(self.env)
        self.env.upgrade()
        #self.db = self.env.get_db_cnx()
        self.crashdump_module = CrashDumpModule(self.env)

    def tearDown(self):
        #self.db.close()
        self.env.shutdown()
        shutil.rmtree(self.env.path)

    def _insert_crashdump(self, **kw):
        """Helper for inserting a ticket into the database"""
        crash = CrashDump(env=self.env)
        for k, v in kw.items():
            crash[k] = v
        crash.insert()
        return crash

    def test_new_crash(self):
        crash = CrashDump(env=self.env)
        crash.insert()
        self.assertIsNotNone(crash)
        self.assertIsNone(crash.uuid)
        self.assertIsNotNone(crash.id)

    def test_existing_crash(self):

        crash = CrashDump(env=self.env, uuid='67cbc89f-1001-4691-a2c2-c1bb40aac806', must_exist=False)
        crash.insert()
        self.assertIsNotNone(crash.uuid)
        self.assertEqual(crash.uuid, '67cbc89f-1001-4691-a2c2-c1bb40aac806')

        crash2 = CrashDump(id=crash.id, env=self.env)
        self.assertIsNotNone(crash2.uuid)

        self.assertEqual(crash.id, crash2.id)
        self.assertEqual(crash.uuid, crash2.uuid)

        crash3 = CrashDump(uuid=crash.uuid, env=self.env)

        self.assertEqual(crash.uuid, crash3.uuid)
        self.assertEqual(crash.id, crash3.id)


        crash4 = CrashDump(id='      #%i           ' % crash.id, env=self.env)

        self.assertEqual(crash.uuid, crash4.uuid)
        self.assertEqual(crash.id, crash4.id)

    def test_non_existing_crash(self):
        self.assertRaises(ResourceNotFound,
                          CrashDump, id='#1742', env=self.env)

        self.assertRaises(ResourceNotFound,
                          CrashDump, id='42', env=self.env)



def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(CrashDumpModelTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')

