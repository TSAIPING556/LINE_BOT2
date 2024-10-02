#======python的函數庫==========
import tempfile, os
import openai
import time
import traceback
import json
import random
import requests
#======python的函數庫==========
from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
from azure.cognitiveservices.vision.computervision.models import VisualFeatureTypes
from msrest.authentication import CognitiveServicesCredentials
from array import array
from PIL import Image
import sys
from azure.core.credentials import AzureKeyCredential
from azure.ai.language.questionanswering import QuestionAnsweringClient
from datetime import datetime, timezone, timedelta
from flask import Flask
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage, PostbackEvent, MemberJoinedEvent

app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# Channel Access Token
# Set up LINE_bot
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# OPENAI API Key初始化設定
endpoint = os.getenv('END_POINT')
open_ai_api_key = os.getenv('OpenAI_API_KEY')
open_ai_endpoint = os.getenv('OpenAI_ENDPOINT')
deployment_name = os.getenv('OpenAI_DEPLOY_NAME')
openai.api_base = open_ai_endpoint
headers = {
    "Content-Type": "application/json",
    "api-key": open_ai_api_key,
}

# Set up Language Studio
credential = AzureKeyCredential(os.getenv('AZURE_KEY'))
knowledge_base_project = os.getenv('PROJECT')
deployment = 'production'

# Authenticate with the Azure Computer Vision service
vision_subscription_key = os.getenv('VISION_SUBSCRIPTION_KEY')
vision_endpoint = os.getenv('VISION_ENDPOINT')
computervision_client = ComputerVisionClient(vision_endpoint, CognitiveServicesCredentials(vision_subscription_key))

# 連接Azure Language Studio，查詢知識庫
def QA_response(text):
    client = QuestionAnsweringClient(endpoint, credential)
    with client:
        output = client.get_answers_to_question(knowledge_base_project, deployment, text)
        return output.answers[0].answer

# 連接Azure OpenAI的Chatgpt
def Chatgpt_response(prompt):   
    payload = {
        "model": "gpt-4o-mini",  
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1000,
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0
    }
    
    response = requests.post(open_ai_endpoint, headers=headers, json=payload)
    
    if response.status_code == 200:
        result = response.json()
        return result['choices'][0]['message']['content']
    else:
        print(f"Error {response.status_code}: {response.text}")

# 圖片轉文字
def extract_text_from_image(image_path):
    with open(image_path, 'rb') as image_stream:
        read_operation = computervision_client.read_in_stream(image_stream, raw=True)
    
    operation_location = read_operation.headers["Operation-Location"]
    operation_id = operation_location.split("/")[-1]
    
    while True:
        result = computervision_client.get_read_result(operation_id)
        if result.status not in ['notStarted', 'running']:
            break
        time.sleep(1)
    
    if result.status == 'succeeded':
        text_results = result.analyze_result.read_results
        extracted_text = ""
        for page in text_results:
            for line in page.lines:
                extracted_text += line.text + "\n"
        return extracted_text
    else:
        return "Text extraction failed."

# 監聽所有來自 /callback 的 Post Request
@app.route("/callback", methods=['POST'])
def callback():
    return 'OK'

# 處理訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    if msg[0:2] == '習題':
        try:
            QA_answer = QA_response(msg)
            print(QA_answer)
            if QA_answer != 'No good match found in KB':
                line_bot_api.reply_message(event.reply_token, TextSendMessage(QA_answer))
        except:
            print(traceback.format_exc())
            line_bot_api.reply_message(event.reply_token, TextSendMessage('QA Error'))
    elif msg[0] == '!':
        try:
            gpt_answer = Chatgpt_response(msg)
            print(gpt_answer)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(gpt_answer))
        except:
            print(traceback.format_exc())
            line_bot_api.reply_message(event.reply_token, TextSendMessage('Please retry later'))

# 處理圖片訊息
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_id = event.message.id
    message_content = line_bot_api.get_message_content(message_id)
    directory = "static"
    
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    image_path = f"static/{message_id}.jpg"
    with open(image_path, 'wb') as f:
        for chunk in message_content.iter_content():
            f.write(chunk)
    
    extracted_text = extract_text_from_image(image_path)
    
    try:
        QA_answer = QA_response(extracted_text)
        print(QA_answer)
        if QA_answer != 'No good match found in KB':
            line_bot_api.reply_message(event.reply_token, TextSendMessage(QA_answer))
        
        gpt_answer = Chatgpt_response(f"這本書的摘要:\n\n{extracted_text}")
        print(gpt_answer)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(gpt_answer))
    except:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage('QA Error'))
        line_bot_api.reply_message(event.reply_token, TextSendMessage('Try later'))        

@handler.add(PostbackEvent)
def handle_postback(event):
    print(event.postback.data)

@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name}歡迎加入')
    line_bot_api.reply_message(event.reply_token, message)

import os
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
