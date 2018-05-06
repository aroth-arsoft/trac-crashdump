#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import shutil
import tempfile
import unittest

from trac.core import Component, implements
from trac.db.api import DatabaseManager
from trac.perm import PermissionSystem
from trac.ticket.model import Ticket
#from trac.db.schema import Table, Column, Index
from trac.test import EnvironmentStub, MockRequest
from trac.resource import ResourceNotFound
from trac.web.api import HTTPBadRequest, RequestDone

from crashdump.web_ui import CrashDumpModule
from crashdump.model import CrashDump
from crashdump.links import CrashDumpTicketLinks

class CrashDumpWebUiTestCase(unittest.TestCase):
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

    def _create_ticket_with_change(self, old_props, new_props,
                                   author='anonymous'):
        """Create a ticket with `old_props` and apply properties
        in `new_props`.
        """
        t = Ticket(self.env)
        t.populate(old_props)
        t.insert()
        comment = new_props.pop('comment', None)
        t.populate(new_props)
        t.save_changes(author, comment=comment)
        return t

    def _insert_ticket(self, **kw):
        """Helper for inserting a ticket into the database"""
        ticket = Ticket(self.env)
        for k, v in kw.items():
            ticket[k] = v
        ticket.insert()
        with self.env.db_transaction as db:
            links = CrashDumpTicketLinks(self.env, ticket, db=db)
            if 'linked_crashes' in kw:
                links.crashes = kw['linked_crashes']
                links.save(author='anonymous', db=db)
            db.commit()
        return ticket, links

    def _insert_crashdump(self, **kw):
        """Helper for inserting a ticket into the database"""
        crash = CrashDump(env=self.env)
        for k, v in kw.items():
            crash[k] = v
        crash.insert()
        return crash

    def test_no_crash_id(self):
        req = MockRequest(self.env, authname='user', method='GET',
                          args={'without-crashid':'42'})
        self.assertRaises(ResourceNotFound,
                          self.crashdump_module.process_request, req)

    def test_non_existing_crash_id(self):
        req = MockRequest(self.env, authname='user', method='GET',
                          args={'crashid':'42'})
        self.assertRaises(ResourceNotFound,
                          self.crashdump_module.process_request, req)

    def test_action_view_crash(self):
        """Full name of reporter and owner are used in ticket properties."""
        self.env.insert_users([('user1', 'User One', ''),
                               ('user2', 'User Two', '')])
        crash = self._insert_crashdump(reporter='user1', owner='user2')
        req = MockRequest(self.env, authname='user', method='GET',
                          args={'crashid':crash.id, 'action': 'view'})
        tmpl, data, extra = self.crashdump_module.process_request(req)

        self.assertEqual(tmpl, 'report.html')


    def test_action_view_crash_child(self):
        """Full name of reporter and owner are used in ticket properties."""
        self.env.insert_users([('user1', 'User One', ''),
                               ('user2', 'User Two', '')])
        crash = self._insert_crashdump(reporter='user1', owner='user2')

        for param in ['sysinfo', 'sysinfo_ex', 'fast_protect_version_info', 'exception', 'memory_regions', 'modules', 'threads', 'memory_block', 'stackdump']:
            req = MockRequest(self.env, authname='user', method='GET',
                            args={'crashid':crash.id, 'action': 'view', 'params': [param] })
            tmpl, data, extra = self.crashdump_module.process_request(req)

            self.assertEqual(tmpl, param + '.html')

    def test_action_view_ticket_linked_crash(self):
        """Full name of reporter and owner are used in ticket properties."""
        self.env.insert_users([('user1', 'User One', ''),
                               ('user2', 'User Two', '')])
        crash = self._insert_crashdump(reporter='user1', owner='user2')
        tkt, tkt_links = self._insert_ticket(reporter='user1', owner='user2', linked_crashes='%i' % crash.id)

        req = MockRequest(self.env, authname='user', method='GET',
                          args={'crashid':crash.id, 'action': 'view'})
        tmpl, data, extra = self.crashdump_module.process_request(req)

        self.assertEqual(tmpl, 'report.html')
        self.assertEqual(crash.linked_tickets, [tkt.id])

    def test_action_view_ticket_linked_crash_bad_crashid(self):
        """Full name of reporter and owner are used in ticket properties."""
        self.env.insert_users([('user1', 'User One', ''),
                               ('user2', 'User Two', '')])
        tkt, tkt_links = self._insert_ticket(reporter='user1', owner='user2')
        crash = self._insert_crashdump(reporter='user1', owner='user2', linked_crashes='Bad#%i' % tkt.id)

        req = MockRequest(self.env, authname='user', method='GET',
                          args={'crashid':crash.id, 'action': 'view'})
        tmpl, data, extra = self.crashdump_module.process_request(req)

        self.assertEqual(tmpl, 'report.html')
        self.assertEqual(crash.linked_tickets, [])


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(CrashDumpWebUiTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')

