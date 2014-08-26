import subprocess
import re

from pkg_resources import resource_filename
from genshi.core import Markup, START, END, TEXT
from genshi.builder import tag

from trac.core import *
from trac.web.api import IRequestHandler, ITemplateStreamFilter
from trac.web.chrome import (
    Chrome, INavigationContributor, ITemplateProvider,
    add_ctxtnav, add_link, add_notice, add_script, add_script_data,
    add_stylesheet, add_warning, auth_link, prevnext_nav, web_context
)

from trac.ticket.model import Ticket
from trac.ticket.query import Query
from trac.config import Option, BoolOption, ChoiceOption
from trac.resource import ResourceNotFound
from trac.util import to_unicode, as_bool, as_int, get_reporter_id
from trac.util.translation import _ 
from trac.util.html import html, Markup
from trac.util.text import (
    exception_to_unicode, empty, obfuscate_email_address, shorten_line,
    to_unicode
)

from trac.util.datefmt import format_datetime, format_time, from_utimestamp, to_utimestamp
from trac.util.compat import set, sorted, partial
import os.path
import math
from .model import CrashDump
from .xmlreport import XMLReport

def hex_format(number, prefix='0x', width=None):
    if width is None:
        if number > 2**48:
            width = 16
        elif number > 2**40:
            width = 12
        elif number > 2**32:
            width = 10
        elif number > 2**24:
            width = 8
        elif number > 2**16:
            width = 6
        elif number > 2**8:
            width = 4
        else:
            width = 2
    fmt = '%%0%ix' % width
    return prefix + fmt % number

class CrashDumpModule(Component):
    """Provides support for ticket dependencies."""
    
    implements(IRequestHandler, INavigationContributor, ITemplateStreamFilter,
               ITemplateProvider)

    dumpdata_dir = Option('crashdump', 'dumpdata_dir', default='dumpdata',
                      doc='Path to the crash dump data directory.')

    crashdump_fields = set(['_crash'])
    datetime_fields = set(['crashtime', 'uploadtime', 'reporttime'])

    @property
    def must_preserve_newlines(self):
        return True

    # INavigationContributor methods
    def get_active_navigation_item(self, req):
        return 'crashdump'

    def get_navigation_items(self, req):
        yield 'mainnav', 'crashes', tag.a(_('Crashes'), href=req.href.crashdump())

    # ITemplateStreamFilter methods
    def filter_stream(self, req, method, filename, stream, data):
        if not data:
            return stream

        # We try all at the same time to maybe catch also changed or processed templates
        if filename in ["report_view.html", "query_results.html", "ticket.html", "query.html"]:
            # For ticket.html
            if 'fields' in data and isinstance(data['fields'], list):
                for field in data['fields']:
                    for f in self.crashdump_fields:
                        if field['name'] == f and data['ticket'][f]:
                            field['rendered'] = self._link_crash(req, data['ticket'][f])
            # For query_results.html and query.html
            if 'groups' in data and isinstance(data['groups'], list):
                for group, tickets in data['groups']:
                    for ticket in tickets:
                        for f in self.crashdump_fields:
                            if f in ticket:
                                ticket[f] = self._link_crash(req, ticket[f])
            # For report_view.html
            if 'row_groups' in data and isinstance(data['row_groups'], list):
                #self.log.debug('got row_groups %s' % str(data['row_groups']))
                for group, rows in data['row_groups']:
                    for row in rows:
                        if 'cell_groups' in row and isinstance(row['cell_groups'], list):
                            for cells in row['cell_groups']:
                                for cell in cells:
                                    # If the user names column in the report differently (blockedby AS "blocked by") then this will not find it
                                    self.log.debug('got cell header %s' % str(cell.get('header', {}).get('col')))
                                    if cell.get('header', {}).get('col') in self.crashdump_fields:
                                        cell['value'] = self._link_crash(req, cell['value'])
                                        cell['header']['hidden'] = False
                                        cell['header']['title'] = 'Crashdump'
                                        self.log.debug('got crash cell %s' % str(cell))
                                    elif cell.get('header', {}).get('col') in self.datetime_fields:
                                        cell['value'] = self._format_datetime(req, cell['value'])
        return stream

    # ITemplateProvider methods
    def get_htdocs_dirs(self):
        """Return the absolute path of a directory containing additional
        static resources (such as images, style sheets, etc).
        """
        return [('crashdump', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        """Return the absolute path of the directory containing the provided
        ClearSilver templates.
        """
        return [resource_filename(__name__, 'templates')]

    # IRequestHandler methods
    def match_request(self, req):
        if not req.path_info.startswith('/crash'):
            return False

        ret = False
        path_info = req.path_info[6:]
        action = None
        self.log.debug('match_request %s' % path_info)
        match = re.match(r'/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(/.+)?$', path_info)
        if match:
            req.args['crashuuid'], action  = match.groups()
            ret = True
        else:
            match = re.match(r'/([0-9]+)(/.+)?$', path_info)
            if match:
                req.args['crashid'], action  = match.groups()
                ret = True
        if ret:
            req.args['action'] = action[1:] if action else None
        self.log.debug('match_request %s' % str(req.args))
        return ret

    def _prepare_data(self, req, crashobj, absurls=False):
        data = {'object': crashobj,
                'to_utimestamp': to_utimestamp,
                'hex_format':hex_format,
                'context': web_context(req, crashobj.resource, absurls=absurls),
                'preserve_newlines': self.must_preserve_newlines,
                'emtpy': empty}
        xmlfile = self._get_dump_filename(crashobj, 'minidumpreportxmlfile')
        xmlreport = XMLReport(xmlfile)
        for f in xmlreport.fields:
            data[f] = getattr(xmlreport, f)
        return data

    def process_request(self, req):
        path_info = req.path_info[6:]
        if 'crashuuid' in req.args:
            crashobj = CrashDump.find_by_uuid(self.env, req.args['crashuuid'])
        elif 'crashid' in req.args:
            crashobj = CrashDump.find_by_id(self.env, req.args['crashid'])
        else:
            crashobj = None
        version = as_int(req.args.get('version'), None)
        xhr = req.get_header('X-Requested-With') == 'XMLHttpRequest'

        if xhr and 'preview_comment' in req.args:
            context = web_context(req, 'ticket', id, version)
            escape_newlines = self.must_preserve_newlines
            rendered = format_to_html(self.env, context,
                                    req.args.get('edited_comment', ''),
                                    escape_newlines=escape_newlines)
            req.send(rendered.encode('utf-8'))

        #req.perm('crash', id, version).require('TICKET_VIEW')
        action = req.args.get('action', ('history' in req.args and 'history' or
                                        'view'))
        data = self._prepare_data(req, crashobj)

        if action in ('history', 'diff'):
            field = req.args.get('field')
            if field:
                text_fields = [field]
            else:
                text_fields = [field['name'] for field in crashobj.fields if
                            field['type'] == 'textarea']
            if action == 'history':
                return self._render_history(req, crashobj, data, text_fields)
            elif action == 'diff':
                return self._render_diff(req, crashobj, data, text_fields)
        elif action == 'comment-history':
            cnum = int(req.args['cnum'])
            return self._render_comment_history(req, crashobj, data, cnum)
        elif action == 'comment-diff':
            cnum = int(req.args['cnum'])
            return self._render_comment_diff(req, crashobj, data, cnum)
        elif 'preview_comment' in req.args:
            field_changes = {}
            data.update({'action': None,
                        'reassign_owner': req.authname,
                        'resolve_resolution': None,
                        'start_time': crashobj['changetime']})
        elif req.method == 'POST':
            if 'cancel_comment' in req.args:
                req.redirect(req.href('crash', str(crashobj.uuid)))
            elif 'edit_comment' in req.args:
                comment = req.args.get('edited_comment', '')
                cnum = int(req.args['cnum_edit'])
                change = crashobj.get_change(cnum)
                if not (req.authname and req.authname != 'anonymous'
                        and change and change['author'] == req.authname):
                    req.perm(crashobj.resource).require('TICKET_EDIT_COMMENT')
                crashobj.modify_comment(change['date'], req.authname, comment)
                req.redirect(req.href('crash', '%s#comment:%d' % (crashobj.uuid, cnum)))

            valid = True

            # Do any action on the crash?
            actions = TicketSystem(self.env).get_available_actions(req, object)
            if action not in actions:
                valid = False
                add_warning(req, _('The action "%(name)s" is not available.',
                                name=action))

            # We have a bit of a problem.  There are two sources of changes to
            # the ticket: the user, and the workflow.  We need to show all the
            # changes that are proposed, but we need to be able to drop the
            # workflow changes if the user changes the action they want to do
            # from one preview to the next.
            #
            # the _populate() call pulls all the changes from the webpage; but
            # the webpage includes both changes by the user and changes by the
            # workflow... so we aren't able to differentiate them clearly.

            self._populate(req, object) # Apply changes made by the user
            field_changes, problems = self.get_ticket_changes(req, object,
                                                            action)
            if problems:
                valid = False
                for problem in problems:
                    add_warning(req, problem)
                add_warning(req,
                            tag_("Please review your configuration, "
                                "probably starting with %(section)s "
                                "in your %(tracini)s.",
                                section=tag.pre('[ticket]', tag.br(),
                                                'workflow = ...'),
                                tracini=tag.tt('trac.ini')))

            # Apply changes made by the workflow
            self._apply_ticket_changes(object, field_changes)
            # Unconditionally run the validation so that the user gets
            # information any and all problems.  But it's only valid if it
            # validates and there were no problems with the workflow side of
            # things.
            valid = self._validate_ticket(req, object, not valid) and valid
            if 'submit' in req.args:
                if valid:
                    # redirected if successful
                    self._do_save(req, object, action)
                # else fall through in a preview
                req.args['preview'] = True

            # Preview an existing crash (after a Preview or a failed Save)
            start_time = from_utimestamp(long(req.args.get('start_time', 0)))
            data.update({
                'action': action, 'start_time': start_time,
                'reassign_owner': (req.args.get('reassign_choice')
                                or req.authname),
                'resolve_resolution': req.args.get('resolve_choice'),
                'valid': valid
                })
        else: # simply 'View'ing the crash
            field_changes = {}
            data.update({'action': None,
                        'reassign_owner': req.authname,
                        'resolve_resolution': None,
                        # Store a timestamp for detecting "mid air collisions"
                        'start_time': crashobj['changetime']})

        data.update({'comment': req.args.get('comment'),
                    'cnum_edit': req.args.get('cnum_edit'),
                    'edited_comment': req.args.get('edited_comment'),
                    'cnum_hist': req.args.get('cnum_hist'),
                    'cversion': req.args.get('cversion')})

        self._insert_crashdump_data(req, object, data,
                                get_reporter_id(req, 'author'), field_changes)

        if xhr:
            data['preview_mode'] = bool(data['change_preview']['fields'])
            return 'report_preview.html', data, None

        mime = Mimeview(self.env)
        format = req.args.get('format')
        if format:
            # FIXME: mime.send_converted(context, ticket, 'ticket_x') (#3332)
            filename = 'crash%s' % str(crashobj.uuid) if format != 'rss' else None
            mime.send_converted(req, 'trac.ticket.Ticket', object,
                                format, filename=filename)

        def add_ticket_link(css_class, uuid):
            t = ticket.resource(id=uuid, version=None)
            if t:
                add_link(req, css_class, req.href('crash', uuid),
                        _("Crash {%(uuid)s}", uuid=uuid))

        # If the ticket is being shown in the context of a query, add
        # links to help navigate in the query result set
        if 'query_tickets' in req.session:
            crashes = req.session['query_crashes'].split()
            if str(uuid.id) in crashes:
                idx = crashes.index(str(ticket.id))
                if idx > 0:
                    add_ticket_link('first', crashes[0])
                    add_ticket_link('prev', crashes[idx - 1])
                if idx < len(crashes) - 1:
                    add_ticket_link('next', crashes[idx + 1])
                    add_ticket_link('last', crashes[-1])
                add_link(req, 'up', req.session['query_href'])

        add_script_data(req, {'comments_prefs': self._get_prefs(req)})
        add_stylesheet(req, 'crashdump/crashdump.css')
        add_script(req, 'common/js/folding.js')
        Chrome(self.env).add_wiki_toolbars(req)
        Chrome(self.env).add_auto_preview(req)

        # Add registered converters
        for conversion in mime.get_supported_conversions('trac.ticket.Ticket'):
            format = conversion[0]
            conversion_href = get_resource_url(self.env, ticket.resource,
                                            req.href, format=format)
            if format == 'rss':
                conversion_href = auth_link(req, conversion_href)
            add_link(req, 'alternate', conversion_href, conversion[1],
                    conversion[4], format)

        prevnext_nav(req, _("Previous Crash"), _("Next Crash"),
                    _("Back to Query"))
        return 'report.html', data, None

    def _prepare_fields(self, req, crashobj, field_changes=None):
        context = web_context(req, crashobj.resource)
        fields = []
        owner_field = None
        for field in crashobj.fields:
            name = field['name']
            type_ = field['type']

            # enable a link to custom query for all choice fields
            if type_ not in ['text', 'textarea']:
                field['rendered'] = self._query_link(req, name, crashobj[name])

            # per field settings
            if name in ('summary', 'reporter', 'description', 'status',
                        'resolution', 'time', 'changetime'):
                field['skip'] = True
            elif name == 'owner':
                CrashDumpSystem(self.env).eventually_restrict_owner(field, ticket)
                type_ = field['type']
                field['skip'] = True
                if not ticket.exists:
                    field['label'] = _("Owner")
                    if 'TICKET_MODIFY' in req.perm(ticket.resource):
                        field['skip'] = False
                        owner_field = field
            elif name == 'milestone':
                milestones = [Milestone(self.env, opt)
                              for opt in field['options']]
                milestones = [m for m in milestones
                              if 'MILESTONE_VIEW' in req.perm(m.resource)]
                groups = group_milestones(milestones, ticket.exists
                    and 'TICKET_ADMIN' in req.perm(ticket.resource))
                field['options'] = []
                field['optgroups'] = [
                    {'label': label, 'options': [m.name for m in milestones]}
                    for (label, milestones) in groups]
                milestone = Resource('milestone', ticket[name])
                field['rendered'] = render_resource_link(self.env, context,
                                                         milestone, 'compact')
            elif name == 'cc':
                cc_changed = field_changes is not None and 'cc' in field_changes
                if ticket.exists and \
                        'TICKET_EDIT_CC' not in req.perm(ticket.resource):
                    cc = ticket._old.get('cc', ticket['cc'])
                    cc_action, cc_entry, cc_list = self._toggle_cc(req, cc)
                    cc_update = 'cc_update' in req.args \
                                and 'revert_cc' not in req.args
                    field['edit_label'] = {
                            'add': _("Add to Cc"),
                            'remove': _("Remove from Cc"),
                            '': _("Add/Remove from Cc")}[cc_action]
                    field['cc_entry'] = cc_entry or _("<Author field>")
                    field['cc_update'] = cc_update or None
                    if cc_changed:
                        field_changes['cc']['cc_update'] = cc_update
                if cc_changed:
                    # normalize the new CC: list; also remove the
                    # change altogether if there's no real change
                    old_cc_list = self._cc_list(field_changes['cc']['old'])
                    new_cc_list = self._cc_list(field_changes['cc']['new']
                                                .replace(' ', ','))
                    if new_cc_list == old_cc_list:
                        del field_changes['cc']
                    else:
                        field_changes['cc']['new'] = ','.join(new_cc_list)

            # per type settings
            if type_ in ('radio', 'select'):
                if ticket.exists:
                    value = ticket.values.get(name)
                    options = field['options']
                    optgroups = []
                    for x in field.get('optgroups', []):
                        optgroups.extend(x['options'])
                    if value and \
                        (not value in options and \
                         not value in optgroups):
                        # Current ticket value must be visible,
                        # even if it's not among the possible values
                        options.append(value)
            elif type_ == 'checkbox':
                value = ticket.values.get(name)
                if value in ('1', '0'):
                    field['rendered'] = self._query_link(req, name, value,
                                _("yes") if value == '1' else _("no"))
            elif type_ == 'text':
                if field.get('format') == 'wiki':
                    field['rendered'] = format_to_oneliner(self.env, context,
                                                           ticket[name])
                elif field.get('format') == 'reference':
                    field['rendered'] = self._query_link(req, name,
                                                         ticket[name])
                elif field.get('format') == 'list':
                    field['rendered'] = self._query_link_words(context, name,
                                                               ticket[name])
            elif type_ == 'textarea':
                if field.get('format') == 'wiki':
                    field['rendered'] = \
                        format_to_html(self.env, context, ticket[name],
                                escape_newlines=self.must_preserve_newlines)

            # ensure sane defaults
            field.setdefault('optional', False)
            field.setdefault('options', [])
            field.setdefault('skip', False)
            fields.append(field)

        # Move owner field to end when shown
        if owner_field is not None:
            fields.remove(owner_field)
            fields.append(owner_field)
        return fields

    def _insert_crashdump_data(self, req, crashobj, data, author_id, field_changes):
        """Insert crashobj data into the template `data`"""
        replyto = req.args.get('replyto')
        data['replyto'] = replyto
        data['version'] = crashobj.resource.version
        data['description_change'] = None

        data['author_id'] = author_id

        # -- Ticket fields

        fields = self._prepare_fields(req, crashobj, field_changes)
        fields_map = dict((field['name'], i) for i, field in enumerate(fields))

        # -- Ticket Change History

        def quote_original(author, original, link):
            if 'comment' not in req.args: # i.e. the comment was not yet edited
                data['comment'] = '\n'.join(
                    ["Replying to [%s %s]:" % (link,
                                        obfuscate_email_address(author))] +
                    ["> %s" % line for line in original.splitlines()] + [''])

        if replyto == 'description':
            quote_original(crashobj['reporter'], crashobj['description'],
                           'crash:%s' % crashobj.uuid)
        values = {}
        replies = {}
        changes = []
        cnum = 0
        skip = False
        start_time = data.get('start_time', crashobj['changetime'])
        conflicts = set()
        for change in self.rendered_changelog_entries(req, crashobj):
            # change['permanent'] is false for attachment changes; true for
            # other changes.
            if change['permanent']:
                cnum = change['cnum']
                if crashobj.resource.version is not None and \
                       cnum > crashobj.resource.version:
                    # Retrieve initial crashobj values from later changes
                    for k, v in change['fields'].iteritems():
                        if k not in values:
                            values[k] = v['old']
                    skip = True
                else:
                    # keep track of replies threading
                    if 'replyto' in change:
                        replies.setdefault(change['replyto'], []).append(cnum)
                    # eventually cite the replied to comment
                    if replyto == str(cnum):
                        quote_original(change['author'], change['comment'],
                                       'comment:%s' % replyto)
                    if crashobj.resource.version:
                        # Override crashobj value by current changes
                        for k, v in change['fields'].iteritems():
                            values[k] = v['new']
                    if 'description' in change['fields']:
                        data['description_change'] = change
                if change['date'] > start_time:
                    conflicts.update(change['fields'])
            if not skip:
                changes.append(change)

        if crashobj.resource.version is not None:
            crashobj.values.update(values)

        # -- Workflow support

        selected_action = req.args.get('action')

        # retrieve close time from changes
        closetime = None
        for c in changes:
            s = c['fields'].get('status')
            if s:
                closetime = c['date'] if s['new'] == 'closed' else None

        # action_controls is an ordered list of "renders" tuples, where
        # renders is a list of (action_key, label, widgets, hints) representing
        # the user interface for each action
        action_controls = []
        sorted_actions = TicketSystem(self.env).get_available_actions(req,
                                                                      crashobj)
        for action in sorted_actions:
            first_label = None
            hints = []
            widgets = []
            for controller in self._get_action_controllers(req, crashobj,
                                                           action):
                label, widget, hint = controller.render_ticket_action_control(
                    req, crashobj, action)
                if not first_label:
                    first_label = label
                widgets.append(widget)
                hints.append(hint)
            action_controls.append((action, first_label, tag(widgets), hints))

        # The default action is the first in the action_controls list.
        if not selected_action:
            if action_controls:
                selected_action = action_controls[0][0]

        # Insert change preview
        change_preview = {
            'author': author_id, 'fields': field_changes, 'preview': True,
            'comment': req.args.get('comment', data.get('comment')),
            'comment_history': {},
        }
        replyto = req.args.get('replyto')
        if replyto:
            change_preview['replyto'] = replyto
        if req.method == 'POST':
            self._apply_ticket_changes(ticket, field_changes)
            self._render_property_changes(req, ticket, field_changes)

        if ticket.resource.version is not None: ### FIXME
            ticket.values.update(values)

        context = web_context(req, ticket.resource)

        # Display the owner and reporter links when not obfuscated
        chrome = Chrome(self.env)
        for user in 'reporter', 'owner':
            if chrome.format_author(req, ticket[user]) == ticket[user]:
                data['%s_link' % user] = self._query_link(req, user,
                                                          ticket[user])
        data.update({
            'context': context, 'conflicts': conflicts,
            'fields': fields, 'fields_map': fields_map,
            'changes': changes, 'replies': replies,
            'attachments': AttachmentModule(self.env).attachment_data(context),
            'action_controls': action_controls, 'action': selected_action,
            'change_preview': change_preview, 'closetime': closetime,
        })

    def _format_datetime(self, req, timestamp):
        return format_datetime(from_utimestamp(long(timestamp)))


    def _get_dump_filename(self, crashdump, name):
        item_name = getattr(crashdump, name)
        crash_file = os.path.join(self.env.path, self.dumpdata_dir, item_name)
        return crash_file

    def _link_crash(self, req, uuid):
        items = []

        try:
            crash = CrashDump(self.env, uuid)
            word = \
                tag.a(
                    '%s' % uuid,
                    class_=crash.status,
                    href=req.href('crash', uuid),
                    title=uuid
                )
        except ResourceNotFound:
            pass
        items.append(word)

        if items:
            return tag(items)
        else:
            return None
