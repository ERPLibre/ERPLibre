#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

private_mode = True
record_mode = False
dark_reader_mode = True


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


if record_mode:
    new_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    sys.path.append(new_path)
    from script.selenium.selenium_video import VideoRecorder

# Configuration pour lancer Firefox en mode de navigation privée
firefox_options = webdriver.FirefoxOptions()
if private_mode:
    firefox_options.add_argument("--private")

# Définissez la préférence pour les notifications de bureau
# 1 signifie "autoriser", 2 signifie "bloquer"
firefox_options.set_preference("permissions.default.desktop-notification", 1)

# Créez une instance du navigateur Firefox avec les options de navigation privée
driver = webdriver.Firefox(options=firefox_options)

# Ajout de l'enregistrement
if record_mode:
    video_recorder = VideoRecorder(driver)
else:
    video_recorder = None

# Install DarkReader to help my eyes
# TODO do a script to check if it's the last version
if dark_reader_mode:
    driver.install_addon(
        "./script/selenium/darkreader-firefox.xpi", temporary=True
    )
    driver.install_addon(
        "./script/selenium/odoo_debug-4.0.xpi", temporary=True
    )

if private_mode and dark_reader_mode:
    driver.get("about:addons")
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
    click(driver, "/html/body/div/div[2]/addon-page-header/div/div[2]/button")
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
driver.get("http://127.0.0.1:8069/web")

# Close tab opening by DarkReader
if not private_mode and dark_reader_mode:
    driver.switch_to.window(driver.window_handles[-1])
    driver.close()
    driver.switch_to.window(driver.window_handles[0])

# Démarrer l'enregistrement
if record_mode:
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

# Open View
click(driver, "/html/body/header/nav/div/div[1]/div[2]/div/div/div/ul/li[2]/a")
click(driver, "/html/body/div[1]/main/div[2]/div/div/table/tbody/tr[1]/td[2]")
click(driver, "/html/body/header/nav/div/div[1]/div[2]/div/div/div/ul/li[2]/a")
click(driver, "/html/body/div[1]/main/div[2]/div/div/table/tbody/tr[1]/td[2]")

# CG self
# Bouton modifier
click(driver, "/html/body/div[1]/main/div[1]/div[2]/div/div/div[1]/button[1]")
# Tab CG
click(driver, "/html/body/div[1]/main/div[2]/div/div/div[7]/ul/li[3]/a")
# Disable «Stop Execution if Env Not Clean
# click(
#     driver,
#     "/html/body/div[1]/main/div[2]/div/div/div[7]/div/div[3]/div[2]/table[2]/tbody/tr/td[1]/label",
# )
# Gen
click(
    driver,
    "/html/body/div[1]/main/div[2]/div/div/div[7]/div/div[3]/div[2]/table[1]/tbody/tr[2]/td[1]/button",
)

# Check error
click(driver, "/html/body/div[1]/main/div[2]/div/div/div[7]/ul/li[14]/a")
# click(driver, "/html/body/div[1]/main/div[2]/div/div/div[6]/div/div[14]/div/div[2]/table/tbody/tr[1]", time=60*2)

# Arrêter l'enregistrement
if record_mode:
    video_recorder.stop()

# Open conversation chat
# conversation_button = driver.find_element(By.XPATH, '/html/body/header/nav/ul[3]/li[2]/a')
# conversation_button.click()

# Close bot chat
# conversation_button = driver.find_element(By.XPATH, '/html/body/div[3]/div[1]/span[2]/a[2]')
# conversation_button.click()

# Fermez le navigateur
# driver.quit()
