#!./.venv/bin/python
import argparse
import csv
import logging
import os
import subprocess
import sys

import xmltodict

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)

PROJECT_NAME = os.path.basename(os.getcwd())
IDEA_PATH = "./.idea"
IDEA_MISC = os.path.join(IDEA_PATH, "misc.xml")
IDEA_WORKSPACE = os.path.join(IDEA_PATH, "workspace.xml")
IDEA_PROJECT_IML = os.path.join(IDEA_PATH, PROJECT_NAME + ".iml")

PATH_EXCLUDE_FOLDER = "./conf/pycharm_exclude_folder.txt"
if os.path.isfile(PATH_EXCLUDE_FOLDER):
    with open(PATH_EXCLUDE_FOLDER) as txt:
        txt_read = txt.read()
        LST_EXCLUDE_FOLDER = txt_read.strip().split("\n")
else:
    LST_EXCLUDE_FOLDER = []

PATH_DEFAULT_CONFIGURATION = "./conf/pycharm_default_configuration.csv"


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Manipulate configuration for your IDE Pycharm about ERPLibre. 
        This script manage only Python configuration, other configuration will be ignore.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--list_configuration",
        action="store_true",
        help=(
            "List all configuration, the configuration is executable with"
            " debugger."
        ),
    )
    parser.add_argument(
        "--list_configuration_full",
        action="store_true",
        help=(
            "List all configuration full details, the configuration is"
            " executable with debugger."
        ),
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize minimum configuration for Pycharm.",
    )
    args = parser.parse_args()

    if args.init or args.list_configuration or args.list_configuration_full:
        args.configuration = True
    else:
        args.configuration = False

    return args


def main():
    has_execute = False
    config = get_config()

    # TODO modifier vcs.xml pour le mapping des répertoires git

    die(
        not os.path.isdir(IDEA_PATH),
        f"Missing {IDEA_PATH} path, are you sure you run this script at root"
        " of the project, are you sure you have a Pycharm project?",
    )
    die(
        not os.path.isfile(IDEA_PROJECT_IML),
        f"Missing {IDEA_PROJECT_IML} file, wait after Pycharm analyze file to"
        " create Python environnement.",
    )
    if config.init:
        has_execute = True
        read_xml_and_execute(
            IDEA_PROJECT_IML, add_exclude_folder, "init", config
        )

    die(
        not os.path.isfile(IDEA_MISC),
        f"Missing {IDEA_MISC} file, wait after Pycharm analyze file to create"
        " Python environnement. You can call --init to accelerate first"
        " Pycharm analyze file.",
    )

    if config.configuration:
        die(
            not os.path.isfile(IDEA_WORKSPACE),
            f"Missing {IDEA_WORKSPACE} file, be sure Pycharm open a project to"
            " your workspace.",
        )
        has_execute = True
        read_xml_and_execute(
            IDEA_WORKSPACE, add_configuration, "workspace", config
        )

    if not has_execute:
        _logger.info("Nothing to do")


def read_xml_and_execute(file_name, cb, name, config):
    with open(file_name) as xml:
        xml_as_string = xml.read()
        dct_project_xml = xmltodict.parse(xml_as_string)
    # Add exclude folder
    has_change = cb(dct_project_xml, file_name, config)
    if has_change:
        xml_format = xmltodict.unparse(
            dct_project_xml, pretty=True, indent="  "
        )
        with open(file_name, mode="w") as xml:
            xml.write(xml_format)
        _logger.info(f"File {file_name} has been write.")
        subprocess.call(
            "prettier --tab-width 2 --print-width 999999 --write"
            f" '{file_name}'",
            shell=True,
        )
    else:
        _logger.info(f"No change '{name}'.")


def add_configuration(dct_xml, file_name, config):
    has_change = False
    dct_project = dct_xml.get("project")
    die(not bool(dct_project), f"Missing 'project' into {file_name}")
    lst_component = dct_project.get("component")
    die(
        not bool(lst_component),
        f"Missing 'project/component' into {file_name}",
    )
    dct_component = [
        a for a in lst_component if a.get("@name") == "RunManager"
    ]
    if not dct_component:
        # Create it
        dct_component = {
            "@name": "RunManager",
            "@selected": "Python.pycharm_configuration",
            "recent_temporary": {
                "list": {
                    "item": {"@itemvalue": "Python.pycharm_configuration"}
                }
            },
            "configuration": [],
            "list": {"item": []},
        }
        lst_component.append(dct_component)
    else:
        dct_component = dct_component[0]
    if config.list_configuration_full:
        print("Configuration list detail:")
    lst_configuration_full = dct_component.get("configuration")
    # Create a unique list of configuration to know if we need to add a new configuration
    lst_unique_configuration = []
    for conf in lst_configuration_full:
        if conf.get("@factoryName") == "Python":
            folder_name = conf.get("@folderName")
            conf_name = conf.get("@name")
            if folder_name:
                conf_name = f"{folder_name}/{conf_name}"
            else:
                folder_name = ""
            if config.list_configuration_full:
                print(f"\t{conf_name}")
            script_name = [
                a.get("@value").replace("$PROJECT_DIR$", ".")
                for a in conf.get("option")
                if a.get("@name") == "SCRIPT_NAME"
            ]
            if not script_name:
                script_name = ""
            else:
                script_name = script_name[0]
            param = [
                a.get("@value")
                for a in conf.get("option")
                if a.get("@name") == "PARAMETERS"
            ]
            if param:
                param = param[0]
            else:
                param = ""
            if config.list_configuration_full:
                print(f"\t\t{script_name} {param}")
            lst_unique_configuration.append(
                f"d {folder_name} s {script_name} p {param}"
            )
    if config.list_configuration:
        print("Configuration list:")
    lst_xml_configuration_name = dct_component.get("list").get("item")
    lst_configuration = [
        a.get("@itemvalue")[7:]
        for a in lst_xml_configuration_name
        if a.get("@itemvalue").startswith("Python.")
    ]
    if config.list_configuration:
        for conf in lst_configuration:
            print(f"\t{conf}")

    if config.init:
        if os.path.isfile(PATH_DEFAULT_CONFIGURATION):
            with open(PATH_DEFAULT_CONFIGURATION) as txt:
                for default_conf in csv.DictReader(txt):
                    conf_name = default_conf.get("name")
                    conf_folder = default_conf.get("folder")
                    conf_script_path = default_conf.get("script_path")
                    conf_script_path_replace = (
                        conf_script_path
                        if not conf_script_path.startswith("./")
                        else f"$PROJECT_DIR${conf_script_path[1:]}"
                    )
                    conf_parameter = default_conf.get("parameters")
                    s_unique_key = (
                        f"d {conf_folder} s"
                        f" {conf_script_path} p"
                        f" {conf_parameter}"
                    )
                    if s_unique_key not in lst_unique_configuration:
                        # add it!
                        if conf_name in lst_configuration:
                            _logger.error(
                                f"Cannot add configuration name '{conf_name}',"
                                " already exist. Delete it manually."
                            )
                        else:
                            has_change = True
                            lst_xml_configuration_name.append(
                                {"@itemvalue": f"Python.conf_name"}
                            )
                            conf_full = {
                                "@name": conf_name,
                                "@type": "PythonConfigurationType",
                                "@factoryName": "Python",
                                "module": {"@name": PROJECT_NAME},
                                "option": [
                                    {
                                        "@name": "INTERPRETER_OPTIONS",
                                        "@value": "",
                                    },
                                    {"@name": "PARENT_ENVS", "@value": "true"},
                                    {
                                        "@name": "SDK_HOME",
                                        "@value": (
                                            "$PROJECT_DIR$/.venv/bin/python"
                                        ),
                                    },
                                    {
                                        "@name": "WORKING_DIRECTORY",
                                        "@value": "$PROJECT_DIR$",
                                    },
                                    {
                                        "@name": "IS_MODULE_SDK",
                                        "@value": "false",
                                    },
                                    {
                                        "@name": "ADD_CONTENT_ROOTS",
                                        "@value": "true",
                                    },
                                    {
                                        "@name": "ADD_SOURCE_ROOTS",
                                        "@value": "true",
                                    },
                                    {
                                        "@name": "SCRIPT_NAME",
                                        "@value": conf_script_path_replace,
                                    },
                                    {
                                        "@name": "PARAMETERS",
                                        "@value": conf_parameter,
                                    },
                                    {
                                        "@name": "SHOW_COMMAND_LINE",
                                        "@value": "false",
                                    },
                                    {
                                        "@name": "EMULATE_TERMINAL",
                                        "@value": "false",
                                    },
                                    {
                                        "@name": "MODULE_MODE",
                                        "@value": "false",
                                    },
                                    {
                                        "@name": "REDIRECT_INPUT",
                                        "@value": "false",
                                    },
                                    {"@name": "INPUT_FILE", "@value": ""},
                                ],
                                "envs": {
                                    "env": {
                                        "@name": "PYTHONUNBUFFERED",
                                        "@value": "1",
                                    }
                                },
                                "EXTENSION": {
                                    "@ID": "PythonCoverageRunConfigurationExtension",
                                    "@runner": "coverage.py",
                                },
                                "method": {"@v": "2"},
                            }
                            if conf_folder:
                                conf_full["@folderName"] = conf_folder
                            lst_configuration_full.insert(0, conf_full)
                    else:
                        _logger.info(
                            f"Configuration already exist: '{s_unique_key}'"
                        )
        else:
            _logger.error(f"Cannot read file '{PATH_DEFAULT_CONFIGURATION}'")
    return has_change


def add_exclude_folder(dct_xml, file_name, config):
    has_change = False
    dct_module = dct_xml.get("module")
    die(not bool(dct_module), f"Missing 'module' into {file_name}")
    lst_component = dct_module.get("component")
    die(
        not bool(lst_component), f"Missing 'module/component' into {file_name}"
    )
    dct_component = [
        a for a in lst_component if a.get("@name") == "NewModuleRootManager"
    ]
    die(
        not bool(dct_component),
        "Missing 'module/component @name NewModuleRootManager' into"
        f" {file_name}",
    )
    dct_component = dct_component[0]
    dct_content = dct_component.get("content")
    die(
        not bool(dct_content),
        "Missing 'module/component @name NewModuleRootManager/content' into"
        f" {file_name}",
    )
    lst_exclude_folder = dct_content.get("excludeFolder")

    lst_exclude_item = [f"file://$MODULE_DIR$/{a}" for a in LST_EXCLUDE_FOLDER]

    if lst_exclude_folder:
        if type(lst_exclude_folder) is list:
            lst_existing_exclude_item = [
                a.get("@url") for a in lst_exclude_folder
            ]
        elif type(lst_exclude_folder) is dict:
            lst_existing_exclude_item = [lst_exclude_folder.get("@url")]
        else:
            die(
                True,
                "Cannot understand type of variable lst_exclude_folder:"
                f" {lst_exclude_folder}",
            )
        lst_diff = list(
            set(lst_exclude_item).difference(set(lst_existing_exclude_item))
        )
    else:
        lst_exclude_folder = []
        dct_content["excludeFolder"] = lst_exclude_folder
        lst_diff = lst_exclude_item

    if lst_diff:
        if type(lst_exclude_folder) is dict:
            # Contain only 1 item
            lst_exclude_folder = [lst_exclude_folder]
            dct_content["excludeFolder"] = lst_exclude_folder
        for diff in lst_diff:
            lst_exclude_folder.append({"@url": diff})
        has_change = True
    return has_change


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
