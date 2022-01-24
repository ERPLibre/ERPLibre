#!./.venv/bin/python
import argparse
import csv
import logging
import os
import sys

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(new_path)

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Take two csv and show difference, intersection and complementarity
""",
        epilog="""\
""",
    )
    parser.add_argument("--csv_1", required=True, help="CSV file first")
    parser.add_argument("--csv_2", required=True, help="CSV file second")
    parser.add_argument(
        "--compare_key",
        required=True,
        help="Key to search and compare with it.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()

    with open(config.csv_1, mode="r") as csv_file_1:
        with open(config.csv_2, mode="r") as csv_file_2:
            csv_reader_1 = csv.DictReader(csv_file_1)
            csv_reader_2 = csv.DictReader(csv_file_2)
            lst_csv_1 = [a.get(config.compare_key) for a in csv_reader_1]
            lst_csv_2 = [a.get(config.compare_key) for a in csv_reader_2]
    set_csv_1 = set(lst_csv_1)
    set_csv_2 = set(lst_csv_2)

    total = set_csv_1.union(set_csv_2)
    same = set_csv_1.intersection(set_csv_2)
    difference_1 = set_csv_1.difference(set_csv_2)
    difference_2 = set_csv_2.difference(set_csv_1)
    print(f"{len(total)} total")
    print(f"{len(same)} same")
    if same:
        print(same)
    print(f"{len(difference_1)} difference csv 1 to csv 2")
    if difference_1:
        print(difference_1)
    print(f"{len(difference_2)} difference csv 2 to csv 1")
    if difference_2:
        print(difference_2)


if __name__ == "__main__":
    main()
