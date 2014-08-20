# Created by Noah Kantrowitz on 2007-07-04.
# Copyright (c) 2007 Noah Kantrowitz. All rights reserved.
import copy
from datetime import datetime

from trac.ticket.model import Ticket
from trac.util.compat import set, sorted
from trac.util.datefmt import utc, to_utimestamp
from uuid import UUID

class CrashDump(object):

    __db_fields = [
        'uuid',
        'crashtime',
        'reporttime',
        'uploadtime',
        'applicationname',
        'applicationfile',
        'uploadhostname',
        'uploadusername',
        'crashhostname',
        'crashusername',
        'productname',
        'productcodename',
        'productversion',
        'producttargetversion',
        'buildtype',
        'buildpostfix',
        'machinetype',
        'systemname',
        'osversion',
        'osrelease',
        'osmachine',
        'minidumpfile',
        'minidumpreporttextfile',
        'minidumpreportxmlfile',
        'minidumpreporthtmlfile',
        'coredumpfile',
        'coredumpreporttextfile',
        'coredumpreportxmlfile',
        'coredumpreporthtmlfile',
        ]

    def __init__(self, uuid, env=None):
        for f in CrashDump.__db_fields:
            setattr(self, f, None)
        self.id = None
        self.uuid = uuid
        self.env = env

    def submit(self):
        ret = None
        with self.env.db_transaction as db:
            cursor = db.cursor()
            fielddata = []
            for f in CrashDump.__db_fields:
                v = getattr(self, f)
                if v is None:
                    fielddata.append('NULL')
                elif isinstance(v, str):
                    fielddata.append('\'' + v + '\'')
                elif isinstance(v, UUID):
                    fielddata.append('\'' + str(v) + '\'')
                elif isinstance(v, bool):
                    fielddata.append( '1' if v else '0')
                elif isinstance(v, int) or isinstance(v, float):
                    fielddata.append(str(v))
                else:
                    fielddata.append('\'' + v + '\'')
            sql = "INSERT INTO crashdump (%s) VALUES (%s)" % \
                (','.join(CrashDump.__db_fields), ','.join(fielddata) )
            self.env.log.info("insert crashdump: %s", sql)
            cursor.execute(sql)
            crashid_id = db.get_last_id(cursor, 'crashdump')
            self.env.log.info("New crashdump: %s id=%i", self.uuid, crashid_id)
            ret = crashid_id
        return ret

    def find_by_uuid(self):
        ret = None
        with self.env.db_transaction as db:
            cursor = db.cursor()
            sql = "SELECT id FROM crashdump WHERE uuid='%s'" % self.uuid
            cursor.execute(sql)
            for crashid in cursor:
                ret = crashid
        return ret

    def does_exist(self):
        ret = False
        with self.env.db_transaction as db:
            cursor = db.cursor()
            sql = "SELECT id FROM crashdump WHERE uuid='%s'" % self.uuid
            cursor.execute(sql)
            for crashid in cursor:
                ret = True
        return ret

    def query(self):
        return []
