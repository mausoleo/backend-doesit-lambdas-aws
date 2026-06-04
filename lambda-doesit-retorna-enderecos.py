import json
import psycopg2
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        # 1. Autenticação
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        
        # 2. Verifica se veio algum ID na Query String
        query_params = event.get('queryStringParameters')
        id_endereco = query_params.get('id') if query_params else None
        
        logger.info(f"Busca iniciada para o usuário {sub}. Filtro ID: {id_endereco}")

    except (KeyError, TypeError):
        return {"statusCode": 401, "body": json.dumps({"error": "Não autorizado"})}

    conn = None
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
            port=5432, sslmode='verify-full', 
            sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
        )
        cur = conn.cursor()

        # 3. Query Dinâmica
        query = """
            SELECT id_endereco, titulo, cep, rua, numero, bairro, cidade, estado, is_favorite
            FROM "tbl_endereco"
            WHERE id_usuario = (SELECT id_usuario FROM "tbl_usuario" WHERE sub_cognito = %s)
        """
        params = [sub]
        
        # Se um ID foi enviado, adicionamos a restrição na consulta
        if id_endereco:
            query += " AND id_endereco = %s"
            params.append(id_endereco)
            
        query += " ORDER BY is_favorite DESC, dt_criacao DESC;"
        
        cur.execute(query, params)
        rows = cur.fetchall()

        # 4. Montagem da resposta
        enderecos = [{
            "id": r[0],
            "titulo": r[1],
            "cep": r[2],
            "rua": r[3],
            "numero": r[4],
            "bairro": r[5],
            "cidade": r[6],
            "estado": r[7],
            "is_favorite": r[8]
        } for r in rows]

        cur.close()
        conn.close()

        logger.info(f'sucesso')
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": json.dumps({"enderecos": enderecos}, ensure_ascii=False)
        }

    except Exception as e:
        logger.error(f"Erro ao buscar endereços: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": "Erro interno"}, ensure_ascii=False)}