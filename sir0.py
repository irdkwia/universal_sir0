import sys
import binascii
import xml.etree.ElementTree as ET

def deconstruct_sir0(sir0_data, ascii_comment=False, verbose=False):
    global struct_id
    struct_id = 0
    file_xml = []
    header_start = int.from_bytes(sir0_data[4:8], 'little')
    ptrlist_start = int.from_bytes(sir0_data[8:12], 'little')
    ptrlist = []
    pointed_addr = []
    multi_pointed_addr = []
    map_addr_id = dict()
    
    def handle_data(data, level):
        if len(data)>0:
            if verbose:
                print("\t"*level+("Data block size %d"%len(data)))
            file_xml.append("\t"*level+"<data>"+binascii.hexlify(data).decode("ascii")+"</data>")
            if ascii_comment:
                file_xml.append("\t"*level+"<!-- "+"".join(chr(b) if 0x20<=b<0x7F else "?" for b in data)+" -->")

    def read_ptr_struct(start, level=0):
        global struct_id
        if verbose:
            print("\t"*level+("Struct at 0x%08X"%start))
        if start in map_addr_id:
            file_xml.append("\t"*level+"<reference ref='"+map_addr_id[start]+"' />")
            return
        if start in multi_pointed_addr:
            file_xml.append("\t"*level+"<struct id='"+str(struct_id)+"'>")
            map_addr_id[start] = str(struct_id)
            struct_id += 1
        else:
            file_xml.append("\t"*level+"<struct>")
        end = pointed_addr[pointed_addr.index(start)+1]
        data_to_handle = b''
        for i in range(start, end, 4):
            if i in ptrlist:
                handle_data(data_to_handle, level+1)
                data_to_handle = b''
                read_ptr_struct(int.from_bytes(sir0_data[i:i+4], 'little'), level+1)
            else:
                data_to_handle += sir0_data[i:min(i+4, end)]
        handle_data(data_to_handle, level+1)
        file_xml.append("\t"*level+"</struct>")
    
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
        addr = int.from_bytes(sir0_data[cursor:cursor+4], 'little')
        if addr in pointed_addr:
            multi_pointed_addr.append(addr)
        else:
            pointed_addr.append(addr)
    pointed_addr.sort()
    if verbose:
        print("Reading data structures...")
    read_ptr_struct(header_start)
    return "\n".join(file_xml)

def construct_sir0(file_xml, verbose=False):
    global sir0_data
    sir0_data = bytearray(b"SIR0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    ptrlist = []
    map_id_addr = dict()
    reflist = dict()
    
    def handle_data(element):
        return binascii.unhexlify(element.text)
        
    def write_ptr_struct(element):
        global sir0_data
        struct_data = bytearray(0)
        pointers = []
        references = []
        for child in element:
            if child.tag=="struct":
                if verbose:
                    print("Encountered Struct!")
                if len(struct_data)%4:
                    raise Exception("Pointer is not 4 bytes aligned")
                pointers.append(len(struct_data))
                addr = write_ptr_struct(child)
                struct_data += addr.to_bytes(4, 'little')
                if 'id' in child.attrib:
                    map_id_addr[child.attrib['id']] = addr
            elif child.tag=="data":
                if verbose:
                    print("Encountered Data!")
                struct_data += handle_data(child)
            elif child.tag=="reference":
                if verbose:
                    print("Encountered Reference!")
                if len(struct_data)%4:
                    raise Exception("Pointer is not 4 bytes aligned")
                pointers.append(len(struct_data))
                references.append((child.attrib["ref"], len(struct_data)))
                struct_data += bytes(4)
        if len(struct_data)%4:
            struct_data += bytes(4-(len(struct_data)%4))
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
    header_start = write_ptr_struct(ET.fromstring(file_xml))
    for k, lv in reflist.items():
        addr = map_id_addr[k]
        for v in lv:
            sir0_data[v:v+4] = addr.to_bytes(4, 'little')
    if len(sir0_data)%16:
        sir0_data += bytes(16-(len(sir0_data)%16))
    if verbose:
        print("Writing pointer list...")
    ptrlist.append(4)
    ptrlist.append(8)
    ptrlist.sort()
    ptrlist_start = len(sir0_data)
    sir0_data[4:8] = header_start.to_bytes(4, 'little')
    sir0_data[8:12] = ptrlist_start.to_bytes(4, 'little')
    prev = 0
    for p in ptrlist:
        offset_to_encode = p-prev
        prev = p
        has_higher_non_zero = False
        for i in range(4, 0, -1):
            currentbyte = (offset_to_encode >> (7 * (i - 1))) & 0x7F
            if i == 1:
                sir0_data += bytes([currentbyte])
            elif currentbyte != 0 or has_higher_non_zero:
                sir0_data += bytes([currentbyte | 0x80])
                has_higher_non_zero = True
    sir0_data += bytes(1)
    if len(sir0_data)%16:
        sir0_data += bytes(16-(len(sir0_data)%16))
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
    if "-v" in lst_opts:
        verbose = True
    if "-a" in lst_opts:
        ascii_comment = True
    if "-d" in lst_opts:
        with open(arg[end_opt], 'rb') as file:
            xml = deconstruct_sir0(file.read(), ascii_comment=ascii_comment, verbose=verbose)
        with open(arg[end_opt+1], 'w') as file:
            file.write(xml)
    else:
        with open(arg[end_opt], 'r') as file:
            data = construct_sir0(file.read(), verbose=verbose)
        with open(arg[end_opt+1], 'wb') as file:
            file.write(data)
else:
    print("Usage: "+arg[0]+" <options> in_data out_data\n\nOptions:\n -a Ascii representation in comments (only for Deconstruct mode)\n -d Deconstruct\n -v Verbose")