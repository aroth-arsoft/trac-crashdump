#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import sys
import base64
from datetime import datetime
from uuid import UUID
from lxml import etree

from exception_info import exception_code_names_per_platform_type, exception_info_per_platform_type

class MemoryBlock(object):
    def __init__(self, memory):
        self._memory = memory
        self._hexdump = None

    @property
    def raw(self):
        return self._memory

    @property
    def size(self):
        return len(self._memory)

    @property
    def hexdump(self):
        if not self._hexdump:
            self._hexdump = self._generate_hexdump()
        return self._hexdump

    class HexDumpLine(object):
        def __init__(self, offset, memory_line, line_length):
            self.offset = offset
            self.raw = memory_line

            self.hex = ''
            self.ascii = ''
            idx = 0
            while idx < 16:
                if idx != 0:
                    self.hex += ' '
                if idx < line_length:
                    c = memory_line[idx]
                    c_i = ord(c)
                    self.hex += '%02X' % c_i
                    if c_i < 32 or c_i >= 127:
                        self.ascii += '.'
                    else:
                        self.ascii += c
                else:
                    self.hex += '  '
                    self.ascii += ' '
                idx += 1

    class HexDump(object):
        def __init__(self, size):
            if size > 65536:
                self.offset_width = 6
            elif size > 256:
                self.offset_width = 4
            else:
                self.offset_width = 2
            self._lines = []
            self._raw_offset = None
            self._raw_hex = None
            self._raw_ascii = None

        def __iter__(self):
            return iter(self._lines)

        def _generate_raw(self):
            self._raw_offset  = ''
            self._raw_hex  = ''
            self._raw_ascii  = ''
            offset_fmt = '0x%%0%dX' % self.offset_width
            first = True
            for line in self._lines:
                if not first:
                    self._raw_offset += '\r\n'
                    self._raw_hex += '\r\n'
                    self._raw_ascii += '\r\n'
                self._raw_offset += offset_fmt % line.offset
                self._raw_hex += line.hex
                self._raw_ascii += line.ascii
                first = False

        @property
        def raw_offset(self):
            if self._raw_offset is None:
                self._generate_raw()
            return self._raw_offset

        @property
        def raw_hex(self):
            if self._raw_hex is None:
                self._generate_raw()
            return self._raw_hex

        @property
        def raw_ascii(self):
            if self._raw_ascii is  None:
                self._generate_raw()
            return self._raw_ascii

    def _generate_hexdump(self):
        offset = 0
        total_size = len(self._memory)
        ret = MemoryBlock.HexDump(total_size)
        while offset < total_size:
            max_row = 16
            remain = total_size - offset
            if remain < 16:
                max_row = remain
            line = MemoryBlock.HexDumpLine(offset, self._memory[offset:offset + max_row], max_row)
            ret._lines.append(line)
            offset += 16
        return ret


class XMLReport(object):

    _main_fields = ['crash_info', 'platform_type', 'system_info', 'file_info', 'exception',
                    'assertion', 'modules', 'threads', 'memory_regions',
                    'memory_blocks', 'handles', 'stackdumps', 'simplified_info', 'processstatuslinux', 'processstatuswin32',
                    'processmemoryinfowin32', 'misc_info',
                    'fast_protect_version_info', 'fast_protect_system_info']

    _crash_dump_fields = ['uuid', 'crash_timestamp', 
                          'report_time', 'report_fqdn', 'report_username', 'report_hostname', 'report_domain', 
                          'application', 'command_line',
                          'symbol_directories', 'image_directories', 'usefulness_id', 'environment']

    _system_info_fields = ['platform_type', 'platform_type_id', 'cpu_type', 'cpu_type_id', 'cpu_name', 'cpu_level', 'cpu_revision', 'cpu_vendor',
                            'number_of_cpus', 'os_version', 'os_version_number', 'os_version_info',
                            'distribution_id', 'distribution_release', 'distribution_codename', 'distribution_description' ]
    _file_info_fields = ['log']
    _file_info_log_message_fields = ['time', 'text']
    _exception_fields = ['threadid', 'code', 'address', 'flags', 'numparams', 'param0', 'param1', 'param2', 'param3']
    _assertion_fields = ['expression', 'function', 'source', 'line', 'typeid']

    _module_fields = ['base', 'size', 'timestamp', 'product_version',
                      'file_version', 'name', 'symbol_file', 'symbol_id', 'symbol_type', 'symbol_type_number',
                      'image_name', 'module_name', 'module_id',
                      'flags' ]

    _thread_fields = ['id', 'exception', 'name', 'memory', 'start_addr', 'main_thread',
                      'create_time', 'exit_time', 'kernel_time', 'user_time',
                      'exit_status', 'cpu_affinity', 'stack_addr',
                      'suspend_count', 'priority_class', 'priority', 'teb', 'tls', 'tib',
                      'dump_flags', 'dump_error', 'rpc_thread'
        ]
    _memory_region_fields = ['base_addr', 'size', 'alloc_base', 'alloc_prot', 'type', 'protect', 'state' ]
    _memory_region_usage_fields = ['threadid', 'usagetype' ]
    _memory_block_fields = ['num', 'base', 'size', 'memory']
    _handle_fields = ['handle', 'type', 'name', 'count', 'pointers' ]

    _stackdump_fields = ['threadid', 'simplified', 'exception']
    _stack_frame_fields = ['num', 'addr', 'retaddr', 'param0', 'param1', 'param2', 'param3', 'infosrc', 'trust_level', 'module', 'function', 'funcoff', 'source', 'line', 'lineoff' ]
    
    _simplified_info_fields = ['threadid', 'missing_debug_symbols', 'missing_image_files', 'first_useful_modules', 'first_useful_functions']
    
    _processstatuslinux_fields = ['name', 'state', 'thread_group', 'pid', 
            'parent_pid', 'tracer_pid', 'real_uid', 'real_gid',
            'effective_uid', 'effective_gid', 'saved_set_uid', 'saved_set_gid',
            'filesystem_uid', 'filesystem_gid', 'num_file_descriptors', 'supplement_groups',
            'vmpeak', 'vmsize', 'vmlocked', 'vmpinned', 'vmhighwatermark',
            'vmresidentsetsize', 'vmdata', 'vmstack', 'vmexe', 'vmlib', 'vmpte',
            'vmswap', 'num_threads', 'voluntary_context_switches', 'nonvoluntary_context_switches',
        ]
    _processstatuswin32_fields = ['dll_path', 'image_path',
            'window_title', 'desktop_name', 'shell_info',
            'runtime_data', 'drive_letter_cwd', 
            'stdin_handle', 'stdout_handle', 'stderr_handle',
            'debug_flags', 'console_handle', 'console_flags',
            'session_id',
        ]
    _processmemoryinfowin32_fields = [
        'page_fault_count', 'peak_working_set_size',
        'working_set_size', 'quota_peak_paged_pool_usage',
        'quota_paged_pool_usage', 'quota_peak_non_paged_pool_usage',
        'quota_non_paged_pool_usage', 'pagefile_usage',
        'peak_pagefile_usage', 'private_usage'
        ]
    
    _misc_info_fields = ['processid', 'process_create_time',
            'user_time', 'kernel_time',
            'processor_max_mhz', 'processor_current_mhz', 'processor_mhz_limit',
            'processor_max_idle_state', 'processor_current_idle_state',
            'process_integrity_level',
            'process_execute_flags', 'protected_process',
            'timezone_id', 'timezone_bias',
            'timezone_standard_name', 'timezone_standard_bias', 'timezone_standard_date',
            'timezone_daylight_name', 'timezone_daylight_bias', 'timezone_daylight_date',
            'build_info', 'debug_build_info'
        ]

    _fast_protect_version_info_fields = [
        'product_name',
        'product_code_name',
        'product_version',
        'product_target_version',
        'root_revision',
        'buildtools_revision',
        'external_revision',
        'third_party_revision',
        'terra3d_revision',
        'jenkins_job_name',
        'jenkins_build_number',
        'jenkins_build_id',
        'jenkins_build_tag',
        'jenkins_build_url',
        'jenkins_git_revision',
        'jenkins_git_branch',
        'jenkins_master',
        'jenkins_nodename'
        ]

    _fast_protect_system_info_fields = [
        'hostname',
        'domain',
        'fqdn',
        'username',
        'timestamp',
        'system_temp_path',
        'user_temp_path',
        'user_persistent_path',
        'terminal_session_id',
        'virtual_machine',
        'remote_session',
        'machine_type',
        'opengl_vendor',
        'opengl_renderer',
        'opengl_version',
        'opengl_vendor_id',
        'opengl_driver_id',
        'opengl_chip_class',
        'opengl_driver_version',
        'opengl_hardware_ok',
        'opengl_use_pbuffer',
        'opengl_hardware_error',
        'opengl_pbuffer_error',
        'cpu_name',
        'cpu_vendor',
        'num_logical_cpus',
        'num_physical_cpus',
        'hyperthread',
        'rawdata'
        ]
    
    class XMLReportException(Exception):
        def __init__(self, report, message):
            super(XMLReport.XMLReportException, self).__init__(message)
            self.report = report

        def __str__(self):
            return '%s(%s): %s' % (type(self).__name__, self.report._filename, self.message)


    class XMLReportIOError(XMLReportException):
        def __init__(self, report, message):
            super(XMLReport.XMLReportIOError, self).__init__(report, message)

    class XMLReportParserError(XMLReportException):
        def __init__(self, report, message):
            super(XMLReport.XMLReportParserError, self).__init__(report, message)

    class ProxyObject(object):
        def __init__(self, report, field_name):
            object.__setattr__(self, '_report', report)
            object.__setattr__(self, '_field_name', field_name)
            object.__setattr__(self, '_real_object', None)

        def __getattr__(self, key):
            if self._real_object is None:
                object.__setattr__(self, '_real_object', getattr(self._report, self._field_name))
            if self._real_object is None:
                return None
            return getattr(self._real_object, key)

        def __setattr__(self, key, value):
            if self._real_object is None:
                object.__setattr__(self, '_real_object', getattr(self._report, self._field_name))
            if self._real_object is None:
                return None
            return setattr(self._real_object, key, value)

        def __iter__(self):
            if self._real_object is None:
                object.__setattr__(self, '_real_object', getattr(self._report, self._field_name))
            if self._real_object is None:
                return None
            return iter(self._real_object)

        def __nonzero__(self):
            if self._real_object is None:
                object.__setattr__(self, '_real_object', getattr(self._report, self._field_name))
            if self._real_object is None:
                return False
            return bool(self._real_object)

        def __len__(self):
            if self._real_object is None:
                object.__setattr__(self, '_real_object', getattr(self._report, self._field_name))
            if self._real_object is None:
                return None
            if hasattr(self._real_object, '__len__'):
                return len(self._real_object)
            else:
                return 0

    @staticmethod
    def unique(items):
        found = set()
        keep = []

        for item in items:
            if item not in found:
                found.add(item)
                keep.append(item)

        return keep

    def __init__(self, filename=None):
        self._filename = filename
        self._xml = None
        self._crash_info = None
        self._system_info = None
        self._file_info = None
        self._exception = None
        self._assertion = None
        self._threads = None
        self._modules = None
        self._memory_regions = None
        self._memory_blocks = None
        self._handles = None
        self._stackdumps = None
        self._simplified_info = None
        self._processstatuslinux = None
        self._processstatuswin32 = None
        self._processmemoryinfowin32 = None
        self._misc_info = None
        self._fast_protect_version_info = None
        self._fast_protect_system_info = None
        self._is_64_bit = None

        if self._filename:
            try:
                self._xml = etree.parse(self._filename)
            except IOError as e:
                raise XMLReport.XMLReportIOError(self, str(e))
            except etree.XMLSyntaxError as e:
                raise XMLReport.XMLReportParserError(self, str(e))

    @property
    def is_platform_windows(self):
        return self.platform_type == 'Win32' or self.platform_type == 'Windows NT'

    class XMLReportEntity(object):
        def __init__(self, owner):
            self._owner = owner

        def __str__(self):
            ret = ''
            for (k,v) in self.__dict__.items():
                if k[0] != '_':
                    if ret:
                        ret += ', '
                    ret = ret + '%s=%s' % (k,v)
            return ret

    class CrashInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.CrashInfo, self).__init__(owner)

        @property
        def path(self):
            ret = []
            env = getattr(self, 'environment', None)
            if env:
                for (k,v) in env.iteritems():
                    if k.lower() == 'path':
                        if self._owner.is_platform_windows:
                            ret = v.split(';')
                        else:
                            ret = v.split(':')
                        break
            return ret

    class SystemInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.SystemInfo, self).__init__(owner)

    class FileInfoLogMessage(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.FileInfoLogMessage, self).__init__(owner)

    class FileInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.FileInfo, self).__init__(owner)
            self.log = []

    class Exception(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Exception, self).__init__(owner)

        @property
        def thread(self):
            ret = None
            for thread in self._owner.threads:
                if thread.id == self.threadid:
                    ret = thread
                    break
            return ret

        @property
        def involved_modules(self):
            t = self.thread
            if t:
                return t.stackdump.involved_modules
            else:
                return None

        @property
        def params(self):
            ret = []
            if self.numparams >= 1:
                ret.append(self.param0)
            if self.numparams >= 2:
                ret.append(self.param1)
            if self.numparams >= 3:
                ret.append(self.param2)
            if self.numparams >= 4:
                ret.append(self.param3)
            return ret

        @property
        def name(self):
            if self._owner.platform_type in exception_code_names_per_platform_type:
                code_to_name_map = exception_code_names_per_platform_type[self._owner.platform_type]
                if self.code in code_to_name_map:
                    return code_to_name_map[self.code]
                else:
                    return 'Unknown(%x)' % (self._owner.platform_type, self.code)
            else:
                return 'UnknownPlatform(%s, %x)' % (self.code, self.code)
        @property
        def info(self):
            if self._owner.platform_type in exception_info_per_platform_type:
                ex_info_func = exception_info_per_platform_type[self._owner.platform_type]
                return ex_info_func(self)
            else:
                return 'UnknownPlatform(%s, %x)' % (self.code, self.code)

    class Assertion(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Assertion, self).__init__(owner)

    class Module(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Module, self).__init__(owner)
            self._basename = None

        @property
        def basename(self):
            if self._basename is None:
                idx = self.name.rfind('/')
                if idx < 0:
                    idx = self.name.rfind('\\')
                if idx >= 0:
                    self._basename = self.name[idx+1:]
                else:
                    self._basename = self.name
            return self._basename

    class Thread(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Thread, self).__init__(owner)

        @property
        def stackdump(self):
            ret = None
            for st in self._owner.stackdumps:
                if st.threadid == self.id and not st.simplified:
                    ret = st
                    break
            return ret

        @property
        def simplified_stackdump(self):
            ret = None
            for st in self._owner.stackdumps:
                if st.threadid == self.id and st.simplified:
                    ret = st
                    break
            return ret

    class MemoryRegion(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.MemoryRegion, self).__init__(owner)

    class MemoryRegionUsage(XMLReportEntity):
        def __init__(self, owner, region):
            super(XMLReport.MemoryRegionUsage, self).__init__(owner)
            self._region = region

        @property
        def thread(self):
            ret = None
            for thread in self._owner.threads:
                if thread.id == self.threadid:
                    ret = thread
                    break
            return ret

    class MemoryBlock(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.MemoryBlock, self).__init__(owner)
            self._thread_id = None

        @property
        def hexdump(self):
            return self.memory.hexdump

        @property
        def threadid(self):
            if self._thread_id is None:
                for thread in self._owner.threads:
                    if thread.memory == self.base:
                        self._thread_id = thread.id
                        break
            return self._thread_id

    class Handle(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Handle, self).__init__(owner)

    class StackDump(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.StackDump, self).__init__(owner)
            self._thread = None

        @property
        def thread(self):
            if self._thread is None:
                for thread in self._owner.threads:
                    if thread.id == self.threadid:
                        self._thread = thread
                        break
            return self._thread

        @property
        def involved_modules(self):
            module_order = []
            for frm in self.callstack:
                if frm.module:
                    module_order.append(frm.module)
            return XMLReport.unique(module_order)

    class StackFrame(XMLReportEntity):
        def __init__(self, owner, dump):
            super(XMLReport.StackFrame, self).__init__(owner)
            self._dump = dump

        @property
        def source_url(self):
            if self.source:
                return 'file:///' + self.source
            else:
                return None

        @property
        def params(self):
            # for the moment there are always four parameters
            ret = [ self.param0, self.param1, self.param2, self.param3]
            return ret

    class SimplifiedInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.SimplifiedInfo, self).__init__(owner)

    class MiscInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.MiscInfo, self).__init__(owner)

    class FastProtectVersionInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.FastProtectVersionInfo, self).__init__(owner)

    class FastProtectSystemInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.FastProtectSystemInfo, self).__init__(owner)

    class ProcessStatusLinux(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.ProcessStatusLinux, self).__init__(owner)

    class ProcessStatusWin32(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.ProcessStatusWin32, self).__init__(owner)

    class ProcessMemoryInfoWin32(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.ProcessMemoryInfoWin32, self).__init__(owner)

    @staticmethod
    def _value_convert(value_str, data_type):
        if data_type == 'uuid':
            try:
                return UUID(value_str)
            except ValueError:
                return None
        elif data_type == 'QString':
            return value_str
        elif data_type == 'QDateTime':
            try:
                return datetime.strptime(value_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return None
        elif data_type == 'bool':
            if value_str == 'true':
                return True
            elif value_str == 'false':
                return False
            else:
                return None
        elif data_type == 'int' or data_type == 'qlonglong':
            try:
                return int(value_str, 10)
            except ValueError:
                return None
        elif data_type == 'uint' or data_type == 'qulonglong':
            try:
                return int(value_str, 16)
            except ValueError:
                return None
        else:
            return str(value_str)

    @staticmethod
    def _get_node_value(node, child, default_value=None):
        if node is None:
            return default_value
        r = node.xpath(child + '/@type')
        data_type = r[0] if r else None

        if data_type == 'QStringList':
            all_subitems = node.xpath(child + '/item/text()')
            ret = []
            for c in all_subitems:
                ret.append(str(c))
        elif data_type == 'QVariantMap':
            all_subitems = node.xpath(child + '/item')
            ret = {}
            for item in all_subitems:
                r = item.xpath('@key')
                item_key = str(r[0]) if r else None

                r = item.xpath('@type')
                item_data_type = str(r[0]) if r else None

                r = item.xpath('text()')
                item_value = r[0] if r else None

                ret[item_key] = XMLReport._value_convert(item_value, item_data_type)
        elif data_type == 'QByteArray':
            r = node.xpath(child + '/@encoding-type')
            encoding_type = r[0] if r else None

            r = node.xpath(child + '/text()')
            value = r[0] if r else None
            if r:
                if encoding_type == 'base64':
                    ret = MemoryBlock(base64.b64decode(r[0]))
                else:
                    ret = MemoryBlock(str(r[0]))
            else:
                ret = default_value
        else:
            r = node.xpath(child + '/text()')
            if r:
                ret = XMLReport._value_convert(r[0], data_type)
            else:
                ret = default_value
        return ret

    @staticmethod
    def _get_attribute(node, attr_name, default_value=None):
        if node is None:
            return default_value
        r = node.xpath('@' + attr_name)
        attr_value = r[0] if r else None

        ok = False
        ret = None
        if attr_value:
            attr_value_low = attr_value.lower()
            if attr_value_low == 'true' or attr_value_low == 'on':
                ret = True
                ok = True
            elif attr_value_low == 'false' or attr_value_low == 'off':
                ret = False
                ok = True

            if not ok:
                if attr_value.startswith('0x'):
                    try:
                        ret = int(attr_value[2:], 16)
                        ok = True
                    except ValueError:
                        pass
            if not ok:
                try:
                    ret = int(attr_value)
                    ok = True
                except ValueError:
                    pass
            if not ok:
                ret = str(attr_value)
        return ret

    @staticmethod
    def _get_first_node(node, child):
        if node is None:
            return None
        r = node.xpath('/' + str(child))
        return r[0] if r else None

    @property
    def crash_info(self):
        if self._crash_info is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump')
            self._crash_info = XMLReport.CrashInfo(self) if i is not None else None
            if i is not None:
                for f in XMLReport._crash_dump_fields:
                    setattr(self._crash_info, f, XMLReport._get_node_value(i, f))
        return self._crash_info
    
    @property
    def platform_type(self):
        s = self.system_info
        if s is None:
            return None
        return s.platform_type
    
    @property
    def is_64_bit(self):
        if self._is_64_bit is None:
            s = self.system_info
            if s is None:
                return None
            # CPUTypeUnknown=-1
            # CPUTypeX86=0
            # CPUTypeMIPS=1
            # CPUTypeAlpha=2
            # CPUTypePowerPC=3
            # CPUTypeSHX=4
            # CPUTypeARM=5
            # CPUTypeIA64=6
            # CPUTypeAlpha64=7
            # CPUTypeMSIL=8
            # CPUTypeAMD64=9
            # CPUTypeX64_Win64=10
            # CPUTypeSparc=11
            # CPUTypePowerPC64=12
            # CPUTypeARM64=13
            if s.cpu_type_id == 0 or \
                s.cpu_type_id == 1 or \
                s.cpu_type_id == 2 or \
                s.cpu_type_id == 3 or \
                s.cpu_type_id == 4 or \
                s.cpu_type_id == 5 or \
                s.cpu_type_id == -1:
                self._is_64_bit = False
            elif s.cpu_type_id == 6 or \
                s.cpu_type_id == 7 or \
                s.cpu_type_id == 8 or \
                s.cpu_type_id == 9 or \
                s.cpu_type_id == 10 or \
                s.cpu_type_id == 11 or \
                s.cpu_type_id == 12 or \
                s.cpu_type_id == 13:
                self._is_64_bit = True
            else:
                self._is_64_bit = False
        return self._is_64_bit

    @property
    def system_info(self):
        if self._system_info is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/system_info')
            self._system_info = XMLReport.SystemInfo(self) if i is not None else None
            if i is not None:
                for f in XMLReport._system_info_fields:
                    setattr(self._system_info, f, XMLReport._get_node_value(i, f))
        return self._system_info

    @property
    def file_info(self):
        if self._file_info is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/file_info')
            self._file_info = XMLReport.FileInfo(self) if i is not None else None
            if i is not None:
                for f in XMLReport._file_info_fields:
                    if f != 'log':
                        setattr(self._file_info, f, XMLReport._get_node_value(i, f))
                i = XMLReport._get_first_node(self._xml, 'crash_dump/file_info/log')
                all_subitems = i.xpath('message') if i is not None else None
                if all_subitems is not None:
                    for item in all_subitems:
                        m = XMLReport.FileInfoLogMessage(self)
                        for f in XMLReport._file_info_log_message_fields:
                            setattr(m, f, XMLReport._get_node_value(item, f))
                        self._file_info.log.append(m)

        return self._file_info

    @property
    def exception(self):
        if self._exception is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/exception')
            self._exception = XMLReport.Exception(self) if i is not None else None
            if i is not None:
                for f in XMLReport._exception_fields:
                    setattr(self._exception, f, XMLReport._get_node_value(i, f))
        return self._exception

    @property
    def assertion(self):
        if self._assertion is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/assertion')
            self._assertion = XMLReport.Assertion(self) if i is not None else None
            if i is not None:
                for f in XMLReport._assertion_fields:
                    setattr(self._assertion, f, XMLReport._get_node_value(i, f))
        return self._assertion

    @property
    def modules(self):
        if self._modules is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/modules')
            self._modules = []
            all_subitems = i.xpath('module') if i is not None else None
            if all_subitems is not None:
                for item in all_subitems:
                    m = XMLReport.Module(self)
                    for f in XMLReport._module_fields:
                        setattr(m, f, XMLReport._get_node_value(item, f))
                    self._modules.append(m)
        return self._modules

    @property
    def threads(self):
        if self._threads is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/threads')
            self._threads = []
            all_subitems = i.xpath('thread') if i is not None else None
            if all_subitems is not None:
                for item in all_subitems:
                    m = XMLReport.Thread(self)
                    for f in XMLReport._thread_fields:
                        setattr(m, f, XMLReport._get_node_value(item, f))
                    if not self._threads:
                        m.main_thread = True
                    self._threads.append(m)
        return self._threads

    @property
    def memory_regions(self):
        if self._memory_regions is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/memory_info')
            self._memory_regions = []
            all_subitems = i.xpath('memory') if i is not None else None
            if all_subitems is not None:
                for item in all_subitems:
                    m = XMLReport.MemoryRegion(self)
                    for f in XMLReport._memory_region_fields:
                        setattr(m, f, XMLReport._get_node_value(item, f))

                    m.usage = []
                    all_subitems = item.xpath('usage')
                    if all_subitems is not None:
                        for item in all_subitems:
                            usage = XMLReport.MemoryRegionUsage(self, m)
                            for f in XMLReport._memory_region_usage_fields:
                                setattr(usage, f, XMLReport._get_node_value(item, f))
                            m.usage.append(usage)

                    self._memory_regions.append(m)
        return self._memory_regions

    @property
    def memory_blocks(self):
        if self._memory_blocks is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/memory_blocks')
            self._memory_blocks = []
            all_subitems = i.xpath('memory_block') if i is not None else None
            if all_subitems is not None:
                for item in all_subitems:
                    m = XMLReport.MemoryBlock(self)
                    for f in XMLReport._memory_block_fields:
                        setattr(m, f, XMLReport._get_node_value(item, f))
                    self._memory_blocks.append(m)
        return self._memory_blocks

    @property
    def handles(self):
        if self._handles is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/handle')
            self._handles = []
            all_subitems = i.xpath('handle') if i is not None else None
            if all_subitems is not None:
                for item in all_subitems:
                    m = XMLReport.Handle(self)
                    for f in XMLReport._handle_fields:
                        setattr(m, f, XMLReport._get_node_value(item, f))
                    self._handles.append(m)
        return self._handles

    @property
    def stackdumps(self):
        if self._stackdumps is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/stackdumps')
            self._stackdumps = []
            all_subitems = i.xpath('stackdump') if i is not None else None
            if all_subitems is not None:
                for item in all_subitems:
                    dump = XMLReport.StackDump(self)
                    for f in XMLReport._stackdump_fields:
                        setattr(dump, f, XMLReport._get_attribute(item, f))

                    dump.callstack = []
                    all_subitems = item.xpath('frame')
                    if all_subitems is not None:
                        for item in all_subitems:
                            frame = XMLReport.StackFrame(self, dump)
                            for f in XMLReport._stack_frame_fields:
                                setattr(frame, f, XMLReport._get_node_value(item, f))
                            dump.callstack.append(frame)

                    self._stackdumps.append(dump)
        return self._stackdumps

    @property
    def simplified_info(self):
        if self._simplified_info is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/simplified_info')
            self._simplified_info = XMLReport.SimplifiedInfo(self) if i is not None else None
            if i is not None:
                for f in XMLReport._simplified_info_fields:
                    setattr(self._simplified_info, f, XMLReport._get_node_value(i, f))
        return self._simplified_info

    @property
    def processstatuslinux(self):
        if self._processstatuslinux is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/processstatuslinux')
            self._processstatuslinux = XMLReport.ProcessStatusLinux(self) if i is not None else None
            if i is not None:
                for f in XMLReport._processstatuslinux_fields:
                    setattr(self._processstatuslinux, f, XMLReport._get_node_value(i, f))
        return self._processstatuslinux

    @property
    def processstatuswin32(self):
        if self._processstatuswin32 is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/processstatuswin32')
            self._processstatuswin32 = XMLReport.ProcessStatusWin32(self) if i is not None else None
            if i is not None:
                for f in XMLReport._processstatuswin32_fields:
                    setattr(self._processstatuswin32, f, XMLReport._get_node_value(i, f))
        return self._processstatuswin32

    @property
    def processmemoryinfowin32(self):
        if self._processmemoryinfowin32 is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/processmemoryinfowin32')
            self._processmemoryinfowin32 = XMLReport.ProcessMemoryInfoWin32(self) if i is not None else None
            if i is not None:
                for f in XMLReport._processmemoryinfowin32_fields:
                    setattr(self._processmemoryinfowin32, f, XMLReport._get_node_value(i, f))
        return self._processmemoryinfowin32

    @property
    def misc_info(self):
        if self._misc_info is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/misc_info')
            self._misc_info = XMLReport.MiscInfo(self) if i is not None else None
            if i is not None:
                for f in XMLReport._processstatuslinux_fields:
                    setattr(self._misc_info, f, XMLReport._get_node_value(i, f))
        return self._misc_info

    @property
    def fast_protect_version_info(self):
        if self._fast_protect_version_info is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/fast_protect_version_info')
            self._fast_protect_version_info = XMLReport.FastProtectVersionInfo(self) if i is not None else None
            if i is not None:
                for f in XMLReport._fast_protect_version_info_fields:
                    setattr(self._fast_protect_version_info, f, XMLReport._get_node_value(i, f))
        return self._fast_protect_version_info

    @property
    def fast_protect_system_info(self):
        if self._fast_protect_system_info is None:
            i = XMLReport._get_first_node(self._xml, 'crash_dump/fast_protect_system_info')
            self._fast_protect_system_info = XMLReport.FastProtectSystemInfo(self) if i is not None else None
            if i is not None:
                for f in XMLReport._fast_protect_system_info_fields:
                    setattr(self._fast_protect_system_info, f, XMLReport._get_node_value(i, f))
        return self._fast_protect_system_info

    @property
    def fields(self):
        return self._main_fields
    
    

if __name__ == '__main__':
    xmlreport = XMLReport(sys.argv[1])
    #print(xmlreport.crash_info)
    #print(xmlreport.system_info)
    #print(xmlreport.file_info)
    #for m in xmlreport.modules:
        #print(m)
    #for m in xmlreport.threads:
        #print(m)
    #for m in xmlreport.handles:
        #print(m)
    #for m in xmlreport.memory_regions:
        #print(m)
    #for m in xmlreport.stackdumps:
        #print('thread %u %s exception' % (m.threadid, 'with' if m.exception else 'without'))
        #for f in m.callstack:
            #print(f)
    #for m in xmlreport.memory_blocks:
        #fmt = '0x%%0%ix: %%s - %%s' % m.hexdump.offset_width
        #for l in m.hexdump:
            #print(fmt % (l.offset, l.hex, l.ascii))
    #for m in xmlreport.memory_blocks:
        #print(m.threadid)

    #for m in xmlreport.threads:
        #print(type(m.id))
        
    def dump_report_entity(entity, indent=0):
        for (k,v) in entity.__dict__.items():
            if k[0] != '_':
                if isinstance(v, list):
                    dump_report_list(v, indent+2)
                else:
                    print((' ' * indent) + '%s=%s' % (k,v))

    def dump_report_list(list, indent=0):
        for num, data_elem in enumerate(list):
            print((' ' * indent) + '%i:' % num)
            dump_report_entity(data_elem, indent + 2)
        
    def dump_report(rep, field, indent=0):
        print((' ' * indent) + field + ':')
        data = getattr(rep, field)
        if data is None:
            print('  None')
        elif isinstance(data, list):
            dump_report_list(data, indent+2)
        else:
            dump_report_entity(data, indent + 2)

    #dump_report(xmlreport, 'crash_info')
    #dump_report(xmlreport, 'system_info')
    #dump_report(xmlreport, 'file_info')
    #dump_report(xmlreport, 'fast_protect_version_info')
    #dump_report(xmlreport, 'fast_protect_system_info')
    #dump_report(xmlreport, 'simplified_info')
    #dump_report(xmlreport, 'modules')
    
    #if xmlreport.exception is not None:
        #print(xmlreport.exception.involved_modules)
        #print(xmlreport.exception.params)
    #dump_report(xmlreport, 'threads')
    #dump_report(xmlreport, 'memory_blocks')
    #dump_report(xmlreport, 'memory_regions')
    
    #dump_report(xmlreport, 'exception')

    #dump_report(xmlreport, 'processmemoryinfowin32')

    pp = XMLReport.ProxyObject(xmlreport, 'memory_regions')
    print(len(pp))

    pp = XMLReport.ProxyObject(xmlreport, 'memory_blocks')
    print(len(pp))
#for m in pp:
        #print(m)
    #dump_report(xmlreport, 'memory_regions')

    #print(xmlreport.crash_info.path)
    #sys.stdout.write(xmlreport.fast_protect_system_info.rawdata.raw)

    #if xmlreport.exception.thread.stackdump:
        #for (no, f) in enumerate(xmlreport.exception.thread.stackdump.callstack):
            #print('%i: %s' % (no, f))
    #else:
        #print('  no stackdump available')
    #print('Simplified Stackdump')
    #if xmlreport.exception.thread.simplified_stackdump:
        #for (no, f) in enumerate(xmlreport.exception.thread.simplified_stackdump.callstack):
            #print('%i: %s' % (no, f))
            #print('%i: %s' % (no, f.params))
    #else:
        #print('  no simplified stackdump available')
