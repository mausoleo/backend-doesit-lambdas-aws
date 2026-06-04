import json
import psycopg2
import os
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)
QUEUE_URL = "https://sqs.sa-east-1.amazonaws.com/102863741683/sqs-doesit-atualiza-lat-lon-fixos"
sqs = boto3.client('sqs')

def lambda_handler(event, context):
    conn = None
    try:
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        id_endereco = event.get('queryStringParameters', {}).get('id')
        
        if not id_endereco:
            return {"statusCode": 400, "body": json.dumps({"error": "ID do endereço não fornecido"})}

        body = json.loads(event.get('body', '{}'))
        is_favorite = body.get('is_favorite', False)

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
            port=5432, sslmode='verify-full', 
            sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
        )
        cur = conn.cursor()

        # 1. Lógica do favorito
        if is_favorite:
            cur.execute("""
                UPDATE "tbl_endereco" 
                SET is_favorite = FALSE 
                WHERE id_usuario = (SELECT id_usuario FROM "tbl_usuario" WHERE sub_cognito = %s)
            """, (sub,))
        
        # 2. Atualiza o endereço alvo
        query = """
            UPDATE "tbl_endereco" SET 
                titulo = %s, cep = %s, rua = %s, numero = %s, 
                bairro = %s, cidade = %s, estado = %s, is_favorite = %s
            WHERE id_endereco = %s 
            AND id_usuario = (SELECT id_usuario FROM "tbl_usuario" WHERE sub_cognito = %s)
            RETURNING id_usuario; -- Retorna para capturar na fila
        """
        cur.execute(query, (
            body.get('titulo'), body.get('cep'), body.get('rua'), body.get('numero'),
            body.get('bairro'), body.get('cidade'), body.get('estado'), is_favorite,
            id_endereco, sub
        ))
        
        result = cur.fetchone()
        if not result:
            return {"statusCode": 404, "body": json.dumps({"error": "Endereço não encontrado ou sem permissão"})}
        
        user_id = result[0]
        conn.commit()
        cur.close()
        conn.close()

        endereco_completo = f"{body.get('rua')}, {body.get('numero')}, {body.get('bairro', '')}, {body.get('cidade')}, {body.get('estado')}, Brazil"
        
        sqs_payload = {
            "id_usuario": user_id,
            "id_endereco": id_endereco,
            "tipo_usuario": "CLIENTE",
            "endereco_completo": endereco_completo
        }
        
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(sqs_payload)
        )
        logger.info(f"Endereço {id_endereco} enviado para re-geocodificação.")

        return {"statusCode": 200, "body": json.dumps({"message": "Endereço atualizado e em processamento"}, ensure_ascii=False)}

    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Erro ao atualizar: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)}, ensure_ascii=False)}
    finally:
        if conn: conn.close()