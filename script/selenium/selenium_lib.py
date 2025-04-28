#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import os
import random
import re
import sys
import time
from subprocess import getoutput

from randomwordfr import RandomWordFr
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class SeleniumLib(object):
    def __init__(self, config):
        self.config = config
        self.video_recorder = None
        if self.config.video_suffix:
            self.filename = (
                f"video_{self.config.video_suffix}_"
                + time.strftime("%Y_%m_%d-%H_%M_%S")
                + ".webm"
            )
        else:
            self.filename = (
                "video_" + time.strftime("%Y_%m_%d-%H_%M_%S") + ".webm"
            )
        self.driver = None
        with open(".odoo-version") as txt:
            self.odoo_version = txt.read()

    def do_screenshot(self):
        if self.config.scenario_screenshot:
            dir_path = os.path.join(".", "screenshots")
            if not os.path.isdir(dir_path):
                os.mkdir(dir_path)
            file_path = os.path.join(
                dir_path,
                f"{self.config.scenario}_{str(int(time.time() * 10000))}.png",
            )
            self.driver.save_screenshot(file_path)

    def configure(self, ignore_open_web=False):
        # Configuration pour lancer Firefox en mode de navigation privée
        firefox_options = webdriver.FirefoxOptions()
        if not self.config.not_private_mode:
            firefox_options.add_argument("--private")

        # firefox_options.set_preference("browser.link.open_newwindow", 3)
        # firefox_options.set_preference("browser.link.open_newwindow.restriction", 2)

        # Définissez la préférence pour les notifications de bureau
        # 1 signifie "autoriser", 2 signifie "bloquer"
        firefox_options.set_preference(
            "permissions.default.desktop-notification", 1
        )
        firefox_services = None
        if self.config.firefox_binary_path:
            firefox_services = Service(
                executable_path=self.config.firefox_binary_path
            )
        if self.config.gecko_binary_path:
            firefox_options.binary_location = self.config.gecko_binary_path

        # Créez une instance du navigateur Firefox avec les options de navigation privée
        try:
            self.driver = webdriver.Firefox(
                options=firefox_options, service=firefox_services
            )
        except Exception:
            print(
                "Cannot open Firefox profile, so will force firefox snap for"
                " Ubuntu users."
            )
            firefox_services = Service(
                executable_path=getoutput(
                    "find /snap/firefox -name geckodriver"
                ).split("\n")[-1]
            )
            firefox_options.binary_location = getoutput(
                "find /snap/firefox -name firefox"
            ).split("\n")[-1]
            self.driver = webdriver.Firefox(
                options=firefox_options, service=firefox_services
            )

        # Ajout de l'enregistrement
        if self.config.record_mode:
            # Create recording
            new_path = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            sys.path.append(new_path)
            from script.selenium.selenium_video import VideoRecorder

            self.video_recorder = VideoRecorder(
                self.driver, filename=self.filename
            )
            # import vlc

        # Install DarkReader to help my eyes
        # TODO do a script to check if it's the last version
        if not self.config.no_dark_mode:
            self.driver.install_addon(
                "./script/selenium/darkreader-firefox.xpi", temporary=True
            )
            self.driver.install_addon(
                "./script/selenium/odoo_debug-4.0.xpi", temporary=True
            )

        if not self.config.not_private_mode and not self.config.no_dark_mode:
            self.driver.get("about:addons")
            # Enable Dark Reader into incognito
            self.click("/html/body/div/div[1]/categories-box/button[2]")
            self.click(
                "/html/body/div/div[2]/div/addon-list/section[1]/addon-card/div/div/div/div/button",
            )
            self.click(
                "/html/body/div/div[2]/div/addon-list/section[1]/addon-card/div/addon-options/panel-list/panel-item[5]",
            )
            self.click(
                "/html/body/div/div[2]/div/addon-card/div/addon-details/named-deck/section/div[5]/div/label[1]/input",
            )

            # Enable Odoo_debug into incognito
            # Back
            self.click(
                "/html/body/div/div[2]/addon-page-header/div/div[2]/button"
            )
            self.click(
                "/html/body/div/div[2]/div/addon-list/section[1]/addon-card[2]/div/div/div/div/button",
            )
            self.click(
                "/html/body/div/div[2]/div/addon-list/section[1]/addon-card[2]/div/addon-options/panel-list/panel-item[5]",
            )
            self.click(
                "/html/body/div/div[2]/div/addon-card/div/addon-details/named-deck/section/div[5]/div/label[1]/input",
            )

        # Ouvrez la page web
        if not ignore_open_web:
            self.driver.get(f"{self.config.url}/web")

        # Close tab opening by DarkReader
        if self.config.not_private_mode and not self.config.no_dark_mode:
            self.driver.switch_to.window(self.driver.window_handles[-1])
            self.driver.close()
            self.driver.switch_to.window(self.driver.window_handles[0])

    @staticmethod
    def get_french_word_no_space_no_accent():
        word = ""
        rw = RandomWordFr()
        while not word or " " in word:
            word = rw.get().get("word")
            if not re.match("^[a-zA-Z_]+$", word):
                word = ""
        return word

    def click(self, xpath, timeout=5):
        wait = WebDriverWait(self.driver, timeout)
        button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    xpath,
                )
            )
        )
        button.click()
        return button

    def get_element(self, by: str = By.ID, value: str = None, timeout=5):
        wait = WebDriverWait(self.driver, timeout)
        ele = wait.until(
            EC.visibility_of_any_elements_located(
                (
                    by,
                    value,
                )
            )
        )

        return ele[0]

    def get_element_not_visible(
        self, by: str = By.ID, value: str = None, timeout=5
    ):
        wait = WebDriverWait(self.driver, timeout)
        ele = wait.until(
            EC.presence_of_element_located(
                (
                    by,
                    value,
                )
            )
        )

        return ele

    def get_elements_not_visible(
        self, by: str = By.ID, value: str = None, timeout=5
    ):
        wait = WebDriverWait(self.driver, timeout)
        ele = wait.until(
            EC.presence_of_all_elements_located(
                (
                    by,
                    value,
                )
            )
        )

        return ele

    def get_all_element(self, by: str = By.ID, value: str = None, timeout=5):
        wait = WebDriverWait(self.driver, timeout)
        ele = wait.until(
            EC.visibility_of_all_elements_located(
                (
                    by,
                    value,
                )
            )
        )

        return ele

    def wait_new_element_and_click(
        self,
        by: str = By.ID,
        value: str = None,
        delay_wait=1,
        timeout=5,
        inject_cursor=False,
    ):
        new_element = self.wait_new_element(
            by=by, value=value, delay_wait=delay_wait, timeout=timeout
        )
        if new_element:
            if inject_cursor:
                self.inject_cursor()
            self.click_with_mouse_move(element=new_element, no_scroll=True)
        return new_element

    def wait_new_element(
        self,
        by: str = By.ID,
        value: str = None,
        delay_wait=1,
        timeout=5,
        timeout_wait=None,
    ):
        element = None
        # TODO support timeout_wait
        while element is None:
            time.sleep(delay_wait)
            try:
                element = self.get_element(by, value, timeout)
            except TimeoutException as e:
                pass
            print(f"Waiting {delay_wait} seconds after value '{value}'")
        return element

    def wait_add_new_element_and_click(
        self, by: str = By.ID, value: str = None, delay_wait=1, timeout=5
    ):
        new_element = self.wait_add_new_element(
            by=by, value=value, delay_wait=delay_wait, timeout=timeout
        )
        self.click_with_mouse_move(element=new_element, no_scroll=True)
        return new_element

    def wait_add_new_element(
        self, by: str = By.ID, value: str = None, delay_wait=1, timeout=5
    ):
        all_element_init = self.get_all_element(by=by, value=value)
        len_all_element_init = len(all_element_init)
        len_all_element = len_all_element_init
        all_element = []
        while len_all_element_init == len_all_element:
            time.sleep(delay_wait)
            all_element = self.get_all_element(by=by, value=value)
            len_all_element = len(all_element)
            print(f"Waiting {delay_wait} seconds after value '{value}'")
        new_element = all_element[-1]
        return new_element

    def wait_increment_number_text_and_click(
        self, by: str = By.ID, value: str = None, delay_wait=1, timeout=5
    ):
        element_init = self.get_element(by=by, value=value, timeout=timeout)
        actual_number = int(element_init.text)
        number_goal = actual_number + 1
        while actual_number < number_goal:
            time.sleep(delay_wait)
            element_goal = self.get_element(
                by=by, value=value, timeout=timeout
            )
            actual_number = int(element_goal.text)
            print(f"Waiting {delay_wait} seconds after value '{value}'")
        self.click_with_mouse_move(element=element_init, no_scroll=True)
        return element_init

    def click_with_mouse_move(
        self,
        by: str = By.ID,
        value: str = None,
        timeout: int = 5,
        no_scroll: bool = False,
        viewport_ele_by: str = By.ID,
        viewport_ele_value: str = None,
        element: WebElement = None,
        with_index: bool = False,
        index_of_list: int = 0,
    ):
        # ele = self.driver.find_element(by, value)
        if element:
            ele = element
        else:
            ele = self.get_element(by, value, timeout)
        if not no_scroll:
            viewport_ele = None
            if viewport_ele_value:
                viewport_ele = self.get_element(
                    viewport_ele_by, viewport_ele_value, timeout
                )
            self.scrollto_element(ele, viewport_ele=viewport_ele)
            # ActionChains(self.driver).move_to_element(ele).click().perform()
            ActionChains(self.driver).move_to_element(ele).perform()
        time.sleep(self.config.selenium_default_delay)
        wait = WebDriverWait(self.driver, timeout)
        if element:
            button = wait.until(EC.element_to_be_clickable(element))
        else:
            if with_index:
                buttons = wait.until(
                    EC.presence_of_all_elements_located(
                        (
                            by,
                            value,
                        )
                    )
                )
                button = buttons[index_of_list]
            else:
                button = wait.until(
                    EC.element_to_be_clickable(
                        (
                            by,
                            value,
                        )
                    )
                )
        try:
            button.click()
        except ElementClickInterceptedException as e:
            try:
                print(e)
                self.driver.execute_script(
                    "arguments[0].scrollIntoView(true);", button
                )
                button.click()
            except ElementClickInterceptedException as e:
                print(e)
                self.driver.execute_script("arguments[0].click();", button)
        return button

    def click_canvas_form(
        self,
        by: str = By.ID,
        value: str = None,
        timeout: int = 5,
        form="carre",
    ):

        # ele = self.driver.find_element(by, value)
        ele = self.get_element(by, value, timeout)
        actions = ActionChains(self.driver)
        actions.move_to_element_with_offset(ele, -50, -50)
        actions.click_and_hold()
        if form == "carre":
            actions.move_by_offset(50, 0)
            actions.move_by_offset(0, 50)
            actions.move_by_offset(-50, 0)
            actions.move_by_offset(0, -50)

        actions.release()
        actions.perform()

    def input_text_with_mouse_move(
        self,
        by: str = By.ID,
        value: str = None,
        text_value: str = "",
        delay_after: int = -1,
        timeout: int = 5,
        no_scroll: bool = False,
        viewport_ele_by: str = By.ID,
        viewport_ele_value: str = None,
        clear_before: bool = False,
        click_before: bool = False,
    ):
        # ele = self.driver.find_element(by, value)
        ele = self.get_element(by, value)
        if not no_scroll:
            viewport_ele = None
            if viewport_ele_value:
                viewport_ele = self.get_element(
                    viewport_ele_by, viewport_ele_value, timeout
                )
            self.scrollto_element(ele, viewport_ele=viewport_ele)
            ActionChains(self.driver).move_to_element(ele).perform()

        # Write content
        if click_before:
            # Need this to update a datetimepicker
            ele.click()
            time.sleep(0.3)
        if clear_before:
            ele.clear()
            if click_before:
                # Need this to update a datetimepicker
                ele.click()
                time.sleep(0.3)
        ele.send_keys(text_value)
        if delay_after > 0:
            time.sleep(delay_after)
        elif self.config.selenium_default_delay > 0:
            time.sleep(self.config.selenium_default_delay)

    def scrollto_element1(self, element_name):
        # ele = self.driver.find_element(By.TAG_NAME, element_name)
        ele = self.get_element(By.TAG_NAME, element_name)
        # delta_y = ele.rect["y"]
        ActionChains(self.driver).scroll_to_element(ele).perform()
        # ele = self.get_element(By.TAG_NAME, element_name)
        # delta_y = ele.rect["y"]
        # ActionChains(self.driver).scroll_by_amount(0, delta_y).perform()
        time.sleep(0.5)

    def scrollto_xpath5(self, xpath):
        footer = self.driver.find_element(By.XPATH, xpath)
        # footer = self.get_element(By.XPATH, xpath)
        delta_y = footer.rect["y"]
        ActionChains(self.driver).scroll_by_amount(0, int(delta_y)).perform()
        time.sleep(0.5)

    def scrollto_xpath2(self, xpath):
        footer = self.driver.find_element(By.XPATH, xpath)
        # footer = self.get_element(By.XPATH, xpath)
        scroll_origin = ScrollOrigin.from_element(footer)
        ActionChains(self.driver).scroll_from_origin(
            scroll_origin, 0, 100
        ).perform()
        time.sleep(0.5)

    def scrollto_xpath3(self, xpath):
        footer = self.driver.find_element(By.XPATH, xpath)
        # footer = self.get_element(By.XPATH, xpath)
        scroll_origin = ScrollOrigin.from_element(footer)
        ActionChains(self.driver).scroll_to_element(scroll_origin).perform()
        time.sleep(0.5)

    def scrollto_xpath(
        self,
        xpath,
        offset_middle=True,
        smooth_scroll=True,
        smooth_speed=50,
        smooth_fps=1 / 25,
    ):
        footer = self.driver.find_element(By.XPATH, xpath)
        # footer = self.get_element(By.XPATH, xpath)
        scroll_origin = ScrollOrigin.from_viewport(10, 10)
        delta_y = footer.rect["y"]
        if offset_middle:
            # TODO check size windows and divide by 2
            delta_y -= 400
        print(f"scroll to xpath at y:{delta_y} position")
        if smooth_scroll:
            actual_pos = 0
            while delta_y > actual_pos:
                actual_pos += smooth_speed
                print(actual_pos)
                ActionChains(self.driver).scroll_from_origin(
                    scroll_origin, 0, int(smooth_speed)
                ).perform()
                print(f"Wait {smooth_fps} seconds")
                time.sleep(smooth_fps)
            print("end")
        else:
            ActionChains(self.driver).scroll_from_origin(
                scroll_origin, 0, int(delta_y)
            ).perform()

        time.sleep(0.5)

    def scrollto_element(
        self,
        element,
        offset_middle=True,
        smooth_scroll=True,
        smooth_speed=50,
        smooth_fps=1 / 25,
        viewport_ele=None,
    ):
        if viewport_ele:
            scroll_origin = ScrollOrigin.from_element(viewport_ele, 10, 10)
        else:
            scroll_origin = ScrollOrigin.from_viewport(10, 10)
        delta_y = element.rect["y"]
        if offset_middle:
            # TODO check size windows and divide by 2
            delta_y -= 400
        print(f"scroll to xpath at y:{delta_y} position")
        if smooth_scroll:
            actual_pos = 0
            while delta_y > actual_pos:
                actual_pos += smooth_speed
                print(actual_pos)
                ActionChains(self.driver).scroll_from_origin(
                    scroll_origin, 0, int(smooth_speed)
                ).perform()
                print(f"Wait {smooth_fps} seconds")
                time.sleep(smooth_fps)
            print("end")
        else:
            ActionChains(self.driver).scroll_from_origin(
                scroll_origin, 0, int(delta_y)
            ).perform()

        # action = ActionChains(self.driver)
        # action.click_and_hold(element).move_by_offset(0, 1).perform()
        # # Don't forget to release the click_and_hold, for example with:
        # action.reset_actions()
        time.sleep(0.5)

    def inject_cursor(self):
        cursor_script = """
        var cursor = document.createElement('div');
        cursor.style.position = 'absolute';
        cursor.style.zIndex = '9999';
        cursor.style.width = '30px';
        cursor.style.height = '30px';
        cursor.style.borderRadius = '50%';
        cursor.style.backgroundColor = 'red';
        cursor.style.pointerEvents = 'none';
        document.body.appendChild(cursor);

        document.addEventListener('mousemove', function(e) {
          cursor.style.left = e.pageX - 5 + 'px';
          cursor.style.top = e.pageY - 5 + 'px';
        });
        """
        try:
            try:
                self.driver.execute_script(cursor_script)
            except Exception as e:
                time.sleep(1)
                print("Error execute script cursor, wait 1 second")
                self.driver.execute_script(cursor_script)
        except Exception as e:
            time.sleep(3)
            print("Error execute script cursor, wait 3 second")
            self.driver.execute_script(cursor_script)

    def scenario_create_new_account_with_random_user(
        self, show_cursor=False, def_action_before_submit=None
    ):
        # Click no account
        if show_cursor:
            self.inject_cursor()
        self.click_with_mouse_move(
            By.XPATH, "/html/body/div[1]/main/div/form/div[3]/div[1]/a[1]"
        )

        # Trouvez les éléments du formulaire
        if show_cursor:
            self.inject_cursor()

        # Remplissez le courriel et le mot de passe
        first_name = self.get_french_word_no_space_no_accent()
        password = first_name.lower()
        second_name = self.get_french_word_no_space_no_accent()
        full_name = f"{first_name} {second_name}"
        domain = self.get_french_word_no_space_no_accent().lower()

        self.input_text_with_mouse_move(
            By.NAME, "login", f"{password}@{domain}.com"
        )
        self.input_text_with_mouse_move(By.NAME, "name", full_name)
        self.input_text_with_mouse_move(By.NAME, "password", password)
        self.input_text_with_mouse_move(By.NAME, "confirm_password", password)
        if def_action_before_submit:
            def_action_before_submit()
        self.click_with_mouse_move(
            By.XPATH, "/html/body/div[1]/main/div/form/div[6]/button"
        )

    def open_tab(self, url):
        # Open a new window
        self.driver.execute_script("window.open('');")
        # Switch to the new window and open new URL
        self.driver.switch_to.window(self.driver.window_handles[1])
        self.driver.get(url)

    def switch_tab(self, index):
        # Switch to the new window and open new URL
        self.driver.switch_to.window(self.driver.window_handles[index])

    def refresh(self):
        self.driver.refresh()

    def check_bot_chat_and_close(self):
        try:
            xpath_button = "/html/body/div[3]/div[1]/span[2]/a[2]"
            button = self.driver.find_element(By.XPATH, xpath_button)
            # button = self.get_element(By.XPATH, xpath_button)
            self.click(self.driver, xpath_button)
        except Exception:
            print("Chatbot cannot be found, stop searching it.")

    # Website
    def odoo_show_robot_message(self, msg="Ho no!"):
        # Injecter l'animation SVG dans la page
        script_text = ""
        if msg:
            script_text = f"""
                // Ajouter le texte
                const textElement = document.createElement('div');
                textElement.innerText = '{msg}';
                textElement.style.color = '#FFFFFF';
                textElement.style.fontSize = '24px';
                textElement.style.marginBottom = '20px';
                textElement.style.fontWeight = 'bold';

                overlay.appendChild(textElement);
            """
        script = (
            """
            (function() {
                // Créer un div pour l'overlay
                const overlay = document.createElement('div');
                overlay.style.position = 'fixed';
                overlay.style.top = '0';
                overlay.style.left = '0';
                overlay.style.width = '100%';
                overlay.style.height = '100%';
                overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
                overlay.style.display = 'flex';
                overlay.style.justifyContent = 'center';
                overlay.style.alignItems = 'center';
                overlay.style.zIndex = '9999';

                // Contenu SVG du robot
                const svgContent = `
                    <svg class="robot-animation" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" style="width: 150px; cursor: pointer;">
                        <circle cx="32" cy="32" r="30" fill="#FF5252"/>
                        <path fill="#FFF" d="M20 27h24l-6-12h-12z"/>
                        <circle cx="24" cy="44" r="4" fill="#FFF"/>
                        <circle cx="40" cy="44" r="4" fill="#FFF"/>
                    </svg>
                `;
                """
            + script_text
            + """
                // Ajouter le contenu SVG au div
                overlay.innerHTML += svgContent;

                // Ajouter un gestionnaire de clic pour supprimer l'overlay
                overlay.onclick = function() {
                    overlay.style.display = 'none';
                };

                // Ajouter l'overlay au corps du document
                document.body.appendChild(overlay);
            })();
        """
        )

        # Exécuter le script pour injecter l'animation
        self.driver.execute_script(script)
        print(f"Script inject robot svg with msg '{msg}'")

    def odoo_website_menu_click(self, from_text=""):
        if not from_text:
            raise Exception(
                "Cannot click, empty parameter from method"
                " odoo_website_menu_click"
            )
        button = self.click_with_mouse_move(
            By.LINK_TEXT, from_text, timeout=30
        )
        return button

    # Web
    def odoo_fill_widget_char(self, field_name, text):
        # Type input
        text_field = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.NAME, field_name))
        )
        text_field.send_keys(text)
        return text_field

    def odoo_web_click_principal_menu(self):
        # Click menu button
        if self.odoo_version == "16.0":
            button = self.click_with_mouse_move(
                By.XPATH,
                "//button[contains(@class, 'dropdown-toggle') and"
                " .//i[contains(@class, 'oi-apps')]]",
                timeout=10,
            )
        elif self.odoo_version == "14.0":
            button = self.click_with_mouse_move(
                By.CSS_SELECTOR, "a.full[data-toggle='dropdown']", timeout=30
            )
        return button

    def odoo_web_principal_menu_click_root_menu(self, from_text=""):
        if not from_text:
            raise Exception(
                "Cannot click, empty parameter from method"
                " odoo_web_principal_menu_click_root_menu"
            )
        button = self.click_with_mouse_move(
            By.LINK_TEXT, from_text, timeout=30
        )
        # If not work, force it
        # selenium_tool.driver.execute_script("arguments[0].click();", button)
        return button

    def odoo_web_form_click_statusbar_button_status(
        self, status_label, timeout=10
    ):
        try:
            status_button = self.click_with_mouse_move(
                By.XPATH,
                "//button[contains(@class, 'o_arrow_button') and"
                f" contains(text(), '{status_label}')]",
                timeout=timeout,
            )
        except Exception as e:
            status_button = self.click_with_mouse_move(
                By.XPATH,
                "//button[contains(@class, 'o_arrow_button') and"
                f" text()='{status_label}']",
                timeout=timeout,
            )
        print(f"Bouton du statusbar avec le label '{status_label}' cliqué.")
        return status_button

    def odoo_web_form_click_statusbar_button_status_floating(
        self, status_label, timeout=10
    ):
        status_button = self.click_with_mouse_move(
            By.XPATH,
            "//span[contains(@class, 'o_arrow_button') and contains(text(),"
            f" '{status_label}')]",
            timeout=timeout,
        )
        print(f"Bouton du statusbar avec le label '{status_label}' cliqué.")
        return status_button

    def odoo_web_form_click_statusbar_button_status_plus(
        self, status_label, timeout=10
    ):
        status_button = self.click_with_mouse_move(
            By.XPATH,
            "//button[contains(@class, 'o_arrow_button') and"
            f" text()='{status_label}']",
            timeout=timeout,
        )
        print(f"Bouton du statusbar avec le label '{status_label}' cliqué.")
        return status_button

    def odoo_web_form_click_button_statusbar(
        self, btn_label, btn_class="btn-primary"
    ):
        status_button = self.click_with_mouse_move(
            By.XPATH,
            f"//button[contains(@class, '{btn_class}') and contains(span,"
            f" '{btn_label}')]",
            timeout=30,
        )
        print(f"Bouton du statusbar avec le label '{btn_label}' cliqué.")
        return status_button

    def odoo_web_form_click_button_action(self, btn_action):
        status_button = self.click_with_mouse_move(
            By.NAME,
            btn_action,
            timeout=30,
        )
        print(f"Bouton avec l'action '{btn_action}' cliqué.")
        return status_button

    def odoo_web_form_click_save_action(self):
        return self.odoo_web_form_click_by_classname_action("o_form_button_save")

    def odoo_web_form_click_web_publish_action(self):
        return self.odoo_web_form_click_button_action("website_publish_button")

    def odoo_web_form_click_by_classname_action(self, custom_class_name):
        status_button = self.click_with_mouse_move(
            By.CLASS_NAME,
            custom_class_name,
            timeout=30,
        )
        print(f"Bouton avec l'action '{custom_class_name}' cliqué.")
        return status_button

    def odoo_web_kanban_card(self, card_label):
        # From web view kanban, list
        kanban_card = self.click_with_mouse_move(
            By.XPATH,
            "//div[contains(@class,"
            f" 'o_kanban_record')]//span[contains(text(), '{card_label}')]",
            timeout=30,
        )
        # kanban_card = self.driver.find_element(By.XPATH,
        #                                        f"//div[contains(@class, 'o_kanban_record')]//span[contains(text(), '{card_label}')]")
        # kanban_card.click()
        print(f"Carte Kanban avec le label '{card_label}' cliquée.")
        return kanban_card

    def odoo_web_action_button_new(self):
        # From web view kanban, list
        return self.click_with_mouse_move(
            By.CLASS_NAME, "o-kanban-button-new", timeout=30
        )

    def odoo_web_kanban_click(self, button_text, btn_class="btn-primary"):
        # From web view kanban, list
        return self.click_with_mouse_move(
            By.XPATH,
            f"//button[contains(@class, 'btn {btn_class} o_kanban_edit') and"
            f" text()='{button_text}']",
            timeout=30,
        )

    def odoo_web_form_notebook_tab_click(self, tab_text):
        return self.click_with_mouse_move(
            By.XPATH,
            f"//a[text()='{tab_text}']",
            timeout=30,
        )

    # Web
    def odoo_fill_widget_char(self, field_name, text, is_label=False):
        # Type input
        if self.odoo_version == "14.0":
            text_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, field_name))
            )
        elif self.odoo_version == "16.0":
            text_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, field_name))
            )

        text_field.send_keys(text)
        return text_field

    def odoo_fill_widget_selection(self, field_name, text):
        return self.odoo_fill_widget_many2one(field_name, text)

    def odoo_fill_widget_boolean(self, field_name, value):
        self.driver.implicitly_wait(10)
        checkbox_div = self.driver.find_element(
            By.XPATH, f"//div[@name='{field_name}']"
        )
        checkbox = checkbox_div.find_element(
            By.CSS_SELECTOR, 'input[type="checkbox"]'
        )
        is_selected = checkbox.get_attribute("selected")
        # Check if already set
        if is_selected == "true" and value:
            return checkbox
        elif is_selected is None and not value:
            return checkbox
        parent_element = checkbox.find_element(By.XPATH, "..")
        parent_element.click()
        return checkbox

    def odoo_fill_widget_many2one(self, field_name, text):
        # TODO read this file odoo/addons/web/static/src/js/fields/field_registry.js
        div_field = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.NAME, field_name))
        )

        input_field = div_field.find_element(By.XPATH, ".//input")
        input_field.send_keys(text)
        # TODO improve speed by observation of comportement
        time.sleep(1)
        input_field.send_keys(Keys.ENTER)

        return input_field

    def odoo_fill_widget_date(self, field_name, date_to_select):
        # Type date
        self.driver.implicitly_wait(10)
        checkbox_div = self.driver.find_element(
            By.XPATH, f"//div[@name='{field_name}']"
        )
        checkbox_div.click()
        # TODO improve speed by observation of comportement
        time.sleep(0.5)
        checkbox_date_div = self.driver.find_element(
            By.CSS_SELECTOR, ".bootstrap-datetimepicker-widget"
        )
        # time.sleep(0.5)
        str_date_today = date_to_select.strftime("%Y-%m-%d")
        new_value = checkbox_date_div.find_element(
            By.XPATH, f"//td[@data-day='{str_date_today}']"
        )
        new_value.click()
        return new_value

    def start_record(self):
        # Démarrer l'enregistrement
        if self.config.record_mode:
            if self.config.record_wait_before_start_time:
                time.sleep(int(self.config.record_wait_before_start_time))
            # Sync before record
            has_sync_error = False
            if self.config.sync_file_record_read:
                if not self.config.sync_file_record_write:
                    print(
                        "Error, cannot sync, missing 'sync_file_record_write'"
                    )
                    has_sync_error = True
            if self.config.sync_file_record_write:
                if not self.config.sync_file_record_read:
                    print(
                        "Error, cannot sync, missing 'sync_file_record_read'"
                    )
                    has_sync_error = True
            if (
                not has_sync_error
                and self.config.sync_file_record_read
                and self.config.sync_file_record_write
            ):
                # Do sync
                file_name_1 = f"/tmp/erplibre_sync_temp_file{self.config.sync_file_record_write}"
                file_name_2 = f"/tmp/erplibre_sync_temp_file{self.config.sync_file_record_read}"
                with open(file_name_1, "w") as file:
                    file.write(f"Recording {self.filename}\n")
                while not os.path.exists(file_name_2):
                    var_wait_time = 0.001
                    print(f"File {self.filename} wait {var_wait_time} seconds")
                    time.sleep(var_wait_time)
            self.video_recorder.start()

    def stop_record(self):
        time.sleep(self.config.selenium_default_delay_presentation)

        # Arrêter l'enregistrement
        if self.config.record_mode:
            time.sleep(self.config.selenium_video_time_waiting_end)
            self.video_recorder.stop()
            print("End of recording video")
            print(self.filename)

            if self.config.selenium_video_auto_play_video:
                print(f"Play video {self.filename}")
                # By python-vlc
                # media_player = vlc.MediaPlayer(filename)
                # media = vlc.Media(filename)
                # media_player.set_media(media)
                # media_player.play()
                # time.sleep(15)
                # By external process
                os.popen(f"vlc {self.filename}")

    def generer_code_postal_quebec(self):
        # Zip code from quebec canada
        premieres_lettres = ["G", "H", "J"]

        premiere_lettre = random.choice(premieres_lettres)

        deuxieme_lettre = chr(random.randint(65, 90))
        chiffre = str(random.randint(0, 9))
        troisieme_lettre = chr(random.randint(65, 90))

        code_postal = f"{premiere_lettre}{chiffre}{deuxieme_lettre} {chiffre}{troisieme_lettre}{chiffre}"

        return code_postal

    def generer_numero_telephone_quebec(self):
        # Number from quebec canada
        indicateurs_regionaux = [
            "418",
            "438",
            "450",
            "514",
            "579",
            "581",
            "819",
            "873",
        ]

        indicatif = random.choice(indicateurs_regionaux)

        numero = "".join(random.choices("0123456789", k=7))

        numero_telephone = f"({indicatif}) {numero[:3]}-{numero[3:]}"

        return numero_telephone

    def generer_date_naissance(self, age_minimum=16):
        annee_actuelle = datetime.datetime.now().year
        annee_maximale = annee_actuelle - age_minimum

        annee_minimale = 1900

        annee_naissance = random.randint(annee_minimale, annee_maximale)

        mois_naissance = random.randint(1, 12)
        jour_naissance = random.randint(1, 28)

        date_naissance = datetime.datetime(
            annee_naissance, mois_naissance, jour_naissance
        )

        return date_naissance.strftime("%Y-%m-%d")


def fill_parser(parser):
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8069",
        help="First URL to open.",
    )

    group_animation = parser.add_argument_group(title="Animation")
    group_animation.add_argument(
        "--selenium_default_delay",
        default=0.4,
        type=float,
        help="Pause at the end of an action.",
    )

    group_browser = parser.add_argument_group(title="Browser")
    group_browser.add_argument(
        "--not_private_mode",
        action="store_true",
        help="Default is private mode.",
    )
    group_browser.add_argument(
        "--no_dark_mode",
        action="store_true",
        help=(
            "By default, will be in dark mode, because the main developer"
            " like it!"
        ),
    )
    group_browser.add_argument(
        "--firefox_binary_path",
        help="Can specify firefox path to open selenium.",
    )
    group_browser.add_argument(
        "--gecko_binary_path",
        help="Can specify firefox path to open selenium.",
    )

    group_record = parser.add_argument_group(title="Recording")
    group_record.add_argument(
        "--record_mode",
        action="store_true",
        help="Start recording (not finish to be implemented).",
    )
    group_record.add_argument(
        "--record_wait_before_start_time",
        help="Time to wait in second before start recording.",
    )
    parser.add_argument(
        "--video_suffix",
        default="",
        help="Will modify video name.",
    )
    parser.add_argument(
        "--sync_file_record_read",
        default="",
        help=(
            "Will sync and check file from tmp before record, write before"
            " read."
        ),
    )
    parser.add_argument(
        "--sync_file_record_write",
        default="",
        help=(
            "Will sync and check file from tmp before record, write before"
            " read."
        ),
    )
    group_record.add_argument(
        "--selenium_video_time_waiting_end",
        default=5,
        type=int,
        help="Pause at the end before close video.",
    )
    group_record.add_argument(
        "--selenium_default_delay_presentation",
        default=2,
        type=float,
        help="Pause at the end before close video.",
    )
    group_record.add_argument(
        "--selenium_video_auto_play_video",
        action="store_true",
        help="Autoplay the video when done.",
    )
