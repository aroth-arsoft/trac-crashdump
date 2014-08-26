from trac.core import *
from trac.util.html import html
from trac.util.datefmt import utc
from trac.web import IRequestHandler, IRequestFilter
from trac.web.api import arg_list_to_args, RequestDone, HTTPMethodNotAllowed, HTTPForbidden, HTTPInternalError
from trac.web.chrome import INavigationContributor, ITemplateProvider
from trac.config import Option, BoolOption, ChoiceOption
from pkg_resources import resource_filename
from uuid import UUID
import os
import shutil
import time
import datetime

from .model import CrashDump

class CrashDumpSubmit(Component):
    implements(IRequestHandler, IRequestFilter, ITemplateProvider)

    dumpdata_dir = Option('crashdump', 'dumpdata_dir', default='dumpdata',
                      doc='Path to the crash dump data directory.')

    default_priority = Option('crashdump', 'default_priority', default='major',
                      doc='Default priority for submitted crash reports.')

    default_milestone = Option('crashdump', 'default_milestone', '',
        """Default milestone for submitted crash reports.""")

    default_component = Option('crashdump', 'default_component', '',
        """Default component for submitted crash reports.""")

    default_severity = Option('crashdump', 'default_severity', '',
        """Default severity for submitted crash reports.""")

    default_summary = Option('crashdump', 'default_summary', '',
        """Default summary (title) for submitted crash reports.""")

    default_description = Option('crashdump', 'default_description', '',
        """Default description for submitted crash reports.""")

    default_keywords = Option('crashdump', 'default_keywords', '',
        """Default keywords for submitted crash reports.""")

    default_reporter = Option('crashdump', 'default_reporter', '< default >',
        """Default reporter for submitted crash reports.""")

    default_owner = Option('crashdump', 'default_owner', '< default >',
        """Default owner for submitted crash reports.""")

    # IRequestHandler methods
    def match_request(self, req):
        if req.method == 'POST' and (req.path_info == '/crashdump/submit' or req.path_info == '/submit'):
            #self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        else:
            return False

    def _error_response(self, req, status, body=None):
        req.send_error(None, template='', content_type='text/plain', status=status, env=None, data=body)

    def _success_response(self, req, body=None, status=200):
        req.send(content=body, content_type='text/plain', status=status)

    def pre_process_request(self, req, handler):
        self.log.debug('CrashDumpSubmit pre_process_request: %s %s', req.method, req.path_info)
        # copy the requested form token from into the args to pass the CSRF test
        req.args['__FORM_TOKEN' ] = req.form_token
        return handler

    def post_process_request(self, req, template, data, content_type, method=None):
        True

    def process_request(self, req):
        self.log.debug('CrashDumpSubmit process_request: %s %s', req.method, req.path_info)
        if req.method != "POST":
            return self._error_response(req, status=HTTPMethodNotAllowed.code, body='Method %s not allowed' % req.method)

        user_agent = req.get_header('User-Agent')
        if user_agent is None:
            return self._error_response(req, status=HTTPForbidden.code, body='No user-agent specified.')
        if '/' in user_agent:
            user_agent, agent_ver = user_agent.split('/', 1)
        if user_agent != 'terra3d-crashuploader':
            return self._error_response(req, status=HTTPForbidden.code, body='User-agent %s not allowed' % user_agent)

        id_str = req.args.get('id')
        if not id_str or not CrashDump.uuid_is_valid(id_str):
            return self._error_response(req, status=HTTPForbidden.code, body='Invalid crash identifier %s specified.' % id_str)

        uuid = UUID(id_str)
        crashid = None
        crashobj = CrashDump.find_by_uuid(self.env, uuid)
        print('found %s' % str(crashobj))
        if not crashobj:
            crashobj = CrashDump(uuid=uuid, env=self.env, must_exist=False)
        else:
            crashid = crashobj.id
        print('found crashid %s' % str(crashid))

        force_str = req.args.get('force') or 'false'
        force = True if force_str.lower() == 'true' else False
        # for easy testing
        force = True
        if crashid is not None and not force:
            return self._error_response(req, status=HTTPForbidden.code, body='Crash identifier %s already uploaded.' % id_str)

        result = False
        ok, crashobj['minidumpfile'] = self._store_dump_file(uuid, req, 'minidump', force)
        if ok:
            result = True
        ok, crashobj['minidumpreporttextfile'] = self._store_dump_file(uuid, req, 'minidumpreport', force)
        if ok:
            result = True
        ok, crashobj['minidumpreportxmlfile'] = self._store_dump_file(uuid, req, 'minidumpreportxml', force)
        if ok:
            result = True
        ok, crashobj['minidumpreporthtmlfile'] = self._store_dump_file(uuid, req, 'minidumpreporthtml', force)
        if ok:
            result = True
        ok, crashobj['coredumpfile'] = self._store_dump_file(uuid, req, 'coredump', force)
        if ok:
            result = True
        ok, crashobj['coredumpreporttextfile'] = self._store_dump_file(uuid, req, 'coredumpreport', force)
        if ok:
            result = True
        ok, crashobj['coredumpreportxmlfile'] = self._store_dump_file(uuid, req, 'coredumpreportxml', force)
        if ok:
            result = True
        ok, crashobj['coredumpreporthtmlfile'] = self._store_dump_file(uuid, req, 'coredumpreporthtml', force)
        if ok:
            result = True

        crashobj['applicationfile'] = req.args.get('applicationfile')

        crashtimestamp = datetime.datetime.strptime(req.args.get('crashtimestamp'), "%Y-%m-%dT%H:%M:%S" )
        crashtimestamp = crashtimestamp.replace(tzinfo = utc)
        reporttimestamp = datetime.datetime.strptime(req.args.get('reporttimestamp'), "%Y-%m-%dT%H:%M:%S" )
        reporttimestamp = reporttimestamp.replace(tzinfo = utc)

        crashobj['crashtime'] = crashtimestamp if crashtimestamp else None
        crashobj['reporttime'] = reporttimestamp if reporttimestamp else None
        crashobj['uploadtime'] = datetime.datetime.now(utc)

        self.log.debug('crashtimestamp %s' % (crashobj['crashtime']))
        self.log.debug('reporttimestamp %s' % (crashobj['reporttime']))

        crashobj['productname'] = req.args.get('productname')
        crashobj['productcodename'] = req.args.get('productcodename')
        crashobj['productversion'] = req.args.get('productversion')
        crashobj['producttargetversion'] = req.args.get('producttargetversion')
        crashobj['uploadhostname'] = req.args.get('fqdn')
        crashobj['uploadusername'] = req.args.get('username')
        crashobj['crashhostname'] = req.args.get('crashfqdn')
        crashobj['crashusername'] = req.args.get('crashusername')
        crashobj['buildtype'] = req.args.get('buildtype')
        crashobj['buildpostfix'] = req.args.get('buildpostfix')
        crashobj['machinetype'] = req.args.get('machinetype')
        crashobj['systemname'] = req.args.get('systemname')
        crashobj['osversion'] = req.args.get('osversion')
        crashobj['osrelease'] = req.args.get('osrelease')
        crashobj['osmachine'] = req.args.get('osmachine')

        # get the application name from the application file
        if crashobj['applicationfile']:
            appbase = os.path.basename(crashobj['applicationfile'])
            (appbase, ext) = os.path.splitext(appbase)
            if crashobj['buildpostfix'] and appbase.endswith(crashobj['buildpostfix']):
                appbase = appbase[:-len(crashobj['buildpostfix'])]
            crashobj['applicationname'] = appbase

        if result:
            if crashid is None:
                crashobj['status'] = 'new'
                crashobj['type'] = 'crash'
                crashobj['priority'] = self.default_priority
                crashobj['milestone'] = self.default_milestone
                crashobj['component'] = self.default_component
                crashobj['severity'] = self.default_severity
                crashobj['summary'] = self.default_summary
                crashobj['description'] = self.default_description
                crashobj['keywords'] = self.default_keywords
                crashobj['owner'] = self.default_owner
                if self.default_reporter == '< default >':
                    crashobj['reporter'] = crashobj['crashusername']
                else:
                    crashobj['reporter'] = self.default_reporter

                if crashobj.insert():
                    return self._success_response(req, body='Crash dump %s uploaded successfully.' % uuid)
                else:
                    return self._error_response(req, status=HTTPInternalError.code, body='Failed to add crash dump %s to database' % uuid)
            else:
                print('save changes')
                if crashobj.save_changes():
                    return self._success_response(req, body='Crash dump %s updated successfully.' % uuid)
                else:
                    return self._error_response(req, status=HTTPInternalError.code, body='Failed to update crash dump %s to database' % uuid)
        else:
            return self._error_response(req, status=HTTPInternalError.code, body='Failed to process crash dump %s' % uuid)

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

    @property
    def path(self):
        return self._get_path(self.env.path, self.parent_realm, self.parent_id,
                              self.filename)

    def _create_crash_file(self, filename, force):
        flags = os.O_CREAT + os.O_WRONLY
        if force:
            flags += os.O_TRUNC
        else:
            if os.path.isfile(filename):
                return None
            flags += os.O_EXCL
        if hasattr(os, 'O_BINARY'):
            flags += os.O_BINARY
        return os.fdopen(os.open(filename, flags, 0660), 'w')

    def _store_dump_file(self, uuid, req, name, force):
        item_name = None
        ret = False
        file = req.args.get(name) if name in req.args else None
        if file is not None:
            filename = file.filename
            fileobj = file.file
            item_name = os.path.join(str(uuid), filename)
            crash_dir = os.path.join(self.env.path, self.dumpdata_dir, str(uuid))
            crash_file = os.path.join(crash_dir, filename)
            self.log.debug('_store_dump_file item_name %s' % (item_name))
            self.log.debug('_store_dump_file crash_dir %s' % (crash_dir))
            self.log.debug('_store_dump_file crash_file %s' % (crash_file))
            if not os.path.isdir(crash_dir):
                os.makedirs(crash_dir)
            targetfileobj = self._create_crash_file(crash_file, force)
            if targetfileobj is None:
                ret = False
            else:
                shutil.copyfileobj(fileobj, targetfileobj)
                ret = True
        return (ret, item_name)
