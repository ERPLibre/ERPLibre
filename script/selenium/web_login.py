#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.firefox.service import Service
from subprocess import getoutput


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Selenium script to open web browser to ERPLibre.""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--open_me_devops",
        action="store_true",
        help="Open application devops and show entry me.",
    )
    parser.add_argument(
        "--open_me_devops_auto",
        action="store_true",
        help="Open application devops and show entry me and run auto setup.",
    )
    parser.add_argument(
        "--open_me_devops_auto_force",
        action="store_true",
        help=(
            "Open application devops and show entry me and run auto setup with"
            " forcing argument."
        ),
    )
    parser.add_argument(
        "--not_private_mode",
        action="store_true",
        help="Default is private mode.",
    )
    parser.add_argument(
        "--record_mode",
        action="store_true",
        help="Start recording (not finish to be implemented).",
    )
    parser.add_argument(
        "--not_dark_mode",
        action="store_true",
        help=(
            "By default, will be in dark mode, because the main developer"
            " like it!"
        ),
    )
    parser.add_argument(
        "--firefox_binary_path",
        help="Can specify firefox path to open selenium.",
    )
    parser.add_argument(
        "--gecko_binary_path",
        help="Can specify firefox path to open selenium.",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8069",
        help="URL to open.",
    )
    args = parser.parse_args()
    if args.open_me_devops_auto_force:
        args.open_me_devops_auto = True
        args.open_me_devops = True
    elif args.open_me_devops_auto:
        args.open_me_devops = True
    return args


def click(driver, xpath, time=5):
    wait = WebDriverWait(driver, time)
    button = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                xpath,
            )
        )
    )
    button.click()


def check_bot_chat_and_close(driver):
    try:
        xpath_button = "/html/body/div[3]/div[1]/span[2]/a[2]"
        button = driver.find_element(By.XPATH, xpath_button)
        click(driver, xpath_button)
    except Exception:
        print("element not found")


def run(config):
    if config.record_mode:
        new_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        sys.path.append(new_path)
        from script.selenium.selenium_video import VideoRecorder

    # Configuration pour lancer Firefox en mode de navigation privée
    firefox_options = webdriver.FirefoxOptions()
    if not config.not_private_mode:
        firefox_options.add_argument("--private")

    # Définissez la préférence pour les notifications de bureau
    # 1 signifie "autoriser", 2 signifie "bloquer"
    firefox_options.set_preference(
        "permissions.default.desktop-notification", 1
    )
    firefox_services = None
    if config.firefox_binary_path:
        firefox_services = Service(executable_path=config.firefox_binary_path)
    if config.gecko_binary_path:
        firefox_options.binary_location = config.gecko_binary_path

    # Créez une instance du navigateur Firefox avec les options de navigation privée
    try:
        driver = webdriver.Firefox(
            options=firefox_options, service=firefox_services
        )
    except Exception:
        print("Cannot open Firefox profile, so will force firefox snap for Ubuntu users.")
        firefox_services = Service(
            executable_path=getoutput(
                "find /snap/firefox -name geckodriver"
            ).split("\n")[-1]
        )
        firefox_options.binary_location = getoutput(
            "find /snap/firefox -name firefox"
        ).split("\n")[-1]
        driver = webdriver.Firefox(
            options=firefox_options, service=firefox_services
        )

    # Ajout de l'enregistrement
    if config.record_mode:
        video_recorder = VideoRecorder(driver)
    else:
        video_recorder = None

    # Install DarkReader to help my eyes
    # TODO do a script to check if it's the last version
    if not config.not_dark_mode:
        driver.install_addon(
            "./script/selenium/darkreader-firefox.xpi", temporary=True
        )
        driver.install_addon(
            "./script/selenium/odoo_debug-4.0.xpi", temporary=True
        )

    if not config.not_private_mode and not config.not_dark_mode:
        driver.get("about:addons")
        # Enable Dark Reader into incognito
        click(driver, "/html/body/div/div[1]/categories-box/button[2]")
        click(
            driver,
            "/html/body/div/div[2]/div/addon-list/section[1]/addon-card/div/div/div/div/button",
        )
        click(
            driver,
            "/html/body/div/div[2]/div/addon-list/section[1]/addon-card/div/addon-options/panel-list/panel-item[5]",
        )
        click(
            driver,
            "/html/body/div/div[2]/div/addon-card/div/addon-details/named-deck/section/div[5]/div/label[1]/input",
        )

        # Enable Odoo_debug into incognito
        # Back
        click(
            driver, "/html/body/div/div[2]/addon-page-header/div/div[2]/button"
        )
        click(
            driver,
            "/html/body/div/div[2]/div/addon-list/section[1]/addon-card[2]/div/div/div/div/button",
        )
        click(
            driver,
            "/html/body/div/div[2]/div/addon-list/section[1]/addon-card[2]/div/addon-options/panel-list/panel-item[5]",
        )
        click(
            driver,
            "/html/body/div/div[2]/div/addon-card/div/addon-details/named-deck/section/div[5]/div/label[1]/input",
        )

    # Ouvrez la page web
    driver.get(f"{config.url}/web")

    # Close tab opening by DarkReader
    if config.not_private_mode and not config.not_dark_mode:
        driver.switch_to.window(driver.window_handles[-1])
        driver.close()
        driver.switch_to.window(driver.window_handles[0])

    # Démarrer l'enregistrement
    if config.record_mode:
        video_recorder.start()

    # Trouvez les éléments du formulaire
    courriel_input = driver.find_element(By.NAME, "login")
    mot_de_passe_input = driver.find_element(By.NAME, "password")
    try:
        connexion_button = driver.find_element(
            By.XPATH,
            "/html/body/div/div/div/form/div[3]/button"
            # '//button[contains(text(), "Log in")]'
        )
    except Exception:
        connexion_button = driver.find_element(
            By.XPATH,
            "/html/body/div/main/div/form/div[3]/button"
            # '//button[contains(text(), "Connexion")]'
        )

    # Remplissez le courriel et le mot de passe
    courriel_input.send_keys("admin")
    mot_de_passe_input.send_keys("admin")

    # Cliquez sur le bouton "Connexion"
    connexion_button.click()

    # Attendez que l'élément soit cliquable
    # wait = WebDriverWait(driver, 5)
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

    # Open View
    if config.open_me_devops:
        click(
            driver,
            "/html/body/header/nav/div/div[1]/div[2]/div/div/div/ul/li[2]/a",
        )
        click(
            driver,
            "/html/body/div[1]/main/div[2]/div/div/table/tbody/tr[1]/td[2]",
        )
        # Remove chat bot if open, because will crash wizard div[4] (to div[5])
        check_bot_chat_and_close(driver)
        if config.open_me_devops_auto:
            click(
                driver,
                "/html/body/header/nav/div/div[1]/div[2]/div/div/div/ul/li[2]/a",
            )
            click(
                driver,
                "/html/body/div[1]/main/div[2]/div/div/table/tbody/tr[1]/td[2]",
            )

            # CG self
            # Bouton modifier
            # click(
            #     driver,
            #     "/html/body/div[1]/main/div[1]/div[2]/div/div/div[1]/button[1]",
            # )
            # Tab Code
            # click(
            #     driver,
            #     "/html/body/div[1]/main/div[2]/div/div/div[7]/ul/li[2]/a",
            # )
            # Bouton Plan
            click(
                driver,
                "/html/body/div[1]/main/div[2]/div/div/div[1]/div/button[1]",
            )

            # Bouton autopoiesis
            click(
                driver,
                "/html/body/div[4]/div/div/main/div/div/div[5]/table[2]/tbody/tr[2]/td[1]/button",
            )

            # Bouton devops regenerate
            click(
                driver,
                "/html/body/div[4]/div/div/main/div/div/div[6]/table[2]/tbody/tr[2]/td/button",
            )

            if config.open_me_devops_auto_force:
                # Disable «Stop Execution if Env Not Clean
                # click(
                #     driver,
                #     "/html/body/div[1]/main/div[2]/div/div/div[7]/div/div[2]/div[6]/table[2]/tbody/tr[3]/td[2]/div/label",
                # )
                # Option Force Generate
                click(
                    driver,
                    "/html/body/div[4]/div/div/main/div/div/div[8]/table/tbody/tr[2]/td[1]/label",
                )

            # Gen
            # click(
            #     driver,
            #     "/html/body/div[1]/main/div[2]/div/div/div[7]/div/div[2]/div[2]/table[1]/tbody/tr/td[1]/button",
            # )

            # Next state
            click(
                driver,
                "/html/body/div[4]/div/div/footer/div/footer/div/button[1]",
            )

            # Check error
            # click(
            #     driver,
            #     "/html/body/div[1]/main/div[2]/div/div/div[7]/ul/li[13]/a",
            # )
            # click(driver, "/html/body/div[1]/main/div[2]/div/div/div[6]/div/div[14]/div/div[2]/table/tbody/tr[1]", time=60*2)

    # Arrêter l'enregistrement
    if config.record_mode:
        video_recorder.stop()

    # Open conversation chat
    # conversation_button = driver.find_element(By.XPATH, '/html/body/header/nav/ul[3]/li[2]/a')
    # conversation_button.click()

    # Close bot chat
    # conversation_button = driver.find_element(By.XPATH, '/html/body/div[3]/div[1]/span[2]/a[2]')
    # conversation_button.click()

    # Fermez le navigateur
    # driver.quit()


def main():
    config = get_config()
    run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
