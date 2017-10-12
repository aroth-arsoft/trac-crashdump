#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import sys
import base64
from datetime import datetime

from arsoft.inifile import IniFile
from xmlreport import XMLReport

class SystemInfoReport(object):

    class SystemInfoReportException(Exception):
        def __init__(self, report, message):
            super(SystemInfoReport.SystemInfoReportException, self).__init__(message)
            self.report = report

        def __str__(self):
            return '%s(%s): %s' % (type(self).__name__, self.report._filename, self.message)


    class SystemInfoReportIOError(SystemInfoReportException):
        def __init__(self, report, message):
            super(SystemInfoReport.SystemInfoReportIOError, self).__init__(report, message)

    class SystemInfoReportParserError(SystemInfoReportException):
        def __init__(self, report, message):
            super(SystemInfoReport.SystemInfoReportParserError, self).__init__(report, message)

    def __init__(self, filename=None, xmlreport=None):
        self._filename = None
        self._xmlreport = None
        self._ini = None

        if filename is not None:
            self.open(filename=filename)
        elif xmlreport is not None:
            self.open(xmlreport=xmlreport)

    def clear(self):
        self._filename = None
        self._ini = None

    def get(self, key, default_value=None):
        if self._ini is None:
            return default_value
        section, key_path = key.split('/', 1)
        key_path = key_path.replace('/', '\\')
        if isinstance(default_value, list):
            return self._ini.getAsArray(section, key_path, default_value)
        else:
            return self._ini.get(section, key_path, default_value)

    def get_tuples(self, key, names, default_value=None):
        if self._ini is None:
            return default_value
        section, key_path = key.split('/', 1)
        key_path = key_path.replace('/', '\\')
        size = self._ini.get(section, key_path + '\\size', None)
        if size is None:
            return default_value
        else:
            ret = []
            for i in range(1, int(size)):
                elem = {}
                for n in names:
                    elem[n] = self._ini.get(section, key_path + '\\%i\\%s' % (i, n), None)
                ret.append(elem)
        return ret

    def __getitem__(self, name):
        return self.get(name)

    def open(self, filename=None, xmlreport=None, minidump=None):
        if filename:
            try:
                self._ini = IniFile(filename, commentPrefix=';', keyValueSeperator='=', qt=True)
                self._filename = filename
            except IOError as e:
                raise SystemInfoReport.SystemInfoReportIOError(self, str(e))
        elif xmlreport:
            if isinstance(xmlreport, XMLReport):
                self._xmlreport = xmlreport
                if xmlreport.fast_protect_system_info is None:
                    raise SystemInfoReport.SystemInfoReportIOError(self, 'No system info include in XMLReport %s' % (str(xmlreport)))
                import StringIO
                stream = StringIO.StringIO(xmlreport.fast_protect_system_info.rawdata.raw)
                self._ini = IniFile(filename=None, commentPrefix=';', keyValueSeperator='=', qt=True)
                self._ini.open(stream)
            else:
                raise SystemInfoReport.SystemInfoReportIOError(self, 'Only XMLReport objects are supported: %s' % type(xmlreport))
        elif minidump:
            raise SystemInfoReport.SystemInfoReportIOError(self, 'Not yet implemented')

if __name__ == '__main__':
    if 0:
        sysinfo = SystemInfoReport(sys.argv[1])
    else:
        xmlreport = XMLReport(sys.argv[1])
        sysinfo = SystemInfoReport(xmlreport=xmlreport)

    print(sysinfo.get('System/fqdn'))
    print(sysinfo.get_tuples('System/Path', ['Ok', 'Dir']))

    print(sysinfo.get_tuples('Qt/fonts/families', ['name']))
    print(sysinfo.get_tuples('Qt/fonts/standardsizes', ['size']))

    print(sysinfo.get('Qt/sysinfo/libraryinfobuild'))


