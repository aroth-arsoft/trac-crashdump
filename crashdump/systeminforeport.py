#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import sys
import base64
import posixpath
import ntpath
from datetime import datetime

from inifile import IniFile
from xmlreport import XMLReport
from utils import language_from_qlocale_language_enum, country_from_qlocale_country_enum, script_from_qlocale_script_enum

class _Terra3DDirectories(object):
    _dirlist = [
        ('ProgramFilesDirectory', 'Program files', None, None),
        ('ProgramDataDirectory', 'Program data', None, None),
        ('CacheDirectory', 'Cache', None, None),
        ('SystemTempDirectory', 'System temp', None, None),
        ('UserTempDirectory', 'User temp', None, None),
        ('UserPersistentTempDirectory', 'User persistent temp', None, None),
        ('ProgramLibrariesDirectory', 'Program libaries', 'ProgramFilesDirectory', '../lib'),
        ('OSGLibraryPath', 'OSG Library', 'ProgramDataDirectory', ''),
        ('CrashDumpDirectory', 'Crash dump', 'UserPersistentTempDirectory', 'dump'),
        ('DebugSymbolsDirectory', 'Debug symbols', 'ProgramFilesDirectory', '../pdb'),
        ('BreakpadSymbolsDirectory', 'Breakpad symbols', 'ProgramDataDirectory', 'breakpad_symbols'),
        ('VideoPluginDirectory', 'Video plugin', 'ProgramFilesDirectory', ''),
        ('CameraControlPluginDirectory', 'Camera control plugin', 'ProgramFilesDirectory', ''),
        ('CameraSensorPluginDirectory', 'Camera sensor plugin', 'ProgramFilesDirectory', ''),
        ('StatusPluginDirectory', 'Status plugin', 'ProgramFilesDirectory', ''),
        ('PythonModuleDirectory', 'Python module', 'ProgramFilesDirectory', 'share/pyshared'),
        ('PythonLibraryDirectory', 'Python library', 'ProgramFilesDirectory', ''),
        ('ConfigDirectory', 'Config', 'ProgramDataDirectory', 'etc'),
        ('DemoDirectory', 'Demo', 'ProgramDataDirectory', 'demo'),
        ('DocumentDirectory', 'Document', 'ProgramDataDirectory', 'documents'),
        ('LayerDirectory', 'Layer', 'ProgramDataDirectory', 'layers'),
        ('TourDirectory', 'Tour', 'ProgramDataDirectory', 'tours'),
        ('LicenseDirectory', 'License', 'ProgramDataDirectory', 'licenses'),
        ('SymbolDirectory', 'Symbol', 'ProgramDataDirectory', 'share/symbols'),
        ('Vicinity3DModelDirectory', 'Vicinity model', 'ProgramDataDirectory', 'vicinitymodels'),
        ('IconDirectory', 'Icon', 'ProgramFilesDirectory', '../share/icons'),
        ('StylesDirectory', 'Styles', 'ProgramFilesDirectory', '../share/styles'),
        ('CfgBinDirectory', 'Binary config', 'ProgramDataDirectory', 'cfgbin'),
        ('OemDirectory', 'OEM', 'ProgramDataDirectory', 'share/oem'),
        ('TextureDirectory', 'Texture', 'ProgramDataDirectory', 'share/textures'),
        ('DatabaseDirectory', 'Database', 'ProgramDataDirectory', 'db'),
        ('MissionsDirectory', 'Missions', 'ProgramDataDirectory', 'missions'),
        ('DatabaseScriptDirectory', 'Database script', 'ProgramDataDirectory', 'share/db'),
        ('DataFileDirectory', 'Data file', 'ProgramDataDirectory', 'share'),
        ('LocaleDirectory', 'Locale', 'ProgramDataDirectory', 'share/locale'),
        ('OSGDataFilePath', 'OSG data file', 'ProgramDataDirectory', ''),
        ('ModelFilesDirectory', 'Model files', 'ProgramDataDirectory', 'share/model'),
        ('WebIoDirectory', 'Web IO', 'ProgramDataDirectory', 'share/webio'),
        ('WebRootDirectory', 'Web root', 'ProgramDataDirectory', 'share/webroot'),
        ('AudioDirectory', 'Audio', 'ProgramDataDirectory', 'share/audio'),
        ('QmlDirectory', 'QML', 'ProgramDataDirectory', 'share/qml'),
        ('ManualDirectory', 'Manual', 'ProgramDataDirectory', 'share/doc'),
        ('ShaderDirectory', 'Shaders', 'ProgramDataDirectory', 'share/shaders'),
        ('GeneratedResourceDirectory', 'Generated resource', 'ProgramDataDirectory', 'generatedresources'),
        ]

    class _item(object):
        def __init__(self, name, description, value):
            self.name = name
            self.description = description
            self.value = value
        def __str__(self):
            return '%s=%s' % (self.name, self.value)

    def __init__(self, owner, section, key_path, default_value):
        values = {}
        for name, description, depend, rel_path in self._dirlist:
            values[name] = section.get(name, default=default_value)
        self._values = []
        for name, description, depend, rel_path in self._dirlist:
            value = values[name]
            if values[name] == '<<default>>':
                value = rel_path
            if depend is not None:
                if values[depend] is not None:
                    if owner.is_platform_windows:
                        value = ntpath.join(values[depend].replace('/', '\\'), value.replace('/', '\\'))
                    else:
                        value = posixpath.join(values[depend], value)
                else:
                    if owner.is_platform_windows:
                        value = '<<%s>>\\%s' % (depend, value.replace('/', '\\'))
                    else:
                        value = '<<%s>>/%s' % (depend, value)
            if value is not None:
                if owner.is_platform_windows:
                    value = ntpath.normpath(value.replace('/', '\\'))
                else:
                    value = posixpath.normpath(value)
            self._values.append( _Terra3DDirectories._item(name, description, value) )

    def __getitem__(self, name):
        return self._values.get(name)

    def __iter__(self):
        return iter(self._values)

class _SystemInfoCPU(object):
    _itemlist = [
        ('name', 'Vendor', str),
        ('brand', 'Name', str),
        ('num_cpu_cores', 'Number of CPU cores', int),
        ('num_logical_cpus', 'Number of logical CPU cores', int),
        ('HyperThread', 'Hyper-Threading', bool),
        ('SSE2', 'SSE2', bool),
        ('SSE3', 'SSE3', bool),
        ('SSSE3', 'SSSE3', bool),
        ('SSE4_1', 'SSE4_1', bool),
        ('SSE4_2', 'SSE4_2', bool),
        ('RTM', 'Restricted Transactional Memory (RTM)', bool),
        ('HLE', 'Hardware Lock Elision (HLE)', bool),
        ('AVX', 'AVX', bool),
        ('AVX2', 'AVX2', bool),
        ('AVX512', 'AVX512', bool),
        ('ARM_NEON', 'ARM Neon', bool),
        ('MIPS_DSP', 'MIPS DSP', bool),
        ('MIPS_DSPR2', 'MIPS DSPR2', bool),
        ('AES', 'AES', bool),
        ('XGETBV', 'XGETBV', bool),
        ('cpuid_max_standard_level', None, int),
        ('cpuid_max_hypervisor_level', None, int),
        ('cpuid_max_extended_level', None, int),
        ]

    class _item(object):
        def __init__(self, name, description, value):
            self.name = name
            self.description = description
            self.value = value
        def __str__(self):
            return '%s=%s' % (self.name, self.value)

    def __init__(self, owner, section, key_path, default_value):
        self._values = []
        for name, description, itemtype in self._itemlist:
            if itemtype == bool:
                value = section.getAsBoolean(name, default=False)
            elif itemtype == int:
                value = section.getAsInteger(name, default=0)
            else:
                value = section.get(name, default=default_value)
            self._values.append(_SystemInfoCPU._item(name, description, value))

    def __getitem__(self, name):
        for item in self._values:
            if item.name == name:
                return item
        return None

    def __iter__(self):
        return iter(self._values)

class _SystemInfoLocale(object):
    _itemlist = [
        ('language', 'Language', int, language_from_qlocale_language_enum),
        ('country', 'Country', int, country_from_qlocale_country_enum),
        ('script', 'Script', int, script_from_qlocale_script_enum),
        ('timezoneIanaId', 'Timezone', str, None),
        ]

    class _item(object):
        def __init__(self, name, description, value, convert_func):
            self.name = name
            self.description = description
            self.rawvalue = value
            self.convert_func = convert_func
            if self.convert_func is None:
                self.value = value
            else:
                self.value = self.convert_func(value)

        def __str__(self):
            return '%s=%s' % (self.name, self.value)

    def __init__(self, owner, section, key_path, default_value):
        self._values = []
        for name, description, itemtype, convert_func in self._itemlist:
            if itemtype == bool:
                value = section.getAsBoolean(name, default=False)
            elif itemtype == int:
                value = section.getAsInteger(name, default=0)
            else:
                value = section.get(name, default=default_value)
            self._values.append(_SystemInfoLocale._item(name, description, value, convert_func))

    def __getitem__(self, name):
        for item in self._values:
            if item.name == name:
                return item
        return None

    def __iter__(self):
        return iter(self._values)

class _SystemInfoNetwork(object):
    class _address(object):
        def __init__(self, section, prefix):
            self.addr = section.get(prefix + 'addr', None)
            self.netmask = section.get(prefix + 'netmask', None)
            self.broadcast = section.get(prefix + 'broadcast', None)
            self.flags = section.getAsInteger(prefix + 'flags', default=0)

        def __str__(self):
            if self.addr is None or not self.addr:
                return 'N/A'
            if self.netmask is not None and self.netmask:
                return str(self.addr) + '/' + str(self.netmask)
            else:
                return str(self.addr)

    class _interface(object):
        def __init__(self, section, prefix):
            self.index = section.getAsInteger(prefix + 'index', default=0)
            self.platform = section.getAsInteger(prefix + 'platform', default=0)
            self.name = section.get(prefix + 'platform', default=None)
            self.description = section.get(prefix + 'description', default=None)
            self.type = section.getAsInteger(prefix + 'type', default=0)
            self.status = section.getAsInteger(prefix + 'status', default=0)
            self.hwaddr = section.get(prefix + 'hwaddr', default=None)
            addrsize = section.getAsInteger(prefix + 'addr\\size', default=0)
            self.addr = []
            for i in range(1, addrsize + 1):
                self.addr.append(_SystemInfoNetwork._address(section, prefix + 'addr\\%i\\' % i))

        def __str__(self):
            return '%s={%s, %s}' % (self.name, self.hwaddr, self.addr)

    def __init__(self, owner, section, key_path, default_value):
        self._interfaces = []
        size = section.getAsInteger('Interface\\size', default=0)
        for i in range(1, size + 1):
            self._interfaces.append(_SystemInfoNetwork._interface(section, 'Interface\\%i\\' % i))

    def __getitem__(self, name):
        for item in self._interfaces:
            if item.name == name:
                return item
        return None

    def __iter__(self):
        return iter(self._interfaces)

class SystemInfoReport(object):
    _plain_arrays = ['OpenGLExtensions/Extension']
    _tuples = {
        'System/Path' : ['Dir', 'Ok'],
        'Process/Module': ['Path', 'BaseAddress', 'Size', 'EntryPoint', 'FileVersion', 'ProductVersion', 'Timestamp', 'TimestampUtc'],
        'Windows/hotfix': ['id'],
        'Network/Interface': ['index', 'name', 'description', 'hwaddr', 'loopback', 'up', 'running', 'wireless', 'pointtopoint', 'multicast', 'broadcast', 'addr'],

        'terra3d-dirs': _Terra3DDirectories,
        'CPU': _SystemInfoCPU,
        'locale': _SystemInfoLocale,
        'Network': _SystemInfoNetwork,
        }
    _dicts = ['Environment']

    class SystemInfoReportException(Exception):
        def __init__(self, report, message):
            super(SystemInfoReport.SystemInfoReportException, self).__init__(message)
            self._message = message
            self.report = report

        def __str__(self):
            return '%s(%s): %s' % (type(self).__name__, self.report._filename, self._message)


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
        self.platform_type = None
        self.is_64_bit = True

        if filename is not None:
            self.open(filename=filename)
        elif xmlreport is not None:
            self.open(xmlreport=xmlreport)

    def clear(self):
        self._filename = None
        self._ini = None

    def _get_as_plain_array(self, section, key, default_value):
        ret = []
        got_value = False
        num = 0
        while 1:
            value = self._ini.get(section, key + '%i' % num, None)
            if value is None:
                break
            got_value = True
            ret.append(value)
            num = num + 1
        if got_value:
            return ret
        else:
            return default_value

    def _get_tuples(self, section, key_path, names, default_value=None):
        if isinstance(names, type):
            ini_section = self._ini.section(section)
            if ini_section is not None:
                ret = names(self, ini_section, key_path, default_value)
            else:
                ret = default_value
        else:
            size = self._ini.getAsInteger(section, key_path + '\\size', None)
            if size is None:
                return default_value
            else:
                ret = []
                for i in range(1, size):
                    elem = {}
                    for n in names:
                        elem[n] = self._ini.get(section, key_path + '\\%i\\%s' % (i, n), None)
                    ret.append(elem)
        return ret

    def _get_dicts(self, section, key_path, names, default_value=None):
        ret = default_value
        if not key_path:
            ini_section = self._ini.section(section)
            if ini_section:
                ret = ini_section.get_all_as_dict()
        return ret

    def get(self, key, default_value=None):
        if self._ini is None:
            return default_value
        if '/' in key:
            section, key_path = key.split('/', 1)
            key_path = key_path.replace('/', '\\')
        else:
            section = key
            key_path = None
        if key in SystemInfoReport._plain_arrays:
            return self._get_as_plain_array(section, key_path, default_value)
        elif key in SystemInfoReport._tuples:
            return self._get_tuples(section, key_path, SystemInfoReport._tuples[key], default_value)
        elif key in SystemInfoReport._dicts:
            return self._get_dicts(section, key_path, default_value)
        elif isinstance(default_value, list):
            return self._ini.getAsArray(section, key_path, default_value)
        else:
            return self._ini.get(section, key_path, default_value)

    def __getitem__(self, name):
        return self.get(name)

    def _post_open(self):
        if self.platform_type is None:
            pass

    @property
    def is_platform_windows(self):
        return self.platform_type == 'Win32' or self.platform_type == 'Windows NT'

    def open(self, filename=None, xmlreport=None, minidump=None):
        if filename:
            try:
                self._ini = IniFile(filename, commentPrefix=';', keyValueSeperator='=', qt=True)
                self._filename = filename
            except IOError as e:
                raise SystemInfoReport.SystemInfoReportIOError(self, str(e))
        elif xmlreport is not None:
            self._xmlreport = xmlreport
            if xmlreport.fast_protect_system_info is None:
                raise SystemInfoReport.SystemInfoReportIOError(self, 'No system info include in XMLReport %s' % (xmlreport.filename))
            if sys.version_info[0] > 2:
                from io import StringIO
                stream = StringIO(xmlreport.fast_protect_system_info.rawdata.raw.decode('utf8'))
            else:
                from StringIO import StringIO
                stream = StringIO(xmlreport.fast_protect_system_info.rawdata.raw)
            self._ini = IniFile(filename=None, commentPrefix=';', keyValueSeperator='=', qt=True)
            self._ini.open(stream)
            self.platform_type = xmlreport.platform_type
            self.is_64_bit = xmlreport.is_64_bit
            #print('platform=%s' % (self.platform_type))
        elif minidump:
            raise SystemInfoReport.SystemInfoReportIOError(self, 'Not yet implemented')
        self._post_open()

    def save(self, filename):
        self._ini.save(filename)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('No system info report file(s) specified')
        sys.exit(1)

    if 1:
        sysinfo = SystemInfoReport(sys.argv[1])
    else:
        xmlreport = XMLReport(sys.argv[1])
        sysinfo = SystemInfoReport(xmlreport=xmlreport)

    #print(sysinfo.get('System/fqdn'))
    #print(sysinfo.get_tuples('System/Path', ['Ok', 'Dir']))

    #print(sysinfo.get_tuples('Qt/fonts/families', ['name']))
    #print(sysinfo.get_tuples('Qt/fonts/standardsizes', ['size']))

    #print(sysinfo.get('Qt/sysinfo/libraryinfobuild'))

    #print(sysinfo['OpenGLExtensions/Extension'])
    #print(sysinfo['System/Path'])
    print(sysinfo['Environment'])
    sysinfo.save('/tmp/sysinfo.ini')
    #print(sysinfo['Network/Interface'])
    #print('Win32' if sysinfo.is_platform_windows else 'Posix')
    #for dir in sysinfo['terra3d-dirs']:
    #    print('%s=%s' % (dir.description, dir.value))
    #for item in sysinfo['CPU']:
        #if item.description is None:
            #print('%s=%s (internal)' % (item.name, item.value))
        #else:
            #print('%s=%s' % (item.description, item.value))
    #print(sysinfo['terra3d-dirs']['DataFileDirectory'])
    #for item in sysinfo['locale']:
        #print('%s=%s' % (item.description, item.value))

    for item in sysinfo['Network']:
        print('%s=%s' % (item.description, item.hwaddr))
        for addr in item.addr:
            print('  %s' % (addr))

