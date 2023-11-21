import json
from channels.generic.websocket import AsyncWebsocketConsumer


class YourConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = 'tasks'
        await self.channel_layer.grou(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data):
        # Process incoming message
        text_data_json = json.loads(text_data)
        name = text_data_json.get('name')
        datetime = text_data_json.get('datetime')
        file = text_data_json.get('file')
        options = text_data_json.get('options')

        # Example processing
        # You can put your processing logic here to handle the incoming message
        # Send a response
        await self.send(text_data=json.dumps({'message': 'The message was received and processed.'}))