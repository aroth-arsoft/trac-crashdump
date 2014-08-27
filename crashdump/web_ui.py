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
from trac.web import (
    arg_list_to_args, parse_arg_list
)
from trac.ticket.model import Milestone, Ticket, group_milestones
from trac.ticket.query import Query
from trac.config import Option, BoolOption, ChoiceOption
from trac.attachment import AttachmentModule
from trac.mimeview.api import Mimeview, IContentConverter
from trac.resource import (
    Resource, ResourceNotFound, get_resource_url, render_resource_link,
    get_resource_shortname
)
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
import time
from .model import CrashDump
from .api import CrashDumpSystem
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

    crashlink_query = Option('crashdump', 'crashlink_query',
        default='?status=!closed',
        doc="""The base query to be used when linkifying values of ticket
            fields. The query is a URL query
            string starting with `?` as used in `query:`
            [TracQuery#UsingTracLinks Trac links].
            (''since 0.12'')""")

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
        if xmlfile:
            start = time.time()
            xmlreport = XMLReport(xmlfile)
            for f in xmlreport.fields:
                data[f] = getattr(xmlreport, f)
            end = time.time()
            data['parsetime'] = end - start
        return data

    def _get_prefs(self, req):
        return {'comments_order': req.session.get('ticket_comments_order',
                                                  'oldest'),
                'comments_only': req.session.get('ticket_comments_only',
                                                 'false')}

    def process_request(self, req):
        path_info = req.path_info[6:]
        start = time.time()
        if 'crashuuid' in req.args:
            crashobj = CrashDump.find_by_uuid(self.env, req.args['crashuuid'])
            if not crashobj:
                raise ResourceNotFound(_("Crash %(id)s does not exist.",
                                        id=req.args['crashuuid']), _("Invalid crash identifier"))
        elif 'crashid' in req.args:
            crashobj = CrashDump.find_by_id(self.env, req.args['crashid'])
            if not crashobj:
                raise ResourceNotFound(_("Crash %(id)s does not exist.",
                                        id=req.args['crashid']), _("Invalid crash identifier"))
        else:
            raise ResourceNotFound(_("No crash identifier specified."))
        end = time.time()
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
        data['dbtime'] = end - start

        field_changes = {}
        data.update({'action': None,
                    # Store a timestamp for detecting "mid air collisions"
                    'start_time': crashobj['changetime']})

        self._insert_crashdump_data(req, crashobj, data,
                                get_reporter_id(req, 'author'), field_changes)

        add_script_data(req, {'comments_prefs': self._get_prefs(req)})
        add_stylesheet(req, 'crashdump/crashdump.css')
        add_script(req, 'common/js/folding.js')

        return 'report.html', data, None

    def _query_link(self, req, name, value, text=None):
        """Return a link to /query with the appropriate name and value"""
        default_query = self.crashlink_query.lstrip('?')
        args = arg_list_to_args(parse_arg_list(default_query))
        args[name] = value
        if name == 'resolution':
            args['status'] = 'closed'
        return tag.a(text or value, href=req.href.query(args))

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
                CrashDumpSystem(self.env).eventually_restrict_owner(field, crashobj)
                type_ = field['type']
                field['skip'] = True
                if not crashobj.exists:
                    field['label'] = _("Owner")
                    if 'TICKET_MODIFY' in req.perm(crashobj.resource):
                        field['skip'] = False
                        owner_field = field
            elif name == 'milestone':
                milestones = [Milestone(self.env, opt)
                              for opt in field['options']]
                milestones = [m for m in milestones
                              if 'MILESTONE_VIEW' in req.perm(m.resource)]
                groups = group_milestones(milestones, crashobj.exists
                    and 'TICKET_ADMIN' in req.perm(crashobj.resource))
                field['options'] = []
                field['optgroups'] = [
                    {'label': label, 'options': [m.name for m in milestones]}
                    for (label, milestones) in groups]
                milestone = Resource('milestone', crashobj[name])
                field['rendered'] = render_resource_link(self.env, context,
                                                         milestone, 'compact')
            elif name == 'cc':
                cc_changed = field_changes is not None and 'cc' in field_changes
                if crashobj.exists and \
                        'TICKET_EDIT_CC' not in req.perm(crashobj.resource):
                    cc = crashobj._old.get('cc', crashobj['cc'])
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
                if crashobj.exists:
                    value = crashobj.values.get(name)
                    options = field['options']
                    optgroups = []
                    for x in field.get('optgroups', []):
                        optgroups.extend(x['options'])
                    if value and \
                        (not value in options and \
                         not value in optgroups):
                        # Current crashobj value must be visible,
                        # even if it's not among the possible values
                        options.append(value)
            elif type_ == 'checkbox':
                value = crashobj.values.get(name)
                if value in ('1', '0'):
                    field['rendered'] = self._query_link(req, name, value,
                                _("yes") if value == '1' else _("no"))
            elif type_ == 'text':
                if field.get('format') == 'wiki':
                    field['rendered'] = format_to_oneliner(self.env, context,
                                                           crashobj[name])
                elif field.get('format') == 'reference':
                    field['rendered'] = self._query_link(req, name,
                                                         crashobj[name])
                elif field.get('format') == 'list':
                    field['rendered'] = self._query_link_words(context, name,
                                                               crashobj[name])
            elif type_ == 'textarea':
                if field.get('format') == 'wiki':
                    field['rendered'] = \
                        format_to_html(self.env, context, crashobj[name],
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

        if crashobj.resource.version is not None:
            crashobj.values.update(values)

        context = web_context(req, crashobj.resource)

        # Display the owner and reporter links when not obfuscated
        chrome = Chrome(self.env)
        for user in 'reporter', 'owner':
            if chrome.format_author(req, crashobj[user]) == crashobj[user]:
                data['%s_link' % user] = self._query_link(req, user,
                                                          crashobj[user])
        data['context'] = context

    def _populate(self, req, crashobj, plain_fields=False):
        if not plain_fields:
            fields = dict((k[6:], v) for k, v in req.args.iteritems()
                          if k.startswith('field_')
                             and not 'revert_' + k[6:] in req.args)
            # Handle revert of checkboxes (in particular, revert to 1)
            for k in list(fields):
                if k.startswith('checkbox_'):
                    k = k[9:]
                    if 'revert_' + k in req.args:
                        fields[k] = crashobj[k]
        else:
            fields = req.args.copy()
        # Prevent direct changes to protected fields (status and resolution are
        # set in the workflow, in get_ticket_changes())
        for each in Ticket.protected_fields:
            fields.pop(each, None)
            fields.pop('checkbox_' + each, None)    # See Ticket.populate()
        crashobj.populate(fields)
        # special case for updating the Cc: field
        if 'cc_update' in req.args and 'revert_cc' not in req.args:
            cc_action, cc_entry, cc_list = self._toggle_cc(req, crashobj['cc'])
            if cc_action == 'remove':
                cc_list.remove(cc_entry)
            elif cc_action == 'add':
                cc_list.append(cc_entry)
            crashobj['cc'] = ', '.join(cc_list)

    def _get_history(self, req, crashobj):
        history = []
        for change in self.rendered_changelog_entries(req, crashobj):
            if change['permanent']:
                change['version'] = change['cnum']
                history.append(change)
        return history

    def _render_history(self, req, crashobj, data, text_fields):
        """Extract the history for a ticket description."""
        req.perm(crashobj.resource).require('TICKET_VIEW')

        history = self._get_history(req, crashobj)
        history.reverse()
        history = [c for c in history if any(f in text_fields
                                             for f in c['fields'])]
        history.append({'version': 0, 'comment': "''Initial version''",
                        'date': crashobj['changetime'],
                        'author': crashobj['reporter'] # not 100% accurate...
                        })
        data.update({'title': _("Crash History"),
                     'resource': crashobj.resource,
                     'history': history})

        add_ctxtnav(req, _("Back to Crash %(id)s", num=str(crashobj.uuid)),
                           req.href('crash', crashobj.id))
        return 'history_view.html', data, None

    def _render_diff(self, req, crashobj, data, text_fields):
        """Show differences between two versions of a ticket description.

        `text_fields` is optionally a list of fields of interest, that are
        considered for jumping to the next change.
        """
        new_version = int(req.args.get('version', 1))
        old_version = int(req.args.get('old_version', new_version))
        if old_version > new_version:
            old_version, new_version = new_version, old_version

        # get the list of versions having a description change
        history = self._get_history(req, crashobj)
        changes = {}
        descriptions = []
        old_idx = new_idx = -1 # indexes in descriptions
        for change in history:
            version = change['version']
            changes[version] = change
            if any(f in text_fields for f in change['fields']):
                if old_version and version <= old_version:
                    old_idx = len(descriptions)
                if new_idx == -1 and new_version and version >= new_version:
                    new_idx = len(descriptions)
                descriptions.append((version, change))

        # determine precisely old and new versions
        if old_version == new_version:
            if new_idx >= 0:
                old_idx = new_idx - 1
        if old_idx >= 0:
            old_version, old_change = descriptions[old_idx]
        else:
            old_version, old_change = 0, None
        num_changes = new_idx - old_idx
        if new_idx >= 0:
            new_version, new_change = descriptions[new_idx]
        else:
            raise TracError(_("No differences to show"))

        tnew = crashobj.resource(version=new_version)
        told = crashobj.resource(version=old_version)

        req.perm(tnew).require('TICKET_VIEW')
        req.perm(told).require('TICKET_VIEW')

        # determine prev and next versions
        prev_version = old_version
        next_version = None
        if new_idx < len(descriptions) - 1:
            next_version = descriptions[new_idx+1][0]

        # -- old properties (old_ticket) and new properties (new_ticket)

        # assume a linear sequence of change numbers, starting at 1, with gaps
        def replay_changes(values, old_values, from_version, to_version):
            for version in range(from_version, to_version+1):
                if version in changes:
                    for k, v in changes[version]['fields'].iteritems():
                        values[k] = v['new']
                        if old_values is not None and k not in old_values:
                            old_values[k] = v['old']

        old_ticket = {}
        if old_version:
            replay_changes(old_ticket, None, 1, old_version)

        new_ticket = dict(old_ticket)
        replay_changes(new_ticket, old_ticket, old_version+1, new_version)

        field_labels = CrashDumpSystem(self.env).get_crash_field_labels()

        changes = []

        def version_info(t, field=None):
            path = _("Crash %(uuid)s", uuid=str(crashobj.uuid))
            # TODO: field info should probably be part of the Resource as well
            if field:
                path = tag(path, Markup(' &ndash; '),
                           field_labels.get(field, field.capitalize()))
            if t.version:
                rev = _("Version %(num)s", num=t.version)
                shortrev = 'v%d' % t.version
            else:
                rev, shortrev = _("Initial Version"), _("initial")
            return {'path':  path, 'rev': rev, 'shortrev': shortrev,
                    'href': get_resource_url(self.env, t, req.href)}

        # -- prop changes
        props = []
        for k, v in new_ticket.iteritems():
            if k not in text_fields:
                old, new = old_ticket[k], new_ticket[k]
                if old != new:
                    label = field_labels.get(k, k.capitalize())
                    prop = {'name': label, 'field': k,
                            'old': {'name': label, 'value': old},
                            'new': {'name': label, 'value': new}}
                    rendered = self._render_property_diff(req, crashobj, k,
                                                          old, new, tnew)
                    if rendered:
                        prop['diff'] = tag.li(
                            tag_("Property %(label)s %(rendered)s",
                                 label=tag.strong(label), rendered=rendered))
                    props.append(prop)
        changes.append({'props': props, 'diffs': [],
                        'new': version_info(tnew),
                        'old': version_info(told)})

        # -- text diffs
        diff_style, diff_options, diff_data = get_diff_options(req)
        diff_context = 3
        for option in diff_options:
            if option.startswith('-U'):
                diff_context = int(option[2:])
                break
        if diff_context < 0:
            diff_context = None

        for field in text_fields:
            old_text = old_ticket.get(field)
            old_text = old_text.splitlines() if old_text else []
            new_text = new_ticket.get(field)
            new_text = new_text.splitlines() if new_text else []
            diffs = diff_blocks(old_text, new_text, context=diff_context,
                                ignore_blank_lines='-B' in diff_options,
                                ignore_case='-i' in diff_options,
                                ignore_space_changes='-b' in diff_options)

            changes.append({'diffs': diffs, 'props': [], 'field': field,
                            'new': version_info(tnew, field),
                            'old': version_info(told, field)})

        # -- prev/up/next links
        if prev_version:
            add_link(req, 'prev', get_resource_url(self.env, crashobj.resource,
                                                   req.href, action='diff',
                                                   version=prev_version),
                     _("Version %(num)s", num=prev_version))
        add_link(req, 'up', get_resource_url(self.env, crashobj.resource,
                                             req.href, action='history'),
                 _("Crash History"))
        if next_version:
            add_link(req, 'next', get_resource_url(self.env, crashobj.resource,
                                                   req.href, action='diff',
                                                   version=next_version),
                     _("Version %(num)s", num=next_version))

        prevnext_nav(req, _("Previous Change"), _("Next Change"),
                     _("Crash History"))
        add_stylesheet(req, 'common/css/diff.css')
        add_script(req, 'common/js/diff.js')

        data.update({
            'title': _("Crash Diff"),
            'resource': crashobj.resource,
            'old_version': old_version, 'new_version': new_version,
            'changes': changes, 'diff': diff_data,
            'num_changes': num_changes, 'change': new_change,
            'old_ticket': old_ticket, 'new_ticket': new_ticket,
            'longcol': '', 'shortcol': ''
        })

        return 'diff_view.html', data, None

    def _make_comment_url(self, req, crashobj, cnum, version=None):
        return req.href('crash', crashobj.id,
                               cnum_hist=cnum if version is not None else None,
                               cversion=version) + '#comment:%d' % cnum

    def _get_comment_history(self, req, crashobj, cnum):
        history = []
        for version, date, author, comment in crashobj.get_comment_history(cnum):
            history.append({
                'version': version, 'date': date, 'author': author,
                'comment': _("''Initial version''") if version == 0 else '',
                'value': comment,
                'url': self._make_comment_url(req, crashobj, cnum, version)
            })
        return history

    def _render_comment_history(self, req, crashobj, data, cnum):
        """Extract the history for a crashobj comment."""
        req.perm(crashobj.resource).require('TICKET_VIEW')
        history = self._get_comment_history(req, crashobj, cnum)
        history.reverse()
        url = self._make_comment_url(req, crashobj, cnum)
        data.update({
            'title': _("Crash Comment History"),
            'resource': crashobj.resource,
            'name': _("Crash %(uuid)s, comment %(cnum)d",
                      uuid=str(crashobj.uuid), cnum=cnum),
            'url': url,
            'diff_action': 'comment-diff', 'diff_args': [('cnum', cnum)],
            'history': history,
        })
        add_ctxtnav(req, _("Back to Crash %(uuid)s", uuid=str(crashobj.uuid)), url)
        return 'history_view.html', data, None

    def _render_comment_diff(self, req, crashobj, data, cnum):
        """Show differences between two versions of a crashobj comment."""
        req.perm(crashobj.resource).require('TICKET_VIEW')
        new_version = int(req.args.get('version', 1))
        old_version = int(req.args.get('old_version', new_version))
        if old_version > new_version:
            old_version, new_version = new_version, old_version
        elif old_version == new_version:
            old_version = new_version - 1

        history = {}
        for change in self._get_comment_history(req, crashobj, cnum):
            history[change['version']] = change

        def version_info(version):
            path = _("Crash %(uuid)s, comment %(cnum)d",
                     uuid=str(crashobj.uuid), cnum=cnum)
            if version:
                rev = _("Version %(num)s", num=version)
                shortrev = 'v%d' % version
            else:
                rev, shortrev = _("Initial Version"), _("initial")
            return {'path':  path, 'rev': rev, 'shortrev': shortrev}

        diff_style, diff_options, diff_data = get_diff_options(req)
        diff_context = 3
        for option in diff_options:
            if option.startswith('-U'):
                diff_context = int(option[2:])
                break
        if diff_context < 0:
            diff_context = None

        def get_text(version):
            try:
                text = history[version]['value']
                return text.splitlines() if text else []
            except KeyError:
                raise ResourceNotFound(_("No version %(version)d for comment "
                                         "%(cnum)d on crash %(uuid)s",
                                         version=version, cnum=cnum,
                                         uuid=str(crashobj.uuid)))

        old_text = get_text(old_version)
        new_text = get_text(new_version)
        diffs = diff_blocks(old_text, new_text, context=diff_context,
                            ignore_blank_lines='-B' in diff_options,
                            ignore_case='-i' in diff_options,
                            ignore_space_changes='-b' in diff_options)

        changes = [{'diffs': diffs, 'props': [],
                    'new': version_info(new_version),
                    'old': version_info(old_version)}]

        # -- prev/up/next links
        prev_version = old_version
        next_version = None
        if new_version < len(history) - 1:
            next_version = new_version + 1

        if prev_version:
            url = req.href('crash', crashobj.id, cnum=cnum, action='comment-diff',
                                  version=prev_version)
            add_link(req, 'prev', url, _("Version %(num)s", num=prev_version))
        add_link(req, 'up', req.href('crash', crashobj.id, cnum=cnum,
                                            action='comment-history'),
                 _("Crash Comment History"))
        if next_version:
            url = req.href('crash', crashobj.id, cnum=cnum, action='comment-diff',
                                  version=next_version)
            add_link(req, 'next', url, _("Version %(num)s", num=next_version))

        prevnext_nav(req, _("Previous Change"), _("Next Change"),
                     _("Crash Comment History"))
        add_stylesheet(req, 'common/css/diff.css')
        add_script(req, 'common/js/diff.js')

        data.update({
            'title': _("Crash Comment Diff"),
            'resource': crashobj.resource,
            'name': _("Crash %(uuid)s, comment %(cnum)d",
                      uuid=str(crashobj.uuid), cnum=cnum),
            'url': self._make_comment_url(req, crashobj, cnum),
            'old_url': self._make_comment_url(req, crashobj, cnum, old_version),
            'new_url': self._make_comment_url(req, crashobj, cnum, new_version),
            'diff_url': req.href('crash', crashobj.id, cnum=cnum,
                                        action='comment-diff',
                                        version=new_version),
            'diff_action': 'comment-diff', 'diff_args': [('cnum', cnum)],
            'old_version': old_version, 'new_version': new_version,
            'changes': changes, 'diff': diff_data,
            'num_changes': new_version - old_version,
            'change': history[new_version],
            'crash': crashobj, 'cnum': cnum,
            'longcol': '', 'shortcol': ''
        })
        return 'diff_view.html', data, None

    def rendered_changelog_entries(self, req, crashobj, when=None):
        """Iterate on changelog entries, consolidating related changes
        in a `dict` object.
        """
        attachment_realm = crashobj.resource.child('attachment')
        for group in self.grouped_changelog_entries(crashobj, when=when):
            t = crashobj.resource(version=group.get('cnum', None))
            if 'TICKET_VIEW' in req.perm(t):
                self._render_property_changes(req, crashobj, group['fields'], t)
                if 'attachment' in group['fields']:
                    filename = group['fields']['attachment']['new']
                    attachment = attachment_realm(id=filename)
                    if 'ATTACHMENT_VIEW' not in req.perm(attachment):
                        del group['fields']['attachment']
                        if not group['fields']:
                            continue
                yield group

    def grouped_changelog_entries(self, crashobj, db=None, when=None):
        """Iterate on changelog entries, consolidating related changes
        in a `dict` object.

        :since 1.0: the `db` parameter is no longer needed and will be removed
        in version 1.1.1
        """
        field_labels = CrashDumpSystem(self.env).get_crash_field_labels()
        changelog = crashobj.get_changelog(when=when)
        autonum = 0 # used for "root" numbers
        last_uid = current = None
        for date, author, field, old, new, permanent in changelog:
            uid = (date,) if permanent else (date, author)
            if uid != last_uid:
                if current:
                    last_comment = comment_history[max(comment_history)]
                    last_comment['comment'] = current['comment']
                    yield current
                last_uid = uid
                comment_history = {0: {'date': date}}
                current = {'date': date, 'fields': {},
                           'permanent': permanent, 'comment': '',
                           'comment_history': comment_history}
                if permanent and not when:
                    autonum += 1
                    current['cnum'] = autonum
            # some common processing for fields
            if not field.startswith('_'):
                current.setdefault('author', author)
                comment_history[0].setdefault('author', author)
            if field == 'comment':
                current['comment'] = new
                # Always take the author from the comment field if available
                current['author'] = comment_history[0]['author'] = author
                if old:
                    if '.' in old: # retrieve parent.child relationship
                        parent_num, this_num = old.split('.', 1)
                        current['replyto'] = parent_num
                    else:
                        this_num = old
                    current['cnum'] = autonum = int(this_num)
            elif field.startswith('_comment'):      # Comment edits
                rev = int(field[8:])
                comment_history.setdefault(rev, {}).update({'comment': old})
                comment_history.setdefault(rev + 1, {}).update(
                        {'author': author, 'date': from_utimestamp(long(new))})
            elif (old or new) and old != new:
                current['fields'][field] = {
                    'old': old, 'new': new,
                    'label': field_labels.get(field, field)}
        if current:
            last_comment = comment_history[max(comment_history)]
            last_comment['comment'] = current['comment']
            yield current

    def _format_datetime(self, req, timestamp):
        return format_datetime(from_utimestamp(long(timestamp)))

    def _get_dump_filename(self, crashobj, name):
        print('_get_dump_filename %s' % name)
        item_name = crashobj[name]
        crash_file = os.path.join(self.env.path, self.dumpdata_dir, item_name)
        return crash_file

    def _link_crash(self, req, uuid):
        items = []

        try:
            crash = CrashDump(env=self.env, uuid=uuid)
            word = \
                tag.a(
                    '%s' % uuid,
                    class_=crash.status,
                    href=req.href('crash', uuid),
                    title=uuid
                )
            items.append(word)
        except ResourceNotFound:
            pass

        if items:
            return tag(items)
        else:
            return None

    # Internal methods
    def _get_action_controllers(self, req, ticket, action):
        """Generator yielding the controllers handling the given `action`"""
        for controller in CrashDumpSystem(self.env).action_controllers:
            actions = [a for w, a in
                       controller.get_ticket_actions(req, ticket) or []]
            if action in actions:
                yield controller
