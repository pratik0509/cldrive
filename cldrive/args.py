# Copyright (C) 2017 Chris Cummins.
#
# This file is part of cldrive.
#
# Cldrive is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# Cldrive is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public
# License for more details.
#
# You should have received a copy of the GNU General Public License
# along with cldrive.  If not, see <http://www.gnu.org/licenses/>.
#
import re

from typing import List

import numpy as np

from pycparser.c_ast import NodeVisitor, PtrDecl, TypeDecl, IdentifierType
from pycparserext.ext_c_parser import OpenCLCParser


class KernelArg(object):
    """
    TODO:
        * Attribute 'numpy_type' should depend on the properties of the device.
          E.g. not all devices will have 32 bit integer widths.
    """
    def __init__(self, ast):
        self.ast = ast

        # determine pointer type
        self.is_pointer = isinstance(self.ast.type, PtrDecl)
        self.is_local = False
        self.is_global = False

        if self.is_pointer:
            if ("local" in self.ast.quals
                or "__local" in self.ast.quals):
                self.is_local = True

            if ("global" in self.ast.quals
                  or "__global" in self.ast.quals):
                self.is_global = True

            if self.is_local and self.is_global:
                raise ValueError("Argument is both global and local qualified")
            elif not self.is_local and not self.is_global:
                raise ValueError("Argument is neither global or local qualified")

        # determine tyename
        if isinstance(self.ast.type.type, IdentifierType):
            typenames = self.ast.type.type.names
        elif isinstance(self.ast.type.type.type, IdentifierType):
            typenames = self.ast.type.type.type.names
        else:
            raise ValueError("unsupported data type")  # e.g. structs

        if len(typenames) != 1:
            raise ValueError("too many typenames")

        self.typename = typenames[0]

        self.name = self.ast.name
        self.quals = self.ast.quals
        self.has_input = not self.is_local
        self.is_scalar = not self.is_pointer
        self.bare_type = self.typename.rstrip('0123456789')
        self.is_vector = self.typename[-1].isdigit()
        self.is_const = "const" in self.quals

        if self.is_vector:
            m = re.search(r'([0-9]+)\*?$', self.typename)
            self.vector_width = int(m.group(1))
        else:
            self.vector_width = 1

        self.numpy_type = {
            "bool": np.bool_,
            "char": np.int8,
            "double": np.float64,
            "float": np.float32,
            "half": np.uint8,
            "int": np.int32,
            "long": np.int64,
            "short": np.int16,
            "uchar": np.uint8,
            "uint": np.uint32,
            "ulong": np.uint64,
            "unsigned char": np.uint8,
            "unsigned int": np.uint32,
            "unsigned long": np.uint64,
            "unsigned short": np.uint16,
            "ushort": np.uint16,
            "void": np.int64,
        }.get(self.bare_type, None)
        if self.numpy_type is None:
            raise cldrive.KernelArgError(self.bare_type)

    def __repr__(self):
        if len(self.quals):
            quals_str = " ".join(self.quals) + " "
        else:
            quals_str = ""
        return f"{self.__class__.__name__} {quals_str}{self.typename} {self.name}"


class ArgumentExtractor(NodeVisitor):
    """
    Extract kernel arguments from an OpenCL AST.

    Attributes:
        args (List[KernelArg]): List of KernelArg instances.

    TODO:
        * build a table of typedefs and substitute the original types when
          constructing kernel args.
    """
    def __init__(self, *args, **kwargs):
        super(ArgumentExtractor, self).__init__(*args, **kwargs)
        self.kernel_count = 0
        self._args: List[KernelArg] = []

    @property
    def args(self):
        if self.kernel_count != 1:
            raise cldrive.ParseError("source contains no kernel definitions.")
        return self._args

    def visit_FuncDef(self, node):
        """
        Raises:
            ParseError: In case of a problem.
        """
        # only visit kernels, not allfunctions
        if ("kernel" in node.decl.funcspec or
            "__kernel" in node.decl.funcspec):
            self.kernel_count += 1
        else:
            return

        # ensure we've only visited one kernel
        if self.kernel_count > 1:
            raise cldrive.ParseError(
                "source contains more than one kernel definition")

        # function may not have arguments
        if node.decl.type.args:
            for param in node.decl.type.args.params:
                self._args.append(KernelArg(param))

__parser = OpenCLCParser()

def extract_args(src: str) -> List[KernelArg]:
    """
    Extract kernel arguments for an OpenCL kernel.

    Returns:
        List[KernelArg]: A list of the kernel's arguments, in order.

    Raises:
        ParseError: If the source contains more than one kernel definition,
            or if any of the kernel's parameters cannot be determined.
        KernelArgError: If any of the kernel's parameters are invalid or
            not supported.

    TODO:
        * Pre-process source code
    """
    ast = __parser.parse(src)
    visitor = ArgumentExtractor()
    visitor.visit(ast)
    return visitor.args