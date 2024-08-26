#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import sys

import black
import xmltodict

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Transform an XML into Python
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--source",
        dest="source",
        required=True,
        help="File to transform (XML)",
    )
    # parser.add_argument(
    #     "--destination",
    #     dest="destination",
    #     help=(
    #         "Result, output (Python). If not set, output will be console."
    #     ),
    # )
    # parser.add_argument(
    #     "-q",
    #     "--quiet",
    #     action="store_true",
    #     help="Don't show output of found model.",
    # )
    args = parser.parse_args()
    if not os.path.isfile(args.source):
        raise Exception("Argument --source need to be a valid path to a file.")
    return args


def get_module_name(filepath):
    manifest_file = "__manifest__.py"
    current_path = os.path.abspath(os.path.dirname(filepath))
    while current_path != "/":
        manifest_path = os.path.join(current_path, manifest_file)
        if os.path.isfile(manifest_path):
            return os.path.basename(current_path)
        current_path = os.path.dirname(current_path)
    raise FileNotFoundError(f"No {manifest_file} found for {filepath}")


def get_value_from_field(lst_field, by_attr, name, record_id, get_attr):
    field_info = [a for a in lst_field if a.get(by_attr) == name]
    if not field_info:
        raise ValueError(
            f"Missing <field {by_attr[1:]}={name}'/> from record {record_id}"
        )
    field_info = field_info[0]
    return field_info.get(get_attr)


def main():
    config = get_config()
    with open(config.source) as xml:
        xml_as_string = xml.read()
        xml_dict = xmltodict.parse(xml_as_string)
        # TODO replace this by get_value(xml_dict, "odoo.data.record")
        xml_dict_odoo = xml_dict.get("odoo")
        if not xml_dict_odoo:
            raise ValueError(f"Missing <odoo> into {config.source}")
        xml_dict_data = xml_dict_odoo.get("data")
        if not xml_dict_data:
            raise ValueError(f"Missing <data> into {config.source}")
        xml_dict_record = xml_dict_data.get("record")
        if not xml_dict_record:
            raise ValueError(f"Missing <record> into {config.source}")
    if type(xml_dict_record) is not list:
        lst_xml_record = [xml_dict_record]
    else:
        lst_xml_record = xml_dict_record
    lst_output = []
    for record in lst_xml_record:
        lst_field = record.get("field")
        if type(lst_field) is not list:
            lst_field = [lst_field]

        # Condition unique
        try:
            get_value_from_field(
                lst_field, "@name", "groups_id", record.get("@id"), "@eval"
            )
        except:
            continue

        url = get_value_from_field(
            lst_field, "@name", "url", record.get("@id"), "#text"
        )
        view_id = get_value_from_field(
            lst_field, "@name", "view_id", record.get("@id"), "@ref"
        )
        module_name = get_module_name(config.source)
        method_name = (
            f'get_{"_".join(url.replace("-", "_").strip("/").split("/"))}'
        )

        #         template = f"""
        # @http.route(
        #     ["{url}"],
        #     type="http",
        #     auth="user",
        #     website=True,
        # )
        # def {method_name}(self, **kw):
        #     return request.env["ir.ui.view"].render_template(
        #         "{module_name}.{view_id}",
        #     )
        template = f"""
@http.route(
    ["{url}"],
    type="http",
    auth="user",
    website=True,
)
def {method_name}(self, **kw):
    return request.env.ref('{module_name}.{view_id}').render()
"""
        lst_output.append(template)
    str_output = "\n".join(lst_output)
    formated_str_output = black.format_str(str_output, mode=black.Mode())
    print(formated_str_output)
    return 0


if __name__ == "__main__":
    status = main()
    sys.exit(status)
