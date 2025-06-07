#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import threading
import time
import io
import subprocess
import itertools
import random
# import keyboard

from fractions import Fraction
from PIL import Image, ImageDraw, ImageFont, ImageSequence, ImageOps
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from StreamDeck.Transport.Transport import TransportError
from StreamDeck.Devices.StreamDeck import DialEventType, TouchscreenEventType

ASSETS_PATH = os.path.join(os.path.dirname(__file__), "Assets")
DEFAULT_BRIGHTNESS = 30
FRAMES_PER_SECOND = 100
KEY_SPACING = (36, 36)


class StreamDeckController(object):
    def init(self):
        self.streamdeck_brightness = DEFAULT_BRIGHTNESS
        streamdecks = DeviceManager().enumerate()

        print("Found {} Stream Deck(s).\n".format(len(streamdecks)))

        for index, deck in enumerate(streamdecks):
            # This example only works with devices that have screens.
            if not deck.is_visual():
                continue

            deck.open()
            deck.reset()

            print("Opened '{}' device (serial number: '{}', fw: '{}')".format(
                deck.deck_type(), deck.get_serial_number(), deck.get_firmware_version()
            ))

            # Set initial screen brightness to 30%.
            deck.set_brightness(self.streamdeck_brightness)

            # Setup image

            # image for idle state
            img = Image.new('RGB', (120, 120), color='black')
            self.released_icon = Image.open(os.path.join(ASSETS_PATH, 'Released.png')).resize((80, 80))
            img.paste(self.released_icon, (20, 20), self.released_icon)

            # img_byte_arr = io.BytesIO()
            # img.save(img_byte_arr, format='JPEG')
            # img_released_bytes = img_byte_arr.getvalue()

            # image for pressed state
            img = Image.new('RGB', (120, 120), color='black')
            self.pressed_icon = Image.open(os.path.join(ASSETS_PATH, 'Pressed.png')).resize((80, 80))
            img.paste(self.pressed_icon, (20, 20), self.pressed_icon)

            # Setup Stream Deck +
            if deck.DECK_TYPE == 'Stream Deck +':
                deck.set_dial_callback(self.dial_change_callback)
                deck.set_touchscreen_callback(self.touchscreen_event_callback)

            print("Loading animations...")
            animations = [
                self.create_animation_frames(deck, "Setting.gif"),
                self.create_animation_frames(deck, "light-bulb-joypixels.gif"),
            ]
            print("Ready.")

            is_big_image = True
            if not is_big_image:
                # Set initial key images.
                key_images = dict()
                for key in range(deck.key_count()):
                    key_images[key] = itertools.cycle(animations[key % len(animations)])
                    # if key == deck.key_count() - 2:
                    #     self.update_key_image(deck, key, False, animated_image=animations[0])
                    # else:
                    #     self.update_key_image(deck, key, False)
                    self.update_key_image(deck, key, False)
            else:
                # Load and resize a source image so that it will fill the given
                # StreamDeck.
                image = self.create_full_deck_sized_image(deck, KEY_SPACING, "Harold.jpg")

                print("Created full deck image size of {}x{} pixels.".format(image.width, image.height))

                # Extract out the section of the image that is occupied by each key.
                key_images = dict()
                for k in range(deck.key_count()):
                    key_images[k] = self.crop_key_image_from_deck_sized_image(deck, image, KEY_SPACING, k)
                # Draw the individual key images to each of the keys.
                for k in range(deck.key_count()):
                    key_image = key_images[k]

                    # Show the section of the main image onto the key.
                    deck.set_key_image(k, key_image)

            # Kick off the key image animating thread.

            threading.Thread(target=self.animate(deck, key_images), args=[FRAMES_PER_SECOND]).start()

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
        monitor.filter_by(subsystem='usb')

        def device_event(action, device):
            # TODO support by number and not by ID_MODEL
            if action == 'add':
                id_model = device.get('ID_MODEL')
                print(f"USB device connected: {id_model}")
                # 'Stream Deck +'
                if id_model in ["Stream_Deck_XL", 'Stream_Deck_MK.2', 'Stream_Deck_Plus']:
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

    def dial_change_callback(self, deck, dial, event, value):
        if event == DialEventType.PUSH:
            print(f"dial pushed: {dial} state: {value}")
            if dial == 3 and value:
                deck.reset()
                deck.close()
            else:
                # build an image for the touch lcd
                img = Image.new('RGB', (800, 100), 'black')
                icon = Image.open(os.path.join(ASSETS_PATH, 'Exit.png')).resize((80, 80))
                img.paste(icon, (690, 10), icon)

                for k in range(0, deck.DIAL_COUNT - 1):
                    img.paste(self.pressed_icon if (dial == k and value) else self.released_icon, (30 + (k * 220), 10),
                              self.pressed_icon if (dial == k and value) else self.released_icon)

                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG')
                img_byte_arr = img_byte_arr.getvalue()

                deck.set_touchscreen_image(img_byte_arr, 0, 0, 800, 100)
        elif event == DialEventType.TURN:
            print(f"dial {dial} turned: {value}")

    def touchscreen_event_callback(self, deck, evt_type, value):
        if evt_type == TouchscreenEventType.SHORT:
            print("Short touch @ " + str(value['x']) + "," + str(value['y']))

        elif evt_type == TouchscreenEventType.LONG:

            print("Long touch @ " + str(value['x']) + "," + str(value['y']))

        elif evt_type == TouchscreenEventType.DRAG:

            print("Drag started @ " + str(value['x']) + "," + str(value['y']) + " ended @ " + str(
                value['x_out']) + "," + str(value['y_out']))

    # Generates an image that is correctly sized to fit across all keys of a given
    # StreamDeck.
    def create_full_deck_sized_image(self, deck, key_spacing, image_filename):
        key_rows, key_cols = deck.key_layout()
        key_width, key_height = deck.key_image_format()['size']
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
        image = Image.open(os.path.join(ASSETS_PATH, image_filename)).convert("RGBA")
        image = ImageOps.fit(image, full_deck_image_size, Image.LANCZOS)
        return image

    # Crops out a key-sized image from a larger deck-sized image, at the location
    # occupied by the given key index.
    def crop_key_image_from_deck_sized_image(self, deck, image, key_spacing, key):
        key_rows, key_cols = deck.key_layout()
        key_width, key_height = deck.key_image_format()['size']
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
            native_frame_image = PILHelper.to_native_key_format(deck, frame_image)

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
        image = PILHelper.create_scaled_key_image(deck, icon, margins=[0, 0, 20, 0])

        # Load a custom TrueType font and use it to overlay the key index, draw key
        # label onto the image a few pixels from the bottom of the key.
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(font_filename, 14)
        draw.text((image.width / 2, image.height - 5), text=label_text, font=font, anchor="ms", fill="white")

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
            "label": label
        }

    # Creates a new key image based on the key index, style and current key state
    # and updates the image on the StreamDeck.
    def update_key_image(self, deck, key, state):
        # Determine what icon and label to use on the generated key.
        key_style = self.get_key_style(deck, key, state)

        # Generate the custom key with the requested image and label.
        icon = key_style["icon"]
        image = self.render_key_image(deck, icon, key_style["font"], key_style["label"])

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
        print("\t - Firmware Version: '{}'".format(deck.get_firmware_version()))
        print("\t - Key Count: {} (in a {}x{} grid)".format(
            deck.key_count(),
            deck.key_layout()[0],
            deck.key_layout()[1]))
        if deck.is_visual():
            print("\t - Key Images: {}x{} pixels, {} format, rotated {} degrees, {}".format(
                key_image_format['size'][0],
                key_image_format['size'][1],
                key_image_format['format'],
                key_image_format['rotation'],
                flip_description[key_image_format['flip']]))

            if deck.is_touch():
                print("\t - Touchscreen: {}x{} pixels, {} format, rotated {} degrees, {}".format(
                    touchscreen_image_format['size'][0],
                    touchscreen_image_format['size'][1],
                    touchscreen_image_format['format'],
                    touchscreen_image_format['rotation'],
                    flip_description[touchscreen_image_format['flip']]))
        else:
            print("\t - No Visual Output")

    def animate(self, deck, key_images):
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
                            elif key > deck.key_count():
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
