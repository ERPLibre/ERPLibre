#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import os
import sys
import time

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from selenium.webdriver.common.by import By

from script.selenium import selenium_lib


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


def run(
    config,
    selenium_tool,
    default_email_auth=None,
    default_password_auth=None,
    no_try_test=False,
):
    # Trouvez les éléments du formulaire
    courriel_input = selenium_tool.get_element(by=By.NAME, value="login")
    mot_de_passe_input = selenium_tool.get_element(
        by=By.NAME, value="password"
    )
    # div_connexion_button = selenium_tool.get_element(by=By.CLASS_NAME, value="oe_login_buttons")
    connexion_button = selenium_tool.get_element(
        by=By.CSS_SELECTOR, value="[type='submit']"
    )

    actual_url = selenium_tool.driver.current_url
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
    email_auth = (
        default_email_auth if default_email_auth else config.default_email_auth
    )
    pass_auth = (
        default_password_auth
        if default_password_auth
        else config.default_password_auth
    )
    courriel_input.clear()
    mot_de_passe_input.clear()
    courriel_input.send_keys(email_auth)
    mot_de_passe_input.send_keys(pass_auth)

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

    if not no_try_test:
        time.sleep(1)
        if actual_url in [
            selenium_tool.driver.current_url,
            f"{selenium_tool.driver.current_url}?redirect=%2Fweb%3F",
        ]:
            run(
                config,
                selenium_tool,
                default_email_auth="test",
                default_password_auth="test",
                no_try_test=True,
            )
            return

    # Remove chatbot if open, because will crash wizard div[4] (to div[5])
    selenium_tool.check_bot_chat_and_close()

    # Open View
    if config.open_dashboard:
        selenium_tool.odoo_website_menu_click(
            "Tableaux de bord"
        )

    # Open conversation chat
    # conversation_button = selenium_tool.driver.find_element(By.XPATH, '/html/body/header/nav/ul[3]/li[2]/a')
    # conversation_button.click()

    # Close bot chat
    # conversation_button = selenium_tool.driver.find_element(By.XPATH, '/html/body/div[3]/div[1]/span[2]/a[2]')
    # conversation_button.click()

    # Fermez le navigateur
    # selenium_tool.driver.quit()

    # Force use dark mode if enable
    selenium_tool.odoo_profile_click(
        enable_dark_mode=not config.no_dark_mode, enable_tour=False
    )

    print("End web_login.py")


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
