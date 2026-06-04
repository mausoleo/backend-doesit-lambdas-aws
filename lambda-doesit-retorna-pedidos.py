import json
import psycopg2
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("Iniciando busca de pedidos...")

    try:
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        # Captura status opcional via query string: /pedidos?status=AGENDADO
        params = event.get('queryStringParameters') or {}
        status_filtro = params.get('status')
        
        logger.info(f"Usuário {sub} buscando pedidos. Filtro status: {status_filtro}")

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
            port=5432, sslmode='verify-full', 
            sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
        )
        cur = conn.cursor()

        # 1. Identificar se o usuário é PRESTADOR ou CLIENTE
        cur.execute('SELECT id_usuario FROM "tbl_usuario" WHERE sub_cognito = %s', (sub,))
        user_id = cur.fetchone()[0]
        
        cur.execute('SELECT 1 FROM "tbl_usuario_prestador" WHERE id_usuario_prestador = %s', (user_id,))
        is_prestador = cur.fetchone() is not None
        
        # 2. Query Dinâmica
        # Relacionamos com tbl_status_servico para trazer o NOME do status
        base_query = """
            SELECT s.id_solicitacao, ts.nome_servico, u_outro.nome_completo, s.dt_agendamento, s.valor_servico, st.nome_status
            FROM "tbl_solicitacao_servico" s
            JOIN "tbl_tipo_servico" ts ON s.id_tipo_servico = ts.id_tipo_servico
            JOIN "tbl_status_servico" st ON s.id_status = st.id_status
            JOIN "tbl_usuario" u_outro ON {} = u_outro.id_usuario
            WHERE {} = %s
        """.format(
            "s.id_usuario_cliente" if is_prestador else "s.id_usuario_prestador",
            "s.id_usuario_prestador" if is_prestador else "s.id_usuario_cliente"
        )
        
        params = [user_id]
        
        if status_filtro:
            base_query += " AND st.nome_status = %s"
            params.append(status_filtro)
            
        base_query += " ORDER BY s.dt_agendamento DESC;"
        
        cur.execute(base_query, params)
        rows = cur.fetchall()
        
        # 3. Formatação
        pedidos = [{
            "id": r[0],           
            "servico": r[1],
            "nome_parte": r[2],
            "data": r[3].isoformat(),
            "valor": float(r[4]),
            "status": r[5]
        } for r in rows]

        cur.close()
        conn.close()
        logger.info(f"Retornando {len(pedidos)} pedidos.")

        return {
            "statusCode": 200,
            "body": json.dumps({"pedidos": pedidos}, ensure_ascii=False)
        }

    except Exception as e:
        logger.error(f"Erro na busca de pedidos: {str(e)}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Erro interno"})}