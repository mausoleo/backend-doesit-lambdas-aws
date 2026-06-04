import json
import psycopg2
import os
import logging

# Configuração do logger para monitoramento
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("Iniciando busca de notificações...")

    # 1. Autenticação e extração do sub
    try:
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        logger.info(f"Usuário autenticado: {sub}")
    except (KeyError, TypeError) as e:
        logger.error("Erro ao autenticar usuário via token.")
        return {"statusCode": 401, "body": json.dumps({"error": "Não autorizado"})}

    conn = None
    try:
        # 2. Conexão ao banco
        logger.info("Conectando ao banco de dados...")
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'),
            database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASS'),
            port=5432, sslmode='verify-full', 
            sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
        )
        cur = conn.cursor()

        # 3. Consulta das notificações ordenadas
        # Usamos JOIN para garantir que a notificação pertence ao id_usuario correto
        query = """
            SELECT n.titulo, n.mensagem, n.dt_notificacao
            FROM "tbl_notificacoes" n
            JOIN "tbl_usuario" u ON n.id_usuario = u.id_usuario
            WHERE u.sub_cognito = %s
            ORDER BY n.dt_notificacao DESC;
        """
        
        cur.execute(query, (sub,))
        rows = cur.fetchall()
        logger.info(f"Encontradas {len(rows)} notificações para o usuário.")

        # 4. Formatação do payload (convertendo datetime para string para evitar erros de JSON)
        notificacoes = [{
            "titulo": r[0],
            "mensagem": r[1],
            "dt_notificacao": r[2].isoformat() if r[2] else None
        } for r in rows]

        cur.close()
        conn.close()

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": json.dumps({"notificacoes": notificacoes}, ensure_ascii=False)
        }

    except Exception as e:
        logger.error(f"Erro crítico ao buscar notificações: {str(e)}", exc_info=True)
        return {
            "statusCode": 500, 
            "body": json.dumps({"error": "Erro ao carregar notificações"}, ensure_ascii=False)
        }
    finally:
        if conn: conn.close()