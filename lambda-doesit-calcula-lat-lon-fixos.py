import json
import requests
import boto3
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Inicializa o cliente SQS fora do handler
sqs = boto3.client('sqs')
QUEUE_URL = "https://sqs.sa-east-1.amazonaws.com/102863741683/sqs-doesit-salva-lat-lon"

def get_lat_long(endereco):
    url = "https://us1.locationiq.com/v1/search"
    params = {
        'key': 'pk.b446421863770d76f87401e7e331210e',
        'q': endereco,
        'format': 'json',
        'limit': 1
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list):
            return data[0]['lat'], data[0]['lon']
    except Exception as e:
        logger.error(f"Erro na API LocationIQ: {e}")
    return None, None

def lambda_handler(event, context):
    for record in event['Records']:
        body = json.loads(record['body'])
        
        # Captura os dados do payload recebido
        user_id = body.get('id_usuario')
        endereco_id = body.get('id_endereco') 
        tipo = body.get('tipo_usuario')
        endereco = body.get('endereco_completo')
        
        lat, lon = get_lat_long(endereco)
        
        if lat and lon:
            # Prepara a mensagem para a próxima fila mantendo o id_endereco
            payload = {
                "id_usuario": user_id,
                "id_endereco": endereco_id, 
                "tipo_usuario": tipo,
                "lat": lat,
                "lon": lon
            }
            
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(payload)
            )
            logger.info(f"Geocodificação processada e enviada para SQS: Endereço {endereco_id} do Usuário {user_id}")
        else:
            logger.warning(f"Geocodificação falhou para o endereço {endereco_id}")
            
    return {"status": "success"}