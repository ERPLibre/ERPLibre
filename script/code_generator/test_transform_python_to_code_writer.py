#!./.venv/bin/python
import argparse
import os
import subprocess
import sys
import tempfile


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Transform a python file in code writer format python file, will generate it in temp file and compare difference.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Show debug information."
    )
    parser.add_argument(
        "--format", action="store_true", help="Format file before test."
    )
    parser.add_argument(
        "-f",
        "--file",
        dest="file",
        required=True,
        help="Path of file to transform to code_writer.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    if config.format:
        result = subprocess.run(
            [
                "bash",
                "./script/maintenance/format_python.sh",
                config.file,
            ],
            capture_output=True,
            text=True,
        )
    with tempfile.NamedTemporaryFile() as temp_file:
        # Generate the generator
        file = temp_file.name
        result = subprocess.run(
            [
                "python",
                "./script/code_generator/transform_python_to_code_writer.py",
                "-f",
                config.file,
                "-o",
                file,
            ],
            capture_output=True,
            text=True,
        )
        # if config.debug:
        #     print("-- show the generator --")
        #     print(result.stdout)
        #     print("-- end show the generator --")
        # Execute the generator
        result_generator = subprocess.run(
            ["python", file], capture_output=True, text=True
        )
        if result_generator.returncode != 0:
            raise Exception(result_generator.stderr)
        if config.debug:
            print("-- show the generator result --")
            print(result_generator.stdout)
            print("-- end show the generator result --")
        # Test the generator output
        fd, temp_file_path = tempfile.mkstemp()
        with os.fdopen(fd, "w+") as temp_file_test:
            temp_file_test.write(result_generator.stdout)
            temp_file_test.seek(0)
            # Compare the output of the generator with original
            result = subprocess.run(
                ["diff", config.file, temp_file_path],
                capture_output=True,
                text=True,
            )
        if config.debug or result.stdout:
            print("-- show diff --")
            print(result.stdout)
            print("-- end show diff --")
        if result.stdout:
            print("FAIL")
            result_wc = subprocess.run(
                ["wc", "-m", config.file], capture_output=True, text=True
            )
            if result_wc.returncode == 0:
                line_count = int(result_wc.stdout.split()[0])
                print(f"{line_count} VS {len(result_generator.stdout)}")
            else:
                print(f"Error with command 'wc -m {config.file}'")
            return -1
        else:
            print("PASS")
        return 0


if __name__ == "__main__":
    sys.exit(main())
