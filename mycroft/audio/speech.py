# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import time
from threading import Lock

import re

from mycroft.configuration import ConfigurationManager
from mycroft.tts import TTSFactory
from mycroft.util import create_signal, stop_speaking, check_for_signal
from mycroft.util.log import LOG

ws = None
config = None
tts = None
tts_hash = None
lock = Lock()

_last_stop_signal = 0


def _trigger_expect_response(message):
    """
        Makes mycroft start listening on 'recognizer_loop:audio_output_end'
    """
    create_signal('startListening')


def handle_speak(event):
    """
        Handle "speak" message
    """
    config = ConfigurationManager.get()
    ConfigurationManager.init(ws)
    global _last_stop_signal

    # Mild abuse of the signal system to allow other processes to detect
    # when TTS is happening.  See mycroft.util.is_speaking()

    utterance = event.data['utterance']
    if event.data.get('expect_response', False):
        ws.once('recognizer_loop:audio_output_end', _trigger_expect_response)

    # This is a bit of a hack for Picroft.  The analog audio on a Pi blocks
    # for 30 seconds fairly often, so we don't want to break on periods
    # (decreasing the chance of encountering the block).  But we will
    # keep the split for non-Picroft installs since it give user feedback
    # faster on longer phrases.
    #
    # TODO: Remove or make an option?  This is really a hack, anyway,
    # so we likely will want to get rid of this when not running on Mimic
    if not config.get('enclosure', {}).get('platform') == "picroft":
        start = time.time()
        chunks = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s',
                          utterance)
        for chunk in chunks:
            try:
                mute_and_speak(chunk)
            except KeyboardInterrupt:
                raise
            except:
                LOG.error('Error in mute_and_speak', exc_info=True)
            if _last_stop_signal > start or check_for_signal('buttonPress'):
                break
    else:
        mute_and_speak(utterance)


def mute_and_speak(utterance):
    """
        Mute mic and start speaking the utterance using selected tts backend.

        Args:
            utterance: The sentence to be spoken
    """
    global tts_hash

    lock.acquire()
    # update TTS object if configuration has changed
    if tts_hash != hash(str(config.get('tts', ''))):
        global tts
        # Stop tts playback thread
        tts.playback.stop()
        tts.playback.join()
        # Create new tts instance
        tts = TTSFactory.create()
        tts.init(ws)
        tts_hash = hash(str(config.get('tts', '')))

    LOG.info("Speak: " + utterance)
    try:
        tts.execute(utterance)
    finally:
        lock.release()


def handle_stop(event):
    """
        handle stop message
    """
    global _last_stop_signal
    _last_stop_signal = time.time()
    tts.playback.clear_queue()
    tts.playback.clear_visimes()
    stop_speaking()


def init(websocket):
    """
        Start speach related handlers
    """

    global ws
    global tts
    global tts_hash
    global config

    ws = websocket
    ConfigurationManager.init(ws)
    config = ConfigurationManager.get()
    ws.on('mycroft.stop', handle_stop)
    ws.on('speak', handle_speak)

    tts = TTSFactory.create()
    tts.init(ws)
    tts_hash = config.get('tts')


def shutdown():
    global tts
    if tts:
        tts.playback.stop()
        tts.playback.join()
