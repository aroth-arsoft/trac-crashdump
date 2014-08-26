from trac.resource import Resource, ResourceNotFound
from trac.util.translation import _
from trac.util.datefmt import from_utimestamp, to_utimestamp, utc, utcmax
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

    def __init__(self, id=None, uuid=None, env=None, version=None, must_exist=True):
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
            self._fetch_crash_by_id(int(id), must_exist=must_exist)
        else:
            self._init_defaults()
        self._old = {}

    exists = property(lambda self: self.id is not None)

    def __getitem__(self, name):
        return self.values.get(name)

    def __setitem__(self, name, value):
        """Log crash modifications so the table crashdump_change can be updated
        """
        if name in self.values and self.values[name] == value:
            return
        if name not in self._old: # Changed field
            self._old[name] = self.values.get(name)
        elif self._old[name] == value: # Change of field reverted
            del self._old[name]
        if value:
            if isinstance(value, list):
                raise TracError(_("Multi-values fields not supported yet"))
            field = [field for field in self.fields if field['name'] == name]
            if field and field[0].get('type') != 'textarea':
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

    def _load_from_record(self, record):
        for i, field in enumerate(self.std_fields):
            if i == 0:
                self.id = row[0]
            else:
                value = row[i]
                if field in self.time_fields:
                    self.values[field] = from_utimestamp(value)
                elif value is None:
                    self.values[field] = empty
                else:
                    self.values[field] = value

    def _fetch_crash_by_id(self, id, must_exist=True):
        row = None
        if self.uuid_is_valid(id):
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
            print("SELECT id,%s FROM crashdump WHERE uuid=%%s" %
                                         ','.join(self.std_fields))
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
