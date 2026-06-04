import json
import psycopg2
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        # Autenticação
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        
        # Ajuste para Query Parameter
        params = event.get('queryStringParameters') or {}
        id_pedido = params.get('id')
        
        if not id_pedido:
            return {"statusCode": 400, "body": json.dumps({"error": "ID do pedido não informado"})}

        logger.info(f"Carregando detalhes do pedido {id_pedido} para sub: {sub}")

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
            port=5432, sslmode='verify-full', sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
        )
        cur = conn.cursor()

        # 1. Identificar usuário e papel (mesma lógica de segurança)
        cur.execute('SELECT id_usuario FROM "tbl_usuario" WHERE sub_cognito = %s', (sub,))
        user_result = cur.fetchone()
        if not user_result:
            return {"statusCode": 401, "body": json.dumps({"error": "Usuário não identificado"})}
        
        user_id = user_result[0]
        cur.execute('SELECT 1 FROM "tbl_usuario_prestador" WHERE id_usuario_prestador = %s', (user_id,))
        is_prestador = cur.fetchone() is not None

        # 2. Buscar detalhes
        query = """
            SELECT s.id_solicitacao, ts.nome_servico, u_cliente.nome_completo as cliente, 
                   u_prestador.nome_completo as prestador, s.dt_agendamento, s.valor_servico,
                   e.rua, e.numero, e.bairro, e.cidade, e.estado, s.descricao_servico, st.nome_status, s.id_status
            FROM "tbl_solicitacao_servico" s
            JOIN "tbl_tipo_servico" ts ON s.id_tipo_servico = ts.id_tipo_servico
            JOIN "tbl_status_servico" st ON s.id_status = st.id_status
            JOIN "tbl_usuario" u_cliente ON s.id_usuario_cliente = u_cliente.id_usuario
            JOIN "tbl_usuario" u_prestador ON s.id_usuario_prestador = u_prestador.id_usuario
            JOIN "tbl_endereco" e ON s.id_endereco = e.id_endereco
            WHERE s.id_solicitacao = %s
        """
        cur.execute(query, (id_pedido,))
        row = cur.fetchone()

        if not row:
            return {"statusCode": 404, "body": json.dumps({"error": "Pedido não encontrado"})}

        detalhes = {
            "id": row[0],
            "servico": row[1],
            "cliente": row[2],
            "prestador": row[3],
            "data": row[4].isoformat(),
            "valor": float(row[5]),
            "endereco": f"{row[6]}, {row[7]} - {row[8]}, {row[9]}/{row[10]}",
            "descricao": row[11],
            "status_nome": row[12],
            "status_id": row[13],
            "minha_role": "PRESTADOR" if is_prestador else "CLIENTE"
        }

        logger.info(f"Pedido {id_pedido} carregado. Status: {detalhes['status_nome']}")
        return {"statusCode": 200, "body": json.dumps(detalhes, ensure_ascii=False)}

    except Exception as e:
        logger.error(f"Erro ao carregar detalhes: {str(e)}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Erro interno"}, ensure_ascii=False)}