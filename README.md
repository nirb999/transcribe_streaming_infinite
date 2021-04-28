# transcribe_streaming_infinite

This is a comparison between the results of versions 1.3.2 and 2.1.0 of the Google Speech Streaming API.

### Files for streaming API v1.3.2:
1) google_speech_streaming_v.1.3.2.py
2) pip.freeze.1.3.2.txt
3) result_streaming_v1.3.2.txt

### Files for streaming API v2.1.0:
1) google_speech_streaming_v.2.1.0.py
2) pip.freeze.2.1.0.txt
3) result_streaming_v2.1.0.txt

### Files for long running API v2.1.0:
1) transcribe_word_time_offsets.py
2) pip.freeze.2.1.0.txt
3) result_long_running_v2.1.0.txt

Doing a three-way copmarison on the files result_streaming_v1.3.2.txt, result_streaming_v2.1.0.txt and result_long_running_v2.1.0.txt, will show that v2.1.0 results have a slight time offset of ~300msec, which will accumulate every time the streaming API will have to restart due to the time limitation.

The solution as explained in [issue 124](https://github.com/googleapis/python-speech/issues/124), is to add for streaming_recognize (google/cloud/speech_v1/services/speech/client.py):
```python
self._transport.streaming_recognize._prefetch_first_result_ = False
```



