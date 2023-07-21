import sys
import binascii
from xml.dom import minidom
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import ElementTree, Element, Comment
from xml.sax.saxutils import escape

from functools import partial

def encode_utf8(_, element):
    i = 0
    encoded = b''
    text = element.text or ""
    while i<len(text):
        if text[i]=="\\":
            if text[i+1]=="\\":
                encoded += b"\\"
                i += 2
            else:
                v = int(text[i+2:i+4],16)
                encoded += bytes([v])
                i += 4
        else:
            encoded += text[i].encode("utf-8")
            i += 1
    return encoded+bytes(1)

def encode_utf16(constructor, element):
    i = 0
    encoded = b''
    text = element.text or ""
    while i<len(text):
        if text[i]=="\\":
            if text[i+1]=="\\":
                encoded += b"\\"
                i += 2
            else:
                v = int(text[i+2:i+6],16)
                if constructor.endianness=='little':
                    encoded += bytes([v&0xFF,v>>8])
                else:
                    encoded += bytes([v>>8,v&0xFF])
                i += 6
        else:
            encoded += text[i].encode("utf-16-le" if constructor.endianness=='little' else "utf-16-be")
            i += 1
    return encoded+bytes(2)

def fraw(_, element, chunk):
    element.text += binascii.hexlify(bytes([chunk[0]])).decode("ascii")
    return chunk[1:]

def fuint(d, element, chunk, size=0):
    if size==0:
        size = d.mode
    element.text = str(int.from_bytes(chunk[:size], d.endianness))
    return chunk[size:]

def fint(d, element, chunk, size=0):
    if size==0:
        size = d.mode
    element.text = str(int.from_bytes(chunk[:size], d.endianness, signed=True))
    return chunk[size:]

def fstr8(_, element, chunk):
    element.text = ""
    for i in range(len(chunk)):
        if chunk[i]==0:
            break
        if 0x20<=v<0x7F:
            if chr(v)=="\\":
                element.text += "\\\\"
            else:
                element.text += chr(v)
        else:
            element.text += "\\x%02X"%v
    return b''

def fstr16(d, element, chunk):
    final = 0
    element.text = ""
    for i in range(0,len(chunk),2):
        v = int.from_bytes(chunk[i:i+2], d.endianness)
        if v==0:
            break
        if 0x20<=v<0x7F:
            if chr(v)=="\\":
                element.text += "\\\\"
            else:
                element.text += chr(v)
        else:
            element.text += "\\x%04X"%v
    return b''

def fsir0(d, element, chunk):
    list_slash = element.attrib["type"].split("/")
    element.attrib["type"] = list_slash[0]
    if len(list_slash)==2:
        yml_data = d.yml_data
        start_type = list_slash[1]
    else:
        yml_data = None
        start_type = None
    print(list_slash, start_type)
    xml = d.__class__(chunk, yml_data=yml_data, endianness=d.endianness, prefix=str(d.nb_prefix)+"_"+d.prefix, start_type=start_type, ascii_comment=d.ascii_comment, verbose=d.verbose).deconstruct()
    d.nb_prefix += 1
    element.append(xml)
    return b''

DECONSTRUCT_HANDLERS = {
    "skip": (True, fraw),
    "raw": (True, fraw),
    "uint": (False, fuint),
    "uint8": (False, partial(fuint, size=1)),
    "uint16": (False, partial(fuint, size=2)),
    "uint32": (False, partial(fuint, size=4)),
    "uint64": (False, partial(fuint, size=8)),
    "int": (False, fint),
    "int8": (False, partial(fint, size=1)),
    "int16": (False, partial(fint, size=2)),
    "int32": (False, partial(fint, size=4)),
    "int64": (False, partial(fint, size=8)),
    "str8": (False, fstr8),
    "str16": (False, fstr16),
    "sir0": (False, fsir0),
    "padding": (False, lambda: b''),
}

CONSTRUCT_HANDLERS = {
    "raw": lambda _, element: binascii.unhexlify(element.text),
    "uint": lambda c, element: int(element.text).to_bytes(c.mode, c.endianness),
    "uint8": lambda c, element: int(element.text).to_bytes(1, c.endianness),
    "uint16": lambda c, element: int(element.text).to_bytes(2, c.endianness),
    "uint32": lambda c, element: int(element.text).to_bytes(4, c.endianness),
    "uint64": lambda c, element: int(element.text).to_bytes(8, c.endianness),
    "int": lambda c, element: int(element.text).to_bytes(c.mode, c.endianness, signed=True),
    "int8": lambda c, element: int(element.text).to_bytes(1, c.endianness, signed=True),
    "int16": lambda c, element: int(element.text).to_bytes(2, c.endianness, signed=True),
    "int32": lambda c, element: int(element.text).to_bytes(4, c.endianness, signed=True),
    "int64": lambda c, element: int(element.text).to_bytes(8, c.endianness, signed=True),
    "str8": encode_utf8,
    "str16": encode_utf16,
    "sir0": lambda c, element: c.__class__(element[0], c.verbose).construct(),
    
}

class SIR0Cursor:
    def __init__(self, struct_data, typeelt):
        self.struct_data = struct_data
        self.stack = [[((typeelt,1),),0,0]]
        self.last_elt = None

    def get_next_element(self, move=True):
        if self.last_elt:
            last_elt = self.last_elt
            if move:
                self.last_elt = None
            return last_elt
        while self.stack[-1][1]>=len(self.stack[-1][0]):
            del self.stack[-1]
        confirmed_elt = None
        while confirmed_elt is None:
            next_elt = self.stack[-1][0][self.stack[-1][1]]
            self.stack[-1][2] += 1
            if self.stack[-1][2]==next_elt[1]:
                self.stack[-1][2] = 0
                self.stack[-1][1] += 1
            if next_elt[0].startswith("*") or next_elt[0].split("/")[0] in DECONSTRUCT_HANDLERS:
                confirmed_elt = next_elt[0]
            else:
                self.stack.append([self.struct_data[next_elt[0]],0,0])
        if not move:
            self.last_elt = confirmed_elt
        return confirmed_elt
        

class SIR0Deconstructor:
    def __init__(self, sir0_data, endianness='little', yml_data=None, prefix="", start_type="Root", ascii_comment=False, verbose=False):
        self.sir0_data = sir0_data
        self.yml_data = yml_data
        self.endianness = endianness
        self.prefix = prefix
        self.start_type = start_type
        self.ascii_comment = ascii_comment
        self.verbose = verbose

        self.mode = 4
        self.nb_prefix = 0
        
        self.pointer_list = []
        self.pointed_addr = []
        self.multi_pointed_addr = []
        self.map_addr_id = dict()

        self.struct_data = None

    def handle_data(self, data, element, cursor):
        if len(data)>0:
            if self.verbose:
                print("Data block size %d"%len(data))
            last_data = None
            chunk = data
            while len(chunk)>0:
                typenextall = cursor.get_next_element(move=False)
                typenext = cursor.get_next_element().split("/")[0]
                if typenext.startswith("*"):
                    delt = Element("data")
                    delt.text = ""
                    delt.attrib["type"] = "uint"
                    chunk = fuint(self, delt, chunk)
                    element.append(delt)
                    continue
                if typenext=="padding":
                    break
                if last_data!=typenext or not DECONSTRUCT_HANDLERS[typenext][0]:
                    last_data = typenext
                    delt = Element("data")
                    delt.text = ""
                    if typenext not in ["raw", "skip"]:
                        delt.attrib["type"] = typenextall
                    element.append(delt)
                chunk = DECONSTRUCT_HANDLERS[typenext][1](self, delt, chunk)
            if self.ascii_comment:
                element.append(Comment(" "+("".join(chr(b) if 0x20<=b<0x2D or 0x2E<=b<0x7F else "?" for b in data))+" "))

    def read_ptr_struct(self, header_start, root, typeroot):
        struct_id = 0
        to_complete = [(header_start, root, typeroot)]
        while len(to_complete)>0:
            start, element, typeelt = to_complete[0]
            del to_complete[0]
            if verbose:
                print((("Struct at 0x%0"+str(self.mode*2)+"X, %s")%(start, typeelt)))
            if typeelt:
                cursor = SIR0Cursor(self.struct_data, typeelt)
            else:
                cursor = SIR0Cursor({"void": (("skip",0),)}, "void")
            if start in self.map_addr_id:
                element.tag = "reference"
                element.attrib["ref"] = self.map_addr_id[start]
                continue
            if start in self.multi_pointed_addr:
                element.attrib["id"] = self.prefix+str(struct_id)
                self.map_addr_id[start] = self.prefix+str(struct_id)
                struct_id += 1
            end = self.pointed_addr[self.pointed_addr.index(start)+1]
            data_to_handle = b''
            for i in range(start, end, self.mode):
                if i in self.ptrlist:
                    self.handle_data(data_to_handle, element, cursor)
                    data_to_handle = b''
                    sub = Element("struct")
                    element.append(sub)
                    typenext = cursor.get_next_element()
                    if typenext.startswith("*"):
                       typenext = typenext[1:]
                    elif typenext=="skip":
                        for j in range(self.mode-1):
                            cursor.get_next_element()
                        typenext = None
                    else:
                        raise Exception("Invalid pointer type '%s'!"%typenext)
                    to_complete.append((int.from_bytes(self.sir0_data[i:i+self.mode], self.endianness), sub, typenext))
                else:
                    data_to_handle += self.sir0_data[i:min(i+self.mode, end)]
            self.handle_data(data_to_handle, element, cursor)

    def deconstruct(self):
        if self.sir0_data[0:4]!=b"SIR0":
            raise Exception("Not SIR0 data!")
        header_start = int.from_bytes(self.sir0_data[4:8], self.endianness)
        if header_start==0:
            self.mode = 8
            header_start = int.from_bytes(self.sir0_data[8:16], self.endianness)
            ptrlist_start = int.from_bytes(self.sir0_data[16:24], self.endianness)
        else:
            self.mode = 4
            ptrlist_start = int.from_bytes(self.sir0_data[8:12], self.endianness)
        self.ptrlist = []
        self.pointed_addr = []
        self.multi_pointed_addr = []
        self.map_addr_id = dict()

        self.nb_prefix = 0
        
        if self.yml_data:
            self.struct_data = dict()
            current = None
            for l in self.yml_data.split("\n"):
                l = l.strip()
                if l.startswith("-"):
                    l = l[1:].strip().split("[")
                    if len(l)==2:
                        br = l[1].split("]")[0].strip()
                        if br!="":
                            br = int(br)
                        else:
                            br = 0
                    else:
                        br = 1
                    self.struct_data[current].append((l[0].strip(), br))
                elif l!="":
                    current = l
                    self.struct_data[current] = []
        else:
            self.struct_data = None
        if self.verbose:
            print("Reading pointer list...")
        off_start = 0
        while True:
            cmd = 0x80
            cursor = 0
            while cmd&0x80:
                cmd = self.sir0_data[ptrlist_start]
                ptrlist_start += 1
                cursor <<= 7
                cursor |= cmd&0x7F
            if cursor==0:
                break
            cursor += off_start
            off_start = cursor
            self.ptrlist.append(cursor)
            addr = int.from_bytes(self.sir0_data[cursor:cursor+self.mode], self.endianness)
            if addr in self.pointed_addr:
                self.multi_pointed_addr.append(addr)
            else:
                self.pointed_addr.append(addr)
        self.pointed_addr.sort()
        if verbose:
            print("Reading data structures...")
        root = Element("struct", {"endianness": self.endianness, "mode": str(self.mode)})
        self.read_ptr_struct(header_start, root, self.start_type if self.struct_data else None)
        return root

class SIR0Constructor:
    def __init__(self, root, verbose=False):
        self.root = root
        self.verbose = verbose

        self.ptrlist = []
        self.map_id_addr = dict()
        self.reflist = dict()
        
        self.sir0_data = bytearray()
        self.mode = 4
        self.endianness = 'little'

    def handle_data(self, element):
        etype = element.attrib.get("type", "raw")
        return CONSTRUCT_HANDLERS[etype](self, element)
        
    def write_ptr_struct(self, element):
        struct_data = bytearray(0)
        pointers = []
        references = []
        for child in element:
            if child.tag=="struct":
                if self.verbose:
                    print("Encountered Struct!")
                if len(struct_data)%self.mode:
                    raise Exception("Pointer is not "+str(self.mode)+" bytes aligned")
                pointers.append(len(struct_data))
                addr = self.write_ptr_struct(child)
                struct_data += addr.to_bytes(self.mode, self.endianness)
                if 'id' in child.attrib:
                    self.map_id_addr[child.attrib['id']] = addr
            elif child.tag=="data":
                if self.verbose:
                    print("Encountered Data!")
                struct_data += self.handle_data(child)
            elif child.tag=="reference":
                if self.verbose:
                    print("Encountered Reference!")
                if len(struct_data)%self.mode:
                    raise Exception("Pointer is not "+str(self.mode)+" bytes aligned")
                pointers.append(len(struct_data))
                references.append((child.attrib["ref"], len(struct_data)))
                struct_data += bytes(self.mode)
        if len(struct_data)%self.mode:
            struct_data += bytes(self.mode-(len(struct_data)%self.mode))
        loc = len(self.sir0_data)
        for ref, p in references:
            lp = self.reflist.get(ref, [])
            lp.append(loc+p)
            self.reflist[ref] = lp
        self.ptrlist.extend([loc+p for p in pointers])
        self.sir0_data += struct_data
        return loc
    
    def construct(self):
        self.endianness = self.root.attrib.get("endianness", 'little')
        self.mode = int(self.root.attrib.get("mode", '4'))
        
        self.sir0_data = bytearray(self.mode*4)
        self.sir0_data[0:4] = b'SIR0'
        self.ptrlist = []
        self.map_id_addr = dict()
        self.reflist = dict()
        
        if self.verbose:
            print("Writing data structures...")
        header_start = self.write_ptr_struct(self.root)
        for k, lv in self.reflist.items():
            addr = self.map_id_addr[k]
            for v in lv:
                self.sir0_data[v:v+self.mode] = addr.to_bytes(self.mode, self.endianness)
        if len(self.sir0_data)%self.mode:
            self.sir0_data += bytes(self.mode-(len(self.sir0_data)%self.mode))
        if verbose:
            print("Writing pointer list...")
        self.ptrlist.append(self.mode)
        self.ptrlist.append(self.mode*2)
        self.ptrlist.sort()
        ptrlist_start = len(self.sir0_data)
        self.sir0_data[self.mode:self.mode*2] = header_start.to_bytes(self.mode, self.endianness)
        self.sir0_data[self.mode*2:self.mode*3] = ptrlist_start.to_bytes(self.mode, self.endianness)
        prev = 0
        for p in self.ptrlist:
            offset_to_encode = p-prev
            prev = p
            has_higher_non_zero = False
            for i in range(self.mode, 0, -1):
                currentbyte = (offset_to_encode >> (7 * (i - 1))) & 0x7F
                if i == 1:
                    self.sir0_data += bytes([currentbyte])
                elif currentbyte != 0 or has_higher_non_zero:
                    self.sir0_data += bytes([currentbyte | 0x80])
                    has_higher_non_zero = True
        self.sir0_data += bytes(1)
        if len(self.sir0_data)%self.mode:
            self.sir0_data += bytes(self.mode-(len(self.sir0_data)%self.mode))
        return bytes(self.sir0_data)

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
if len(arg)-end_opt==2 or len(arg)-end_opt==3 and "-d" in lst_opts:
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
        if len(arg)-end_opt==3:
            with open(arg[end_opt+2]) as file:
                yml = file.read()
        else:
            yml = None
        with open(arg[end_opt], 'rb') as file:
            xml = SIR0Deconstructor(file.read(), yml_data=yml, endianness=endianness, ascii_comment=ascii_comment, verbose=verbose).deconstruct()
        with open(arg[end_opt+1], 'w') as file:
            file.write(minidom.parseString(ET.tostring(xml)).toprettyxml(indent="\t"))
    else:
        with open(arg[end_opt], 'r') as file:
            data = SIR0Constructor(ET.fromstring(file.read()), verbose=verbose).construct()
        with open(arg[end_opt+1], 'wb') as file:
            file.write(data)
else:
    print("Usage: "+arg[0]+" <options> in_data out_data [struct_data]\n\nOptions:\n -a Ascii representation in comments (only for Deconstruct mode)\n -b Big endian mode (only for Deconstruct mode)\n -d Deconstruct\n -v Verbose")
