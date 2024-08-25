#!/usr/bin/env python3
import sys
import argparse
import web_login
import selenium_lib


def run(config, selenium_tool):
    if config.open_me_devops:
        selenium_tool.click(
            "/html/body/header/nav/div/div[1]/div[2]/div/div/div/ul/li[2]/a",
        )
        selenium_tool.click(
            "/html/body/div[1]/main/div[2]/div/div/table/tbody/tr[1]/td[2]",
        )
        if config.open_me_devops_auto:
            selenium_tool.click(
                "/html/body/header/nav/div/div[1]/div[2]/div/div/div/ul/li[2]/a",
            )
            selenium_tool.click(
                "/html/body/div[1]/main/div[2]/div/div/table/tbody/tr[1]/td[2]",
            )

            # CG self
            # Bouton modifier
            # selenium_tool.click(
            #     "/html/body/div[1]/main/div[1]/div[2]/div/div/div[1]/button[1]",
            # )
            # Tab Code
            # selenium_tool.click(
            #     "/html/body/div[1]/main/div[2]/div/div/div[7]/ul/li[2]/a",
            # )
            # Bouton Plan
            selenium_tool.click(
                "/html/body/div[1]/main/div[2]/div/div/div[1]/div/button[1]",
            )

            # Bouton autopoiesis
            selenium_tool.click(
                "/html/body/div[4]/div/div/main/div/div/div[5]/table[2]/tbody/tr[2]/td[1]/button",
            )

            # Bouton devops regenerate
            selenium_tool.click(
                "/html/body/div[4]/div/div/main/div/div/div[6]/table[2]/tbody/tr[2]/td/button",
            )

            if config.open_me_devops_auto_force:
                # Disable «Stop Execution if Env Not Clean
                # selenium_tool.click(
                #     "/html/body/div[1]/main/div[2]/div/div/div[7]/div/div[2]/div[6]/table[2]/tbody/tr[3]/td[2]/div/label",
                # )
                # Option Force Generate
                selenium_tool.click(
                    "/html/body/div[4]/div/div/main/div/div/div[8]/table/tbody/tr[2]/td[1]/label",
                )

            # Gen
            # selenium_tool.click(
            #     "/html/body/div[1]/main/div[2]/div/div/div[7]/div/div[2]/div[2]/table[1]/tbody/tr/td[1]/button",
            # )

            # Next state
            selenium_tool.click(
                "/html/body/div[4]/div/div/footer/div/footer/div/button[1]",
            )

            # Check error
            # selenium_tool.click(
            #     "/html/body/div[1]/main/div[2]/div/div/div[7]/ul/li[13]/a",
            # )
            # selenium_tool.click("/html/body/div[1]/main/div[2]/div/div/div[6]/div/div[14]/div/div[2]/table/tbody/tr[1]", timeout=60*2)


def fill_parser(parser):
    group_devops = parser.add_argument_group(title="DevOps")
    group_devops.add_argument(
        "--open_me_devops",
        action="store_true",
        help="Open application devops and show entry me.",
    )
    group_devops.add_argument(
        "--open_me_devops_auto",
        action="store_true",
        help="Open application devops and show entry me and run auto setup.",
    )
    group_devops.add_argument(
        "--open_me_devops_auto_force",
        action="store_true",
        help=(
            "Open application devops and show entry me and run auto setup with"
            " forcing argument."
        ),
    )


def compute_args(args):
    if args.open_me_devops_auto_force:
        args.open_me_devops_auto = True
        args.open_me_devops = True
    elif args.open_me_devops_auto:
        args.open_me_devops = True


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Selenium script to open web browser to ERPLibre adapted for ORE.""",
    )
    # Generate parser
    selenium_lib.fill_parser(parser)
    web_login.fill_parser(parser)
    fill_parser(parser)
    args = parser.parse_args()
    web_login.compute_args(args)
    compute_args(args)
    # Instance selenium tool
    selenium_tool = selenium_lib.SeleniumLib(args)
    selenium_tool.configure()
    selenium_tool.start_record()
    # Execute
    web_login.run(args, selenium_tool)
    run(args, selenium_tool)
    selenium_tool.stop_record()
    return 0


if __name__ == "__main__":
    sys.exit(main())
