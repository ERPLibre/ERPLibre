#!/usr/bin/env python3
from randomwordfr import RandomWordFr
import re
import os
import sys
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.firefox.service import Service
from subprocess import getoutput
from selenium.webdriver import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin


class SeleniumLib(object):
    def __init__(self, config):
        self.config = config
        self.video_recorder = None
        self.filename = "video_" + time.strftime("%Y_%m_%d-%H_%M_%S") + ".webm"
        self.driver = None

    def configure(self):
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

    def click_with_mouse_move(
        self,
        by: str = By.ID,
        value: str = None,
        timeout: int = 5,
        no_scroll: bool = False,
        viewport_ele_by: str = By.ID,
        viewport_ele_value: str = None,
    ):
        # ele = self.driver.find_element(by, value)
        ele = self.get_element(by, value, timeout)
        if not no_scroll:
            viewport_ele = None
            if viewport_ele_value:
                viewport_ele = self.get_element(
                    viewport_ele_by, viewport_ele_value, timeout
                )
            self.scrollto_element(ele, viewport_ele=viewport_ele)
            ActionChains(self.driver).move_to_element(ele).perform()
        time.sleep(self.config.selenium_default_delay)
        wait = WebDriverWait(self.driver, timeout)
        button = wait.until(
            EC.element_to_be_clickable(
                (
                    by,
                    value,
                )
            )
        )
        button.click()

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
        self.driver.execute_script(cursor_script)

    def open_tab(self, url):
        # Open a new window
        self.driver.execute_script("window.open('');")
        # Switch to the new window and open new URL
        self.driver.switch_to.window(self.driver.window_handles[1])
        self.driver.get(url)

    def check_bot_chat_and_close(self):
        try:
            xpath_button = "/html/body/div[3]/div[1]/span[2]/a[2]"
            button = self.driver.find_element(By.XPATH, xpath_button)
            # button = self.get_element(By.XPATH, xpath_button)
            self.click(self.driver, xpath_button)
        except Exception:
            print("Chatbot cannot be found, stop searching it.")

    def start_record(self):
        # Démarrer l'enregistrement
        if self.config.record_mode:
            self.video_recorder.start()

    def stop_record(self):
        time.sleep(self.config.selenium_default_delay_presentation)

        # Arrêter l'enregistrement
        if self.config.record_mode:
            time.sleep(self.config.selenium_video_time_waiting_end)
            self.video_recorder.stop()
            print("End of recording video")

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
        help="Pause at the end before close video.",
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
