#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import subprocess
import sys
import uuid

from code_writer import CodeWriter

# import tokenize


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Transform a python file in code writer format python file.
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


def count_space_tab(word, group_space=4):
    """

    :param word:
    :param group_space: count tab for number of group_space
    :return: number of tab, or -1 if ignore line or empty, nb_space of over
    """
    nb_tab = 0
    nb_space = 0
    for s_char in word:
        if s_char in ["\n", "\r"]:
            return -1, 0
        elif s_char in ["\t"]:
            nb_tab += 1
        elif s_char == " ":
            nb_space += 1
            if nb_space == group_space:
                nb_space = 0
                nb_tab += 1
        else:
            # Finish to count
            break
    return nb_tab, nb_space


def main():
    config = get_config()
    cw = CodeWriter()
    last_nb_tab = 0
    nb_tab = 0
    no_tab = 0

    # Validate file format
    out = subprocess.check_output(
        f"python -m tabnanny {config.file}",
        stderr=subprocess.STDOUT,
        shell=True,
    )
    if out:
        print(out)
        sys.exit(1)

    # with tokenize.open(config.file) as f:
    #     tokens = tokenize.generate_tokens(f.readline)
    #     for token in tokens:
    #         print(token)

    cw.emit("from code_writer import CodeWriter")
    cw.emit("cw = CodeWriter()")
    unique_str = f"#{uuid.uuid4().hex}#"

    no_line = 1
    with open(config.file, "r") as file:
        for line in file.readlines():
            nb_tab, nb_space = count_space_tab(line)
            diff_tab = nb_tab - last_nb_tab
            new_line = line.strip()

            # Support \, because with cw.emit("\") this will break
            new_line = new_line.replace("\\", "\\\\")
            # Support " into string
            new_line = new_line.replace('"', '\\"')
            # Fix """
            new_line = new_line.replace('\\"\\"\\"', unique_str)

            status_no_tab = add_line(
                cw, new_line, no_line, nb_tab, no_tab, no_tab, nb_space
            )
            if status_no_tab >= 0:
                no_tab = status_no_tab

            last_nb_tab = nb_tab
            no_line += 1
    argument_print = ""
    if line[-1] != "\n":
        # Remove last endline if missing
        argument_print = ", end=''"
    # Ignore last character, it's an empty space
    # TODO find another technique to support """, instead of using uuid
    cw.emit(
        f"print(cw.render()[:-1].replace('{unique_str}',"
        f' \'"""\'){argument_print})'
    )

    output = cw.render()
    if config.output:
        with open(config.output, "w") as file:
            file.write(output)
    else:
        print(output)


def add_line(
    cw,
    line,
    no_line,
    nb_indent,
    no_indent,
    init_no_intend,
    nb_space,
    deindent=False,
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
        if no_indent > 0:
            cw.emit_raw(" " * no_indent * 4 + f"cw.emit()\n")
            return no_indent
        else:
            cw.emit("cw.emit()")
            return 0
    elif nb_indent == no_indent:
        if nb_indent == 0:
            cw.emit(f'cw.emit("{line}")')
            return 0
        elif nb_indent == 1:
            if no_indent != init_no_intend and not deindent:
                cw.emit(f"with cw.indent({4 + nb_space if nb_space else ''}):")
            with cw.indent():
                cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 2:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            # TODO support indent with cw.emit_raw
            with cw.indent():
                if no_indent != init_no_intend and not deindent:
                    cw.emit(
                        f"with cw.indent({4 + nb_space if nb_space else ''}):"
                    )
                with cw.indent():
                    cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 3:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if no_indent != init_no_intend and not deindent:
                        cw.emit(
                            "with"
                            f" cw.indent({4 + nb_space if nb_space else ''}):"
                        )
                    with cw.indent():
                        cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 4:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if no_indent != init_no_intend and not deindent:
                            cw.emit(
                                "with"
                                f" cw.indent({4 + nb_space if nb_space else ''}):"
                            )
                        with cw.indent():
                            cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 5:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if no_indent != init_no_intend and not deindent:
                                cw.emit(
                                    "with"
                                    f" cw.indent({4 + nb_space if nb_space else ''}):"
                                )
                            with cw.indent():
                                cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 6:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if (
                                    no_indent != init_no_intend
                                    and not deindent
                                ):
                                    cw.emit(
                                        "with"
                                        f" cw.indent({4 + nb_space if nb_space else ''}):"
                                    )
                                with cw.indent():
                                    cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 7:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if (
                                        no_indent != init_no_intend
                                        and not deindent
                                    ):
                                        cw.emit(
                                            "with"
                                            f" cw.indent({4 + nb_space if nb_space else ''}):"
                                        )
                                    with cw.indent():
                                        cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 8:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if (
                                            no_indent != init_no_intend
                                            and not deindent
                                        ):
                                            cw.emit(
                                                "with"
                                                f" cw.indent({4 + nb_space if nb_space else ''}):"
                                            )
                                        with cw.indent():
                                            cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 9:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if (
                                                no_indent != init_no_intend
                                                and not deindent
                                            ):
                                                cw.emit(
                                                    "with"
                                                    f" cw.indent({4 + nb_space if nb_space else ''}):"
                                                )
                                            with cw.indent():
                                                cw.emit(f'cw.emit("{line}")')
        elif nb_indent == 10:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    no_indent != init_no_intend
                                                    and not deindent
                                                ):
                                                    cw.emit(
                                                        "with"
                                                        f" cw.indent({4 + nb_space if nb_space else ''}):"
                                                    )
                                                with cw.indent():
                                                    cw.emit(
                                                        f'cw.emit("{line}")'
                                                    )
        elif nb_indent == 11:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        no_indent
                                                        != init_no_intend
                                                    ):
                                                        cw.emit(
                                                            "with"
                                                            f" cw.indent({4 + nb_space if nb_space else ''}):"
                                                        )
                                                    with cw.indent():
                                                        cw.emit(
                                                            f'cw.emit("{line}")'
                                                        )
        elif nb_indent == 12:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        nb_indent - 1
                                                        > init_no_intend
                                                    ):
                                                        cw.emit(
                                                            f"with"
                                                            f" cw.indent():"
                                                        )
                                                    with cw.indent():
                                                        if (
                                                            no_indent
                                                            != init_no_intend
                                                        ):
                                                            cw.emit(
                                                                "with"
                                                                f" cw.indent({4 + nb_space if nb_space else ''}):"
                                                            )
                                                        with cw.indent():
                                                            cw.emit(
                                                                f'cw.emit("{line}")'
                                                            )
        elif nb_indent == 13:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        nb_indent - 1
                                                        > init_no_intend
                                                    ):
                                                        cw.emit(
                                                            f"with"
                                                            f" cw.indent():"
                                                        )
                                                    with cw.indent():
                                                        if (
                                                            nb_indent - 1
                                                            > init_no_intend
                                                        ):
                                                            cw.emit(
                                                                f"with"
                                                                f" cw.indent():"
                                                            )
                                                        with cw.indent():
                                                            if (
                                                                no_indent
                                                                != init_no_intend
                                                            ):
                                                                cw.emit(
                                                                    "with"
                                                                    f" cw.indent({4 + nb_space if nb_space else ''}):"
                                                                )
                                                            with cw.indent():
                                                                cw.emit(
                                                                    f'cw.emit("{line}")'
                                                                )
        elif nb_indent == 14:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        nb_indent - 1
                                                        > init_no_intend
                                                    ):
                                                        cw.emit(
                                                            f"with"
                                                            f" cw.indent():"
                                                        )
                                                    with cw.indent():
                                                        if (
                                                            nb_indent - 1
                                                            > init_no_intend
                                                        ):
                                                            cw.emit(
                                                                f"with"
                                                                f" cw.indent():"
                                                            )
                                                        with cw.indent():
                                                            if (
                                                                nb_indent - 1
                                                                > init_no_intend
                                                            ):
                                                                cw.emit(
                                                                    f"with"
                                                                    f" cw.indent():"
                                                                )
                                                            with cw.indent():
                                                                if (
                                                                    no_indent
                                                                    != init_no_intend
                                                                ):
                                                                    cw.emit(
                                                                        "with"
                                                                        f" cw.indent({4 + nb_space if nb_space else ''}):"
                                                                    )
                                                                with cw.indent():
                                                                    cw.emit(
                                                                        f'cw.emit("{line}")'
                                                                    )
        elif nb_indent == 15:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        nb_indent - 1
                                                        > init_no_intend
                                                    ):
                                                        cw.emit(
                                                            f"with"
                                                            f" cw.indent():"
                                                        )
                                                    with cw.indent():
                                                        if (
                                                            nb_indent - 1
                                                            > init_no_intend
                                                        ):
                                                            cw.emit(
                                                                f"with"
                                                                f" cw.indent():"
                                                            )
                                                        with cw.indent():
                                                            if (
                                                                nb_indent - 1
                                                                > init_no_intend
                                                            ):
                                                                cw.emit(
                                                                    f"with"
                                                                    f" cw.indent():"
                                                                )
                                                            with cw.indent():
                                                                if (
                                                                    nb_indent
                                                                    - 1
                                                                    > init_no_intend
                                                                ):
                                                                    cw.emit(
                                                                        f"with"
                                                                        f" cw.indent():"
                                                                    )
                                                                with cw.indent():
                                                                    if (
                                                                        no_indent
                                                                        != init_no_intend
                                                                    ):
                                                                        cw.emit(
                                                                            "with"
                                                                            f" cw.indent({4 + nb_space if nb_space else ''}):"
                                                                        )
                                                                    with cw.indent():
                                                                        cw.emit(
                                                                            f'cw.emit("{line}")'
                                                                        )
        elif nb_indent == 16:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        nb_indent - 1
                                                        > init_no_intend
                                                    ):
                                                        cw.emit(
                                                            f"with"
                                                            f" cw.indent():"
                                                        )
                                                    with cw.indent():
                                                        if (
                                                            nb_indent - 1
                                                            > init_no_intend
                                                        ):
                                                            cw.emit(
                                                                f"with"
                                                                f" cw.indent():"
                                                            )
                                                        with cw.indent():
                                                            if (
                                                                nb_indent - 1
                                                                > init_no_intend
                                                            ):
                                                                cw.emit(
                                                                    f"with"
                                                                    f" cw.indent():"
                                                                )
                                                            with cw.indent():
                                                                if (
                                                                    nb_indent
                                                                    - 1
                                                                    > init_no_intend
                                                                ):
                                                                    cw.emit(
                                                                        f"with"
                                                                        f" cw.indent():"
                                                                    )
                                                                with cw.indent():
                                                                    if (
                                                                        nb_indent
                                                                        - 1
                                                                        > init_no_intend
                                                                    ):
                                                                        cw.emit(
                                                                            f"with"
                                                                            f" cw.indent():"
                                                                        )
                                                                    with cw.indent():
                                                                        if (
                                                                            no_indent
                                                                            != init_no_intend
                                                                        ):
                                                                            cw.emit(
                                                                                f"with cw.indent({4 + nb_space if nb_space else ''}):"
                                                                            )
                                                                        with cw.indent():
                                                                            cw.emit(
                                                                                f'cw.emit("{line}")'
                                                                            )
        elif nb_indent == 17:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        nb_indent - 1
                                                        > init_no_intend
                                                    ):
                                                        cw.emit(
                                                            f"with"
                                                            f" cw.indent():"
                                                        )
                                                    with cw.indent():
                                                        if (
                                                            nb_indent - 1
                                                            > init_no_intend
                                                        ):
                                                            cw.emit(
                                                                f"with"
                                                                f" cw.indent():"
                                                            )
                                                        with cw.indent():
                                                            if (
                                                                nb_indent - 1
                                                                > init_no_intend
                                                            ):
                                                                cw.emit(
                                                                    f"with"
                                                                    f" cw.indent():"
                                                                )
                                                            with cw.indent():
                                                                if (
                                                                    nb_indent
                                                                    - 1
                                                                    > init_no_intend
                                                                ):
                                                                    cw.emit(
                                                                        f"with"
                                                                        f" cw.indent():"
                                                                    )
                                                                with cw.indent():
                                                                    if (
                                                                        nb_indent
                                                                        - 1
                                                                        > init_no_intend
                                                                    ):
                                                                        cw.emit(
                                                                            f"with"
                                                                            f" cw.indent():"
                                                                        )
                                                                    with cw.indent():
                                                                        if (
                                                                            nb_indent
                                                                            - 1
                                                                            > init_no_intend
                                                                        ):
                                                                            cw.emit(
                                                                                f"with cw.indent():"
                                                                            )
                                                                        with cw.indent():
                                                                            if (
                                                                                no_indent
                                                                                != init_no_intend
                                                                            ):
                                                                                cw.emit(
                                                                                    f"with cw.indent({4 + nb_space if nb_space else ''}):"
                                                                                )
                                                                            with cw.indent():
                                                                                cw.emit(
                                                                                    f'cw.emit("{line}")'
                                                                                )
        elif nb_indent == 18:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        nb_indent - 1
                                                        > init_no_intend
                                                    ):
                                                        cw.emit(
                                                            f"with"
                                                            f" cw.indent():"
                                                        )
                                                    with cw.indent():
                                                        if (
                                                            nb_indent - 1
                                                            > init_no_intend
                                                        ):
                                                            cw.emit(
                                                                f"with"
                                                                f" cw.indent():"
                                                            )
                                                        with cw.indent():
                                                            if (
                                                                nb_indent - 1
                                                                > init_no_intend
                                                            ):
                                                                cw.emit(
                                                                    f"with"
                                                                    f" cw.indent():"
                                                                )
                                                            with cw.indent():
                                                                if (
                                                                    nb_indent
                                                                    - 1
                                                                    > init_no_intend
                                                                ):
                                                                    cw.emit(
                                                                        f"with"
                                                                        f" cw.indent():"
                                                                    )
                                                                with cw.indent():
                                                                    if (
                                                                        nb_indent
                                                                        - 1
                                                                        > init_no_intend
                                                                    ):
                                                                        cw.emit(
                                                                            f"with"
                                                                            f" cw.indent():"
                                                                        )
                                                                    with cw.indent():
                                                                        if (
                                                                            nb_indent
                                                                            - 1
                                                                            > init_no_intend
                                                                        ):
                                                                            cw.emit(
                                                                                f"with cw.indent():"
                                                                            )
                                                                        with cw.indent():
                                                                            if (
                                                                                nb_indent
                                                                                - 1
                                                                                > init_no_intend
                                                                            ):
                                                                                cw.emit(
                                                                                    f"with cw.indent():"
                                                                                )
                                                                            with cw.indent():
                                                                                if (
                                                                                    no_indent
                                                                                    != init_no_intend
                                                                                ):
                                                                                    cw.emit(
                                                                                        f"with cw.indent({4 + nb_space if nb_space else ''}):"
                                                                                    )
                                                                                with cw.indent():
                                                                                    cw.emit(
                                                                                        f'cw.emit("{line}")'
                                                                                    )
        elif nb_indent == 19:
            if nb_indent - 1 > init_no_intend:
                cw.emit(f"with cw.indent():")
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
            with cw.indent():
                if nb_indent - 1 > init_no_intend:
                    cw.emit(f"with cw.indent():")
                with cw.indent():
                    if nb_indent - 1 > init_no_intend:
                        cw.emit(f"with cw.indent():")
                    with cw.indent():
                        if nb_indent - 1 > init_no_intend:
                            cw.emit(f"with cw.indent():")
                        with cw.indent():
                            if nb_indent - 1 > init_no_intend:
                                cw.emit(f"with cw.indent():")
                            with cw.indent():
                                if nb_indent - 1 > init_no_intend:
                                    cw.emit(f"with cw.indent():")
                                with cw.indent():
                                    if nb_indent - 1 > init_no_intend:
                                        cw.emit(f"with cw.indent():")
                                    with cw.indent():
                                        if nb_indent - 1 > init_no_intend:
                                            cw.emit(f"with cw.indent():")
                                        with cw.indent():
                                            if nb_indent - 1 > init_no_intend:
                                                cw.emit(f"with cw.indent():")
                                            with cw.indent():
                                                if (
                                                    nb_indent - 1
                                                    > init_no_intend
                                                ):
                                                    cw.emit(
                                                        f"with cw.indent():"
                                                    )
                                                with cw.indent():
                                                    if (
                                                        nb_indent - 1
                                                        > init_no_intend
                                                    ):
                                                        cw.emit(
                                                            f"with"
                                                            f" cw.indent():"
                                                        )
                                                    with cw.indent():
                                                        if (
                                                            nb_indent - 1
                                                            > init_no_intend
                                                        ):
                                                            cw.emit(
                                                                f"with"
                                                                f" cw.indent():"
                                                            )
                                                        with cw.indent():
                                                            if (
                                                                nb_indent - 1
                                                                > init_no_intend
                                                            ):
                                                                cw.emit(
                                                                    f"with"
                                                                    f" cw.indent():"
                                                                )
                                                            with cw.indent():
                                                                if (
                                                                    nb_indent
                                                                    - 1
                                                                    > init_no_intend
                                                                ):
                                                                    cw.emit(
                                                                        f"with"
                                                                        f" cw.indent():"
                                                                    )
                                                                with cw.indent():
                                                                    if (
                                                                        nb_indent
                                                                        - 1
                                                                        > init_no_intend
                                                                    ):
                                                                        cw.emit(
                                                                            f"with"
                                                                            f" cw.indent():"
                                                                        )
                                                                    with cw.indent():
                                                                        if (
                                                                            nb_indent
                                                                            - 1
                                                                            > init_no_intend
                                                                        ):
                                                                            cw.emit(
                                                                                f"with cw.indent():"
                                                                            )
                                                                        with cw.indent():
                                                                            if (
                                                                                nb_indent
                                                                                - 1
                                                                                > init_no_intend
                                                                            ):
                                                                                cw.emit(
                                                                                    f"with cw.indent():"
                                                                                )
                                                                            with cw.indent():
                                                                                if (
                                                                                    nb_indent
                                                                                    - 1
                                                                                    > init_no_intend
                                                                                ):
                                                                                    cw.emit(
                                                                                        f"with cw.indent():"
                                                                                    )
                                                                                with cw.indent():
                                                                                    if (
                                                                                        no_indent
                                                                                        != init_no_intend
                                                                                    ):
                                                                                        cw.emit(
                                                                                            f"with cw.indent({4 + nb_space if nb_space else ''}):"
                                                                                        )
                                                                                    with cw.indent():
                                                                                        cw.emit(
                                                                                            f'cw.emit("{line}")'
                                                                                        )
        return nb_indent
    else:
        if no_indent > nb_indent:
            # deindent
            return add_line(
                cw,
                line,
                no_line,
                nb_indent,
                no_indent - 1,
                init_no_intend,
                nb_space,
                deindent=True,
            )
        else:
            # indent
            return add_line(
                cw,
                line,
                no_line,
                nb_indent,
                no_indent + 1,
                init_no_intend,
                nb_space,
            )
    print("BUG")
    return -1


if __name__ == "__main__":
    main()
