import json
import psycopg2
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("Iniciando preparação da tela de Solicitação...")

    try:
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        logger.info(f"Carregando contexto para sub: {sub}")

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
            port=5432, sslmode='verify-full', 
            sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
        )
        cur = conn.cursor()

        # 1. Buscar Gênero do Usuário
        cur.execute("""
            SELECT g.nome_genero 
            FROM tbl_usuario u 
            JOIN tbl_tipo_genero g ON u.id_tipo_genero = g.id_tipo_genero 
            WHERE u.sub_cognito = %s
        """, (sub,))
        genero = cur.fetchone()[0]

        # 2. Buscar Endereços
        cur.execute("""
            SELECT id_endereco, titulo, rua, numero, cidade 
            FROM tbl_endereco 
            WHERE id_usuario = (SELECT id_usuario FROM tbl_usuario WHERE sub_cognito = %s)
            ORDER BY is_favorite DESC;
        """, (sub,))
        enderecos = [{"id": r[0], "titulo": r[1], "formatado": f"{r[2]}, {r[3]}, {r[4]}"} for r in cur.fetchall()]

        # 3. Buscar Tipos de Serviço
        cur.execute("SELECT id_tipo_servico, nome_servico FROM tbl_tipo_servico ORDER BY nome_servico ASC;")
        servicos = [{"id": r[0], "nome": r[1]} for r in cur.fetchall()]

        cur.close()
        conn.close()

        # 4. Montar Payload (Regra: filtro de mulher só aparece se gênero for 'Feminino')
        response_data = {
            "genero": genero,
            "mostrar_filtro_mulheres": (genero == 'Feminino'),
            "enderecos": enderecos,
            "servicos": servicos
        }

        logger.info("Dados de preparação carregados com sucesso.")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": json.dumps(response_data, ensure_ascii=False)
        }

    except Exception as e:
        logger.error(f"Erro ao preparar tela: {str(e)}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Erro interno ao carregar dados da tela"})}