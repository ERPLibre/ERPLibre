#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import os
import sys
import time

import selenium_lib
from selenium.webdriver.common.by import By


def fill_parser(parser):
    group_login = parser.add_argument_group(title="Login")
    group_login.add_argument(
        "--open_dashboard",
        action="store_true",
        help="Open application Board.",
    )
    group_login.add_argument(
        "--default_email_auth",
        default="admin",
        help="Email to use to authenticate with admin.",
    )
    group_login.add_argument(
        "--default_password_auth",
        default="admin",
        help="Password to use to authenticate with admin.",
    )


def run(config, selenium_tool):
    # Trouvez les éléments du formulaire
    courriel_input = selenium_tool.driver.find_element(By.NAME, "login")
    mot_de_passe_input = selenium_tool.driver.find_element(By.NAME, "password")
    div_connexion_button = selenium_tool.driver.find_element(
        By.CLASS_NAME, "oe_login_buttons"
    )
    connexion_button = div_connexion_button.find_element(
        By.CLASS_NAME, "btn-primary"
    )
    # try:
    #     connexion_button = selenium_tool.driver.find_element(
    #         By.XPATH,
    #         "/html/body/div/div/div/form/div[3]/button",
    #         # '//button[contains(text(), "Log in")]'
    #     )
    # except Exception:
    #     connexion_button = selenium_tool.driver.find_element(
    #         By.XPATH,
    #         "/html/body/div/main/div/form/div[3]/button",
    #         # '//button[contains(text(), "Connexion")]'
    #     )

    # Remplissez le courriel et le mot de passe
    courriel_input.send_keys(config.default_email_auth)
    mot_de_passe_input.send_keys(config.default_password_auth)

    # Cliquez sur le bouton "Connexion"
    try:
        connexion_button.click()
    except Exception as e:
        if (
            'class="modal o_technical_modal show modal_shown"> obscures it'
            in str(e)
        ):
            # Click it
            # xpath_button = "//div[hasclass('o_technical_modal')]/div/div/footer/button"
            xpath_button = (
                "//div[contains(@class,"
                " 'o_technical_modal')]/div/div/footer/button"
            )
            error_button = selenium_tool.driver.find_element(
                By.XPATH, xpath_button
            )
            error_button.click()

            # Remplissez le courriel et le mot de passe
            courriel_input.send_keys(config.default_email_auth)
            mot_de_passe_input.send_keys(config.default_password_auth)

            connexion_button.click()
        else:
            raise e

    # Attendez que l'élément soit cliquable
    # wait = WebDriverWait(selenium_tool.driver, 5)
    # menu_toggle = wait.until(
    #     EC.element_to_be_clickable((By.XPATH, "/html/body/header/nav/ul[1]/li/a"))
    # )
    #
    # # Cliquez sur l'élément
    # menu_toggle.click()
    #
    # # Attendez que le lien soit cliquable
    # menu_item = wait.until(
    #     EC.element_to_be_clickable(
    #         (
    #             By.XPATH,
    #             "/html/body/header/nav/ul[1]/li/div/a[2]",
    #         )
    #     )
    # )

    # Remove chatbot if open, because will crash wizard div[4] (to div[5])
    selenium_tool.check_bot_chat_and_close()

    # Open View
    if config.open_dashboard:
        selenium_tool.click(
            "/html/body/header/nav/div/div[1]/div[2]/div/div/div/ul/li[3]/a",
            timeout=15,
        )

    # Open conversation chat
    # conversation_button = selenium_tool.driver.find_element(By.XPATH, '/html/body/header/nav/ul[3]/li[2]/a')
    # conversation_button.click()

    # Close bot chat
    # conversation_button = selenium_tool.driver.find_element(By.XPATH, '/html/body/div[3]/div[1]/span[2]/a[2]')
    # conversation_button.click()

    # Fermez le navigateur
    # selenium_tool.driver.quit()


def compute_args(args):
    pass


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Selenium script to open web browser to ERPLibre.""",
        epilog="""\
    """,
    )
    # Generate parser
    selenium_lib.fill_parser(parser)
    fill_parser(parser)
    args = parser.parse_args()
    compute_args(args)
    # Instance selenium tool
    selenium_tool = selenium_lib.SeleniumLib(args)
    selenium_tool.configure()
    selenium_tool.start_record()
    # Execute
    run(args, selenium_tool)
    selenium_tool.stop_record()
    return 0


if __name__ == "__main__":
    sys.exit(main())
