from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.response import Response
from .serializers import TodoSerializer
from .models import Todo
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

import openai
import json

import tempfile
import os


import boto3
from pathlib import Path

import base64

import requests
# Create your views here.


@csrf_exempt
def getAssistContent(request):
    """
 List  customers, or create a new customer.
 """

    if request.method == 'POST':
        print("chatgpt available")
        raw_data = request.body
        print(raw_data)
        # Convert the byte string to a regular string
        data = raw_data.decode('utf-8')

        # get conversation history
        # Todo.objects.all().delete()
        # objs = Todo.objects.all()

        # serialize = TodoSerializer(objs, many=True)
        # objs_len = len(serialize.data)
        # st_index = max(objs_len - 2, 0)
        msgs = [{"role": "system", "content": "You are a helpful assistant."}]
        # for i in range(st_index, objs_len):
        #     msg = dict(role="user", content=serialize.data[i]["user_context"])
        #     msgs.append(msg)
        #     msg = dict(role="assistant",
        #                content=serialize.data[i]["assist_context"])
        #     msgs.append(msg)

        msgs.append({"role": "user", "content": data})
        print(msgs)

        openai.api_key = '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'
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=msgs
        )

        t_result = completion.choices[0].message

        # save user input and assistance reply to serialize
        serialize_data = dict(
            user_context=data, assist_context=t_result["content"])
        serialize = TodoSerializer(data=serialize_data)
        if serialize.is_valid():
            serialize.save()
        print("chatbot reply is: ", t_result['content'])

        # using Amazon Account
        try:
            # text-to-speech using Amazon Polly
            polly_client = boto3.Session(
                aws_access_key_id="AKIA6MR7SOI53BAVLKGN",
                aws_secret_access_key="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",
                region_name="eu-west-2"
            ).client('polly')

            # Create a folder called "audio" in the folder where the script is running
            Path("audio").mkdir(parents=True, exist_ok=True)
            open("audio/response.mp3", "a").close()

            audio = polly_client.synthesize_speech(
                Text=t_result["content"],
                VoiceId='Joanna',
                Engine='neural',
                LanguageCode='en-US',
                OutputFormat="mp3"
            )

            # print("audio type: ", audio)
            # Get the content of the generated audio file
            audio_stream = audio["AudioStream"]
            print("audio stream type: ", type(audio_stream))
            # Save the content of the audio file to a local file
            binary_audio = audio_stream.read()
            with open("audio/response.mp3", "wb") as file:
                file.write(binary_audio)
            # Convert audio data to base64-encoded string
            audio_base64 = base64.b64encode(binary_audio).decode('utf-8')
        except:
            audio_base64 = None

        # using Endl Ai

        # headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoiZjQwZWI5NTMtYTdkNS00ZjdkLThlYzktOWMzMzNhNTkzMDRhIiwidHlwZSI6ImZyb250X2FwaV90b2tlbiJ9.0h4vvtO43hpNZ9N6wTBdU26FwuiBP8I3676fSqt8iWI"}

        # url = "https://api.edenai.run/v2/audio/text_to_speech"
        # payload = {"show_original_response": False, "fallback_providers": "",
        #            "providers": "google", "language": "en-US", "option": "FEMALE", "text": t_result['content']}

        # response = requests.post(url, json=payload, headers=headers)

        # a_result = json.loads(response.text)
        # print(a_result)

        # return JsonResponse(dict(audio=a_result['google']['audio'], text=t_result['content']))
        return JsonResponse(dict(audio=audio_base64, text=t_result['content']))


@csrf_exempt
def SpeechToText(request):
    if request.method == "POST":

        blob = request.FILES['file']
        name = request.POST.get('name')
        datetime = request.POST.get("datetime")
        options = json.loads(request.POST.get("options"))
        audio = None
        print(type(options['language']))

        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(blob.name)[1], delete=False) as f:
            for chunk in blob.chunks():
                f.write(chunk)
            f.seek(0)

        ##################################### whisper ###############################################
        
        client = openai.OpenAI()

        audio_file = open(f.name, "rb")
        transcript = client.audio.transcriptions.create(
        model="whisper-1", 
        file=audio_file, 
        response_format="text"
        )

        return JsonResponse({"text": transcript['text']})


