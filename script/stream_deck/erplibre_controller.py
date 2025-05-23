#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import threading
import time
import subprocess
import itertools

from fractions import Fraction
from PIL import Image, ImageDraw, ImageFont, ImageSequence
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import StreamDeck
from StreamDeck.ImageHelpers import PILHelper
from StreamDeck.Transport.Transport import TransportError

ASSETS_PATH = os.path.join(os.path.dirname(__file__), "Assets")
DEFAULT_BRIGHTNESS = 30
FRAMES_PER_SECOND = 30
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

            print("Loading animations...")
            animations = [
                self.create_animation_frames(deck, "Setting.gif"),
                self.create_animation_frames(deck, "light-bulb-joypixels.gif"),
            ]
            print("Ready.")

            # Set initial key images.
            key_images = dict()
            for key in range(deck.key_count()):
                key_images[key] = itertools.cycle(animations[key % len(animations)])
                # if key == deck.key_count() - 2:
                #     self.update_key_image(deck, key, False, animated_image=animations[0])
                # else:
                #     self.update_key_image(deck, key, False)
                self.update_key_image(deck, key, False)

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

    # Prints key state change information, updates rhe key image and performs any
    # associated actions when a key is pressed.
    def key_change_callback(self, deck, key, state):
        # Print new key state
        print("Deck {} Key {} = {}".format(deck.id(), key, state), flush=True)

        # Don't try to draw an image on a touch button
        if key >= deck.key_count():
            return

        # Update the key image based on the new key state.
        self.update_key_image(deck, key, state)

        # Check if the key is changing to the pressed state.
        if state:
            key_style = self.get_key_style(deck, key, state)

            if key == 24:
                self.streamdeck_brightness += 10
                if self.streamdeck_brightness > 100:
                    self.streamdeck_brightness = 100
                deck.set_brightness(self.streamdeck_brightness)
            elif key == 25:
                self.streamdeck_brightness -= 10
                if self.streamdeck_brightness < 5:
                    self.streamdeck_brightness = 5
                deck.set_brightness(self.streamdeck_brightness)
            elif key == 0:
                subprocess.run(
                    "gnome-terminal -- bash -c './script/todo/source_todo.sh'",
                    shell=True,
                    executable="/bin/bash",
                )

            # When an exit button is pressed, close the application.
            if key_style["name"] == "exit":
                # Use a scoped-with on the deck to ensure we're the only thread
                # using it right now.
                with deck:
                    # Reset deck, clearing all button images.
                    deck.reset()

                    # Close deck handle, terminating internal worker threads.
                    deck.close()

    # Helper function that will run a periodic loop which updates the
    # images on each key.
    def animate(self, deck, key_images):
        def inter_animate(fps):
            # Convert frames per second to frame time in seconds.
            #
            # Frame time often cannot be fully expressed by a float type,
            # meaning that we have to use fractions.
            frame_time = Fraction(1, fps)

            # Get a starting absolute time reference point.
            #
            # We need to use an absolute time clock, instead of relative sleeps
            # with a constant value, to avoid drifting.
            #
            # Drifting comes from an overhead of scheduling the sleep itself -
            # it takes some small amount of time for `time.sleep()` to execute.
            next_frame = Fraction(time.monotonic())

            # Periodic loop that will render every frame at the set FPS until
            # the StreamDeck device we're using is closed.
            while deck.is_open():
                try:
                    # Use a scoped-with on the deck to ensure we're the only
                    # thread using it right now.
                    with deck:
                        # Update the key images with the next animation frame.
                        for key, frames in key_images.items():
                            if key == deck.key_count() - 2:
                                deck.set_key_image(key, next(frames))
                            # else:
                            #     self.update_key_image(deck, key, False)
                except TransportError as err:
                    print("TransportError: {0}".format(err))
                    # Something went wrong while communicating with the device
                    # (closed?) - don't re-schedule the next animation frame.
                    break

                # Set the next frame absolute time reference point.
                #
                # We are running at the fixed `fps`, so this is as simple as
                # adding the frame time we calculated earlier.
                next_frame += frame_time

                # Knowing the start of the next frame, we can calculate how long
                # we have to sleep until its start.
                sleep_interval = float(next_frame) - time.monotonic()

                # Schedule the next periodic frame update.
                #
                # `sleep_interval` can be a negative number when current FPS
                # setting is too high for the combination of host and
                # StreamDeck to handle. If this is the case, we skip sleeping
                # immediately render the next frame to try to catch up.
                if sleep_interval >= 0:
                    time.sleep(sleep_interval)

        return inter_animate


if __name__ == "__main__":
    sdc = StreamDeckController()
    sdc.init_and_run()
