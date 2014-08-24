# Created by Noah Kantrowitz on 2007-07-04.
# Copyright (c) 2007 Noah Kantrowitz. All rights reserved.
import re

from trac.core import *
from trac.env import IEnvironmentSetupParticipant
from trac.db import DatabaseManager
from trac.util.compat import set, sorted

import db_default
from .model import CrashDump
from trac.ticket.model import Ticket

class CrashDumpSystem(Component):
    """Central functionality for the MasterTickets plugin."""

    implements(IEnvironmentSetupParticipant)
    
    NUMBERS_RE = re.compile(r'\d+', re.U)
    
    # IEnvironmentSetupParticipant methods

    def environment_created(self):
        self._upgrade_db(self.env.get_db_cnx())

    def environment_needs_upgrade(self, db):
        schema_ver = db_default.get_current_schema_version(db)
        if schema_ver == db_default.schema_version:
            return False
        if schema_ver > db_default.schema_version:
            raise TracError(_("""A newer plugin version has been installed
                              before, but downgrading is unsupported."""))
        self.log.info("TracAnnouncer db schema version is %d, should be %d"
                      % (schema_ver, db_default.schema_version))
        return True

    def upgrade_environment(self, db):
        self._upgrade_db(db)

    def _upgrade_db(self, db):
        """Each schema version should have its own upgrade module, named
        upgrades/dbN.py, where 'N' is the version number (int).
        """
        db_mgr = DatabaseManager(self.env)
        schema_ver = db_default.get_current_schema_version(db)

        cursor = db.cursor()
        # Is this a new installation?
        if not schema_ver:
            # Perform a single-step install: Create plugin schema and
            # insert default data into the database.
            connector = db_mgr._get_connector()[0]
            for table in db_default.schema:
                for stmt in connector.to_sql(table):
                    cursor.execute(stmt)
            for table, cols, vals in db_default.get_data(db):
                print("INSERT INTO %s (%s) VALUES (%s)" % (table,
                                   ','.join(cols),
                                   ','.join(['%s' for c in cols])))
                print(vals)
                cursor.executemany("INSERT INTO %s (%s) VALUES (%s)" % (table,
                                   ','.join(cols),
                                   ','.join(['%s' for c in cols])), vals)
        else:
            # Perform incremental upgrades.
            for i in range(schema_ver + 1, db_default.schema_version + 1):
                name  = 'db%i' % i
                try:
                    upgrades = __import__(__name__ + '.upgrades', globals(),
                                          locals(), [name])
                    script = getattr(upgrades, name)
                except AttributeError:
                    raise TracError(_("""
                        No upgrade module for version %(num)i (%(version)s.py) in %(module)s
                        """, num=i, version=name, module=__name__ + '.upgrades'))
                script.do_upgrade(self.env, i, cursor)
        cursor.execute("""
            UPDATE system
               SET value=%i
             WHERE name='%s'
            """ % (db_default.schema_version, db_default.name))
        self.log.info("Upgraded %s db schema from version %d to %d"
                      % (db_default.name, schema_ver, db_default.schema_version))
        db.commit()


