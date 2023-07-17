# SIR0 Universal Reader & Writer

## Summary

A tool and standard format for reading and writing SIR0 files.

### What is it?

The purpose of this tool (and specification) is to propose a universal way
of representing SIR0 files, as well as read and write them.

SIR0 files are used in most of Spike Chunsoft works, and are containers
that can store quite everything.

The goal here is to have a way to represent them all.

### Why have a universal tool/specification?

SIR0 files represent arbitrary data, and can be hard to read at first glance.

However, it seems possible to extract a universally readable structure solely based on
the SIR0 contents; the file actually has a pointer list that references all
pointers to other offsets of the file. Considering each pointer as the
beginning of a new structure, it is possible to split all structures and
represent them as a tree of nested structures.

This can be really useful for researching purposes; having a tree of nested structures
makes it easier to find the pattern of a file, instead of having to check for it
manually.

This also helps for editing undefined SIR0 files, as you don't have to mess with
the pointer list when trying to change/add elements inside a SIR0 file, as it's
handled by reconstruction based on the tree structure.

Finally, it can be a good alternative at editing them when no other tool is available
for this specific SIR0 format.

Note: this does not magically explain all the file's contents. This will get you
a good overview of the file structure, but raw data parts will still be
rendered as raw data. Trying to figure out what each value does is still your doing.

## Tool

The tool provided implements the specification detailed below.

This needs python3 to be installed, no other dependencies are required.

To use this in command line: 

```
Usage: python3 sir0.py <options> in_data out_data

Options:
 -a Ascii representation in comments (only for Deconstruct mode)
 -d Deconstruct
 -v Verbose
 ```
By default, the tool parses the xml file in `in_data` to produce a SIR0 file at `out_data`.

Use `-d` to parse a SIR0 file in `in_data` and produce the xml representation at `out_data`.

You can also use `-a` in this mode to add in xml comments the ascii representation of each data block,
which can be useful to search for strings (non representable characters are marked with '?').

## XML Representation

### Specification

XML Representation of SIR0 with this specification is straightforward. 3 types of elements are defined: 
- `<struct>` elements are pointers to another structure, referenced by a 4 bytes pointer in the SIR0 file.
  The represented structure can contain any of the elements defined, including nested `<struct>`
- `<data>` elements contain raw data, stored in hexadecimal string representation

These two elements could technically cover all SIR0 files, but at the cost of redundancy, as some structures
may be referenced multiple times. To support a more accurate representation, a third element is introduced: 
- `<reference ref='X'>` is a reference to another `<struct>` element present somewhere in the xml tree.
  `X` is an identifier that must be declared in only one `<struct>` adding a `id` attribute like this: `<struct id='X'>`

Order of elements nested in `<struct>` is important: each element will be assembled from top to bottom to
create the resulting structure.

Additionally, `<struct>` will always be the root element, as the SIR0 header starts with a pointer to a structure.

### Examples

A simple hello world message
```XML
<struct>
    <data>48656c6c6f20576f726c642100</data>
</struct>
```
Note that consecutive `<data>` elements are equivalent to a single one containing the concatenation of both: 
```XML
<struct>
    <struct>
        <data>48656c6c6f20576f726c642100</data>
    </struct>
</struct>
```
is equivalent to
```XML
<struct>
    <struct>
        <data>48656c6c6f20</data>
        <data>576f726c642100</data>
    </struct>
</struct>
```
BUT NOT
```XML
<struct>
    <struct>
        <data>48656c6c6f20</data>
    </struct>
    <struct>
        <data>576f726c642100</data>
    </struct>
</struct>
```
as the latter creates two different structures that could be moved anywhere in the final SIR0 file.

Nested structures
```XML
<struct>
    <data>00000000</data>
    <struct>
        <data>01000000</data>
    </struct>
    <struct>
        <data>02000000</data>
        <struct>
            <data>03000000</data>
        </struct>
        <data>04000000</data>
        <struct>
            <data>05000000</data>
        </struct>
    </struct>
</struct>
```
References
```XML
<struct>
    <struct id='HELLO'>
        <data>48656c6c6f20576f726c642100</data>
    </struct>
    <reference ref='HELLO'/>
</struct>
```
This creates a single nested structure containing 'Hello World!', which is referenced twice
in the header structure. Both will be converted as pointing the same offset in the result SIR0.

## Drawbacks

### Result SIR0 file size and structure

Since the specification does not keep the original layout of the SIR0, structures can
be placed anywhere in the result file.

This means the structure created may not ressemble others of the same format.

This can also cause a problem if you are checking identity of produced SIR0 against original
as you can't byte compare both files to check identity between files.

However, both files should be fundamentally equivalent.

### Taking back 'Universal'

If I said that this specification was 'Universal', that may not be true in fact.

This specification only works if the SIR0 has no 'middle structure' pointer.

A 'middle structure' pointer is a pointer that points right in the middle of
a contiguous structure.

The tool tries to deconstruct SIR0 files by splitting structures using pointed
offsets, so if that happen it would cause errors when recontructing the SIR0 file.

However, cases of this tend to be rare (if not non existent) and do not have any practical usage
so it may not be that important.

## Extensions

Currently, the biggest extension that could be done is
to improve readability of `<data>` sections.

One way of making it more readable is to support
providing (partial) definition of the target SIR0 structure
and/or add customizable `<data>` section handlers.
