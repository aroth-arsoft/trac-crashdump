# Created by Noah Kantrowitz on 2007-07-04.
# Copyright (c) 2007 Noah Kantrowitz. All rights reserved.
import copy
from datetime import datetime

from trac.ticket.model import Ticket
from trac.util.compat import set, sorted
from trac.util.datefmt import utc, to_utimestamp
from uuid import UUID

class CrashDumpState(object):
    __db_fields = [
        'name',
        'description'
        ]
    def __init__(self, id=None, env=None):
        for f in CrashDumpState.__db_fields:
            setattr(self, f, None)
        self.id = None
        self.env = env

    @staticmethod
    def by_name(self, env, name):
        ret = None
        with self.env.db_transaction as db:
            cursor = db.cursor()
            sql = "SELECT id FROM crashdump_state WHERE name='%s'" % name
            cursor.execute(sql)
            for stateid in cursor:
                ret = CrashDumpState(stateid[0], env=env)
        return ret


class CrashDump(object):

    __db_fields = [
        'uuid',
        'state',
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
        self.status = None
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

    def update(self):
        ret = False
        with self.env.db_transaction as db:
            cursor = db.cursor()
            update_fields = []
            for f in CrashDump.__db_fields:
                v = getattr(self, f)
                if v is None:
                    continue
                elif isinstance(v, str):
                    update_fields.append(f + '=' + '\'' + v + '\'')
                elif isinstance(v, UUID):
                    update_fields.append(f + '=' + '\'' + str(v) + '\'')
                elif isinstance(v, bool):
                    update_fields.append(f + '=' + '1' if v else '0')
                elif isinstance(v, int) or isinstance(v, float):
                    update_fields.append(f + '=' + str(v))
                else:
                    update_fields.append(f + '=' + '\'' + v + '\'')

            sql = "UPDATE crashdump SET %s WHERE id=%i" % \
                (','.join(update_fields), self.id )
            self.env.log.info("update crashdump: %s", sql)
            cursor.execute(sql)
            self.env.log.info("update crashdump: %s id=%i", self.uuid, self.id)
            ret = True
        return ret

    @staticmethod
    def find_by_uuid(env, uuid):
        ret = None
        with env.db_transaction as db:
            cursor = db.cursor()
            sql = "SELECT id,%s FROM crashdump WHERE uuid='%s'" % \
                (','.join(CrashDump.__db_fields), str(uuid))
            cursor.execute(sql)
            for record in cursor:
                ret = CrashDump(None, env)
                idx = 0
                ret.id = record[idx]
                idx += 1
                for f in CrashDump.__db_fields:
                    setattr(ret, f, record[idx])
                    idx += 1
                break
        return ret

    @staticmethod
    def find_by_id(env, id):
        ret = None
        with env.db_transaction as db:
            cursor = db.cursor()
            sql = "SELECT id,%s FROM crashdump WHERE id='%i'" % \
                (','.join(CrashDump.__db_fields), id)
            cursor.execute(sql)
            for record in cursor:
                ret = CrashDump(None, env)
                idx = 0
                ret.id = record[idx]
                idx += 1
                for f in CrashDump.__db_fields:
                    setattr(ret, f, record[idx])
                    idx += 1
                break
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

    @staticmethod
    def query(env=None, filter=None):
        ret = []
        where_expr = '1' if filter is None else filter
        with env.db_transaction as db:
            cursor = db.cursor()
            sql = "SELECT id,%s FROM crashdump WHERE %s" % \
                (','.join(CrashDump.__db_fields), where_expr)
            cursor.execute(sql)
            for record in cursor:
                item = CrashDump(None, env)
                idx = 0
                item.id = record[idx]
                idx += 1
                for f in CrashDump.__db_fields:
                    setattr(item, f, record[idx])
                    idx += 1
                ret.append(item)
        return ret
