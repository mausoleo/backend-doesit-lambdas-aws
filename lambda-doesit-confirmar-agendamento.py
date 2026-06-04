import json
import psycopg2
import os
import logging
import boto3
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("Iniciando confirmação de agendamento...")

    try:
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        body = json.loads(event.get('body', '{}'))
        
        id_prestador = body.get('id_prestador')
        id_tipo_servico = body.get('id_tipo_servico')
        id_endereco = body.get('id_endereco')
        is_for_now = body.get('is_for_now')
        is_woman_filter = body.get('is_woman_filter', False)
        descricao_servico = body.get('descricao_servico', '')
        valor_servico = body.get('valor_servico')
        dt_agendamento_str = body.get('dt_agendamento')

        if not all([id_prestador, id_tipo_servico, id_endereco, valor_servico]):
            return {"statusCode": 400, "body": json.dumps({"error": "Parâmetros obrigatórios ausentes no payload."})}

        if is_for_now:
            dt_agendamento_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif not dt_agendamento_str:
            return {"statusCode": 400, "body": json.dumps({"error": "Data de agendamento obrigatória para serviços futuros."})}

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
            port=5432
        )
        cur = conn.cursor()

        cur.execute("SELECT id_usuario FROM tbl_usuario WHERE sub_cognito = %s", (sub,))
        resultado_cliente = cur.fetchone()
        
        if not resultado_cliente:
            cur.close()
            conn.close()
            return {"statusCode": 404, "body": json.dumps({"error": "Cliente não encontrado na base de dados."})}
            
        id_cliente = resultado_cliente[0]

        query_insert = """
            INSERT INTO tbl_solicitacao_servico (
                id_usuario_cliente, id_usuario_prestador, id_endereco, id_status,
                id_tipo_servico, is_for_now, is_woman_filter, descricao_servico,
                valor_servico, dt_agendamento
            ) VALUES (
                %s, %s, %s, 1, %s, %s, %s, %s, %s, %s
            ) RETURNING id_solicitacao;
        """
        
        cur.execute(query_insert, (
            id_cliente, id_prestador, id_endereco, id_tipo_servico,
            is_for_now, is_woman_filter, descricao_servico, valor_servico, dt_agendamento_str
        ))
        
        id_solicitacao = cur.fetchone()[0]
        conn.commit()
        
        cur.close()
        conn.close()
        logger.info(f"Solicitação {id_solicitacao} gravada com sucesso no status Pendente.")

        sqs = boto3.client('sqs', region_name='sa-east-1')
        queue_url = 'https://sqs.sa-east-1.amazonaws.com/102863741683/sqs-doesit-envia-notificacao'
        
        sqs_payload = {
            "id_solicitacao": id_solicitacao,
            "novo_status_id": 1,
            "id_cliente": id_cliente,
            "id_prestador": id_prestador,
            "executor_id": id_cliente
        }
        
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(sqs_payload)
        )
        logger.info("Mensagem de notificação enviada para a fila SQS com sucesso.")

        return {
            "statusCode": 201,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": json.dumps({
                "mensagem": "Agendamento confirmado com sucesso",
                "id_solicitacao": id_solicitacao
            }, ensure_ascii=False)
        }

    except Exception as e:
        logger.error(f"Erro ao confirmar agendamento: {str(e)}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Erro interno ao salvar a solicitação."})}