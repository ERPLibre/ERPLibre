"""Video recorder for Selenium WebDriver."""

import threading

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)


class VideoRecorder(object):
    """Record video of a Selenium test run in WebM format through repeated
    screenshot captures.

    :type driver: selenium.webdriver.Remote
    :param filename: Path of the video file to create, or `None` to view live
                     video output.
    :param framerate: Rate of screenshot capture as fraction [fps].
    :param width: Crop screenshots to this width [pixels].
    :param height: Crop screenshots to this height [pixels].
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        driver,
        filename="video.webm",
        framerate="33/1",
        width=None,
        height=None,
    ):
        self.driver = driver
        _patch_driver(self.driver)

        if filename and not filename.endswith(".webm"):
            filename += ".webm"

        caps = ["video/x-raw", "framerate={}".format(framerate)]
        if width:
            caps.append("width={}".format(width))
        if height:
            caps.append("height={}".format(height))

        elements = [
            "appsrc name=src is-live=true do-timestamp=true caps=image/png",
            "pngdec",
            "videoconvert",
            "videorate",
            "videocrop name=crop",
            ",".join(caps),
            "queue",
        ]
        if filename:
            elements += [
                "vp8enc",
                "webmmux",
                "filesink location={}".format(filename),
            ]
        else:
            elements.append("autovideosink sync=false")
        self._pipeline = Gst.parse_launch(" ! ".join(elements))

        self._appsrc = self._pipeline.get_by_name("src")
        self._appsrc.connect("need-data", self._push_screenshot)

        videocrop = self._pipeline.get_by_name("crop")
        if width:
            videocrop.set_property("right", -1)  # Auto-crop
        if height:
            videocrop.set_property("bottom", -1)  # Auto-crop

    def start(self):
        """Start video recording."""
        self._pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        """Stop video recording."""
        self._appsrc.emit("end-of-stream")
        self._pipeline.set_state(Gst.State.NULL)

    def _push_screenshot(self, *_):
        """Emit a WebDriver screenshot from appsrc."""
        self._appsrc.emit(
            "push-buffer",
            Gst.Buffer.new_wrapped(self.driver.get_screenshot_as_png()),
        )


def VideoViewer(*args, **kwargs):
    """Shorthand for `VideoRecorder(filename=None)`.

    Useful with PhantomJS.
    """
    kwargs["filename"] = None
    return VideoRecorder(*args, **kwargs)


def _patch_driver(driver):
    """Prevent failures caused by concurrent connections to the remote
    WebDriver.

    Another option would be to use a WebDriver proxy. Monkey patching `driver`
    is simpler, though more hacky.
    """
    lock = threading.Lock()
    execute_unsafe = driver.execute

    def execute_safe(driver_command, params=None):
        with lock:
            return execute_unsafe(driver_command, params)

    driver.execute = execute_safe
