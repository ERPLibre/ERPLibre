#!./.venv/bin/python
import argparse
import logging
import os
import sys
from xml.dom import Node, minidom

from code_writer import CodeWriter

from script.git_tool import GitTool


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    config = GitTool.get_project_config()

    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Transform a xml file in code writer format xml file.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-f",
        "--file",
        dest="file",
        required=True,
        help="Path of file to transform to code_writer.",
    )
    parser.add_argument(
        "-o", "--output", dest="output", help="The output file."
    )
    args = parser.parse_args()
    return args


def transform_string_to_list(str_info):
    # lst_info = [a.strip() for a in str_info.split("\n") if a.strip()]
    lst_info = [a for a in str_info.split("\n") if a.strip()]
    return lst_info


def code_writer_deep_xml(nodes):
    if not nodes:
        return
    size_nodes = len(nodes.childNodes)
    lst_result = []
    for node in nodes.childNodes:
        if node.nodeType == Node.ELEMENT_NODE:
            value = code_writer_deep_xml(node)
            comment_str = node.toprettyxml()
            comment = ""
            if comment_str:
                lst_comment = comment_str.split("\n")
                if lst_comment:
                    comment = f"# {lst_comment[0]}"

            code_line = (
                f"E.{node.tagName}({str(dict(node.attributes.items()))})",
                value,
            )
            lst_result.append((comment, code_line))
        elif node.nodeType == Node.TEXT_NODE:
            if size_nodes == 1:
                return node.data
    return lst_result


class GenerateCode:
    def __init__(self):
        self._result = ""

    @property
    def result(self):
        return self._result

    def generate_code(self, lst_in):
        if type(lst_in) is list:
            i = 1
            max = len(lst_in)
            for tpl_in in lst_in:
                self._result += f"\n{tpl_in[0]}\n"
                self.generate_code(tpl_in[1])
                if i != max:
                    self._result += ","
                i += 1
        elif type(lst_in) is tuple:
            if lst_in[1]:
                self._result += f"{lst_in[0][:-1]}, "
                if type(lst_in[1]) is str:
                    self._result += f"'{lst_in[1].strip()}'"
                else:
                    self.generate_code(lst_in[1])
                self._result += ")"
            else:
                self._result += f"{lst_in[0][:-1]})"


def main():
    config = get_config()
    cw = CodeWriter()

    mydoc = minidom.parse(config.file)
    if not mydoc:
        print(f"Error, cannot parse {config.file}")
        sys.exit(1)

    cw.emit("from lxml.builder import E")
    cw.emit("from lxml import etree as ET")
    cw.emit("from code_writer import CodeWriter")
    cw.emit("")
    cw.emit('print(\'<?xml version="1.0" encoding="utf-8"?>\')')
    cw.emit('print("<odoo>")')

    lst_function = []
    comment_for_next_group = None

    for odoo in mydoc.getElementsByTagName("odoo"):
        for ir_view_item in odoo.childNodes:
            if ir_view_item.nodeType == Node.ELEMENT_NODE:
                # Show part of xml
                fct_name = "ma_fonction"
                lst_function.append(fct_name)
                cw.emit(f"def {fct_name}():")
                with cw.indent():
                    cw.emit('"""')
                    for line in transform_string_to_list(
                        ir_view_item.toprettyxml()
                    ):
                        cw.emit(line)
                    cw.emit('"""')
                    # Show comment
                    if comment_for_next_group:
                        cw.emit(
                            "print('<!--"
                            f" {comment_for_next_group.strip()} -->')"
                        )
                        comment_for_next_group = None
                    attributes_root = dict(ir_view_item.attributes.items())

                    lst_out = code_writer_deep_xml(ir_view_item)

                    generate_code = GenerateCode()
                    generate_code.generate_code(lst_out)
                    child_root = generate_code.result

                    code = (
                        "root ="
                        f" E.{ir_view_item.tagName}({str(attributes_root)},"
                        f" {child_root})"
                    )

                    for line in code.split("\n"):
                        cw.emit(line)

                    cw.emit("content = ET.tostring(root, pretty_print=True)")
                    cw.emit()
                    cw.emit("cw = CodeWriter()")
                    cw.emit(
                        'for line in content.decode("utf-8").split("\\n"):'
                    )
                    with cw.indent():
                        cw.emit("with cw.indent():")
                        with cw.indent():
                            cw.emit("cw.emit(line)")
                    cw.emit("print(cw.render())")
                cw.emit(f"{fct_name}()")
            elif ir_view_item.nodeType == Node.COMMENT_NODE:
                comment_for_next_group = ir_view_item.data
            else:
                # print(ir_view_item)
                pass

    cw.emit('print("</odoo>")')

    output = cw.render()
    if config.output:
        with open(config.output, "w") as file:
            file.write(output)
    else:
        print(output)


def add_line(
    cw, line, no_line, nb_indent, no_indent, init_no_intend, nb_space
):
    """
    Recursive check indent and write line
    :param cw: code_writer module
    :param line: line to write
    :param line: actual position of line, useful for debug
    :param nb_indent: number of indent to support
    :param no_indent: actual indentation
    :param init_no_intend: initial indentation, can detect if new indent or use the last
    :param nb_space: more space to add
    :return: the actual no_indent
    """
    max_indent = 19
    if nb_indent > max_indent:
        print(f"Do not support more than {max_indent} indent.")
        sys.exit(-1)

    if nb_indent == -1:
        cw.emit('cw.emit("")')
        return 0
    elif nb_indent == no_indent:
        if nb_indent == 0:
            cw.emit(f'cw.emit("{line}")')
            return 0
        elif nb_indent == 1:
            if no_indent != init_no_intend:
                cw.emit(f"with cw.indent({4 + nb_space if nb_space else ''}):")
            with cw.indent():
                cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 2:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")


if __name__ == "__main__":
    main()
