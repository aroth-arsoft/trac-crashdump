#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import sys
import base64
from datetime import datetime
from uuid import UUID
from lxml import etree

class MemoryBlock(object):
    def __init__(self, memory):
        self._memory = memory
        self._hexdump = None

    @property
    def raw(self):
        return self._memory

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

    _main_fields = ['crash_info', 'system_info', 'file_info', 'exception',
                    'assertion', 'modules', 'threads', 'memory_regions',
                    'memory_blocks', 'handles', 'stackdumps' ]

    _crash_dump_fields = ['uuid', 'crash_timestamp', 'report_time', 'report_fqdn',
                          'report_username', 'application', 'command_line',
                          'symbol_directories', 'image_directories', 'environment']


    _system_info_fields = ['platform_type', 'cpu_type', 'cpu_64_bit', 'cpu_name', 'cpu_level', 'cpu_revision', 'cpu_vendor',
                            'number_of_cpus', 'os_version', 'os_version_info',
                            'distribution_id', 'distribution_release', 'distribution_codename', 'distribution_description' ]
    _file_info_fields = ['log']
    _exception_fields = ['threadid', 'code', 'name', 'info', 'address', 'flags']
    _assertion_fields = ['expression', 'function', 'source', 'line']

    _module_fields = ['base', 'size', 'timestamp', 'product_version', 'file_version', 'name', 'symbol_file', 'flags' ]
    _thread_fields = ['id', 'exception', 'name', 'memory', 'start_addr', 'create_time', 'exit_time', 'kernel_time', 'user_time' ]
    _memory_region_fields = ['base_addr', 'size', 'alloc_base', 'alloc_prot', 'type', 'protect', 'state' ]
    _memory_block_fields = ['num', 'base', 'size', 'memory']
    _handle_fields = ['handle', 'type', 'name', 'count', 'pointers' ]

    _stackdump_fields = ['threadid', 'exception']
    _stack_frame_fields = ['num', 'addr', 'retaddr', 'param0', 'param1', 'param2', 'param3', 'module', 'function', 'source', 'line', 'lineoff' ]

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

    _fast_protect_gfxcaps_fields = [
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
        'rawdata'
        ]

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
        print(self._filename)
        self._xml = etree.parse(self._filename) if self._filename else None

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

    class SystemInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.SystemInfo, self).__init__(owner)

    class FileInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.FileInfo, self).__init__(owner)

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

    class Assertion(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Assertion, self).__init__(owner)

    class Module(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Module, self).__init__(owner)

    class Thread(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Thread, self).__init__(owner)

        @property
        def stackdump(self):
            ret = None
            for st in self._owner.stackdumps:
                if st.threadid == self.id:
                    ret = st
                    break
            return ret

    class MemoryRegion(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.MemoryRegion, self).__init__(owner)

    class MemoryBlock(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.MemoryBlock, self).__init__(owner)
        @property
        def hexdump(self):
            return self.memory.hexdump

        @property
        def threadid(self):
            ret = None
            for thread in self._owner.threads:
                if thread.memory == self.base:
                    ret = thread.id
                    break
            return ret

    class Handle(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.Handle, self).__init__(owner)

    class StackDump(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.StackDump, self).__init__(owner)

        @property
        def involved_modules(self):
            module_order = []
            for frm in self.callstack:
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
    class FastProtectVersionInfo(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.FastProtectVersionInfo, self).__init__(owner)

    class FastProtectGfxCaps(XMLReportEntity):
        def __init__(self, owner):
            super(XMLReport.FastProtectGfxCaps, self).__init__(owner)

    @staticmethod
    def _value_convert(value_str, data_type):
        if data_type == 'uuid':
            return UUID(value_str)
        elif data_type == 'QString':
            return value_str
        elif data_type == 'QDateTime':
            return datetime.strptime(value_str, '%Y-%m-%d %H:%M:%S')
        elif data_type == 'bool':
            if value_str == 'true':
                return True
            elif value_str == 'false':
                return False
            else:
                return None
        elif data_type == 'int' or data_type == 'qlonglong':
            return int(value_str, 10)
        elif data_type == 'uint' or data_type == 'qulonglong':
            return int(value_str, 16)
        else:
            return str(value_str)

    @staticmethod
    def _get_node_value(node, child, default_value=None):
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
        r = node.xpath('/' + str(child))
        return r[0] if r else None

    @property
    def crash_info(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump')
        ret = XMLReport.CrashInfo(self) if i is not None else None
        if i is not None:
            for f in XMLReport._crash_dump_fields:
                setattr(ret, f, XMLReport._get_node_value(i, f))
        return ret

    @property
    def system_info(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/system_info')
        ret = XMLReport.SystemInfo(self) if i is not None else None
        if i is not None:
            for f in XMLReport._system_info_fields:
                setattr(ret, f, XMLReport._get_node_value(i, f))
        return ret

    @property
    def file_info(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/file_info')
        ret = XMLReport.FileInfo(self) if i is not None else None
        if i is not None:
            for f in XMLReport._file_info_fields:
                setattr(ret, f, XMLReport._get_node_value(i, f))
        return ret

    @property
    def exception(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/exception')
        ret = XMLReport.Exception(self) if i is not None else None
        if i is not None:
            for f in XMLReport._exception_fields:
                setattr(ret, f, XMLReport._get_node_value(i, f))
        return ret

    @property
    def assertion(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/assertion')
        ret = XMLReport.Assertion(self) if i is not None else None
        if i is not None:
            for f in XMLReport._assertion_fields:
                setattr(ret, f, XMLReport._get_node_value(i, f))
        return ret

    @property
    def modules(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/modules')
        ret = []
        all_subitems = i.xpath('module') if i is not None else None
        if all_subitems is not None:
            for item in all_subitems:
                m = XMLReport.Module(self)
                for f in XMLReport._module_fields:
                    setattr(m, f, XMLReport._get_node_value(item, f))
                ret.append(m)
        return ret

    @property
    def threads(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/threads')
        ret = []
        all_subitems = i.xpath('thread') if i is not None else None
        if all_subitems is not None:
            for item in all_subitems:
                m = XMLReport.Thread(self)
                for f in XMLReport._thread_fields:
                    setattr(m, f, XMLReport._get_node_value(item, f))
                ret.append(m)
        return ret

    @property
    def memory_regions(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/memory')
        ret = []
        all_subitems = i.xpath('memory') if i is not None else None
        if all_subitems is not None:
            for item in all_subitems:
                m = XMLReport.MemoryRegion(self)
                for f in XMLReport._memory_region_fields:
                    setattr(m, f, XMLReport._get_node_value(item, f))
                ret.append(m)
        return ret

    @property
    def memory_blocks(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/memory_blocks')
        ret = []
        all_subitems = i.xpath('memory_block') if i is not None else None
        if all_subitems is not None:
            for item in all_subitems:
                m = XMLReport.MemoryBlock(self)
                for f in XMLReport._memory_block_fields:
                    setattr(m, f, XMLReport._get_node_value(item, f))
                ret.append(m)
        return ret

    @property
    def handles(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/handle')
        ret = []
        all_subitems = i.xpath('handle') if i is not None else None
        if all_subitems is not None:
            for item in all_subitems:
                m = XMLReport.Handle(self)
                for f in XMLReport._handle_fields:
                    setattr(m, f, XMLReport._get_node_value(item, f))
                ret.append(m)
        return ret

    @property
    def stackdumps(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/stackdumps')
        ret = []
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

                ret.append(dump)
        return ret

    @property
    def fast_protect_version_info(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/fast_protect_version_info')
        ret = XMLReport.FastProtectVersionInfo(self) if i is not None else None
        if i is not None:
            for f in XMLReport._fast_protect_version_info_fields:
                setattr(ret, f, XMLReport._get_node_value(i, f))
        return ret

    @property
    def fast_protect_gfxcaps(self):
        i = XMLReport._get_first_node(self._xml, 'crash_dump/fast_protect_gfxcaps')
        ret = XMLReport.FastProtectGfxCaps(self) if i is not None else None
        if i is not None:
            for f in XMLReport._fast_protect_gfxcaps_fields:
                setattr(ret, f, XMLReport._get_node_value(i, f))
        return ret

    @property
    def fields(self):
        return self._main_fields

if __name__ == '__main__':
    xmlreport = XMLReport(sys.argv[1])
    #print(xmlreport.crash_info)
    print(xmlreport.system_info)
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

    #for m in xmlreport.threads:
        #print(type(m.id))

    print(xmlreport.fast_protect_version_info)
    print(xmlreport.fast_protect_gfxcaps)
    print(xmlreport.exception.involved_modules)
