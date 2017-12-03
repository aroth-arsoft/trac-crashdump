#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import re
import copy
from trac.resource import Resource, ResourceNotFound
from trac.util.translation import _
from trac.util.datefmt import from_utimestamp, to_utimestamp, utc, utcmax
from trac.util.compat import set, sorted
from trac.util.text import empty
from trac.ticket.model import Ticket

from .api import CrashDumpSystem
from uuid import UUID
from datetime import datetime

def _fixup_cc_list(cc_value):
    """Fix up cc list separators and remove duplicates."""
    cclist = []
    for cc in re.split(r'[;,\s]+', cc_value):
        if cc and cc not in cclist:
            cclist.append(cc)
    return ', '.join(cclist)

class CrashDump(object):

    # Fields that must not be modified directly by the user
    protected_fields = ('resolution', 'status', 'time', 'changetime')

    __db_fields = [
        'uuid',
        'type',
        'status',
        'priority',
        'milestone',
        'component',
        'severity',
        'summary',
        'description',
        'keywords',
        'owner',
        'reporter',
        'cc',
        'crashtime',
        'reporttime',
        'uploadtime',
        'changetime',
        'closetime',
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

    @staticmethod
    def id_is_valid(num):
        return 0 < int(num) <= 1L << 31

    @staticmethod
    def uuid_is_valid(uuid):
        if isinstance(uuid, UUID):
            return True
        else:
            try:
                UUID(uuid)
                return True
            except:
                return False

    @staticmethod
    def get_crash_id(s, default_id=None):
        if isinstance(s, str) or isinstance(s, unicode):
            s = s.strip()
            if s[0] == '#':
                s = s[1:]
            try:
                return int(s)
            except ValueError:
                return default_id
        elif isinstance(s, int):
            return s
        else:
            return default_id

    def __init__(self, id=None, uuid=None, env=None, version=None, must_exist=True, row=None):
        self.id = None
        self.status = None
        self.uuid = uuid
        self.env = env
        self._changes = None
        self.resource = Resource('crash', uuid, version)
        self.fields = CrashDumpSystem(self.env).get_crash_fields()
        self.std_fields, self.custom_fields, self.time_fields = [], [], []
        for f in self.fields:
            if f.get('custom'):
                self.custom_fields.append(f['name'])
            else:
                self.std_fields.append(f['name'])
            if f['type'] == 'time':
                self.time_fields.append(f['name'])
        self.values = {}
        if uuid is not None:
            self._fetch_crash_by_uuid(uuid, must_exist=must_exist)
        elif id is not None:
            crash_id = CrashDump.get_crash_id(id)
            if crash_id is None:
                raise ResourceNotFound(_("Crash %(id)s does not exist.",
                                        id=id), _("Invalid crash identifier"))
            self._fetch_crash_by_id(crash_id, must_exist=must_exist)
        elif row is not None:
            self._load_from_record(row)
        else:
            self._init_defaults()
        self._old = {}

    def _init_defaults(self):
        for field in self.fields:
            default = None
            if field['name'] in self.protected_fields:
                # Ignore for new - only change through workflow
                pass
            elif not field.get('custom'):
                default = self.env.config.get('ticket',
                                              'default_' + field['name'])
            else:
                default = self._custom_field_default(field)
            if default:
                self.values.setdefault(field['name'], default)

    exists = property(lambda self: self.id is not None)

    def __getitem__(self, name):
        return self.values.get(name)

    def __setitem__(self, name, value):
        """Log crash modifications so the table crashdump_change can be updated
        """
        if name in self.values and self.values[name] == value:
            return
        if name not in self._old: # Changed field
            if name in self.time_fields:
                self._old[name] = to_utimestamp(self.values.get(name))
            else:
                self._old[name] = self.values.get(name)
        elif self._old[name] == value: # Change of field reverted
            del self._old[name]
        if value:
            if isinstance(value, list):
                if len(value) == 1:
                    value = value[0]
                else:
                    raise ValueError(_("Multi-values field %s not supported yet: %s") % (name, value))
            field = [field for field in self.fields if field['name'] == name]
            if field:
                field_type = field[0].get('type')
                if field_type == 'time':
                    pass
                elif field_type != 'textarea':
                    value = value.strip()

        self.values[name] = value

    def get_value_or_default(self, name):
        """Return the value of a field or the default value if it is undefined
        """
        try:
            value = self.values[name]
            return value if value is not empty else self.get_default(name)
        except KeyError:
            pass

    def get_default(self, name):
        """Return the default value of a field."""
        field = [field for field in self.fields if field['name'] == name]
        if field:
            return field[0].get('value', '')

    def populate(self, values):
        """Populate the ticket with 'suitable' values from a dictionary"""
        field_names = [f['name'] for f in self.fields]
        for name in [name for name in values.keys() if name in field_names]:
            self[name] = values.get(name, '')

        # We have to do an extra trick to catch unchecked checkboxes
        for name in [name for name in values.keys() if name[9:] in field_names
                     and name.startswith('checkbox_')]:
            if name[9:] not in values:
                self[name[9:]] = '0'

    def _load_from_record(self, row):
        for i, field in enumerate(self.std_fields):
            #print('_load_from_record %i, %s=%s' % (i, field, row[i+1]))
            if i == 0:
                self.id = row[0]
            elif field == 'uuid':
                self.uuid = row[i + 1]
            else:
                value = row[i + 1]
                if value is None:
                    self.values[field] = empty
                elif field in self.time_fields:
                    self.values[field] = from_utimestamp(value)
                else:
                    self.values[field] = value

    def _fetch_crash_by_id(self, id, must_exist=True):
        row = None
        if self.id_is_valid(id):
            # Fetch the standard crashdump fields
            for row in self.env.db_query("SELECT id,%s FROM crashdump WHERE id=%%s" %
                                         ','.join(self.std_fields), (id,)):
                break
        if not row and must_exist:
            raise ResourceNotFound(_("Crash %(id)s does not exist.",
                                     id=id), _("Invalid crash identifier"))

        if row:
            self.id = id
            self._load_from_record(row)

    def _fetch_crash_by_uuid(self, uuid, must_exist=True):
        row = None
        if self.uuid_is_valid(uuid):
            # Fetch the standard crashdump fields
            for row in self.env.db_query("SELECT id,%s FROM crashdump WHERE uuid=%%s" %
                                         ','.join(self.std_fields), (str(uuid),)):
                break
        if not row and must_exist:
            raise ResourceNotFound(_("Crash %(uuid)s does not exist.",
                                     uuid=uuid), _("Invalid crash identifier"))

        if row:
            self.uuid = uuid
            self._load_from_record(row)

    def insert(self, when=None, db=None):
        """Add crash to database.

        :since 1.0: the `db` parameter is no longer needed and will be removed
        in version 1.1.1
        """
        assert not self.exists, 'Cannot insert an existing ticket'

        if 'cc' in self.values:
            self['cc'] = _fixup_cc_list(self.values['cc'])

        # Add a timestamp
        if when is None:
            when = datetime.now(utc)
        self.values['uploadtime'] = self.values['changetime'] = when
        self.values['uuid'] = str(self.uuid)

        # The owner field defaults to the component owner
        if self.values.get('owner') == '< default >':
            default_to_owner = ''
            if self.values.get('component'):
                try:
                    component = Component(self.env, self['component'])
                    default_to_owner = component.owner # even if it's empty
                except ResourceNotFound:
                    # No such component exists
                    pass
            # If the current owner is "< default >", we need to set it to
            # _something_ else, even if that something else is blank.
            self['owner'] = default_to_owner

        # Perform type conversions
        values = dict(self.values)
        for field in self.time_fields:
            if field in values:
                values[field] = to_utimestamp(values[field])

        # Insert ticket record
        std_fields = []
        custom_fields = []
        for f in self.fields:
            fname = f['name']
            if fname in self.values:
                if f.get('custom'):
                    custom_fields.append(fname)
                else:
                    std_fields.append(fname)
        with self.env.db_transaction as db:
            cursor = db.cursor()
            cursor.execute("INSERT INTO crashdump (%s) VALUES (%s)"
                           % (','.join(std_fields),
                              ','.join(['%s'] * len(std_fields))),
                           [values[name] for name in std_fields])
            crash_id = db.get_last_id(cursor, 'crashdump')

            # Insert custom fields
            if custom_fields:
                db.executemany(
                    """INSERT INTO crashdump_custom (crash, name, value)
                       VALUES (%s, %s, %s)
                    """, [(crash_id, c, self[c]) for c in custom_fields])

        self.id = crash_id
        self.resource = self.resource(id=crash_id)
        self._old = {}
        return self.id

    def save_changes(self, author=None, comment=None, when=None, db=None,
                     cnum='', replyto=None):
        """
        Store ticket changes in the database. The ticket must already exist in
        the database.  Returns False if there were no changes to save, True
        otherwise.

        :since 1.0: the `db` parameter is no longer needed and will be removed
        in version 1.1.1
        :since 1.0: the `cnum` parameter is deprecated, and threading should
        be controlled with the `replyto` argument
        """
        assert self.exists, "Cannot update a new crash dump"

        if 'cc' in self.values:
            self['cc'] = _fixup_cc_list(self.values['cc'])

        # Perform type conversions
        for field in self.time_fields:
            if field in self.values:
                self.values[field] = to_utimestamp(self.values[field])

        props_unchanged = all(self.values.get(k) == v
                              for k, v in self._old.iteritems())
        if (not comment or not comment.strip()) and props_unchanged:
            return False # Not modified

        if when is None:
            when = datetime.now(utc)
        when_ts = to_utimestamp(when)

        if 'component' in self.values:
            # If the component is changed on a 'new' ticket
            # then owner field is updated accordingly. (#623).
            if self.values.get('status') == 'new' \
                    and 'component' in self._old \
                    and 'owner' not in self._old:
                try:
                    old_comp = Component(self.env, self._old['component'])
                    old_owner = old_comp.owner or ''
                    current_owner = self.values.get('owner') or ''
                    if old_owner == current_owner:
                        new_comp = Component(self.env, self['component'])
                        if new_comp.owner:
                            self['owner'] = new_comp.owner
                except TracError:
                    # If the old component has been removed from the database
                    # we just leave the owner as is.
                    pass

        with self.env.db_transaction as db:
            db("UPDATE crashdump SET changetime=%s WHERE id=%s",
               (when_ts, self.id))

            # find cnum if it isn't provided
            if not cnum:
                num = 0
                for ts, old in db("""
                        SELECT DISTINCT tc1.time, COALESCE(tc2.oldvalue,'')
                        FROM crashdump_change AS tc1
                        LEFT OUTER JOIN crashdump_change AS tc2
                        ON tc2.crash=%s AND tc2.time=tc1.time
                           AND tc2.field='comment'
                        WHERE tc1.crash=%s ORDER BY tc1.time DESC
                        """, (self.id, self.id)):
                    # Use oldvalue if available, else count edits
                    try:
                        num += int(str(old).rsplit('.', 1)[-1])
                        break
                    except ValueError:
                        num += 1
                cnum = str(num + 1)
                if replyto:
                    cnum = '%s.%s' % (replyto, cnum)

            # store fields
            for name in self._old.keys():
                if name in self.custom_fields:
                    for row in db("""SELECT * FROM crash_custom
                                     WHERE crash=%s and name=%s
                                     """, (self.id, name)):
                        db("""UPDATE crash_custom SET value=%s
                              WHERE crash=%s AND name=%s
                              """, (self[name], self.id, name))
                        break
                    else:
                        db("""INSERT INTO crash_custom (crash,name,value)
                              VALUES(%s,%s,%s)
                              """, (self.id, name, self[name]))
                else:
                    db("UPDATE crashdump SET %s=%%s WHERE id=%%s"
                       % name, (self[name], self.id))
                db("""INSERT INTO crashdump_change
                        (crash,time,author,field,oldvalue,newvalue)
                      VALUES (%s, %s, %s, %s, %s, %s)
                      """, (self.id, when_ts, author, name, self._old[name],
                            self[name]))

            # always save comment, even if empty
            # (numbering support for timeline)
            db("""INSERT INTO crashdump_change
                    (crash,time,author,field,oldvalue,newvalue)
                  VALUES (%s,%s,%s,'comment',%s,%s)
                  """, (self.id, when_ts, author, cnum, comment))

        old_values = self._old
        self._old = {}
        self.values['changetime'] = when

        return int(cnum.rsplit('.', 1)[-1])

    def get_changelog(self, when=None, db=None):
        """Return the changelog as a list of tuples of the form
        (time, author, field, oldvalue, newvalue, permanent).

        While the other tuple elements are quite self-explanatory,
        the `permanent` flag is used to distinguish collateral changes
        that are not yet immutable (like attachments, currently).

        :since 1.0: the `db` parameter is no longer needed and will be removed
        in version 1.1.1
        """
        sid = str(self.id)
        when_ts = to_utimestamp(when)
        if when_ts:
            sql = """
                SELECT time, author, field, oldvalue, newvalue, 1 AS permanent
                FROM crashdump_change WHERE crash=%s AND time=%s
                  UNION
                SELECT time, author, 'attachment', null, filename,
                  0 AS permanent
                FROM attachment WHERE type='crash' AND id=%s AND time=%s
                  UNION
                SELECT time, author, 'comment', null, description,
                  0 AS permanent
                FROM attachment WHERE type='crash' AND id=%s AND time=%s
                ORDER BY time,permanent,author
                """
            args = (self.id, when_ts, sid, when_ts, sid, when_ts)
        else:
            sql = """
                SELECT time, author, field, oldvalue, newvalue, 1 AS permanent
                FROM crashdump_change WHERE crash=%s
                  UNION
                SELECT time, author, 'attachment', null, filename,
                  0 AS permanent
                FROM attachment WHERE type='crash' AND id=%s
                  UNION
                SELECT time, author, 'comment', null, description,
                  0 AS permanent
                FROM attachment WHERE type='crash' AND id=%s
                ORDER BY time,permanent,author
                """
            args = (self.id, sid, sid)
        return [(from_utimestamp(t), author, field, oldvalue or '',
                 newvalue or '', permanent)
                for t, author, field, oldvalue, newvalue, permanent in
                self.env.db_query(sql, args)]

    @staticmethod
    def query(env, status=None, threshold=None):
        ret = []
        where_clause = ''
        if status is not None:
            if status == 'active':
                where_clause = ' WHERE status<>\'closed\''
            elif status == 'closed':
                where_clause = ' WHERE status=\'closed\''
            elif status == 'new':
                where_clause = ' WHERE status=\'new\''
            else:
                where_clause = ' WHERE status=\'%s\'' % status

        if threshold is not None:
            (threshold_column, threshold_time) = threshold
            if where_clause:
                where_clause += ' AND %s < %i' % (threshold_column, to_utimestamp(threshold_time))
            else:
                where_clause = ' WHERE %s < %i' % (threshold_column, to_utimestamp(threshold_time))

        fields = CrashDumpSystem(env).get_crash_fields()
        std_fields = []
        for f in fields:
            if f.get('custom'):
                pass
            else:
                std_fields.append(f['name'])

        # Fetch the standard crashdump fields
        for row in env.db_query("SELECT id,%s FROM crashdump %s" % (','.join(std_fields), where_clause)):
            crash = CrashDump(env=env, must_exist=True, row=row)
            ret.append(crash)
        return ret

    @staticmethod
    def find_by_uuid(env, uuid):
        ret = CrashDump(env=env, uuid=uuid, must_exist=False)
        return ret if ret.id is not None else None

    @staticmethod
    def find_by_id(env, id):
        ret = CrashDump(env=env, id=id, must_exist=False)
        return ret if ret.id is not None else None

    def does_exist(self):
        ret = False
        with self.env.db_transaction as db:
            cursor = db.cursor()
            sql = "SELECT id FROM crashdump WHERE uuid='%s'" % self.uuid
            cursor.execute(sql)
            for crashid in cursor:
                ret = True
        return ret

    @property
    def changes(self):
        if self._changes is None:
            self._changes = []
        return self._changes

    @property
    def linked_tickets(self):
        ret = []
        with self.env.db_transaction as db:
            cursor = db.cursor()
            sql = "SELECT ticket FROM crashdump_ticket WHERE crash='%s'" % self.id
            cursor.execute(sql)
            for ticketid, in cursor:
                ret.append(int(ticketid))
        return ret

    @staticmethod
    def query_old_data(env, threshold, column='crashtime'):
        return CrashDump.query(env=env, threshold=(column, threshold))

    @staticmethod
    def purge_old_data(env, threshold, column='crashtime'):
        _crash_file_fields = [
                'minidumpfile',
                'minidumpreporttextfile',
                'minidumpreportxmlfile',
                'minidumpreporthtmlfile',
                'coredumpfile',
                'coredumpreporttextfile',
                'coredumpreportxmlfile',
                'coredumpreporthtmlfile',
            ]
        dumpdata_dir = os.path.join(env.path, self.dumpdata_dir)
        crashes = CrashDump.query(env=env, threshold=(column, threshold))
        for crash in crashes:
            crash_dir = os.path.join(dumpdata_dir, crash.uuid)
            for field in _crash_file_fields:
                if crash[field]:
                    crash_file = os.path.join(crash_dir, crash[field])
                    if os.path.exists(crash_file):
                        os.remove(crash_file)
            if os.path.isdir(crash_dir):
                import shutil
                shutil.rmtree(crash_dir)



class CrashDumpStackFrame(object):

    __db_fields = [
        'crash',
        'threadid',
        'frameno',
        'module',
        'function',
        'funcoff',
        'source',
        'line',
        'lineoff',
        ]

    def __init__(self, crashid=None, threadid=None, frameno=None, env=None, version=None):
        self.crashid = crashid
        self.threadid = threadid
        self.frameno = frameno
        self.env = env
        self.values = {}
        self.exists = False
        if self.crashid is not None:
            self.values['crash'] = self.crashid
        if self.threadid is not None:
            self.values['threadid'] = self.threadid
        if self.frameno is not None:
            self.values['frameno'] = self.frameno

    def __getitem__(self, name):
        return self.values.get(name)

    def __setitem__(self, name, value):
        self.values[name] = value

    def insert(self, when=None, db=None):
        """Add crash stack frame to database.

        :since 1.0: the `db` parameter is no longer needed and will be removed
        in version 1.1.1
        """
        assert not self.exists, 'Cannot insert an existing stack frame'

        # Insert stack frame record
        std_fields = []
        for fname in self.__db_fields:
            if fname in self.values:
                std_fields.append(fname)
        with self.env.db_transaction as db:
            cursor = db.cursor()
            cursor.execute("INSERT INTO crashdump_stack (%s) VALUES (%s)"
                           % (','.join(std_fields),
                              ','.join(['%s'] * len(std_fields))),
                           [self.values[name] for name in std_fields])
            crash_id = db.get_last_id(cursor, 'crashdump')
        return (self.crashid, self.threadid, self.frameno)
