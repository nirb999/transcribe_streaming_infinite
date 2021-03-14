import sys
import os
import copy
import threading
import datetime
import time

from google.cloud import speech
from google.api_core import exceptions
import queue

# Audio recording parameters
STREAMING_LIMIT = 180000  # 3 minutes
SAMPLE_RATE = 16000
CHUNK_SIZE = int(2 * SAMPLE_RATE / 10)  # 100ms


class PcmReader(threading.Thread):

    def __init__(self, pcm_file_name, stream_generator):
        self.pcm_file_name = pcm_file_name
        self.sample_rate = SAMPLE_RATE
        self.stream_generator = stream_generator

        threading.Thread.__init__(self, name='pcm_reader')

    def run(self):

        chunk_size = CHUNK_SIZE

        with open(self.pcm_file_name, 'rb') as pcm:

            audio_data = pcm.read()

            audio_time = datetime.timedelta(seconds=(float(len(audio_data)) / float(2 * self.sample_rate)))
            target_time = datetime.datetime.now() + audio_time

            index = 0
            while index < len(audio_data):

                if chunk_size > len(audio_data) - index:
                    chunk_size = len(audio_data) - index

                self.stream_generator.put_audio_data(audio_data[index:(index + chunk_size)])
                index += chunk_size
                
                bytes_left = len(audio_data) - index
                if bytes_left > 0:
                    current_time = datetime.datetime.now()
                    if target_time > current_time:
                        time_left = target_time - current_time
                        rate = time_left.total_seconds() / float(bytes_left)
                        time.sleep(rate * chunk_size)

class StreamGenerator:

    def __init__(self):
        self.sample_rate = SAMPLE_RATE
        self._queue = queue.Queue()
        self.closed = True
        self.current_time = 0.0
        self.start_time = self.current_time
        self.last_audio_input = b''
        self.final_result_end_time = 0.0
        self.new_stream = True

    def __enter__(self):
        self.closed = False
        return self

    def __exit__(self, type, value, traceback):
        self.closed = True

    def put_audio_data(self, audio_data):
        self._queue.put(audio_data)

    def generator(self):

        while not self.closed:

            data = []

            if self.new_stream:

                print("--------------------------------------------------------- NEW GENERATOR STREAM")

                if len(self.last_audio_input) > 0:

                    data.append(copy.deepcopy(self.last_audio_input))  # TODO: do we need the deepcopy

                self.new_stream = False

            chunk = self._queue.get()

            if chunk is None:
                return

            else:

                data.append(chunk)
                self.last_audio_input += chunk

                self.current_time += round(float(len(chunk)) / float(self.sample_rate * 2) * 1000, 2)

                while True:
                    try:
                        chunk = self._queue.get(block=False)

                        if chunk is None:
                            return
                        data.append(chunk)
                        self.last_audio_input += chunk

                        self.current_time += round(float(len(chunk)) / float(self.sample_rate * 2) * 1000, 2)

                    except queue.Empty:
                        break

            yield b''.join(data)


class GoogleTranscribe:

    def __init__(self, stream_generator):

        self.generator = stream_generator
        
        self.client = speech.SpeechClient()

        config = speech.types.RecognitionConfig(
            encoding=speech.enums.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            language_code='en-US',
            enable_word_time_offsets=True,
            enable_automatic_punctuation=True,
            max_alternatives=1,
            model='video',
            use_enhanced=True
        )

        self.streaming_config = speech.types.StreamingRecognitionConfig(
            config=config,
            #single_utterance=True,
            interim_results=True
        )

    def start(self):

        with self.generator as stream:

            while not stream.closed:

                audio_generator = stream.generator()

                requests = (speech.types.StreamingRecognizeRequest(audio_content=content)for content in audio_generator)

                responses = self.client.streaming_recognize(self.streaming_config, requests)

                self.handle_responses(responses, stream)

                stream.new_stream = True

    def handle_responses(self, responses, stream):

        for response in responses:

            if not response.results:
                continue

            result = response.results[0]

            if not result.alternatives:
                continue

            if result.is_final:

                transcript = result.alternatives[0].transcript

                if len(result.alternatives[0].words) > 0:
                    print("***************************************************")
                    result_start_time = stream.start_time / 1000.0
                    for word in result.alternatives[0].words:
                        print(f"Word: {word.word}, start_time: {self.add_time(word.start_time, result_start_time)}, end_time: {self.add_time(word.end_time, result_start_time)}")
                    print("result_start_time={}".format(result_start_time))
                    print("Transcript: {}".format(transcript))
                    print("***************************************************")
    
                result_end_time = self.calculate_time(result.result_end_time)
                print("result_end_time={}".format(result_end_time))
              
                new_final_result_end_time = result_end_time + float(stream.start_time)
                print("new_final_result_end_time={}".format(new_final_result_end_time))

                time_diff = new_final_result_end_time - stream.final_result_end_time
                offset = round(time_diff * stream.sample_rate * 2 / 1000)

                stream.last_audio_input = stream.last_audio_input[int(offset):]
                stream.final_result_end_time = new_final_result_end_time

                if stream.current_time - stream.start_time >= STREAMING_LIMIT:
                    stream.start_time = stream.final_result_end_time
                    break

    def calculate_time(self, _time) -> float:
        sec = 0
        nanos = 0

        if _time.seconds:
            sec = _time.seconds

        if _time.nanos:
            nanos = _time.nanos

        return round((sec * 1000) + (nanos / (1000 * 1000)), 2)

    def add_time(self, word_time, time_offset) -> float:

        time_offset_seconds = int(time_offset)
        time_offset_nanos = (time_offset - time_offset_seconds) * 1e9

        word_time_seconds = 0
        if word_time.seconds:
            word_time_seconds = word_time.seconds

        word_time_nanos = 0
        if word_time.nanos:
            word_time_nanos = word_time.nanos

        result_time_nanos = time_offset_nanos + word_time_nanos
        result_time_seconds = time_offset_seconds + word_time_seconds

        if result_time_nanos >= 1e9:
            result_time_seconds += 1
            result_time_nanos -= 1e9

        return round((int(result_time_seconds)) + (int(result_time_nanos) / (1000 * 1000 * 1000)), 2)
                  

if __name__ == "__main__":

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ""

    stream_generator = StreamGenerator()
    
    google_transcribe = GoogleTranscribe(stream_generator)

    pcm_reader = PcmReader("example.pcm", stream_generator)
    pcm_reader.start()

    google_transcribe.start()

    
