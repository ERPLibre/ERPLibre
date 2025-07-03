#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import io
import itertools
import os
import random
import subprocess
import threading
import time
from fractions import Fraction

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import DialEventType, TouchscreenEventType
from StreamDeck.ImageHelpers import PILHelper
from StreamDeck.Transport.Transport import TransportError

# import keyboard


ASSETS_PATH = os.path.join(os.path.dirname(__file__), "Assets")
DEFAULT_BRIGHTNESS = 30
FRAMES_PER_SECOND = 100
KEY_SPACING = (36, 36)
default_police = ""
is_all_animation_test = False
is_big_image = True
# is_feature = "uniselection"
is_feature = "dynamic_smyles"
# default_police = "arial.ttf"


class StreamDeckController(object):
    def init(self):
        self.streamdeck_brightness = DEFAULT_BRIGHTNESS
        streamdecks = DeviceManager().enumerate()
        self.lst_smyles = [
            {"x": 0, "y": 100},
            {"x": 220, "y": 100},
            {"x": 220 * 2, "y": 100},
            {"x": 220 * 3, "y": 100},
        ]
        self.is_debug = False
        self.last_generated_img_byte_arr = None
        self.last_dial = None
        self.last_value = None
        self.last_is_move_dist_x = None
        self.last_is_touch = None
        self.last_is_direction_left = None

        print("Found {} Stream Deck(s).\n".format(len(streamdecks)))

        for index, deck in enumerate(streamdecks):
            # This example only works with devices that have screens.
            if not deck.is_visual():
                continue

            try:
                deck.open()
            except TransportError:
                time.sleep(random.random() * 5)
                try:
                    deck.open()
                except TransportError:
                    print("ok")
            deck.reset()

            print(
                "Opened '{}' device (serial number: '{}', fw: '{}')".format(
                    deck.deck_type(),
                    deck.get_serial_number(),
                    deck.get_firmware_version(),
                )
            )

            # Set initial screen brightness to 30%.
            deck.set_brightness(self.streamdeck_brightness)

            # Setup image
            # TODO move this information into scenario

            # image for idle state
            x_default_item_size = int(deck.KEY_PIXEL_WIDTH * .6666)
            y_default_item_size = int(deck.KEY_PIXEL_HEIGHT * .6666)
            x_default_item_smaller_size = int(deck.KEY_PIXEL_WIDTH * .16666)
            y_default_item_smaller_size = int(deck.KEY_PIXEL_HEIGHT * .16666)
            img = Image.new("RGB", (deck.KEY_PIXEL_WIDTH, deck.KEY_PIXEL_HEIGHT), color="black")
            self.released_icon = Image.open(
                os.path.join(ASSETS_PATH, "Released.png")
            ).resize((x_default_item_size, y_default_item_size))
            img.paste(self.released_icon, (x_default_item_smaller_size, y_default_item_smaller_size),
                      self.released_icon)

            # img_byte_arr = io.BytesIO()
            # img.save(img_byte_arr, format='JPEG')
            # img_released_bytes = img_byte_arr.getvalue()

            # image for pressed state
            img = Image.new("RGB", (deck.KEY_PIXEL_WIDTH, deck.KEY_PIXEL_HEIGHT), color="black")
            self.pressed_icon = Image.open(
                os.path.join(ASSETS_PATH, "Pressed.png")
            ).resize((x_default_item_size, y_default_item_size))
            self.pressed_moved_icon = Image.open(
                os.path.join(ASSETS_PATH, "PressedMoved.png")
            ).resize((x_default_item_size, y_default_item_size))
            img.paste(self.pressed_icon, (x_default_item_smaller_size, y_default_item_smaller_size), self.pressed_icon)

            # Setup dial controller like Stream Deck +
            if deck.DIAL_COUNT > 0:
                deck.set_dial_callback(self.dial_change_callback)

            # Setup dial controller like Stream Deck +
            if deck.DECK_TOUCH:
                deck.set_touchscreen_callback(self.touchscreen_event_callback)

            print("Loading animations...")
            animations = [
                self.create_animation_frames(deck, "Setting.gif"),
                self.create_animation_frames(deck, "light-bulb-joypixels.gif"),
            ]
            print("Ready.")

            if not is_big_image:
                # Set initial key images.
                key_images = dict()
                for key in range(deck.key_count()):
                    key_images[key] = itertools.cycle(
                        animations[key % len(animations)]
                    )
                    # if key == deck.key_count() - 2:
                    #     self.update_key_image(deck, key, False, animated_image=animations[0])
                    # else:
                    #     self.update_key_image(deck, key, False)
                    self.update_key_image(deck, key, False)
            else:
                # Load and resize a source image so that it will fill the given
                # StreamDeck.
                image = self.create_full_deck_sized_image(
                    deck, KEY_SPACING, "Harold.jpg"
                )

                print(
                    "Created full deck image size of {}x{} pixels.".format(
                        image.width, image.height
                    )
                )

                # Extract out the section of the image that is occupied by each key.
                key_images = dict()
                for k in range(deck.key_count()):
                    key_images[k] = self.crop_key_image_from_deck_sized_image(
                        deck, image, KEY_SPACING, k
                    )
                # Draw the individual key images to each of the keys.
                for k in range(deck.key_count()):
                    key_image = key_images[k]

                    # Show the section of the main image onto the key.
                    deck.set_key_image(k, key_image)

            # Kick off the key image animating thread.

            threading.Thread(
                target=self.animate(
                    deck, key_images, is_big_image=is_big_image
                ),
                args=[FRAMES_PER_SECOND],
            ).start()

            # Register callback function for when a key state changes.
            deck.set_key_callback(self.key_change_callback)

    def run(self):
        # Wait until all application threads have terminated (for this example,
        # this is when all deck handles are closed).
        for t in threading.enumerate():
            try:
                t.join()
            except (TransportError, RuntimeError):
                pass

    def init_and_run(self):
        self.init()

        import pyudev

        context = pyudev.Context()

        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem="usb")

        def device_event(action, device):
            # TODO support by number and not by ID_MODEL
            if action == "add":
                id_model = device.get("ID_MODEL")
                print(f"USB device connected: {id_model}")
                # 'Stream Deck +'
                if id_model in [
                    "Stream_Deck_XL",
                    "Stream_Deck_MK.2",
                    "Stream_Deck_Plus",
                ]:
                    sdc = StreamDeckController()
                    # TODO Le init est le bogue au redémarrage sur le hub
                    sdc.init()

        # Observer pour les événements de manière non bloquante
        observer = pyudev.MonitorObserver(monitor, device_event)
        observer.start()

        # Garder le programme en cours d'exécution
        # try:
        #     while True:
        #         pass
        # except KeyboardInterrupt:
        #     observer.stop()
        self.run()
        # TODO move into except of try
        observer.stop()

    def dial_change_callback(
        self,
        deck,
        dial,
        event,
        value,
        move_dist_x=0,
        is_touch=True,
        is_direction_left=False,
    ):
        if event == DialEventType.PUSH:
            print(f"dial pushed: {dial} state: {value}")
            self.set_touchscreen_generate_image(
                deck,
                dial,
                value,
                move_dist_x=move_dist_x,
                is_touch=is_touch,
                is_direction_left=is_direction_left,
            )

        elif event == DialEventType.TURN:
            print(f"dial {dial} turned: {value}")
            self.dial_change_callback(
                deck,
                dial,
                DialEventType.PUSH,
                False,
                move_dist_x=value,
                is_touch=False,
                is_direction_left=value < 0,
            )

    def touchscreen_refresh_image(self, deck):
        # self.last_value
        # self.last_is_move_dist_x
        self.set_touchscreen_generate_image(
            deck,
            self.last_dial,
            0,
            move_dist_x=0,
            is_touch=self.last_is_touch,
            is_direction_left=self.last_is_direction_left,
        )

    def set_touchscreen_generate_image(
        self,
        deck,
        dial,
        value,
        move_dist_x=0,
        is_touch=True,
        is_direction_left=False,
    ):
        # if dial == 3 and value:
        #     deck.reset()
        #     deck.close()
        # else:
        # build an image for the touch lcd
        # TODO move this information somewhere
        x_default_item_size = int(deck.KEY_PIXEL_WIDTH * .6666)
        y_default_item_size = int(deck.KEY_PIXEL_HEIGHT * .6666)
        x_font_size = int(x_default_item_size / 2)
        x_font_debug_size = int(x_default_item_size / 4)

        # w_screen = 800
        w_screen = deck.SCREEN_PIXEL_WIDTH or deck.TOUCHSCREEN_PIXEL_WIDTH
        middle_w_screen = w_screen / 2
        # h_screen = 100
        # h_max_draw = 110
        # w_max_draw = 220
        h_screen = deck.SCREEN_PIXEL_HEIGHT or deck.TOUCHSCREEN_PIXEL_HEIGHT
        h_max_draw = h_screen + 10
        w_max_draw = int(w_screen / 4 + w_screen / x_font_size)
        h_padding_draw = 10
        w_padding_draw = 30
        speed_increase = 5
        x_move_speed_increase = (
                                    move_dist_x * speed_increase if not is_touch else move_dist_x
                                ) or 0
        dial = dial or 0
        lst_collision_position = []
        # self.lst_smyles[dial]["x"] += (
        #     move_dist_x * speed_increase
        #     if not is_touch
        #     else move_dist_x
        # )

        img = Image.new("RGB", (w_screen, h_screen), "black")
        draw = ImageDraw.Draw(img)
        # icon = Image.open(os.path.join(ASSETS_PATH, 'Exit.png')).resize((80, 80))
        # img.paste(icon, (690, 10), icon)

        if default_police:
            try:
                font = ImageFont.truetype(
                    default_police, x_font_size
                )  # Remplacez "arial.ttf" par le chemin de votre police
                font_debug = ImageFont.truetype(
                    default_police, x_font_debug_size
                )  # Remplacez "arial.ttf" par le chemin de votre police
            except IOError:
                print(
                    "Impossible de charger la police arial.ttf. Utilisation de la police par défaut."
                )
                font = ImageFont.load_default(x_font_size)
                font_debug = ImageFont.load_default(x_font_debug_size)
        else:
            font = ImageFont.load_default(x_font_size)
            font_debug = ImageFont.load_default(x_font_debug_size)
        # Only 1
        if is_feature == "uniselection":
            for k in range(0, deck.DIAL_COUNT - 1):
                move_dist_index_x = 0
                if dial == k:
                    move_dist_index_x = move_dist_x
                    print(f"Dist {move_dist_index_x} moved index {dial}")
                    if value:
                        icon_reaction = self.pressed_icon
                    else:
                        icon_reaction = self.released_icon
                else:
                    icon_reaction = self.released_icon
                img.paste(
                    icon_reaction,
                    (
                        w_padding_draw + (k * w_max_draw) + move_dist_index_x,
                        h_padding_draw,
                    ),
                    icon_reaction,
                )
        elif is_feature == "dynamic_smyles":
            self.lst_smyles[dial]["x"] += x_move_speed_increase
            lst_x_size = [
                (a.get("x") - h_max_draw, a.get("x") + h_max_draw)
                for a in self.lst_smyles
            ]
            if move_dist_x == 0:
                self.lst_smyles[dial]["x"] = dial * w_max_draw
            lst_mapping = []
            for k, dct_smyles in enumerate(self.lst_smyles):
                if move_dist_x >= 0:
                    icon_reaction = self.pressed_moved_icon
                else:
                    icon_reaction = self.pressed_moved_icon.transpose(
                        Image.FLIP_LEFT_RIGHT
                    )

                x = dct_smyles.get("x")
                for check_min_x, check_max_x in (
                    lst_x_size[0:dial] + lst_x_size[dial:]
                ):
                    if check_min_x < x < check_max_x and dial != k:
                        icon_reaction = self.released_icon
                # img.paste(icon_reaction, (30 + (k * 220) + move_dist_index_x, 10), icon_reaction)
                new_x = w_padding_draw + x
                new_y = h_padding_draw
                feature_resize = "linear_from_start"
                if feature_resize == "linear_from_start":
                    new_size_h = max(
                        w_padding_draw,
                        int(((new_x / 2) / middle_w_screen) * h_screen),
                    )
                    original_icon_copy = icon_reaction.copy()
                    icon_reaction_resize = original_icon_copy.resize(
                        (new_size_h, new_size_h)
                    )
                else:
                    icon_reaction_resize = icon_reaction
                    new_size_h = y_default_item_size
                lst_mapping.append(
                    {
                        "x": new_x,
                        "y": new_y,
                        "icon": icon_reaction_resize,
                        "position_item": k,
                        "w": new_size_h,
                        "h": new_size_h,
                    }
                )

            is_feature_push_collision = True

            def update_collision(
                dct_mapping_other_item_inner,
                k_index,
                dial_inner,
                check_x_min,
                check_x_max,
                is_direction_left,
            ):
                # k_index static item
                # dial_inner moving item
                diff_x_inner = 0
                x_other_item = dct_mapping_other_item_inner["x"]
                w_other_item = dct_mapping_other_item_inner["w"]
                y_other_item = dct_mapping_other_item_inner["y"]
                # x_min_check = int(x_other_item)
                # x_max_check = int(x_other_item + w_max_draw / 2)
                x_min_check = x_other_item
                x_max_check = x_other_item + w_other_item
                check_x_max_2 = check_x_max - w_other_item
                # if check_x_max > x_min_check and check_x_min < x_max_check:
                #     print(f"detect collision {k_index} with {dial_inner}")
                #
                # elif x_min_check < check_x_min < x_max_check:
                if (
                    x_min_check < check_x_min < x_max_check
                    and is_direction_left
                    or x_min_check < check_x_min < x_max_check
                    and not is_direction_left
                ):
                    # if check_x_min < x_max_check < check_x_max_2:
                    #     west_switch = True
                    # else:
                    #     west_switch = False
                    print(f"detect collision {k_index} with {dial_inner}")
                    if x_min_check < check_x_min:
                        # diff_x_inner = x_other_item + check_x + w_max_draw
                        diff_x_inner = x_other_item - (
                            x_max_check - check_x_min
                        )
                        diff_x_inner = check_x_min - x_max_check
                    else:
                        diff_x_inner = x_other_item - (
                            x_max_check - check_x_min
                        )
                        # diff_x_inner = x_other_item - check_x + w_max_draw
                return diff_x_inner

            if is_feature_push_collision:
                for k, dct_smyles in enumerate(self.lst_smyles):
                    dct_mapping = lst_mapping[k]
                    # Collision
                    check_x = dct_mapping.get("x")
                    check_y = dct_mapping.get("y")

                for dct_mapping_other_item in lst_mapping:
                    position_other_item = dct_mapping_other_item[
                        "position_item"
                    ]
                    if position_other_item != dial:
                        diff_x = update_collision(
                            dct_mapping_other_item,
                            dct_mapping_other_item.get("position_item"),
                            dial,
                            check_x,
                            check_x + dct_mapping.get("w"),
                            is_direction_left,
                        )
                        if abs(diff_x) > 0:
                            dct_mapping_other_item["x"] += diff_x
                            # print(f"colision detected {position_other_item}")
                            lst_collision_position.append(position_other_item)
                # for dct_mapping_other_item in lst_mapping[:dial]:
                #     update_collision(dct_mapping_other_item, k, dial)
                # for dct_mapping_other_item in lst_mapping[dial + 1:]:
                #     update_collision(dct_mapping_other_item, k, dial)

                # print("Check collision")

            for k, dct_smyles in enumerate(self.lst_smyles):
                dct_mapping = lst_mapping[k]
                icon = dct_mapping.get("icon")
                x = dct_mapping.get("x")
                y = dct_mapping.get("y")
                w = dct_mapping.get("w")
                h = dct_mapping.get("h")
                # Draw
                img.paste(
                    icon,
                    (x, y),
                    icon,
                )

                number_to_draw = str(k)
                text_color = (255, 255, 255)
                text_x = x
                text_y = x_font_size
                draw.text(
                    (text_x, text_y),
                    number_to_draw,
                    fill=text_color,
                    font=font,
                )

                if self.is_debug:
                    x_str = str(x)
                    extra_x = 0
                    if len(x_str) >= 3:
                        extra_x = 10
                    # TODO move this into method
                    # new_size_h = max(
                    #     w_padding_draw,
                    #     int(((x / 2) / middle_w_screen) * h_screen),
                    # )
                    if x < x_font_size:
                        text_x = x + w + extra_x
                    else:
                        text_x = x - x_font_size - extra_x
                    if k in lst_collision_position:
                        text_color = (255, 0, 0)
                    else:
                        text_color = (0, 255, 0)

                    number_to_draw = f"x{x}"
                    text_y = h_padding_draw + x_font_debug_size * 0
                    draw.text(
                        (text_x, text_y),
                        number_to_draw,
                        fill=text_color,
                        font=font_debug,
                    )

                    number_to_draw = f"y{y}"
                    text_y = h_padding_draw + x_font_debug_size * 1
                    draw.text(
                        (text_x, text_y),
                        number_to_draw,
                        fill=text_color,
                        font=font_debug,
                    )

                    number_to_draw = f"w{w}"
                    text_y = h_padding_draw + x_font_debug_size * 2
                    draw.text(
                        (text_x, text_y),
                        number_to_draw,
                        fill=text_color,
                        font=font_debug,
                    )

                    number_to_draw = f"h{h}"
                    text_y = h_padding_draw + x_font_debug_size * 3
                    draw.text(
                        (text_x, text_y),
                        number_to_draw,
                        fill=text_color,
                        font=font_debug,
                    )

        if deck.KEY_FLIP == (True, True):
            img = img.transpose(Image.Transpose.ROTATE_180)
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="JPEG")
        img_byte_arr = img_byte_arr.getvalue()
        self.last_generated_img_byte_arr = img_byte_arr
        self.last_dial = dial
        self.last_value = value
        self.last_is_move_dist_x = move_dist_x
        self.last_is_touch = is_touch
        self.last_is_direction_left = is_direction_left
        if deck.DECK_TOUCH:
            deck.set_touchscreen_image(img_byte_arr, 0, 0, w_screen, h_screen)
        else:
            deck.set_screen_image(img_byte_arr)

    def touchscreen_event_callback(self, deck, evt_type, value):
        dial_index = int(value["x"] / 200)
        if evt_type == TouchscreenEventType.SHORT:
            print("Short touch @ " + str(value["x"]) + "," + str(value["y"]))
            self.dial_change_callback(
                deck, dial_index, DialEventType.PUSH, True
            )

        elif evt_type == TouchscreenEventType.LONG:
            print("Long touch @ " + str(value["x"]) + "," + str(value["y"]))
            self.dial_change_callback(
                deck, dial_index, DialEventType.PUSH, False
            )

        elif evt_type == TouchscreenEventType.DRAG:
            print(
                "Drag started @ "
                + str(value["x"])
                + ","
                + str(value["y"])
                + " ended @ "
                + str(value["x_out"])
                + ","
                + str(value["y_out"])
            )
            move_x = value["x_out"] - value["x"]
            self.dial_change_callback(
                deck, dial_index, DialEventType.PUSH, False, move_dist_x=move_x
            )

    # Generates an image that is correctly sized to fit across all keys of a given
    # StreamDeck.
    def create_full_deck_sized_image(self, deck, key_spacing, image_filename):
        key_rows, key_cols = deck.key_layout()
        key_width, key_height = deck.key_image_format()["size"]
        spacing_x, spacing_y = key_spacing

        # Compute total size of the full StreamDeck image, based on the number of
        # buttons along each axis. This doesn't take into account the spaces between
        # the buttons that are hidden by the bezel.
        key_width *= key_cols
        key_height *= key_rows

        # Compute the total number of extra non-visible pixels that are obscured by
        # the bezel of the StreamDeck.
        spacing_x *= key_cols - 1
        spacing_y *= key_rows - 1

        # Compute final full deck image size, based on the number of buttons and
        # obscured pixels.
        full_deck_image_size = (key_width + spacing_x, key_height + spacing_y)

        # Resize the image to suit the StreamDeck's full image size. We use the
        # helper function in Pillow's ImageOps module so that the image's aspect
        # ratio is preserved.
        image = Image.open(os.path.join(ASSETS_PATH, image_filename)).convert(
            "RGBA"
        )
        image = ImageOps.fit(image, full_deck_image_size, Image.LANCZOS)
        return image

    # Crops out a key-sized image from a larger deck-sized image, at the location
    # occupied by the given key index.
    def crop_key_image_from_deck_sized_image(
        self, deck, image, key_spacing, key
    ):
        key_rows, key_cols = deck.key_layout()
        key_width, key_height = deck.key_image_format()["size"]
        spacing_x, spacing_y = key_spacing

        # Determine which row and column the requested key is located on.
        row = key // key_cols
        col = key % key_cols

        # Compute the starting X and Y offsets into the full size image that the
        # requested key should display.
        start_x = col * (key_width + spacing_x)
        start_y = row * (key_height + spacing_y)

        # Compute the region of the larger deck image that is occupied by the given
        # key, and crop out that segment of the full image.
        region = (start_x, start_y, start_x + key_width, start_y + key_height)
        segment = image.crop(region)

        # Create a new key-sized image, and paste in the cropped section of the
        # larger image.
        key_image = PILHelper.create_key_image(deck)
        key_image.paste(segment)

        return PILHelper.to_native_key_format(deck, key_image)

    def create_animation_frames(self, deck, image_filename):
        icon_frames = list()

        # Open the source image asset.
        icon = Image.open(os.path.join(ASSETS_PATH, image_filename))

        # Iterate through each animation frame of the source image
        for frame in ImageSequence.Iterator(icon):
            # Create new key image of the correct dimensions, black background.
            frame_image = PILHelper.create_scaled_key_image(deck, frame)

            # Pre-convert the generated image to the native format of the StreamDeck
            # so we don't need to keep converting it when showing it on the device.
            native_frame_image = PILHelper.to_native_key_format(
                deck, frame_image
            )

            # Store the rendered animation frame for later user.
            icon_frames.append(native_frame_image)

        # Return the decoded list of frames - the caller will need to decide how to
        # sequence them for display.
        return icon_frames

    # Generates a custom tile with run-time generated text and custom image via the
    # PIL module.
    def render_key_image(self, deck, icon_filename, font_filename, label_text):
        # Resize the source image asset to best-fit the dimensions of a single key,
        # leaving a margin at the bottom so that we can draw the key title
        # afterwards.
        icon = Image.open(icon_filename)
        image = PILHelper.create_scaled_key_image(
            deck, icon, margins=[0, 0, 20, 0]
        )

        # Load a custom TrueType font and use it to overlay the key index, draw key
        # label onto the image a few pixels from the bottom of the key.
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(font_filename, 14)
        draw.text(
            (image.width / 2, image.height - 5),
            text=label_text,
            font=font,
            anchor="ms",
            fill="white",
        )

        return PILHelper.to_native_key_format(deck, image)

    # Returns styling information for a key based on its position and state.
    def get_key_style(self, deck, key, state):
        # Last button in the example application is the exit button.
        exit_key_index = deck.key_count() - 1

        if key == exit_key_index:
            name = "exit"
            icon = "{}.png".format("Exit")
            font = "Roboto-Regular.ttf"
            label = "Bye" if state else "Exit"
        else:
            name = "emoji"
            icon = "{}.png".format("Pressed" if state else "Released")
            font = "Roboto-Regular.ttf"
            label = "Pressed!" if state else "Key {}".format(key)

        return {
            "name": name,
            "icon": os.path.join(ASSETS_PATH, icon),
            "font": os.path.join(ASSETS_PATH, font),
            "label": label,
        }

    # Creates a new key image based on the key index, style and current key state
    # and updates the image on the StreamDeck.
    def update_key_image(self, deck, key, state):
        # Determine what icon and label to use on the generated key.
        key_style = self.get_key_style(deck, key, state)

        # Generate the custom key with the requested image and label.
        icon = key_style["icon"]
        image = self.render_key_image(
            deck, icon, key_style["font"], key_style["label"]
        )

        # Use a scoped-with on the deck to ensure we're the only thread using it
        # right now.
        with deck:
            # Update requested key with the generated image.
            deck.set_key_image(key, image)

    def key_change_callback(self, deck, key, state):
        print("Deck {} Key {} = {}".format(deck.id(), key, state), flush=True)
        if key >= deck.key_count():
            return
        self.update_key_image(deck, key, state)
        if state:
            key_style = self.get_key_style(deck, key, state)

            if key == 1:
                self.streamdeck_brightness += 10
                if self.streamdeck_brightness > 100:
                    self.streamdeck_brightness = 100
                deck.set_brightness(self.streamdeck_brightness)
            elif key == 2:
                self.streamdeck_brightness -= 10
                if self.streamdeck_brightness < 5:
                    self.streamdeck_brightness = 5
                deck.set_brightness(self.streamdeck_brightness)
            elif key == 3:
                subprocess.run(
                    "gnome-terminal -- bash -c 'sudo ./.venv/bin/python ./script/stream_deck/keyboard_talk.py;bash'",
                    shell=True,
                    executable="/bin/bash",
                )
            elif key == 4:
                deck.reset()
            elif key == 5:
                # Debug enable
                self.is_debug = not self.is_debug
                # Force refresh
                self.touchscreen_refresh_image(deck)
            elif key == 0:
                subprocess.run(
                    "gnome-terminal -- bash -c './script/todo/source_todo.sh'",
                    shell=True,
                    executable="/bin/bash",
                )
            if key_style["name"] == "exit":
                # with deck:
                #     deck.reset()
                #     deck.close()
                # Don't exit...
                self.print_deck_info(deck)

    def print_deck_info(self, deck):
        key_image_format = deck.key_image_format()
        touchscreen_image_format = deck.touchscreen_image_format()

        flip_description = {
            (False, False): "not mirrored",
            (True, False): "mirrored horizontally",
            (False, True): "mirrored vertically",
            (True, True): "mirrored horizontally/vertically",
        }

        print("Deck {}.".format(deck.deck_type()))
        print("\t - ID: {}".format(deck.id()))
        print("\t - Serial: '{}'".format(deck.get_serial_number()))
        print(
            "\t - Firmware Version: '{}'".format(deck.get_firmware_version())
        )
        print(
            "\t - Key Count: {} (in a {}x{} grid)".format(
                deck.key_count(), deck.key_layout()[0], deck.key_layout()[1]
            )
        )
        if deck.is_visual():
            print(
                "\t - Key Images: {}x{} pixels, {} format, rotated {} degrees, {}".format(
                    key_image_format["size"][0],
                    key_image_format["size"][1],
                    key_image_format["format"],
                    key_image_format["rotation"],
                    flip_description[key_image_format["flip"]],
                )
            )

            if deck.is_touch():
                print(
                    "\t - Touchscreen: {}x{} pixels, {} format, rotated {} degrees, {}".format(
                        touchscreen_image_format["size"][0],
                        touchscreen_image_format["size"][1],
                        touchscreen_image_format["format"],
                        touchscreen_image_format["rotation"],
                        flip_description[touchscreen_image_format["flip"]],
                    )
                )
        else:
            print("\t - No Visual Output")

    def animate(self, deck, key_images, is_big_image=False):
        def inter_animate(fps):
            frame_time = Fraction(1, fps)
            next_frame = Fraction(time.monotonic())
            has_overrun = False
            while deck.is_open():
                try:
                    with deck:
                        for key, frames in key_images.items():
                            if has_overrun:
                                next(frames)
                            elif not is_big_image and (
                                key == deck.key_count() - 2
                                or is_all_animation_test
                            ):
                                # TODO more configuration for animation case
                                deck.set_key_image(key, next(frames))

                            # else:
                            #     self.update_key_image(deck, key, False)
                    has_overrun = False
                except TransportError as err:
                    print("TransportError: {0}".format(err))
                    break
                next_frame += frame_time
                sleep_interval = float(next_frame) - time.monotonic()
                if sleep_interval >= 0:
                    time.sleep(sleep_interval)
                else:
                    has_overrun = False
                    print("Overrun")

        return inter_animate


if __name__ == "__main__":
    sdc = StreamDeckController()
    sdc.init_and_run()
