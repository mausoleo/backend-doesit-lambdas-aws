import json
import psycopg2
import os
import logging

# Configuração do log
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def mask_cpf(cpf):
    # CPF original deve ter 11 dígitos. Ex: 12345678900 -> 123.***.***-00
    if not cpf or len(cpf) < 11:
        return "***.***.***-**"
    return f"{cpf[:3]}.***.***-{cpf[-2:]}"

def format_phone(phone):
    # Assume que o telefone vem apenas números. Ex: 11999999999 -> (11) 99999-9999
    if not phone or len(phone) < 10:
        return phone
    return f"({phone[:2]}) {phone[2:7]}-{phone[7:]}"

def lambda_handler(event, context):
    # Pega o sub do autorizador JWT do API Gateway
    # sub = event['requestContext']['authorizer']['claims']['sub']
    sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
    logger.info(f"Buscando dados para o sub: {sub}")

    db_host = os.environ.get('DB_HOST')
    db_name = os.environ.get('DB_NAME')
    db_user = os.environ.get('DB_USER')
    db_pass = os.environ.get('DB_PASS')
    cert_path = os.path.join(os.getcwd(), 'global-bundle.pem')
    
    conn = None
    try:
        conn = psycopg2.connect(host=db_host, database=db_name, user=db_user, password=db_pass, 
                                port=5432, sslmode='verify-full', sslrootcert=cert_path)
        cur = conn.cursor()
        
        # 1. Buscar dados base do usuário
        cur.execute("""
            SELECT u.id_usuario, u.nome_completo, u.cpf, u.dt_nascimento, e.email_usuario, t.telefone_usuario, u.id_tipo_genero
            FROM tbl_usuario u
            LEFT JOIN tbl_email_usuario e ON u.id_usuario = e.id_usuario
            LEFT JOIN tbl_telefone_usuario t ON u.id_usuario = t.id_usuario
            WHERE u.sub_cognito = %s;
        """, (sub,))
        
        row = cur.fetchone()
        if not row:
            logger.warning(f"Usuário não encontrado: {sub}")
            return {'statusCode': 404, 'body': json.dumps({'message': 'Usuário não encontrado'})}
            
        user_id, nome, cpf, dt_nasc, email, telefone, genero = row
        
        # 2. Verificar se é PRESTADOR ou CLIENTE
        cur.execute("SELECT 1 FROM tbl_usuario_prestador WHERE id_usuario_prestador = %s;", (user_id,))
        is_prestador = cur.fetchone() is not None
        
        # 3. Montar payload com formatação
        response_data = {
            "nome": nome,
            "cpf": mask_cpf(cpf),
            "data_nascimento": dt_nasc.strftime('%d/%m/%Y'),
            "email": email,
            "telefone": format_phone(telefone),
            "tipo": "PRESTADOR" if is_prestador else "CLIENTE",
            "genero": genero
        }
        
        logger.info(f"Dados recuperados com sucesso para o usuário {user_id}")
        cur.close()
        conn.close()
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(response_data)
        }
        
    except Exception as e:
        logger.error(f"Erro ao buscar dados: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'message': 'Erro interno no servidor'})}