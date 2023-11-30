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

from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

import sounddevice

import time

from dotenv import load_dotenv

import queue

load_dotenv()

# Get AWS credentials from environment variables
aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"]
aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"]

# Create your views here.
ai_sentences = queue.Queue()
openai_response_flag = False
chunks = []
mic_state = False
aws_transcribe_flag = False
user_sentences = ""



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




class MyEventHandler(TranscriptResultStreamHandler):
    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        # This handler can be implemented to handle transcriptions as needed.
        # Here's an example to get started.
        global mic_state, user_sentences, aws_transcribe_flag
        results = transcript_event.transcript.results
        for result in results:
            if not result.is_partial and aws_transcribe_flag:
                for alt in result.alternatives:
                    print("user: {}".format(alt.transcript))
                    user_sentences =user_sentences + " " + alt.transcript

        for result in results:
            if not result.is_partial:
                if not mic_state:
                    aws_transcribe_flag = False
                    break
                


       

async def mic_stream():
    # This function wraps the raw input stream from the microphone forwarding
    # the blocks to an asyncio.Queue.
    loop = asyncio.get_event_loop()
    input_queue = asyncio.Queue()

    def callback(indata, frame_count, time_info, status):
        loop.call_soon_threadsafe(input_queue.put_nowait, (bytes(indata), status))

    # Be sure to use the correct parameters for the audio stream that matches
    # the audio formats described for the source language you'll be using:
    # https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html
    stream = sounddevice.RawInputStream(
        channels=1,
        samplerate=16000,
        callback=callback,
        blocksize=1024 * 2,
        dtype="int16",
    )
    # Initiate the audio stream and asynchronously yield the audio chunks
    # as they become available.
    with stream:
        while True:
            indata, status = await input_queue.get()
            yield indata, status

async def write_chunks(stream):
    # This connects the raw audio chunks generator coming from the microphone
    # and passes them along to the transcription stream.
    async for chunk, status in mic_stream():
        await stream.input_stream.send_audio_event(audio_chunk=chunk)
    await stream.input_stream.end_stream()


async def basic_transcribe():
    print('-------------basic_transcribe()----------------')
    # Setup up our client with our chosen AWS region
    client = TranscribeStreamingClient(region="eu-west-2")

    # Start transcription to generate our async stream
    stream = await client.start_stream_transcription(
        language_code="nl-NL",
        media_sample_rate_hz=16000,
        media_encoding="pcm",
    )

    # Instantiate our handler and start processing events
    handler = MyEventHandler(stream.output_stream)
    await asyncio.gather(write_chunks(stream), handler.handle_events())


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
        global ai_sentences, openai_response_flag
        msgs = [{"role": "system", "content": "You are a helpful assistant."}]


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
                        LanguageCode='en-US',
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

def run_transcribe_task():
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(basic_transcribe())
    loop.close()


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
    thread = threading.Thread(target=run_transcribe_task)
    thread.start()
    application.listen(8000)



    # asyncio.run(consume_stream())
    tornado.ioloop.IOLoop.instance().start()




