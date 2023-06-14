#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" Binary firmware with ARM code to ELF converter.

 Converts BIN firmware with ARM code from a binary image form into
 ELF format. The ELF format can be then easily disassembled, as most
 tools can read ELF files.

 The BIN firmware is often linked and prepared like this:

```
  arm-none-eabi-ld \
   -EL -p --no-undefined --gc-sections \
   -nostdlib -nodefaultlibs -nostartfiles \
   -o out/firmware.elf -T custom_sections.lds \
   --start-group --whole-archive \
   lib/libapp.a \
   [...]
   lib/libmain.a \
   --no-whole-archive -lc -lnosys -lm -lgcc -lrdimon -lstdc++ \
   --end-group

  arm-none-eabi-nm -n -l out/firmware.elf

  arm-none-eabi-objcopy -O binary out/firmware.elf out/firmware.bin
```

 Note that the last command converts a linked ELF file into a binary
 memory image. The purpose of this tool is to revert that last operation,
 which makes it a lot easier to use tols like objdump or IDA Pro.

 The script uses an ELF template, which was prepared especially for BINs
 within DJI firmwares. It was made by compiling an example mock firmware,
 and then stripping all the data with use of objcopy.
"""

# Copyright (C) 2016,2017 Mefistotelis <mefistotelis@gmail.com>
# Copyright (C) 2018 Original Gangsters <https://dji-rev.slack.com/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__version__ = "0.3.1"
__author__ = "Mefistotelis @ Original Gangsters"
__license__ = "GPL"

import sys
import argparse
import os
import re
from ctypes import c_uint, sizeof, LittleEndianStructure

sys.path.insert(0, '../pyelftools')
try:
    import elftools.elf.elffile
    import elftools.elf.sections
    if not callable(getattr(elftools.elf.elffile.ELFFile, "write_changes", None)):
       raise ImportError("The pyelftools library provided has no write support")
except ImportError:
    print("Warning:")
    print("This tool requires version of pyelftools with ELF write support.")
    print("Get it from https://github.com/mefistotelis/pyelftools.git")
    print("clone to upper level folder, '../pyelftools'.")
    raise


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


class ExIdxEntry(LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
      ('tboffs', c_uint),
      ('entry', c_uint)
    ]

    def dict_export(self):
        d = dict()
        for (varkey, vartype) in self._fields_:
            val = getattr(self, varkey)
            d[varkey] = "{:08X}".format(val)
        return d

    def __repr__(self):
        d = self.dict_export()
        from pprint import pformat
        return pformat(d, indent=4, width=1)


def sign_extend(value, bits):
    """ Sign-extend an integer value from given amount of bits to full Python int
    """
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


def prel31_to_addr(ptr, refptr):
    """ Convert a prel31 symbol to an absolute address
    """
    offset = sign_extend(ptr, 31)
    return c_uint(refptr + offset).value


def armfw_is_proper_ARMexidx_entry(po, fwpartfile, eexidx, memaddr_base, func_align, arr_pos, ent_pos):
    """ Checks whether given ExIdxEntry object stores a proper entry of
        .ARM.exidx section. The entries are described in detail in
        "Exception Handling ABI for the ARM Architecture" document.
        The function assumes that .text section with code is located before
        the .ARM.exidx section, starting at memaddr_base.
    """
    sectname = ".ARM.exidx"
    # Spec states clearly this offset is "with bit 31 clear"
    if (eexidx.tboffs == 0) or (eexidx.tboffs & 0x80000000):
        return False
    glob_offs = prel31_to_addr(eexidx.tboffs, memaddr_base+ent_pos)
    # Check if first word offset falls into ".text" section and can be a function start
    if (glob_offs <= memaddr_base) or (glob_offs >= memaddr_base+arr_pos) or ((glob_offs % func_align) != 0):
        return False
    #TODO we could also check if the handling function starts with STORE/STM instruction; it is very unlikely to start in different way
    # Second word can be one of 3 things: table entry offset, exception entry itself or EXIDX_CANTUNWIND
    # Check if second word contains EXIDX_CANTUNWIND value (0x01)
    if (eexidx.entry == 0x01):
        if (po.verbose > 2):
            print("{}: Matching '{:s}' entry at 0x{:08x}: 0x{:08x} 0x{:08x} [CANTUNWIND]"
              .format(po.fwpartfile, sectname, ent_pos, glob_offs, eexidx.entry))
        return True
    # Check if second word contains exception handling entry itself
    if (eexidx.entry & 0x80000000):
        # According to specs, bits 30-28 should be zeros; personality routine and index are stored on lower bits
        if (eexidx.entry & 0x70000000):
            return False
        if (po.verbose > 2):
            print("{}: Matching '{:s}' entry at 0x{:08x}: 0x{:08x} 0x{:08x} [handling entry, idx 0x{:02x}]"
              .format(po.fwpartfile, sectname, ent_pos, glob_offs, eexidx.entry, (eexidx.entry >> 24) & 7))
        return True
    # Check if second word contains table entry start offset
    # the offset is not to the .data segment, but to a separate .ARM.extab segment
    # Let's assume this segment is somewhere adjacent to our .ARM.exidx segment
    # Size of the table entry which is being pointed at is no less than 4 bytes
    tbent_offs = prel31_to_addr(eexidx.entry, memaddr_base+ent_pos)
    if ((tbent_offs >= memaddr_base+arr_pos-po.expect_sect_align*0x10) and (tbent_offs <= memaddr_base+arr_pos-4) or
      (tbent_offs < memaddr_base+ent_pos+po.expect_sect_align*0x20) and (tbent_offs >= memaddr_base+ent_pos+sizeof(eexidx))):
        # We can assume the table is aligned; we don't know the size of the entry, but it is multiplication of 4
        if ((tbent_offs % 4) != 0):
            return False
        # Try to read at that offset - it should start with function address (so-called personality routine)
        fwpartfile.seek(tbent_offs-memaddr_base, os.SEEK_SET)
        pers_routine_offs = c_uint(0)
        if fwpartfile.readinto(pers_routine_offs) != sizeof(pers_routine_offs):
            return False
        if (pers_routine_offs.value <= memaddr_base) or (pers_routine_offs.value >= memaddr_base+arr_pos) or ((pers_routine_offs.value % func_align) != 0):
            return False
        if (po.verbose > 2):
            print("{}: Matching '{:s}' entry at 0x{:08x}: 0x{:08x} 0x{:08x} [table entry offs 0x{:08x}]"
              .format(po.fwpartfile, sectname, ent_pos, glob_offs, eexidx.entry, tbent_offs))
        return True
    return False


def armfw_detect_sect_ARMexidx(po, fwpartfile, memaddr_base, start_pos, func_align, sect_align):
    """ Finds position and size of .ARM.exidx section. That section contains entries
        used for exception handling, and have a particular structure that is quite easy
        to detect, with minimal amount of false positives.
    """
    sectname = ".ARM.exidx"
    eexidx = ExIdxEntry()
    match_count = 0
    match_pos = -1
    match_entries = 0
    reached_eof = False
    pos = start_pos
    assert sect_align >= sizeof(ExIdxEntry), "Section alignment exceeds .ARM.exidx entry size"
    while (True):
        # Check how many correct exception entries we have
        entry_count = 0
        entry_pos = pos
        while (True):
            fwpartfile.seek(entry_pos, os.SEEK_SET)
            if fwpartfile.readinto(eexidx) != sizeof(eexidx):
                reached_eof = True
                break
            if not armfw_is_proper_ARMexidx_entry(po, fwpartfile, eexidx, memaddr_base, func_align, pos, entry_pos):
                break
            entry_count += 1
            entry_pos += sizeof(eexidx)
        # Do not allow entry at EOF
        if (reached_eof):
            break
        # verify if padding area is completely filled with 0x00
        if (entry_count > 0):
            if ((entry_pos % sect_align) > 0):
                fwpartfile.seek(entry_pos, os.SEEK_SET)
                padding = fwpartfile.read(sect_align - (entry_pos % sect_align))
                if (padding[0] != 0x00) or (len(set(padding)) > 1):
                    entry_count = 0
        # If entry is ok, consider it a match
        if entry_count > 0:
            if (po.verbose > 1):
                print("{}: Matching '{:s}' section at 0x{:08x}: {:d} exception entries".format(po.fwpartfile,sectname,pos,entry_count))
            match_pos = pos
            match_entries = entry_count
            match_count += 1
        # Set position to search for next entry
        pos += sect_align
    if (match_count > 1):
        eprint("{}: Warning: multiple ({:d}) matches found for section '{:s}' with alignment 0x{:02x}"
          .format(po.fwpartfile,match_count,sectname,sect_align))
    if (match_count < 1):
        return -1, 0
    return match_pos, match_entries * sizeof(ExIdxEntry)


def armfw_detect_empty_sect_ARMexidx(po, fwpartfile, memaddr_base, start_pos, func_align, sect_align):
    """ Finds position of empty .ARM.exidx section. This is a last resort solution, when the
        section appears not to exist. In that case, we will try to find a zero-filled block
        which ends at an aligned offset; it is likely that the place where .text ends and .data starts
        will look like this.
    """
    match_count = 0
    match_pos = -1
    pos = start_pos
    while (True):
        fwpartfile.seek(pos, os.SEEK_SET)
        buf = fwpartfile.read(sect_align)
        if len(buf) != sect_align:
            break
        buf_set = set(buf)
        if (0x00 in buf_set) and (len(buf_set) == 1):
            match_pos = pos + sect_align
            match_count += 1
        elif (match_count > 0):
            break
        # Set position to search for next entry
        pos += sect_align
    if (match_count < 1):
        return -1, 0
    return match_pos, 0


def armfw_bin2elf_settle_sect_ARMexidx(po, fwpartfile):
    """ Find ARM exceptions index section and set it within `po`.

    It is easy to find, if it has any entries.
    """
    sectname = ".ARM.exidx"
    sect_align = po.expect_sect_align
    if (sectname not in po.section_addr):
        sect_pos, sect_len = armfw_detect_sect_ARMexidx(po, fwpartfile,  po.baseaddr, 0, po.expect_func_align, sect_align)
        if (sect_pos < 0):
            sect_align = (po.expect_sect_align >> 1)
            sect_pos, sect_len = armfw_detect_sect_ARMexidx(po, fwpartfile,  po.baseaddr, 0, po.expect_func_align, sect_align)
        if (sect_pos < 0):
            if (po.verbose > 1):
                eprint("{}: Warning: Real '{:s}' section not found, looking for empty one; consider manually providing its address"
                  .format(po.fwpartfile,sectname))
            sect_align = po.expect_sect_align
            sect_pos, sect_len = armfw_detect_empty_sect_ARMexidx(po, fwpartfile,  po.baseaddr, 0, po.expect_func_align, sect_align)
        if (sect_pos < 0):
            raise EOFError("No matches found for section '{:s}' in binary file.".format(sectname))
        po.section_addr[sectname] = po.baseaddr + sect_pos
    else:
        sect_pos = po.section_addr[sectname] - po.baseaddr
        sect_len = po.expect_sect_align
    if (sectname not in po.section_size):
        po.section_size[sectname] = sect_len
    else:
        sect_len = po.section_size[sectname]
    # Now we have position and length of the .ARM.exidx section within `po`
    if (po.verbose > 1):
        print("{}: Set '{:s}' section at mem addr 0x{:08x}, size 0x{:08x}"
          .format(po.fwpartfile,sectname,po.section_addr[sectname],po.section_size[sectname]))


def armfw_bin2elf_settle_sect_text(po, fwpartfile):
    """ Find ARM Target Executable section and set it within `po`.

    Let's assume that the .ARM.exidx section is located after .text section. While the .text section
    usually contains interrupt table located at offset 0, it doesn't mean it's first - we can't assume that.
    This is because interrupt vector address can be changed on most platforms. So RAM or MMIO sections can be
    before .text. Anyway, if user did not provided any .bss params, there is no way for us to automatically
    find any sections before .text, and since most platforms don't have them, let's assume there are none.
    """
    sectname = ".ARM.exidx"
    assert sectname in po.section_addr, "Settling '{:s}' not possible without '{:s}' settled".format(".text",sectname)
    sect_pos = po.section_addr[sectname] - po.baseaddr
    # Make sure we will not realign sections by mistake; we will update alignment in file later
    sect_align = 1

    sectname = ".text"
    if (sectname not in po.section_addr):
        if (sect_pos > po.expect_func_align * 8):
            po.section_addr[sectname] = po.baseaddr + 0x0
        else:
            raise EOFError("No place for '{:s}' section before the '{:s}' section in binary file."
              .format(sectname,".ARM.exidx"))
    if (sectname not in po.section_size):
        po.section_size[sectname] = sect_pos - (po.section_addr[sectname] - po.baseaddr)
    if (po.verbose > 1):
        print("{}: Set '{:s}' section at mem addr 0x{:08x}, size 0x{:08x}"
          .format(po.fwpartfile,sectname,po.section_addr[sectname],po.section_size[sectname]))


def armfw_bin2elf_settle_sect_data(po, fwpartfile):
    """ Find Data section and set it within `po`.

    After the .ARM.exidx section come .data section.
    """
    sectname = ".ARM.exidx"
    assert sectname in po.section_addr, "Settling '{:s}' not possible without '{:s}' settled".format(".data", sectname)
    sect_pos = po.section_addr[sectname] - po.baseaddr
    sect_len = po.section_size[sectname]
    # Make sure we will not realign sections by mistake; we will update alignment in file later
    sect_align = 1

    sectname = ".data"
    if (sectname not in po.section_addr):
        sect_pos += sect_len
        if (sect_pos % sect_align) != 0:
            sect_pos += sect_align - (sect_pos % sect_align)
        po.section_addr[sectname] = po.baseaddr + sect_pos
    else:
        sect_pos = po.section_addr[sectname] - po.baseaddr
    if (sectname not in po.section_size):
        fwpartfile.seek(0, os.SEEK_END)
        sect_len = fwpartfile.tell() - sect_pos
        po.section_size[sectname] = sect_len
    else:
        sect_len = po.section_size[sectname]
    if (po.verbose > 1):
        print("{}: Set '{:s}' section at mem addr 0x{:08x}, size 0x{:08x}"
          .format(po.fwpartfile,sectname,po.section_addr[sectname],po.section_size[sectname]))


def armfw_bin2elf_settle_sect_bss(po, fwpartfile):
    """ Find Block Starting Symbol sections and set it within `po`.

    This section stores statically allocated variables that are declared
    but have not been assigned a value - so its content is not stored.
    We can use it for defining any hardware-mapped areas as well.
    Set position for .bss to the place where it should be
    if it had the content stored. Allow multiple such sections.
    """
    sectname = ".data"
    assert sectname in po.section_addr, "Settling '{:s}' not possible without '{:s}' settled".format(".bss", sectname)
    sect_pos = po.section_addr[sectname] - po.baseaddr
    sect_len = po.section_size[sectname]
    sect_align = 1

    if True:
        sectname = ".bss"
        if (sectname not in po.section_addr):
            sect_pos += sect_len
            if (sect_pos % sect_align) != 0:
                sect_pos += sect_align - (sect_pos % sect_align)
            po.section_addr[sectname] = po.baseaddr + sect_pos
        else:
            sect_pos = po.section_addr[sectname] - po.baseaddr
        if (sectname not in po.section_size):
            sect_len = po.addrspacelen - sect_pos
            if (sect_len < 0): sect_len = 0
            po.section_size[sectname] = sect_len
        else:
            sect_len = po.section_size[sectname]
        if (po.verbose > 1):
            print("{}: Set '{:s}' section at mem addr 0x{:08x}, size 0x{:08x}"
              .format(po.fwpartfile,sectname,po.section_addr[sectname],po.section_size[sectname]))
    # Allow more .bss sections, as long as size is provided
    for sectname in po.section_size.keys():
        if not re.search('^[.]bss[0-9]+$', sectname):
            continue
        if (sectname not in po.section_size):
            break
        if (sectname not in po.section_addr):
            sect_pos += sect_len
            if (sect_pos % sect_align) != 0:
                sect_pos += sect_align - (sect_pos % sect_align)
            po.section_addr[sectname] = po.baseaddr + sect_pos
        else:
            sect_pos = po.section_addr[sectname] - po.baseaddr
        sect_len = po.section_size[sectname]
        if (po.verbose > 1):
            print("{}: Set '{:s}' section at mem addr 0x{:08x}, size 0x{:08x}"
              .format(po.fwpartfile,sectname,po.section_addr[sectname],po.section_size[sectname]))


def armfw_bin2elf_get_sections_order(po, addrspace_limit):
    """ Prepare list of sections in the order of position.
    """
    sections_order = []
    for sortaddr in sorted(set(po.section_addr.values())):
       if (sortaddr > addrspace_limit):
           eprint("{}: Warning: sections placed beyond address space limit, like at 0x{:x}, were not created"
             .format(po.fwpartfile,sortaddr))
           break
       # First add sections with size equal zero
       for sectname, addr in po.section_addr.items():
           if addr == sortaddr:
               if sectname in po.section_size.keys():
                   if (po.section_size[sectname] < 1):
                       sections_order.append(sectname)
       # The non-zero sized section should be last
       for sectname, addr in po.section_addr.items():
           if addr == sortaddr:
               if sectname not in sections_order:
                   sections_order.append(sectname)
    return sections_order


def armfw_bin2elf_copy_template(po):
    """ Copy an ELF template to destination file name.
    """
    #TODO this is old, non-pythonic code; use shutil instead?
    elf_templt = open(po.tmpltfile, "rb")
    if not po.dry_run:
        elf_fh = open(po.elffile, "wb")
    n = 0
    while (1):
        copy_buffer = elf_templt.read(1024 * 1024)
        if not copy_buffer:
            break
        n += len(copy_buffer)
        if not po.dry_run:
            elf_fh.write(copy_buffer)
    elf_templt.close()
    if not po.dry_run:
        elf_fh.close()
    if (po.verbose > 1):
        print("{}: ELF template '{:s}' copied to '{:s}', {:d} bytes"
          .format(po.fwpartfile, po.tmpltfile, po.elffile, n))


def armfw_bin2elf_get_sections_align(po, sections_order):
    """ Figure out alignment of sections.

    Needs to be called after addresses and sizes of sections are settled.
    """
    # Keep it near expected alignment, but adjust if the size does not meet expectations
    sections_align = {}
    for sectname in sections_order:
        sect_align = (po.expect_sect_align << 1)
        while (po.section_addr[sectname] % sect_align) != 0: sect_align = (sect_align >> 1)
        while (po.section_size[sectname] % sect_align) != 0: sect_align = (sect_align >> 1)
        sections_align[sectname] = sect_align
        if (po.verbose > 0):
            print("{}: Section '{:s}' alignment set to 0x{:02x}".format(po.fwpartfile, sectname, sections_align[sectname]))
    return sections_align


def armfw_bin2elf_get_sections_pos(po, sections_order):
    """ Prepare array of file positions.

    We have an array of target memory addresses; make them into an array of file offsets. Since BIN
    is a linear mem dump, addresses are the same as file offsets, only shifted by baseaddr.
    """
    sections_pos = {}
    for sectname in sections_order:
        sect_pos = po.section_addr[sectname] - po.baseaddr
        if (sect_pos < 0): sect_pos = 0
        sections_pos[sectname] = sect_pos
        if (po.verbose > 0):
            print("{}: Section '{:s}' file position set to 0x{:08x}"
              .format(po.fwpartfile, sectname, sections_pos[sectname]))
    return sections_pos


def armfw_bin2elf_update_sect_sizes(po, sections_order, addrspace_limit):
    """ Prepare list of section sizes.
    """
    sectaddr_next = po.baseaddr + po.addrspacelen + 1 # max size is larger than bin file size due to uninitialized sections (bss)
    for sectname in reversed(sections_order):
        sectpos_delta = sectaddr_next - po.section_addr[sectname]
        # Distance between sorted sections cannot be negative
        if sectname == sections_order[-1]:
            assert sectpos_delta >= 0, "Address space length too small to fit section '{:s}'".format(sectname)
        else:
            assert sectpos_delta >= 0, "Trusting addresses leads to negative distance after '{:s}'".format(sectname)
        # Do not allow to exceed limit imposed by address space bit length
        if (po.section_addr[sectname] + sectpos_delta > addrspace_limit + 1 - po.expect_sect_align):
            sectpos_delta = addrspace_limit + 1 - po.expect_sect_align - po.section_addr[sectname]
        assert sectpos_delta >= 0, "Trusting address limits leads to negative distance after '{:s}'".format(sectname)
        if sectname in po.section_size.keys():
            if (po.section_size[sectname] > sectpos_delta):
                eprint("{}: Warning: section '{:s}' size reduced to 0x{:x} due to overlapping"
                  .format(po.fwpartfile, sectname, sectpos_delta))
                po.section_size[sectname] = sectpos_delta
        else:
            po.section_size[sectname] = sectpos_delta
        sectaddr_next = po.section_addr[sectname]


def armfw_bin2elf_update_elffile(po, elf_fh, fwpartfile, sections_order, sections_pos, sections_align):
    """ Update the opened ELF template into a proper final ELF file.
    """
    # Update entry point in the ELF header
    elfobj = elftools.elf.elffile.ELFFile(elf_fh)
    elfobj.header['e_entry'] = po.baseaddr
    # Update section sizes, including the uninitialized (.bss*) sections
    for sectname in sections_order:
        # This function always returns a copy of section object, or newly created section object; so no need to copy it again
        sect = elfobj.get_section_by_name(sectname)
        # If no such section found, maybe we've added number at end
        sectname_m = None
        if sect is None:
            sectname_m = re.search('^(?P<name>[.].*[^0-9])(?P<num>[0-9]+)$', sectname)
            if sectname_m.group('name') is not None:
                sect = elfobj.get_section_by_name(sectname_m.group('name'))
            if sect is not None:
                sect.name = sectname
                sectname_prev = '{:s}{:d}'.format(sectname_m.group('name'), int(sectname_m.group('num'), 10) - 1)
                if elfobj.get_section_by_name(sectname_prev) is None:
                    sectname_prev = sectname_m.group('name')
                elfobj.insert_section_after(sectname_prev, sect)
        if sect is None:
            raise EOFError("Could not read section '{:s}' from binary file.".format(sectname))
        if (po.verbose > 0):
            print("{}: Preparing ELF section '{:s}' from binary pos 0x{:08x}"
              .format(po.fwpartfile, sectname, sections_pos[sectname]))
        sect.header['sh_addr'] = po.section_addr[sectname]
        sect.header['sh_addralign'] = sections_align[sectname]
        # for non-bss sections, size will be updated automatically when replacing data
        if sect.header['sh_type'] == 'SHT_NOBITS':
            sect.header['sh_size'] = po.section_size[sectname]
        elif po.section_size[sectname] <= 0:
            sect.set_data(b'')
        else:
            fwpartfile.seek(sections_pos[sectname], os.SEEK_SET)
            data_buf = fwpartfile.read(po.section_size[sectname])
            if not data_buf:
                raise EOFError("Couldn't read section '{:s}' from binary file.".format(sectname))
            sect.set_data(data_buf)
        if (po.verbose > 2):
            print("{}: Updating section '{:s}' and shifting subsequent sections".format(po.fwpartfile, sectname))
        elfobj.set_section_by_name(sectname, sect)
    if (po.verbose > 1):
        print("{}: Writing changes to '{:s}'".format(po.fwpartfile,po.elffile))
    if not po.dry_run:
        elfobj.write_changes()


def armfw_bin2elf(po, fwpartfile):
    if (po.verbose > 0):
        print("{}: Memory base address set to 0x{:08x}".format(po.fwpartfile,po.baseaddr))
    # detect position of each section in the binary file
    if (po.verbose > 1):
        print("{}: Searching for sections".format(po.fwpartfile))
    # currently we only support 32-bit arm; we'd need to read e_machine from template
    # and check if it's EM_AARCH64 in order to support the 64-bit spaces
    is_arm64 = False
    # set addresses and sizes of sections within `po`
    armfw_bin2elf_settle_sect_ARMexidx(po, fwpartfile)
    armfw_bin2elf_settle_sect_text(po, fwpartfile)
    armfw_bin2elf_settle_sect_data(po, fwpartfile)
    armfw_bin2elf_settle_sect_bss(po, fwpartfile)

    if is_arm64:
        addrspace_limit = 2**64 - 1
    else:
        addrspace_limit = 2**32 - 1

    sections_order = armfw_bin2elf_get_sections_order(po, addrspace_limit)
    armfw_bin2elf_update_sect_sizes(po, sections_order, addrspace_limit)

    sections_align = armfw_bin2elf_get_sections_align(po, sections_order)
    sections_pos = armfw_bin2elf_get_sections_pos(po, sections_order)

    # Create the ELF file from template
    armfw_bin2elf_copy_template(po)
    if (po.verbose > 0):
        print("{}: Updating entry point and section headers".format(po.fwpartfile))
    if not po.dry_run:
        elf_fh = open(po.elffile, 'r+b')
    else:
        elf_fh = open(po.tmpltfile, 'rb')
    armfw_bin2elf_update_elffile(po, elf_fh, fwpartfile, sections_order, sections_pos, sections_align)
    elf_fh.close()


def parse_section_param(s):
    """ Parses the section parameter argument.
    """
    sect = {'addr': {}, 'len': {},}
    arg_m = re.search('(?P<name>[0-9A-Za-z._-]+)(@(?P<addr>[Xx0-9A-Fa-f]+))?(:(?P<len>[Xx0-9A-Fa-f]+))?', s)
    # Convert to integer, detect base from prefix
    if arg_m.group('addr') is not None:
        sect['addr'][arg_m.group('name')] = int(arg_m.group('addr'), 0)
    if arg_m.group('len') is not None:
        sect['len'][arg_m.group('name')] = int(arg_m.group('len'), 0)
    return sect


def main():
    """ Main executable function.

    Its task is to parse command line options and call a function which performs requested command.
    """
    parser = argparse.ArgumentParser(description=__doc__.split('.')[0])

    parser.add_argument('-p', '--fwpartfile', type=str, required=True,
          help="executable ARM firmware binary module file")

    parser.add_argument('-o', '--elffile', type=str,
          help=("directory and file name of output ELF file "
           "(default is base name of fwpartfile with extension switched to elf, in working dir)"))

    parser.add_argument('-t', '--tmpltfile', type=str, default="arm_bin2elf_template.elf",
          help="template ELF file to use header fields from (default is \"%(default)s\")")

    parser.add_argument('-l', '--addrspacelen', default=0x2000000, type=lambda x: int(x,0),
          help=("set address space length after base; the tool will expect used "
            "addresses to end at baseaddr+addrspacelen, so it influences size "
            "of last section (defaults to max of 0x%(default)X and section ends computed "
            "from '--section' params)"))

    parser.add_argument('-b', '--baseaddr', default=0x1000000, type=lambda x: int(x,0),
          help=("set base address; first section from BIN file will start "
                 "at this memory location (defaults to 0x%(default)X)"))

    parser.add_argument('-s', '--section', action='append', metavar='SECT@ADDR:LEN', type=parse_section_param,
          help=("set section position and/or length; can be used to override "
           "detection of sections; setting section .ARM.exidx will influence "
           ".text and .data, moving them and sizing to fit one before and one "
           "after the .ARM.exidx. Parameters are: "
           "SECT - a text name of the section, as defined in elf template; multiple sections "
           "can be cloned from the same template section by adding index at end (ie. .bss2); "
           "ADDR - is an address of the section within memory (not input file position); "
           "LEN - is the length of the section (in both input file and memory, unless its "
           "uninitialized section, in which case it is memory size as file size is 0)"))

    parser.add_argument('--dry-run', action='store_true',
          help="do not write any files or do permanent changes")

    parser.add_argument('-v', '--verbose', action='count', default=0,
          help="increases verbosity level; max level is set by -vvv")

    subparser = parser.add_mutually_exclusive_group()

    subparser.add_argument('-e', '--mkelf', action='store_true',
          help="make ELF file from a binary image")

    subparser.add_argument('--version', action='version', version="%(prog)s {version} by {author}"
            .format(version=__version__, author=__author__),
          help="display version information and exit")

    po = parser.parse_args()

    po.expect_func_align = 2
    po.expect_sect_align = 0x10
    # For some reason, if no "--section" parameters are present, argparse leaves this unset
    if po.section is None:
        po.section = []
    # Flatten the sections we got in arguments
    po.section_addr = {}
    po.section_size = {}
    for sect in po.section:
        po.section_addr.update(sect['addr'])
        po.section_size.update(sect['len'])
    # Getting end of last section, to update address space length if it is too small
    if len(po.section_addr) > 0:
        sect_last = max(po.section_addr, key=po.section_addr.get)
        last_section_end = po.section_addr[sect_last] + po.section_size[sect_last] - po.baseaddr
        if (last_section_end > po.addrspacelen):
            po.addrspacelen = min(last_section_end, 0xFFFFFFFF)
            if (po.verbose > 0):
                print("{}: Address space length auto-expanded to 0x{:08X}".format(po.fwpartfile, po.addrspacelen))

    po.basename = os.path.splitext(os.path.basename(po.fwpartfile))[0]
    if len(po.fwpartfile) > 0 and (po.elffile is None or len(po.elffile) == 0):
        po.elffile = po.basename + ".elf"

    if po.mkelf:
        if (po.verbose > 0):
            print("{}: Opening for conversion to ELF".format(po.fwpartfile))
        with open(po.fwpartfile, 'rb') as fwpartfile:
            armfw_bin2elf(po, fwpartfile)

    else:
        raise NotImplementedError("Unsupported command.")


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        eprint("Error: "+str(ex))
        if 0: raise
        sys.exit(10)
