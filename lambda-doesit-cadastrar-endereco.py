import json
import psycopg2
import os
import logging
import boto3

# Configuração global do logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
QUEUE_URL = "https://sqs.sa-east-1.amazonaws.com/102863741683/sqs-doesit-atualiza-lat-lon-fixos"
sqs = boto3.client('sqs')

def lambda_handler(event, context):
    logger.info("Iniciando processo de cadastro de endereço...")

    # 1. Recuperação do sub do token (Autenticação)
    try:
        # Acesso ao sub vindo do Cognito Authorizer no API Gateway
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        logger.info(f"Usuário autenticado: {sub}")
    except (KeyError, TypeError) as e:
        logger.error("Falha ao recuperar sub do token. O autorizador está configurado?")
        return {"statusCode": 401, "body": json.dumps({"error": "Não autorizado"})}

    # 2. Parsing e Validação básica do corpo (Payload)
    try:
        body = json.loads(event.get('body', '{}'))
        required = ['cep', 'rua', 'numero', 'cidade', 'estado']
        if not all(k in body for k in required):
            raise ValueError(f"Campos obrigatórios faltando: {required}")
    except Exception as e:
        logger.error(f"Erro no formato do JSON enviado: {e}")
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}

    # 3. Conexão com o Banco de Dados
    conn = None
    try:
        logger.info("Tentando conexão com RDS...")
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'),
            database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASS'),
            port=5432,
            sslmode='verify-full',
            sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
        )
        cur = conn.cursor()
        logger.info("Conexão estabelecida com sucesso.")

        # 4. Consulta do ID do Usuário
        cur.execute('SELECT id_usuario FROM "tbl_usuario" WHERE sub_cognito = %s', (sub,))
        result = cur.fetchone()
        
        if not result:
            logger.warning(f"Usuário com sub {sub} não encontrado na tabela tbl_usuario.")
            return {"statusCode": 404, "body": json.dumps({"error": "Usuário não registrado no sistema"})}
        
        user_id = result[0]

        # 5. Execução do INSERT
        query = """
            INSERT INTO "tbl_endereco" (id_usuario, cep, rua, numero, bairro, cidade, estado, titulo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id_endereco;
        """
        params = (user_id, body['cep'], body['rua'], body['numero'], 
                  body.get('bairro'), body['cidade'], body['estado'], body.get('titulo', 'Casa'))
        
        cur.execute(query, params)
        new_id = cur.fetchone()[0]
        
        conn.commit()
        cur.close()
        logger.info(f"Endereço {new_id} inserido com sucesso para o usuário {user_id}.")

        endereco_completo = f"{body['rua']}, {body['numero']}, {body.get('bairro', '')}, {body['cidade']}, {body['estado']}, Brazil"

        payload = {
            "id_usuario": user_id,
            "id_endereco": new_id,
            "tipo_usuario": "CLIENTE",
            "endereco_completo": endereco_completo
        }

        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(payload)
        )
        logger.info(f"Endereço {new_id} enviado para geocodificação via SQS.")

        return {
            "statusCode": 201,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": json.dumps({"message": "Endereço cadastrado e em processamento", "id": new_id}, ensure_ascii=False)
        }

    except Exception as e:
        if conn: conn.rollback() # Garante a integridade em caso de erro
        logger.error(f"Erro crítico ao salvar endereço no banco: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Erro interno: {str(e)}"}, ensure_ascii=False)
        }
    finally:
        if conn: conn.close()
        logger.info("Conexão com banco fechada.")