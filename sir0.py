import sys
import binascii
from xml.dom import minidom
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import ElementTree, Element, Comment

def deconstruct_sir0(sir0_data, endianness="little", ascii_comment=False, verbose=False):
    if sir0_data[0:4]!=b"SIR0":
        raise Exception("Not SIR0 data!")
    header_start = int.from_bytes(sir0_data[4:8], endianness)
    if header_start==0:
        mode = 8
        header_start = int.from_bytes(sir0_data[8:16], endianness)
        ptrlist_start = int.from_bytes(sir0_data[16:24], endianness)
    else:
        mode = 4
        ptrlist_start = int.from_bytes(sir0_data[8:12], endianness)
    ptrlist = []
    pointed_addr = []
    multi_pointed_addr = []
    map_addr_id = dict()
    
    def handle_data(data, element):
        if len(data)>0:
            if verbose:
                print("Data block size %d"%len(data))
            delt = Element("data")
            delt.text = binascii.hexlify(data).decode("ascii")
            element.append(delt)
            if ascii_comment:
                element.append(Comment(" "+("".join(chr(b) if 0x20<=b<0x7F else "?" for b in data))+" "))

    def read_ptr_struct(header_start, root, mode):
        struct_id = 0
        to_complete = [(header_start, root)]
        while len(to_complete)>0:
            start, element = to_complete[0]
            del to_complete[0]
            if verbose:
                print((("Struct at 0x%0"+str(mode*2)+"X")%start))
            if start in map_addr_id:
                element.tag = "reference"
                element.attrib["ref"] = map_addr_id[start]
                continue
            if start in multi_pointed_addr:
                element.attrib["id"] = str(struct_id)
                map_addr_id[start] = str(struct_id)
                struct_id += 1
            end = pointed_addr[pointed_addr.index(start)+1]
            data_to_handle = b''
            for i in range(start, end, mode):
                if i in ptrlist:
                    handle_data(data_to_handle, element)
                    data_to_handle = b''
                    sub = Element("struct")
                    element.append(sub)
                    to_complete.append((int.from_bytes(sir0_data[i:i+mode], endianness), sub))
                else:
                    data_to_handle += sir0_data[i:min(i+mode, end)]
            handle_data(data_to_handle, element)
    
    if verbose:
        print("Reading pointer list...")
    off_start = 0
    while True:
        cmd = 0x80
        cursor = 0
        while cmd&0x80:
            cmd = sir0_data[ptrlist_start]
            ptrlist_start += 1
            cursor <<= 7
            cursor |= cmd&0x7F
        if cursor==0:
            break
        cursor += off_start
        off_start = cursor
        ptrlist.append(cursor)
        addr = int.from_bytes(sir0_data[cursor:cursor+mode], endianness)
        if addr in pointed_addr:
            multi_pointed_addr.append(addr)
        else:
            pointed_addr.append(addr)
    pointed_addr.sort()
    if verbose:
        print("Reading data structures...")
    root = Element("struct", {"endianness": endianness, "mode": str(mode)})
    read_ptr_struct(header_start, root, mode)
    return minidom.parseString(ET.tostring(root)).toprettyxml(indent="\t")

def construct_sir0(file_xml, verbose=False):
    global sir0_data, mode, endianness
    root = ET.fromstring(file_xml)
    endianness = root.attrib.get("endianness", 'little')
    mode = int(root.attrib.get("mode", '4'))
    
    sir0_data = bytearray(mode*4)
    sir0_data[0:4] = b'SIR0'
    ptrlist = []
    map_id_addr = dict()
    reflist = dict()
    
    def handle_data(element):
        return binascii.unhexlify(element.text)
        
    def write_ptr_struct(element):
        global sir0_data, mode, endianness
        struct_data = bytearray(0)
        pointers = []
        references = []
        for child in element:
            if child.tag=="struct":
                if verbose:
                    print("Encountered Struct!")
                if len(struct_data)%mode:
                    raise Exception("Pointer is not "+str(mode)+" bytes aligned")
                pointers.append(len(struct_data))
                addr = write_ptr_struct(child)
                struct_data += addr.to_bytes(mode, endianness)
                if 'id' in child.attrib:
                    map_id_addr[child.attrib['id']] = addr
            elif child.tag=="data":
                if verbose:
                    print("Encountered Data!")
                struct_data += handle_data(child)
            elif child.tag=="reference":
                if verbose:
                    print("Encountered Reference!")
                if len(struct_data)%mode:
                    raise Exception("Pointer is not "+str(mode)+" bytes aligned")
                pointers.append(len(struct_data))
                references.append((child.attrib["ref"], len(struct_data)))
                struct_data += bytes(mode)
        if len(struct_data)%mode:
            struct_data += bytes(mode-(len(struct_data)%mode))
        loc = len(sir0_data)
        for ref, p in references:
            lp = reflist.get(ref, [])
            lp.append(loc+p)
            reflist[ref] = lp
        ptrlist.extend([loc+p for p in pointers])
        sir0_data += struct_data
        return loc
    if verbose:
        print("Writing data structures...")
    header_start = write_ptr_struct(root)
    for k, lv in reflist.items():
        addr = map_id_addr[k]
        for v in lv:
            sir0_data[v:v+mode] = addr.to_bytes(mode, endianness)
    if len(sir0_data)%mode:
        sir0_data += bytes(mode-(len(sir0_data)%mode))
    if verbose:
        print("Writing pointer list...")
    ptrlist.append(mode)
    ptrlist.append(mode*2)
    ptrlist.sort()
    ptrlist_start = len(sir0_data)
    sir0_data[mode:mode*2] = header_start.to_bytes(mode, endianness)
    sir0_data[mode*2:mode*3] = ptrlist_start.to_bytes(mode, endianness)
    prev = 0
    for p in ptrlist:
        offset_to_encode = p-prev
        prev = p
        has_higher_non_zero = False
        for i in range(mode, 0, -1):
            currentbyte = (offset_to_encode >> (7 * (i - 1))) & 0x7F
            if i == 1:
                sir0_data += bytes([currentbyte])
            elif currentbyte != 0 or has_higher_non_zero:
                sir0_data += bytes([currentbyte | 0x80])
                has_higher_non_zero = True
    sir0_data += bytes(1)
    if len(sir0_data)%mode:
        sir0_data += bytes(mode-(len(sir0_data)%mode))
    return bytes(sir0_data)

arg = sys.argv
end_opt = 1
lst_opts = []
while end_opt<len(arg):
    opt = arg[end_opt]
    if opt[0]!="-":
        break
    else:
        lst_opts.append(opt)
    end_opt += 1
if len(arg)-end_opt==2:
    ascii_comment = False
    verbose = False
    endianness = 'little'
    if "-v" in lst_opts:
        verbose = True
    if "-a" in lst_opts:
        ascii_comment = True
    if "-b" in lst_opts:
        endianness = 'big'
    if "-d" in lst_opts:
        with open(arg[end_opt], 'rb') as file:
            xml = deconstruct_sir0(file.read(), endianness=endianness, ascii_comment=ascii_comment, verbose=verbose)
        with open(arg[end_opt+1], 'w') as file:
            file.write(xml)
    else:
        with open(arg[end_opt], 'r') as file:
            data = construct_sir0(file.read(), verbose=verbose)
        with open(arg[end_opt+1], 'wb') as file:
            file.write(data)
else:
    print("Usage: "+arg[0]+" <options> in_data out_data\n\nOptions:\n -a Ascii representation in comments (only for Deconstruct mode)\n -b Big endian mode (only for Deconstruct mode)\n -d Deconstruct\n -v Verbose")
