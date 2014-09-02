import re
import copy

from trac.core import *
from trac.env import IEnvironmentSetupParticipant
from trac.db import DatabaseManager
from trac.perm import IPermissionRequestor, PermissionCache, PermissionSystem
from trac.ticket.api import ITicketChangeListener
from trac.util.compat import set, sorted
from trac.util.translation import _, N_, gettext
from trac.cache import cached

import db_default
from trac.ticket.model import Ticket
from .links import CrashDumpTicketLinks

class CrashDumpSystem(Component):
    """Central functionality for the CrashDump plugin."""

    implements(IEnvironmentSetupParticipant, ITicketChangeListener)
    
    NUMBERS_RE = re.compile(r'\d+', re.U)
    
    # IEnvironmentSetupParticipant methods

    restrict_owner = True

    def environment_created(self):
        self._upgrade_db(self.env.get_db_cnx())

    def environment_needs_upgrade(self, db):
        schema_ver = db_default.get_current_schema_version(db)
        if schema_ver == db_default.schema_version:
            return False
        if schema_ver > db_default.schema_version:
            raise TracError(_("""A newer plugin version has been installed
                              before, but downgrading is unsupported."""))
        self.log.info("%s db schema version is %d, should be %d"
                      % (__name__, schema_ver, db_default.schema_version))
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
                except (AttributeError, ImportError) as e:
                    self.log.info("No upgrade module for version %(num)i (%(version)s.py) in %(module)s" % { 'num':i, 'version':name, 'module':__name__ + '.upgrades'})
                    script = None
                if script:
                    script.do_upgrade(self.env, i, cursor)
        cursor.execute("""
            UPDATE system
               SET value=%i
             WHERE name='%s'
            """ % (db_default.schema_version, db_default.name + '_version'))
        self.log.info("Upgraded %s db schema from version %d to %d"
                      % (db_default.name, schema_ver, db_default.schema_version))
        db.commit()

        custom = self.config['ticket-custom']
        config_dirty = False
        if 'linked_crash' not in custom:
            custom.set('linked_crash', 'text')
            custom.set('linked_crash.label', 'Linked crash')
            config_dirty = True
        if config_dirty:
            self.config.save()

    def get_custom_fields(self):
        return copy.deepcopy(self.custom_fields)

    @cached
    def custom_fields(self, db):
        """Return the list of custom crash fields available for crashes."""
        fields = []
        return fields

    def get_crash_field_labels(self):
        """Produce a (name,label) mapping from `get_crash_fields`."""
        labels = dict((f['name'], f['label'])
                      for f in self.get_crash_fields())
        labels['attachment'] = _("Attachment")
        return labels

    def get_crash_fields(self):
        """Returns list of fields available for tickets.

        Each field is a dict with at least the 'name', 'label' (localized)
        and 'type' keys.
        It may in addition contain the 'custom' key, the 'optional' and the
        'options' keys. When present 'custom' and 'optional' are always `True`.
        """
        fields = copy.deepcopy(self.fields)
        label = 'label' # workaround gettext extraction bug
        for f in fields:
            f[label] = gettext(f[label])
        return fields

    def reset_crash_fields(self):
        """Invalidate crash field cache."""
        del self.fields

    @cached
    def fields(self, db):
        """Return the list of fields available for crashes."""
        from trac.ticket import model

        fields = []

        # Basic text fields
        fields.append({'name': 'summary', 'type': 'text',
                       'label': N_('Summary')})
        fields.append({'name': 'reporter', 'type': 'text',
                       'label': N_('Reporter')})

        # Owner field, by default text but can be changed dynamically
        # into a drop-down depending on configuration (restrict_owner=true)
        field = {'name': 'owner', 'label': N_('Owner')}
        field['type'] = 'text'
        fields.append(field)

        simple_string_fields = [
            ('uuid', N_('Crash identifier') ),
            ('applicationname', N_('Application') ),
            ('applicationfile', N_('Application file') ),
            ('uploadhostname', N_('Upload FQDN') ),
            ('uploadusername', N_('Upload username') ),
            ('crashhostname', N_('Crash FQDN') ),
            ('crashusername', N_('Crash username') ),
            ('productname', N_('Product name') ),
            ('productcodename', N_('Product code name') ),
            ('productversion', N_('Product version') ),
            ('producttargetversion', N_('Product target version') ),
            ('buildtype', N_('Build type') ),
            ('buildpostfix', N_('Build postfix') ),
            ('machinetype', N_('Machine type') ),
            ('systemname', N_('System name') ),
            ('osversion', N_('OS version') ),
            ('osrelease', N_('OS release') ),
            ('osmachine', N_('OS machine') ),
            ('minidumpfile', N_('Minidump file') ),
            ('minidumpreporttextfile', N_('Minidump text report') ),
            ('minidumpreportxmlfile', N_('Minidump XML report') ),
            ('minidumpreporthtmlfile', N_('Minidump HTML report') ),
            ('coredumpfile', N_('Coredump file') ),
            ('coredumpreporttextfile', N_('Coredump text report') ),
            ('coredumpreportxmlfile', N_('Coredump XML report') ),
            ('coredumpreporthtmlfile', N_('Coredump HTML report') ),
            ]
        for (name, label) in simple_string_fields:
            fields.append({'name': name, 'type': 'text', 'label': label})

        # Description
        fields.append({'name': 'description', 'type': 'textarea',
                       'label': N_('Description')})

        # Default select and radio fields
        selects = [('type', N_('Type'), model.Type),
                   ('status', N_('Status'), model.Status),
                   ('priority', N_('Priority'), model.Priority),
                   ('milestone', N_('Milestone'), model.Milestone),
                   ('component', N_('Component'), model.Component),
                   ('version', N_('Version'), model.Version),
                   ('severity', N_('Severity'), model.Severity),
                   ('resolution', N_('Resolution'), model.Resolution)]
        for name, label, cls in selects:
            options = [val.name for val in cls.select(self.env, db=db)]
            if not options:
                # Fields without possible values are treated as if they didn't
                # exist
                continue
            field = {'name': name, 'type': 'select', 'label': label,
                     'value': getattr(self, 'default_' + name, ''),
                     'options': options}
            if name in ('status', 'resolution'):
                field['type'] = 'radio'
                field['optional'] = True
            elif name in ('milestone', 'version'):
                field['optional'] = True
            fields.append(field)

        # Advanced text fields
        fields.append({'name': 'keywords', 'type': 'text', 'format': 'list',
                       'label': N_('Keywords')})
        fields.append({'name': 'cc', 'type': 'text',  'format': 'list',
                       'label': N_('Cc')})

        # Date/time fields
        fields.append({'name': 'crashtime', 'type': 'time',
                       'label': N_('Crash time')})
        fields.append({'name': 'reporttime', 'type': 'time',
                       'label': N_('Report time')})
        fields.append({'name': 'uploadtime', 'type': 'time',
                       'label': N_('Upload time')})
        fields.append({'name': 'changetime', 'type': 'time',
                       'label': N_('Modified')})
        fields.append({'name': 'closetime', 'type': 'time',
                       'label': N_('Closed')})

        for field in self.get_custom_fields():
            if field['name'] in [f['name'] for f in fields]:
                self.log.warning('Duplicate field name "%s" (ignoring)',
                                 field['name'])
                continue
            if field['name'] in self.reserved_field_names:
                self.log.warning('Field name "%s" is a reserved name '
                                 '(ignoring)', field['name'])
                continue
            if not re.match('^[a-zA-Z][a-zA-Z0-9_]+$', field['name']):
                self.log.warning('Invalid name for custom field: "%s" '
                                 '(ignoring)', field['name'])
                continue
            field['custom'] = True
            fields.append(field)

        return fields

    def eventually_restrict_owner(self, field, crashobj=None):
        """Restrict given owner field to be a list of users having
        the TICKET_MODIFY permission (for the given crashobj)
        """
        if self.restrict_owner:
            field['type'] = 'select'
            possible_owners = []
            for user in PermissionSystem(self.env) \
                    .get_users_with_permission('TICKET_MODIFY'):
                if not crashobj or \
                        'TICKET_MODIFY' in PermissionCache(self.env, user,
                                                           crashobj.resource):
                    possible_owners.append(user)
            possible_owners.sort()
            possible_owners.insert(0, '< default >')
            field['options'] = possible_owners
            field['optional'] = True

    def get_available_actions(self, req, crashobj):
        """Returns a sorted list of available actions"""
        # The list should not have duplicates.
        actions = {}
        #for controller in self.action_controllers:
            #weighted_actions = controller.get_ticket_actions(req, crashobj) or []
            #for weight, action in weighted_actions:
                #if action in actions:
                    #actions[action] = max(actions[action], weight)
                #else:
                    #actions[action] = weight
        all_weighted_actions = [(weight, action) for action, weight in
                                actions.items()]
        return [x[1] for x in sorted(all_weighted_actions, reverse=True)]

    # ITicketChangeListener methods
    def ticket_created(self, tkt):
        self.ticket_changed(tkt, '', tkt['reporter'], {})

    def ticket_changed(self, tkt, comment, author, old_values):
        db = self.env.get_db_cnx()
        links = self._prepare_links(tkt, db)
        links.save(author, comment, tkt.time_changed, db)
        db.commit()

    def ticket_deleted(self, tkt):
        db = self.env.get_db_cnx()

        links = CrashDumpTicketLinks(self.env, tkt, db)
        links.crashes = set()
        links.save('trac', 'Ticket #%s deleted'%tkt.id, when=None, db=db)

        db.commit()

    # Internal methods
    def _prepare_links(self, tkt, db):
        links = CrashDumpTicketLinks(self.env, tkt, db)
        links.crashes = set(int(n) for n in self.NUMBERS_RE.findall(tkt['linked_crash'] or ''))
        print('links for %i: %s' % (tkt.id, str(links.crashes)))
        return links
