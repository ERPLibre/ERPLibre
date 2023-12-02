#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from selenium import webdriver
from selenium.webdriver.common.by import By

# Configuration pour lancer Firefox en mode de navigation privée
firefox_options = webdriver.FirefoxOptions()
firefox_options.add_argument("--private")

# Définissez la préférence pour les notifications de bureau
# 1 signifie "autoriser", 2 signifie "bloquer"
firefox_options.set_preference("permissions.default.desktop-notification", 1)

# Créez une instance du navigateur Firefox avec les options de navigation privée
driver = webdriver.Firefox(options=firefox_options)

# Ouvrez la page web
driver.get("http://127.0.0.1:8069/web")

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

# Fermez le navigateur
# driver.quit()
