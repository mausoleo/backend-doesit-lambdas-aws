import json
import psycopg2
import os
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client('sqs', region_name='sa-east-1')
QUEUE_URL = 'https://sqs.sa-east-1.amazonaws.com/102863741683/sqs-doesit-envia-notificacao'

def lambda_handler(event, context):
    try:
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        body = json.loads(event.get('body', '{}'))
        id_pedido = body.get('id_solicitacao')
        novo_status = body.get('novo_status_id')

        if not id_pedido or not novo_status:
            return {"statusCode": 400, "body": json.dumps({"error": "Parâmetros inválidos"})}

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
            port=5432, sslmode='verify-full', sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
        )
        cur = conn.cursor()

        # 1. Identificar usuário e recuperar IDs para o payload
        cur.execute('SELECT id_usuario FROM "tbl_usuario" WHERE sub_cognito = %s', (sub,))
        user_id = cur.fetchone()[0]

        # 2. Validar permissão e buscar dados para o payload da fila
        cur.execute("""
            SELECT id_usuario_cliente, id_usuario_prestador 
            FROM "tbl_solicitacao_servico" WHERE id_solicitacao = %s
        """, (id_pedido,))
        pedido = cur.fetchone()
        
        if not pedido or (user_id != pedido[0] and user_id != pedido[1]):
            return {"statusCode": 403, "body": json.dumps({"error": "Acesso negado"})}

        # 3. Atualizar Status
        query = 'UPDATE "tbl_solicitacao_servico" SET id_status = %s'
        params = [novo_status]
        if novo_status == 2:
            query += ", dt_resposta_solicitacao = CURRENT_TIMESTAMP"
        query += " WHERE id_solicitacao = %s"
        params.append(id_pedido)
        
        cur.execute(query, params)
        conn.commit()
        logger.info(f"DB: Pedido {id_pedido} atualizado para status {novo_status} para usuario {user_id}")
        
        # 4. Enviar mensagem para a fila SQS
        payload = {
            "id_solicitacao": id_pedido,
            "novo_status_id": novo_status,
            "id_cliente": pedido[0],
            "id_prestador": pedido[1],
            "executor_id": user_id
        }
        
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(payload),
            MessageAttributes={
                'TipoEvento': {'StringValue': 'AtualizacaoStatus', 'DataType': 'String'}
            }
        )
        logger.info(f"SQS: Evento enviado para a fila. Payload: {payload}")
        
        cur.close()
        conn.close()
        
        return {"statusCode": 200, "body": json.dumps({"message": "Status atualizado e notificação enfileirada"}, ensure_ascii=False)}

    except Exception as e:
        if 'conn' in locals() and conn: conn.rollback()
        logger.error(f"Erro crítico: {str(e)}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Erro interno no servidor"}, ensure_ascii=False)}