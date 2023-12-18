from typing import Any
import uuid
import tornado
from tornado import httputil
import tornado.ioloop
import tornado.web
import tornado.websocket

from openai import OpenAI
import os

import boto3
from pathlib import Path

import base64

import requests

import threading
import tempfile
from django.http import JsonResponse
import json
import asyncio

import queue
import re
import sys

from google.cloud import speech

import pyaudio

import time

from dotenv import load_dotenv

import queue

load_dotenv()

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms

# Create your views here.
ai_sentences = queue.Queue()
openai_response_flag = False
chunks = []
mic_state = False
aws_transcribe_flag = False
user_sentences = ""

# Get AWS credentials from environment variables
aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"]
aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"]

language_code = "en-US"  # a BCP-47 language tag

def getOpenAiResponse(msgs):
    print(msgs)
    global ai_sentences, openai_response_flag

    response = ai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=msgs,
        stream=True
        )
    
    collected_chunks = []
    collected_messages = []


    for chunk in response:
        collected_chunks.append(chunk)  # save the event response
        chunk_message = chunk.choices[0].delta  # extract the message
        # print(chunk_message)
        collected_text = chunk_message.content
        if collected_text is None:
            collected_text = ""
        collected_messages.append(collected_text)
        text = ''.join(collected_messages)

        if '.' in text or '?' in text or '!' in text:
            print(text)
            collected_messages = []
            ai_sentences.put(text)

    openai_response_flag = True

def clearFolder(folder_path):
    # Get a list of all files and directories in the folder
    items = os.listdir(folder_path)

    # Loop through each item and remove it
    for item in items:
        item_path = os.path.join(folder_path, item)
        if os.path.isfile(item_path):
            os.remove(item_path)
        elif os.path.isdir(item_path):
            os.rmdir(item_path)




class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self: object, rate: int = RATE, chunk: int = CHUNK) -> None:
        """The audio -- and generator -- is guaranteed to be on the main thread."""
        self._rate = rate
        self._chunk = chunk

        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self.closed = True

    def __enter__(self: object) -> object:
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            # The API currently only supports 1-channel (mono) audio
            # https://goo.gl/z757pE
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
        )

        self.closed = False

        return self

    def __exit__(
        self: object,
        type: object,
        value: object,
        traceback: object,
    ) -> None:
        """Closes the stream, regardless of whether the connection was lost or not."""
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(
        self: object,
        in_data: object,
        frame_count: int,
        time_info: object,
        status_flags: object,
    ) -> object:
        """Continuously collect data from the audio stream, into the buffer.

        Args:
            in_data: The audio data as a bytes object
            frame_count: The number of frames captured
            time_info: The time information
            status_flags: The status flags

        Returns:
            The audio data as a bytes object
        """
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self: object) -> object:
        """Generates audio chunks from the stream of audio data in chunks.

        Args:
            self: The MicrophoneStream object

        Returns:
            A generator that outputs audio chunks.
        """
        while not self.closed:
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b"".join(data)


def listen_print_loop(responses: object) -> str:
    """Iterates through server responses and prints them.

    The responses passed is a generator that will block until a response
    is provided by the server.

    Each response may contain multiple results, and each result may contain
    multiple alternatives; for details, see https://goo.gl/tjCPAU.  Here we
    print only the transcription for the top alternative of the top result.

    In this case, responses are provided for interim results as well. If the
    response is an interim one, print a line feed at the end of it, to allow
    the next result to overwrite it, until the response is a final one. For the
    final one, print a newline to preserve the finalized transcription.

    Args:
        responses: List of server responses

    Returns:
        The transcribed text.
    """
    global user_sentences, aws_transcribe_flag, mic_state
    num_chars_printed = 0

    for response in responses:
        if not response.results:
            continue

        # The `results` list is consecutive. For streaming, we only care about
        # the first result being considered, since once it's `is_final`, it
        # moves on to considering the next utterance.
        result = response.results[0]
        if not result.alternatives:
            continue

        # Display the transcription of the top alternative.
        transcript = result.alternatives[0].transcript
        
        num_chars_printed = len(transcript)

        # Display interim results, but with a carriage return at the end of the
        # line, so subsequent lines will overwrite them.
        #
        # If the previous result was longer than this one, we need to print
        # some extra spaces to overwrite the previous result
        overwrite_chars = " " * (num_chars_printed - len(transcript))

        if not result.is_final:
            # sys.stdout.write(transcript + overwrite_chars + "\r")
            # sys.stdout.flush()

            num_chars_printed = len(transcript)

        else:
            # print(transcript + overwrite_chars)
            if aws_transcribe_flag:
                print("user: {}".format(transcript))
                user_sentences = user_sentences + " " + transcript
            if not mic_state:
                aws_transcribe_flag = False
            # Exit recognition if any of the transcribed phrases could be
            # one of our keywords.
            if re.search(r"\b(exit|quit)\b", transcript, re.I):
                print("Exiting..")
                break

            num_chars_printed = 0

    # return "".join(transcripts)
    return



class CorsWebSocketHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

class CorsHandler(tornado.web.RequestHandler):
    def initialize(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept")

    def options(self):
        # Respond to CORS preflight requests
        self.set_status(204)
        self.finish()

class EchoWebSocket(CorsWebSocketHandler):
    waiters = set()
    user = None
    init = False
    thread = None


    def open(self):
        EchoWebSocket.waiters.add(self)
        print("WebSocket opened")

        # self.thread = threading.Thread(target=run_transcribe_task)
        # self.thread.start()

    def on_close(self):
        try:
            EchoWebSocket.waiters.remove(self)
        except ValueError:
            pass
        print("WebSocket closed")

        # self.thread.join()

    def on_message(self, message):
        global mic_state, chunks, aws_transcribe_flag, user_sentences
        if message == "Start":
            print('------------------------- started -----------------------------')
            mic_state = True
            aws_transcribe_flag = True
            return
            # asyncio.ensure_future(basic_transcribe())

        elif message == 'End':
            mic_state = False
            
            if not mic_state:
                aws_transcribe_flag = False
            while True:
                if not aws_transcribe_flag:
                    if user_sentences:
                        print('whole user question: {}'.format(user_sentences))
                        self.getAssistantContent(user_sentences)
                        user_sentences = '' 
                    break 
                else:
                    time.sleep(0.1)
                
            print('------------------------- ended -----------------------------')

            # self.write_message('end')
            return



            # print(message)




        # if message.startswith('user:'):
        #     print('User logged: '+message)
        #     self.user = message.split(':')[1]
        #     self.user_uuid = str(uuid.uuid4())
        #     return
        # if message == 'refresh' and self.user is not None:
        #     print('refreshing...')
        #     for w in EchoWebSocket.waiters:
        #         if w != self and w.user == self.user:
        #             w.write_message('refresh')



    def options(self):
        # Respond to CORS preflight requests
        self.set_status(204)
        self.finish()

    def getAssistantContent(self, data):
        global ai_sentences, openai_response_flag, language_code

        system_content = "You are a helpful assistant."
        if language_code == 'nl-NL':
            system_content = '''You are a translator and helpful assistant. You always receive Dutch messages. For all messages users submit to you you must, 
            1. Generate a literal translation of input text into into English.
            2. Response properly in Dutch.
            '''
        
        msgs = [{"role": "system", "content": system_content}]


        msgs.append({"role": "user", "content": data})
        # print(msgs)

        openai_response_flag = False
        ai_sentences.queue.clear()
        thread = threading.Thread(target=getOpenAiResponse, args=(msgs,))
        thread.start()

        
        # Path("audio").mkdir(parents=True, exist_ok=True)
        # clearFolder('audio')

        ready = True
        sentence_cnt = 0
        while True:
            if ai_sentences.empty() and openai_response_flag:
                break
            if not ai_sentences.empty() and ready:
                # print('text to speech process')
                ready = False
                sentence = ai_sentences.get()

                # for test
                print('Ai: {}'.format(sentence))

                # open("audio/{}.mp3".format(sentence_cnt), "a").close()
                st_time = time.time()
                audio = polly_client.synthesize_speech(
                        Text=sentence,
                        VoiceId='Joanna',
                        Engine='neural',
                        LanguageCode=language_code,
                        OutputFormat="mp3"
                    )
                # print('text-to-speech elasped: {}'.format(round(time.time() - st_time), 2))

                # print("audio type: ", audio)
                # Get the content of the generated audio file
                audio_stream = audio["AudioStream"]
                # print("audio stream type: ", type(audio_stream))
                # Save the content of the audio file to a local file
                binary_audio = audio_stream.read()
                # with open("audio/{}.mp3".format(sentence_cnt), "wb") as file:
                #         file.write(binary_audio)
                    # Convert audio data to base64-encoded string
                audio_base64 = base64.b64encode(binary_audio).decode('utf-8')
                audioTextResponse = dict(audio=audio_base64, text=sentence)
                # self.write_message(JsonResponse(audioTextResponse))
                json_data = json.dumps(audioTextResponse)
                self.write_message(json_data)

                
                sentence_cnt += 1
                ready = True
            else:
                time.sleep(0.1)
            
            

            # Wait for the thread to exit
        thread.join()
        print('all finished')

            # return JsonResponse(dict(audio=audio_base64, text=t_result['content']))

        return


application = tornado.web.Application([
    (r'/ws', EchoWebSocket),
    (r'/static/(.*)', tornado.web.StaticFileHandler, {'path': '/path/to/static/files'}),
    (r'/cors', CorsHandler),
])

def basic_transcribe(streaming_config):
    print('-------------basic_transcribe()----------------')
    """Transcribe speech from audio file."""
    # See http://g.co/cloud/speech/docs/languages
    # for a list of supported languages.
    

    client = speech.SpeechClient()
    
    with MicrophoneStream(RATE, CHUNK) as stream:
        audio_generator = stream.generator()
        requests = (
            speech.StreamingRecognizeRequest(audio_content=content)
            for content in audio_generator
        )

        responses = client.streaming_recognize(streaming_config, requests)

        # Now, put the transcription responses to use.
        listen_print_loop(responses)


if __name__ == '__main__':
    chunks = []
    mic_state = False

    print('loading...')
    polly_client = boto3.Session(
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    region_name="eu-west-2"
                ).client('polly')

    print('amazon polly loaded')
    ai_client = OpenAI()
    print('chatgpt loaded')

    
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=language_code,
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config, interim_results=True
    )

    thread = threading.Thread(target=basic_transcribe, args=(streaming_config,))
    thread.start()
    application.listen(8000)



    # asyncio.run(consume_stream())
    tornado.ioloop.IOLoop.instance().start()




