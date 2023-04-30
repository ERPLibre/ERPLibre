#!./.venv/bin/python
import argparse
import configparser
import logging
import os
import sys
import tempfile
import uuid
import json

from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError


CODE_GENERATOR_DIRECTORY = "./addons/TechnoLibre_odoo-code-generator-template/"
CODE_GENERATOR_DEMO_NAME = "code_generator_demo"
KEY_REPLACE_CODE_GENERATOR_DEMO = 'MODULE_NAME = "%s"'

logging.basicConfig(
    format=(
        "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
        " %(message)s"
    ),
    datefmt="%Y-%m-%d:%H:%M:%S",
    level=logging.INFO,
)
_logger = logging.getLogger(__name__)


class Struct:
    def __init__(self, **entries):
        self.__dict__.update(entries)


# TODO execute create_code_generator_from_existing_module.sh with force option
# TODO open web interface on right database already selected locally with make run


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Create new project for a single module with code generator suite.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-d",
        "--directory",
        required=True,
        help="Directory of the module, need to be a git root directory.",
    )
    parser.add_argument(
        "-m",
        "--module",
        required=True,
        help="Module name to create",
    )
    parser.add_argument(
        "--config",
        help="""Configuration to create models with fields and type. JSON style.
        Example : "{\"model\":[{\"name\":\"a\",\"fields\":[{\"name\":\"a\",\"type\":\"char\"}]}]}" """,
    )
    parser.add_argument(
        "--directory_code_generator",
        help="The directory of the code_generator to use.",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Execute coverage file.",
    )
    parser.add_argument(
        "--code_generator_name",
        help="The name of the code_generator to use.",
    )
    parser.add_argument(
        "--directory_template_name",
        help="The directory of the template to use.",
    )
    parser.add_argument(
        "--template_name",
        help="The name of the template to use.",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force override directory and module.",
    )
    parser.add_argument(
        "--keep_bd_alive",
        action="store_true",
        help="By default, the bd is cleaned after a run.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output",
    )
    args = parser.parse_args()
    return args


class ProjectManagement:
    def __init__(
        self,
        module_name,
        module_directory,
        cg_name="",
        cg_directory="",
        template_name="",
        template_directory="",
        force=False,
        keep_bd_alive=False,
        coverage=False,
        config="",
    ):
        self.force = force
        self._coverage = coverage
        self.keep_bd_alive = keep_bd_alive
        self.msg_error = ""
        self.has_config_update = False

        self.module_directory = module_directory
        if not os.path.exists(self.module_directory):
            self.msg_error = (
                f"Path directory '{self.module_directory}' not exist. You"
                f" actual path is: '{os.getcwd()}'."
            )
            _logger.error(self.msg_error)
            return

        self.cg_directory = cg_directory if cg_directory else module_directory
        if not os.path.exists(self.cg_directory):
            self.msg_error = (
                f"Path cg directory '{self.cg_directory}' not exist. You"
                f" actual path is: '{os.getcwd()}'."
            )
            _logger.error(self.msg_error)
            return

        self.template_directory = (
            template_directory if template_directory else module_directory
        )
        if not os.path.exists(self.template_directory):
            self.msg_error = (
                f"Path template directory '{self.template_directory}' not"
                " exist."
            )
            _logger.error(self.msg_error)
            return

        if not module_name:
            self.msg_error = "Module name is missing."
            _logger.error(self.msg_error)
            return

        # Get module name
        self.module_name = module_name
        # Get code_generator name
        self.cg_name = self._generate_cg_name(default=cg_name)
        # Get template name
        self.template_name = self._generate_template_name(
            default=template_name
        )

        self._parse_config(config)

    def _parse_config(self, config):
        if not config:
            self.config = {}
            self.config_lst_model = []
        else:
            self.config = json.loads(config)
            self.config_lst_model = self.config.get("model")

    def _generate_cg_name(self, default=""):
        if default:
            return default
        return f"code_generator_{self.module_name}"

    def _generate_template_name(self, default=""):
        if default:
            return default
        return f"code_generator_template_{self.module_name}"

    def search_and_replace_file(self, filepath, lst_search_and_replace):
        """
        lst_search_and_replace is a list of tuple, first item is search, second is replace
        """
        with open(filepath, "r") as file:
            txt = file.read()
            for search, replace in lst_search_and_replace:
                if search not in txt:
                    self.msg_error = (
                        f"Cannot find '{search}' in file '{filepath}'"
                    )
                    _logger.error(self.msg_error)
                    return False
                txt = txt.replace(search, replace)
        with open(filepath, "w") as file:
            file.write(txt)
        return True

    @staticmethod
    def validate_path_ready_to_be_override(name, directory, path=""):
        if not path:
            path = os.path.join(directory, name)
        if not os.path.exists(path):
            return True
        # Check if in git
        try:
            git_repo = Repo(directory)
        except NoSuchPathError:
            _logger.error(f"Directory not existing '{directory}'")
            return False
        except InvalidGitRepositoryError:
            _logger.error(
                f"The path '{path}' exist, but no git repo, use force to"
                " ignore it."
            )
            return False

        status = git_repo.git.status(name, porcelain=True)
        if status:
            _logger.error(
                f"The directory '{path}' has git difference, use force to"
                " ignore it."
            )
            print(status)
            return False
        return True

    @staticmethod
    def restore_git_code_generator_demo(
        code_generator_demo_path, relative_path
    ):
        try:
            git_repo = Repo(code_generator_demo_path)
        except NoSuchPathError:
            _logger.error(
                f"Directory not existing '{code_generator_demo_path}'"
            )
            return False
        except InvalidGitRepositoryError:
            _logger.error(
                f"The path '{code_generator_demo_path}' exist, but no git repo"
            )
            return False

        git_repo.git.restore(relative_path)

    def generate_module(self):
        # TODO copy directory in temp workspace file before update it
        module_path = os.path.join(self.module_directory, self.module_name)
        if not self.force and not self.validate_path_ready_to_be_override(
            self.module_name, self.module_directory, path=module_path
        ):
            self.msg_error = f"Cannot generate on module path '{module_path}'"
            _logger.error(self.msg_error)
            return False

        cg_path = os.path.join(self.cg_directory, self.cg_name)
        cg_hooks_py = os.path.join(cg_path, "hooks.py")
        if not self.force and not self.validate_path_ready_to_be_override(
            self.cg_name, self.cg_directory, path=cg_path
        ):
            self.msg_error = f"Cannot generate on cg path '{cg_path}'"
            _logger.error(self.msg_error)
            return False

        template_path = os.path.join(
            self.template_directory, self.template_name
        )
        template_hooks_py = os.path.join(template_path, "hooks.py")
        if not self.force and not self.validate_path_ready_to_be_override(
            self.template_name, self.template_directory, path=template_path
        ):
            self.msg_error = (
                f"Cannot generate on template path '{template_path}'"
            )
            _logger.error(self.msg_error)
            return False

        # Validate code_generator_demo
        code_generator_demo_path = os.path.join(
            CODE_GENERATOR_DIRECTORY, CODE_GENERATOR_DEMO_NAME
        )
        code_generator_demo_hooks_py = os.path.join(
            code_generator_demo_path, "hooks.py"
        )
        code_generator_hooks_path_relative = os.path.join(
            CODE_GENERATOR_DEMO_NAME, "hooks.py"
        )
        if not os.path.exists(code_generator_demo_path):
            self.msg_error = (
                "code_generator_demo is not accessible"
                f" '{code_generator_demo_path}'"
            )
            _logger.error(self.msg_error)
            return False

        if not (
            self.validate_path_ready_to_be_override(
                CODE_GENERATOR_DEMO_NAME, CODE_GENERATOR_DIRECTORY
            )
            and self.search_and_replace_file(
                code_generator_demo_hooks_py,
                [
                    (
                        KEY_REPLACE_CODE_GENERATOR_DEMO
                        % CODE_GENERATOR_DEMO_NAME,
                        KEY_REPLACE_CODE_GENERATOR_DEMO % self.template_name,
                    ),
                    (
                        'value["enable_sync_template"] = False',
                        'value["enable_sync_template"] = True',
                    ),
                    (
                        "# path_module_generate ="
                        " os.path.normpath(os.path.join(os.path.dirname(__file__),"
                        " '..'))",
                        f'path_module_generate = "{self.module_directory}"',
                    ),
                    (
                        '# "path_sync_code": path_module_generate,',
                        '"path_sync_code": path_module_generate,',
                    ),
                    (
                        '# value["template_module_path_generated_extension"]'
                        ' = "."',
                        'value["template_module_path_generated_extension"] ='
                        f' "{self.cg_directory}"',
                    ),
                ],
            )
        ):
            return False
        config_path = self.update_config()

        bd_name_demo = f"new_project_code_generator_demo_{uuid.uuid4()}"[:63]
        cmd = f"./script/database/db_restore.py --database {bd_name_demo}"
        _logger.info(cmd)
        os.system(cmd)
        _logger.info("========= GENERATE code_generator_demo =========")

        if self._coverage:
            cmd = (
                "./script/addons/coverage_install_addons_dev.sh"
                f" {bd_name_demo} code_generator_demo {config_path}"
            )
        else:
            cmd = (
                f"./script/addons/install_addons_dev.sh {bd_name_demo}"
                f" code_generator_demo {config_path}"
            )
        os.system(cmd)

        if not self.keep_bd_alive:
            cmd = (
                "./.venv/bin/python3 ./odoo/odoo-bin db --drop --database"
                f" {bd_name_demo}"
            )
            _logger.info(cmd)
            os.system(cmd)

        # Revert code_generator_demo
        self.restore_git_code_generator_demo(
            CODE_GENERATOR_DIRECTORY, code_generator_hooks_path_relative
        )

        # Validate
        if not os.path.exists(template_path):
            _logger.error(f"Module template not exists '{template_path}'")
            return False
        else:
            _logger.info(f"Module template exists '{template_path}'")

        lst_template_hooks_py_replace = [
            (
                'value["enable_template_wizard_view"] = False',
                'value["enable_template_wizard_view"] = True',
            ),
        ]

        # Add model from config
        if self.config:
            str_lst_model = "; ".join(
                [a.get("name") for a in self.config_lst_model]
            )
            old_str = 'value["template_model_name"] = ""'
            new_str = f'value["template_model_name"] = "{str_lst_model}"'
            lst_template_hooks_py_replace.append((old_str, new_str))

            self.search_and_replace_file(
                template_hooks_py,
                lst_template_hooks_py_replace,
            )

        # Execute all
        bd_name_template = (
            f"new_project_code_generator_template_{uuid.uuid4()}"[:63]
        )
        cmd = f"./script/database/db_restore.py --database {bd_name_template}"
        os.system(cmd)
        _logger.info(cmd)
        _logger.info(f"========= GENERATE {self.template_name} =========")
        # TODO maybe the module exist somewhere else
        if os.path.exists(module_path):
            # Install module before running code generator
            cmd = (
                "./script/code_generator/search_class_model.py --quiet -d"
                f" {module_path} -t {template_path}"
            )
            _logger.info(cmd)
            os.system(cmd)
            if self._coverage:
                cmd = (
                    "./script/addons/coverage_install_addons_dev.sh"
                    f" {bd_name_template} {self.module_name} {config_path}"
                )
            else:
                cmd = (
                    f"./script/addons/install_addons_dev.sh {bd_name_template}"
                    f" {self.module_name} {config_path}"
                )
            _logger.info(cmd)
            os.system(cmd)

        if self._coverage:
            cmd = (
                "./script/addons/coverage_install_addons_dev.sh"
                f" {bd_name_template} {self.template_name} {config_path}"
            )
        else:
            cmd = (
                f"./script/addons/install_addons_dev.sh {bd_name_template}"
                f" {self.template_name} {config_path}"
            )
        _logger.info(cmd)
        os.system(cmd)

        if not self.keep_bd_alive:
            cmd = (
                "./.venv/bin/python3 ./odoo/odoo-bin db --drop --database"
                f" {bd_name_template}"
            )
            _logger.info(cmd)
            os.system(cmd)

        # Validate
        if not os.path.exists(cg_path):
            _logger.error(f"Module cg not exists '{cg_path}'")
            return False
        else:
            _logger.info(f"Module cg exists '{cg_path}'")

        bd_name_generator = f"new_project_code_generator_{uuid.uuid4()}"[:63]
        cmd = f"./script/database/db_restore.py --database {bd_name_generator}"
        _logger.info(cmd)
        os.system(cmd)
        _logger.info(f"========= GENERATE {self.cg_name} =========")

        # Add field from config
        if self.config:
            lst_update_cg = []
            for model in self.config_lst_model:
                model_name = model.get("name")
                dct_field = {
                    a.get("name"): {"ttype": a.get("type")}
                    for a in model.get("fields")
                }
                if "name" not in dct_field.keys():
                    dct_field["name"] = {"ttype": "char"}
                old_str = (
                    f'model_model = "{model_name}"\n       '
                    " code_generator_id.add_update_model(model_model)"
                )
                new_str = (
                    f'model_model = "{model_name}"\n        dct_field ='
                    f" {dct_field}\n       "
                    " code_generator_id.add_update_model(model_model,"
                    " dct_field=dct_field)"
                )
                lst_update_cg.append((old_str, new_str))

            # Force add menu and access
            lst_update_cg.append(('"disable_generate_menu": True,', ""))
            lst_update_cg.append(('"disable_generate_access": True,', ""))
            self.search_and_replace_file(
                cg_hooks_py,
                lst_update_cg,
            )

        if self._coverage:
            cmd = (
                "./script/addons/coverage_install_addons_dev.sh"
                f" {bd_name_generator} {self.cg_name} {config_path}"
            )
        else:
            cmd = (
                f"./script/addons/install_addons_dev.sh {bd_name_generator}"
                f" {self.cg_name} {config_path}"
            )
        _logger.info(cmd)
        os.system(cmd)

        if not self.keep_bd_alive:
            cmd = (
                "./.venv/bin/python3 ./odoo/odoo-bin db --drop --database"
                f" {bd_name_generator}"
            )
            _logger.info(cmd)
            os.system(cmd)

        # Validate
        if not os.path.exists(template_path):
            _logger.error(f"Module not exists '{module_path}'")
            return False
        else:
            _logger.info(f"Module exists '{module_path}'")

        return True

    def update_config(self):
        config = configparser.ConfigParser()
        config.read("./config.conf")
        addons_path = config.get("options", "addons_path")
        lst_addons_path = addons_path.split(",")
        lst_directory = list(
            {
                self.cg_directory,
                self.module_directory,
                self.template_directory,
            }
        )
        has_change = False
        for new_addons_path in lst_directory:
            for actual_addons_path in lst_addons_path:
                if not actual_addons_path:
                    continue
                # Validate if not existing and valide is different path
                relative_actual_addons_path = os.path.relpath(
                    actual_addons_path
                )
                relative_new_addons_path = os.path.relpath(new_addons_path)
                if relative_actual_addons_path == relative_new_addons_path:
                    break
            else:
                lst_addons_path.insert(0, new_addons_path)
                has_change = True
        if has_change:
            config.set("options", "addons_path", ",".join(lst_addons_path))
        temp_file = tempfile.mktemp()
        with open(temp_file, "w") as configfile:
            config.write(configfile)
        _logger.info(f"Create temporary config file: {temp_file}")
        return temp_file


def main():
    config = get_config()
    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    project = ProjectManagement(
        config.module,
        config.directory,
        cg_name=config.code_generator_name,
        template_name=config.template_name,
        force=config.force,
        keep_bd_alive=config.keep_bd_alive,
        coverage=config.coverage,
        config=config.config,
    )
    if project.msg_error:
        return -1

    if not project.generate_module():
        return -1

    return 0


if __name__ == "__main__":
    sys.exit(main())
