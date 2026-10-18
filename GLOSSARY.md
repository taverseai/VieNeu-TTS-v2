# Speech Synthesis

Terms used by VieNeu-TTS when accepting text and producing speech audio.

## Synthesis

**Backbone**:
The speech model family used to synthesize audio from text and voice information.

**Voice**:
A selectable speaker identity used during synthesis. A voice may be built in or enrolled from a reference clip.
_Avoid_: Sample voice, voice sample (when referring to a selectable voice)

**Voice reference clip**:
An audio recording of a speaker used to enroll a voice for speech synthesis.
_Avoid_: Sample voice

**Text chunk**:
A segment of input text synthesized as one unit before moving to the next segment.

**Audio chunk**:
A segment of generated audio that can be returned while synthesis is still in progress.

**Batch size**:
The server's capacity for processing concurrent speech synthesis streams.
_Avoid_: Number of text chunks in one request

**Speaking rate**:
The relative playback tempo of synthesized speech, expressed as a percentage change from the original tempo.
_Avoid_: Sample rate

**Pitch shift**:
A relative change in the perceived pitch of synthesized speech, expressed in cents; 100 cents equal one semitone.
_Avoid_: Pitch in Hz (for a relative shift without a reference frequency)
