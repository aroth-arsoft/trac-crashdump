import subprocess
import re

from pkg_resources import resource_filename
from genshi.core import Markup, START, END, TEXT
from genshi.builder import tag

from trac.core import *
from trac.web.api import IRequestHandler, IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import ITemplateProvider, INavigationContributor, add_stylesheet, add_script, \
                            add_ctxtnav
from trac.ticket.api import ITicketManipulator
from trac.ticket.model import Ticket
from trac.ticket.query import Query
from trac.config import Option, BoolOption, ChoiceOption
from trac.resource import ResourceNotFound
from trac.util import to_unicode
from trac.util.translation import _ 
from trac.util.html import html, Markup
from trac.util.text import shorten_line
from trac.util.compat import set, sorted, partial

import graphviz
from model import TicketLinks

class CrashDumpModule(Component):
    """Provides support for ticket dependencies."""
    
    implements(IRequestHandler, IRequestFilter, INavigationContributor, ITemplateStreamFilter,
               ITemplateProvider, ITicketManipulator)
    
    dot_path = Option('crashdump', 'dot_path', default='dot',
                      doc='Path to the dot executable.')
    gs_path = Option('crashdump', 'gs_path', default='gs',
                     doc='Path to the ghostscript executable.')
    use_gs = BoolOption('crashdump', 'use_gs', default=False,
                        doc='If enabled, use ghostscript to produce nicer output.')
    
    closed_color = Option('crashdump', 'closed_color', default='green',
        doc='Color of closed tickets')
    opened_color = Option('crashdump', 'opened_color', default='red',
        doc='Color of opened tickets')

    graph_direction = ChoiceOption('crashdump', 'graph_direction', choices = ['TD', 'LR', 'DT', 'RL'],
        doc='Direction of the dependency graph (TD = Top Down, DT = Down Top, LR = Left Right, RL = Right Left)')

    fields = set(['blocking', 'blockedby'])
    
    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        return handler
        
    def post_process_request(self, req, template, data, content_type):
        if req.path_info.startswith('/crashdump/'):
            # In case of an invalid ticket, the data is invalid
            if not data:
                return template, data, content_type
            tkt = data['ticket']
            links = TicketLinks(self.env, tkt)
            
            for i in links.blocked_by:
                if Ticket(self.env, i)['status'] != 'closed':
                    add_script(req, 'crashdump/disable_resolve.js')
                    break

            # Add link to depgraph if needed
            if links:
                add_ctxtnav(req, 'Depgraph', req.href.depgraph(tkt.id))
            
            for change in data.get('changes', {}):
                if not change.has_key('fields'):
                    continue
                for field, field_data in change['fields'].iteritems():
                    if field in self.fields:
                        if field_data['new'].strip():
                            new = set([int(n) for n in field_data['new'].split(',')])
                        else:
                            new = set()
                        if field_data['old'].strip():
                            old = set([int(n) for n in field_data['old'].split(',')])
                        else:
                            old = set()
                        add = new - old
                        sub = old - new
                        elms = tag()
                        if add:
                            elms.append(
                                tag.em(u', '.join([unicode(n) for n in sorted(add)]))
                            )
                            elms.append(u' added')
                        if add and sub:
                            elms.append(u'; ')
                        if sub:
                            elms.append(
                                tag.em(u', '.join([unicode(n) for n in sorted(sub)]))
                            )
                            elms.append(u' removed')
                        field_data['rendered'] = elms

        return template, data, content_type

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
                    for f in self.fields:
                        if field['name'] == f and data['ticket'][f]:
                            field['rendered'] = self._link_tickets(req, data['ticket'][f])
            # For query_results.html and query.html
            if 'groups' in data and isinstance(data['groups'], list):
                for group, tickets in data['groups']:
                    for ticket in tickets:
                        for f in self.fields:
                            if f in ticket:
                                ticket[f] = self._link_tickets(req, ticket[f])
            # For report_view.html
            if 'row_groups' in data and isinstance(data['row_groups'], list):
                for group, rows in data['row_groups']:
                    for row in rows:
                        if 'cell_groups' in row and isinstance(row['cell_groups'], list):
                            for cells in row['cell_groups']:
                                for cell in cells:
                                    # If the user names column in the report differently (blockedby AS "blocked by") then this will not find it
                                    if cell.get('header', {}).get('col') in self.fields:
                                        cell['value'] = self._link_tickets(req, cell['value'])
        return stream
        
    # ITicketManipulator methods
    def prepare_ticket(self, req, ticket, fields, actions):
        pass
        
    def validate_ticket(self, req, ticket):
        if req.args.get('action') == 'resolve' and req.args.get('action_resolve_resolve_resolution') == 'fixed': 
            links = TicketLinks(self.env, ticket)
            for i in links.blocked_by:
                if Ticket(self.env, i)['status'] != 'closed':
                    yield None, 'Ticket #%s is blocking this ticket'%i

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
        return req.path_info.startswith('/crashdump')

    def process_request(self, req):
        path_info = req.path_info[10:]
        if path_info == '/list' or not path_info:
            content = 'Hello World list!'
        else:
            content = 'Hello World !'
        req.send_response(200)
        req.send_header('Content-Type', 'text/plain')
        req.send_header('Content-Length', len(content))
        req.end_headers()
        req.write(content)

    def _link_tickets(self, req, tickets):
        items = []

        for i, word in enumerate(re.split(r'([;,\s]+)', tickets)):
            if i % 2:
                items.append(word)
            elif word:
                ticketid = word
                word = '#%s' % word

                try:
                    ticket = Ticket(self.env, ticketid)
                    if 'TICKET_VIEW' in req.perm(ticket.resource):
                        word = \
                            tag.a(
                                '#%s' % ticket.id,
                                class_=ticket['status'],
                                href=req.href.ticket(int(ticket.id)),
                                title=shorten_line(ticket['summary'])
                            )
                except ResourceNotFound:
                    pass
               
                items.append(word)

        if items:
            return tag(items)
        else:
            return None
