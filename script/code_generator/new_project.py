#!./.venv/bin/python
import argparse
import logging
import os
import sys
import uuid

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

# TODO Check if exist DONE
# TODO change name into code_generator_demo DONE
# TODO Create code generator empty module with demo DONE
# TODO revert code_generator_demo DONE
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
        "--directory_code_generator",
        help="The directory of the code_generator to use.",
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
        "--do_not_update_config",
        action="store_true",
        help=(
            "Ignore updating config file. This is a patch for a bug for"
            " duplicate path, but 1 relative and the other is absolute."
        ),
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
        ignore_config=False,
        keep_bd_alive=False,
    ):
        self.force = force
        self.ignore_config = ignore_config
        self.keep_bd_alive = keep_bd_alive
        self.msg_error = ""
        self.origin_config_txt = ""
        self.has_config_update = False

        self.module_directory = module_directory
        if not os.path.exists(self.module_directory):
            self.msg_error = (
                f"Path directory '{self.module_directory}' not exist."
            )
            _logger.error(self.msg_error)
            return

        self.cg_directory = cg_directory if cg_directory else module_directory
        if not os.path.exists(self.cg_directory):
            self.msg_error = (
                f"Path cg directory '{self.cg_directory}' not exist."
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
        module_path = os.path.join(self.module_directory, self.module_name)
        if not self.force and not self.validate_path_ready_to_be_override(
            self.module_name, self.module_directory, path=module_path
        ):
            self.msg_error = f"Cannot generate on module path '{module_path}'"
            _logger.error(self.msg_error)
            return False

        cg_path = os.path.join(self.cg_directory, self.cg_name)
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
        self.update_config()

        bd_name_demo = f"new_project_code_generator_demo_{uuid.uuid4()}"[:63]
        cmd = f"./script/db_restore.py --database {bd_name_demo}"
        _logger.info(cmd)
        os.system(cmd)
        _logger.info("========= GENERATE code_generator_demo =========")
        cmd = (
            f"./script/addons/install_addons_dev.sh {bd_name_demo}"
            " code_generator_demo"
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
            self.revert_config()
            return False
        else:
            _logger.info(f"Module template exists '{template_path}'")

        self.search_and_replace_file(
            template_hooks_py,
            [
                (
                    'value["enable_template_wizard_view"] = False',
                    'value["enable_template_wizard_view"] = True',
                ),
            ],
        )

        # Execute all
        bd_name_template = (
            f"new_project_code_generator_template_{uuid.uuid4()}"[:63]
        )[:63]
        cmd = f"./script/db_restore.py --database {bd_name_template}"
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
            cmd = (
                f"./script/addons/install_addons_dev.sh {bd_name_template}"
                f" {self.module_name}"
            )
            _logger.info(cmd)
            os.system(cmd)

        cmd = (
            f"./script/addons/install_addons_dev.sh {bd_name_template}"
            f" {self.template_name}"
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
            self.revert_config()
            return False
        else:
            _logger.info(f"Module cg exists '{cg_path}'")

        bd_name_generator = f"new_project_code_generator_{uuid.uuid4()}"[:63]
        cmd = f"./script/db_restore.py --database {bd_name_generator}"
        _logger.info(cmd)
        os.system(cmd)
        _logger.info(f"========= GENERATE {self.cg_name} =========")

        cmd = (
            f"./script/addons/install_addons_dev.sh {bd_name_generator}"
            f" {self.cg_name}"
        )
        _logger.info(cmd)
        os.system(cmd)

        if not self.keep_bd_alive:
            cmd = (
                "./.venv/bin/python3 ./odoo/odoo-bin db --drop --database"
                f" {bd_name_generator}"
            )[:63]
            _logger.info(cmd)
            os.system(cmd)

        # Validate
        if not os.path.exists(template_path):
            _logger.error(f"Module not exists '{module_path}'")
            self.revert_config()
            return False
        else:
            _logger.info(f"Module exists '{module_path}'")

        self.revert_config()
        return True

    def update_config(self):
        if self.ignore_config:
            return
        # Backup config and restore it after, check if path exist or add it temporary
        with open("./config.conf") as config:
            config_txt = config.read()
            self.origin_config_txt = config_txt
            lst_directory = list(
                {
                    self.cg_directory,
                    self.module_directory,
                    self.template_directory,
                }
            )
            lst_directory_to_add = []
            for directory in lst_directory:
                if directory not in config_txt:
                    self.has_config_update = True
                    lst_directory_to_add.append(directory)

        if lst_directory_to_add:
            new_str = "addons_path = " + ",".join(lst_directory_to_add) + ","
            config_txt = config_txt.replace("addons_path = ", new_str)
            with open("./config.conf", "w") as config:
                config.write(config_txt)

    def revert_config(self):
        if self.ignore_config:
            return
        with open("./config.conf", "w") as config:
            config.write(self.origin_config_txt)


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
        ignore_config=config.do_not_update_config,
        keep_bd_alive=config.keep_bd_alive,
    )
    if project.msg_error:
        return -1

    if not project.generate_module():
        return -1

    return 0


if __name__ == "__main__":
    sys.exit(main())
