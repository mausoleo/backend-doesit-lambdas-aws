import json
import psycopg2
import os
import logging
import boto3

# Configuração do log
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    user_attrs = event['request']['userAttributes']
    sub = event['userName']

    logger.info(f"Iniciando processamento para o sub: {sub}")

    # Mapeamento de atributos
    tipo_usuario = user_attrs.get('custom:tipo_usuario', 'CLIENTE')
    nome = user_attrs.get('name')
    cpf = user_attrs.get('custom:cpf')
    dt_nasc = user_attrs.get('birthdate')
    genero_id = int(user_attrs.get('custom:id_genero', 1))

    cep = user_attrs.get('address', '00000-000')
    rua = user_attrs.get('custom:rua')
    num = user_attrs.get('custom:numero')
    bairro = user_attrs.get('custom:bairro')
    cidade = user_attrs.get('custom:cidade')
    estado = user_attrs.get('custom:estado')
    email = user_attrs.get('email')
    telefone = user_attrs.get('custom:telefone')

    db_host = os.environ.get('DB_HOST')
    db_name = os.environ.get('DB_NAME')
    db_user = os.environ.get('DB_USER')
    db_pass = os.environ.get('DB_PASS')
    cert_path = os.path.join(os.getcwd(), 'global-bundle.pem')
    
    conn = None
    sqs = boto3.client('sqs')
    QUEUE_URL = "https://sqs.sa-east-1.amazonaws.com/102863741683/sqs-doesit-atualiza-lat-lon-fixos"

    try:
        conn = psycopg2.connect(host=db_host, database=db_name, user=db_user, password=db_pass,
                                port=5432, sslmode='verify-full', sslrootcert=cert_path)
        cur = conn.cursor()

        # 1. Inserção Usuário
        cur.execute("""
            INSERT INTO tbl_usuario (sub_cognito, nome_completo, cpf, dt_nascimento, id_tipo_genero)
            VALUES (%s, %s, %s, %s, %s) RETURNING id_usuario;
        """, (sub, nome, cpf, dt_nasc, genero_id))
        user_id = cur.fetchone()[0]

        # 2. Lógica Cliente/Prestador
        if tipo_usuario == 'PRESTADOR':
            cur.execute("INSERT INTO tbl_usuario_prestador (id_usuario_prestador) VALUES (%s);", (user_id,))
        else:
            cur.execute("INSERT INTO tbl_usuario_cliente (id_usuario_cliente) VALUES (%s);", (user_id,))

        # 3. Inserção Endereço com captura de ID
        cur.execute("""
            INSERT INTO tbl_endereco (id_usuario, cep, rua, numero, bairro, cidade, estado)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id_endereco;
        """, (user_id, cep, rua, num, bairro, cidade, estado))
        endereco_id = cur.fetchone()[0]

        # 4. Outras inserções
        cur.execute("INSERT INTO tbl_email_usuario (id_usuario, email_usuario) VALUES (%s, %s);", (user_id, email))
        if telefone:
            cur.execute("INSERT INTO tbl_telefone_usuario (id_usuario, telefone_usuario) VALUES (%s, %s);", (user_id, telefone))

        conn.commit()
        logger.info(f"Dados salvos. Enviando endereço {endereco_id} para fila SQS.")

        # 5. Envio para o SQS (Dispara a geocodificação assíncrona)
        endereco_completo = f"{rua}, {num}, {bairro}, {cidade}, {estado}, Brazil"
        sqs_payload = {
            "id_usuario": user_id,
            "id_endereco": endereco_id,
            "tipo_usuario": tipo_usuario,
            "endereco_completo": endereco_completo
        }
        
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(sqs_payload)
        )

        cur.close()
        conn.close()

        event['response']['autoConfirmUser'] = True
        event['response']['autoVerifyEmail'] = True
        return event

    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Erro crítico: {str(e)}")
        raise e
    finally:
        if conn: conn.close()