from trac.core import *
from trac.util.html import html
from trac.web import IRequestHandler, IRequestFilter
from trac.web.api import arg_list_to_args, RequestDone, HTTPMethodNotAllowed, HTTPForbidden, HTTPInternalError
from trac.web.chrome import INavigationContributor, ITemplateProvider
from trac.config import Option, BoolOption, ChoiceOption
from pkg_resources import resource_filename
from uuid import UUID
import os
import shutil

class CrashDump(object):
    def __init__(self, uuid, env=None):
        self.uuid = uuid
        self.env = env

    def submit(self):
        with self.env.db_transaction as db:
            self.env.log.info("about to New crashdump: %s", str(self.uuid))
            db("INSERT INTO crashdump (uuid) VALUES (%s)", ( str(self.uuid) ) )
            self.env.log.info("New crashdump: %s", self.uuid)


class CrashDumpSubmit(Component):
    implements(IRequestHandler, IRequestFilter, ITemplateProvider)

    dumpdata_dir = Option('crashdump', 'dumpdata_dir', default='dumpdata',
                      doc='Path to the crash dump data directory.')

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
        if not id_str or id_str == '00000000-0000-0000-0000-000000000000' or id_str == '{00000000-0000-0000-0000-000000000000}':
            return self._error_response(req, status=HTTPForbidden.code, body='Invalid crash identifier %s specified.' % id_str)

        uuid = UUID(id_str)
        crashdump = CrashDump(uuid, env=self.env)
        force_str = req.args.get('force') or 'false'
        force = True if force_str.lower() == 'true' else False

        result = False
        ok, crashdump.minidumpFile = self._store_dump_file(uuid, req, 'minidump', force)
        if ok:
            result = True
        ok, crashdump.minidumpReportTextFile = self._store_dump_file(uuid, req, 'minidumpreport', force)
        if ok:
            result = True
        ok, crashdump.minidumpReportXMLFile = self._store_dump_file(uuid, req, 'minidumpreportxml', force)
        if ok:
            result = True
        ok, crashdump.minidumpReportHTMLFile = self._store_dump_file(uuid, req, 'minidumpreporthtml', force)
        if ok:
            result = True
        ok, crashdump.coredumpFile = self._store_dump_file(uuid, req, 'coredump', force)
        if ok:
            result = True
        ok, crashdump.coredumpReportTextFile = self._store_dump_file(uuid, req, 'coredumpreport', force)
        if ok:
            result = True
        ok, crashdump.coredumpReportXMLFile = self._store_dump_file(uuid, req, 'coredumpreportxml', force)
        if ok:
            result = True
        ok, crashdump.coredumpReportHTMLFile = self._store_dump_file(uuid, req, 'coredumpreporthtml', force)
        if ok:
            result = True
        ok, crashdump.gfxCapsFile = self._store_dump_file(uuid, req, 'gfxcaps', force)
        if ok:
            result = True

        crashdump.applicationFile = req.args.get('applicationfile')
        crashdump.timestamp = req.args.get('timestamp')

        crashdump.productName = req.args.get('productname')
        crashdump.productVersion = req.args.get('productversion')
        crashdump.productTargetVersion = req.args.get('producttargetversion')
        crashdump.uploadFQDN = req.args.get('fqdn')
        crashdump.uploadUsername = req.args.get('username')
        crashdump.buildType = req.args.get('buildtype')
        crashdump.buildPostfix = req.args.get('buildpostfix')
        crashdump.machineType = req.args.get('machinetype')
        crashdump.systemName = req.args.get('systemname')
        crashdump.osVersion = req.args.get('osversion')
        crashdump.osRelease = req.args.get('osrelease')
        crashdump.osMachine = req.args.get('osmachine')
        crashdump.sysinfo = req.args.get('sysinfo')

        if result:
            if crashdump.submit():
                return self._success_response(req, body='Crash dump %s uploaded successfully.' % uuid)
            else:
                return self._error_response(req, status=HTTPInternalError.code, body='Failed to add crash dump %s to database' % uuid)
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
