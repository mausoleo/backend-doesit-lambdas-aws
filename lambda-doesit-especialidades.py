import json
import os
import logging
import psycopg2
from decimal import Decimal

# Configuração do Logger para monitoramento no CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Classe auxiliar para converter objetos Decimal em float durante a serialização JSON
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    logger.info("=== Iniciando Processamento de Especialidades (Fluxo Novo) ===")
    
    # Identifica o método HTTP da requisição (Ajustado para API Gateway HTTP API)
    http_method = event.get('requestContext', {}).get('http', {}).get('method')
    
    logger.info(f"Método HTTP detectado: {http_method}")

    try:
        # Extração do ID único do Cognito (sub) passado pelo Authorizer JWT
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        logger.info(f"Usuário identificado via sub: {sub}")
        
        # Conectando ao banco de dados PostgreSQL usando as variáveis de ambiente
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'),
            database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASS'),
            port=int(os.environ.get('DB_PORT', 5432))
        )
        cur = conn.cursor()
        
        # Define o schema padrão do seu banco
        cur.execute('SET search_path TO "doesit_schema";')

        # -------------------------------------------------------------------------
        # ROTA: GET /retorna-especialidades
        # -------------------------------------------------------------------------
        if http_method == "GET":
            logger.info("Executando: GET - Buscando especialidades e catálogo geral")
            
            # Query 1: Retorna o id interno do prestador baseado no sub do cognito
            cur.execute('SELECT id_usuario FROM tbl_usuario WHERE sub_cognito = %s;', (sub,))
            usuario_row = cur.fetchone()
            
            if not usuario_row:
                cur.close()
                conn.close()
                logger.warning(f"Usuário com sub {sub} não foi encontrado na tbl_usuario.")
                return {"statusCode": 404, "body": json.dumps({"error": "Prestador não encontrado no sistema."})}
                
            id_prestador = usuario_row[0]

            # Query 2: Especialidades atuais que este prestador atende
            query_atuais = """
                SELECT ts.id_tipo_servico, ts.nome_servico, ps.preco_base
                FROM tbl_prestador_servico ps
                JOIN tbl_tipo_servico ts ON ps.id_tipo_servico = ts.id_tipo_servico
                WHERE ps.id_usuario_prestador = %s
                ORDER BY ts.nome_servico ASC;
            """
            cur.execute(query_atuais, (id_prestador,))
            especialidades_vinculadas = cur.fetchall()
            
            # Mapeia as especialidades atuais retornadas do banco
            lista_atuais = [
                {"id_tipo_servico": r[0], "nome_servico": r[1], "preco_base": r[2]}
                for r in especialidades_vinculadas
            ]
            
            # Query 3: Catálogo completo de serviços ativos no sistema para alimentar o select/dropdown
            query_catalogo = "SELECT id_tipo_servico, nome_servico FROM tbl_tipo_servico ORDER BY nome_servico ASC;"
            cur.execute(query_catalogo)
            catalogo_geral = cur.fetchall()
            
            lista_catalogo = [
                {"id_tipo_servico": r[0], "nome_servico": r[1]}
                for r in catalogo_geral
            ]
            
            cur.close()
            conn.close()
            
            logger.info(f"Sucesso. Retornadas {len(lista_atuais)} especialidades do prestador e {len(lista_catalogo)} serviços do catálogo.")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json; charset=utf-8"},
                "body": json.dumps({
                    "especialidades_vinculadas": lista_atuais,
                    "catalogo_geral_servicos": lista_catalogo
                }, cls=DecimalEncoder, ensure_ascii=False)
            }

        # -------------------------------------------------------------------------
        # ROTA: PUT /salva-especialidades
        # -------------------------------------------------------------------------
        elif http_method == "PUT":
            logger.info("Executando: PUT - Substituindo a lista completa de especialidades")
            
            body = json.loads(event.get('body', '{}'))
            logger.info(f"BODY RECEBIDO NO PUT: {body}")
            # O payload esperado é uma lista de objetos contendo id_tipo_servico e preco_base
            novas_especialidades = body.get('especialidades', [])
            
            # 1. Busca o ID interno do prestador
            cur.execute('SELECT id_usuario FROM tbl_usuario WHERE sub_cognito = %s;', (sub,))
            usuario_row = cur.fetchone()
            
            if not usuario_row:
                cur.close()
                conn.close()
                return {"statusCode": 404, "body": json.dumps({"error": "Prestador não encontrado no sistema."})}
                
            id_prestador = usuario_row[0]
            
            try:
                # 2. Inicia uma transação explícita no PostgreSQL
                cur.execute("BEGIN;")
                
                # 3. Limpa TODAS as especialidades anteriores do prestador
                logger.info(f"Limpando especialidades antigas do prestador ID: {id_prestador}")
                cur.execute('DELETE FROM tbl_prestador_servico WHERE id_usuario_prestador = %s;', (id_prestador,))
                
                # 4. Se a lista enviada não estiver vazia, realiza a inserção em lote (Bulk Insert)
                if novas_especialidades:
                    logger.info(f"Inserindo {len(novas_especialidades)} novas especialidades escolhidas na tela...")
                    
                    query_insert = """
                        INSERT INTO tbl_prestador_servico (id_usuario_prestador, id_tipo_servico, preco_base)
                        VALUES (%s, %s, %s);
                    """
                    
                    # Prepara os parâmetros para execução em lote
                    valores_lote = [
                        (id_prestador, item['id_tipo_servico'], item['preco_base'])
                        for item in novas_especialidades
                    ]
                    
                    cur.executemany(query_insert, valores_lote)
                
                # 5. Salva permanentemente as alterações se tudo correu bem
                conn.commit()
                logger.info("Transação concluída e gravada com sucesso no banco de dados!")
                
            except Exception as tx_error:
                # Caso ocorra qualquer erro em alguma das inserções, desfaz tudo
                conn.rollback()
                logger.error(f"Erro na transação do banco. Rollback aplicado. Detalhes: {str(tx_error)}")
                raise tx_error
            
            cur.close()
            conn.close()
            
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "Alterações salvas com sucesso!"})
            }

        # Resposta caso caia algum método não configurado no API Gateway
        else:
            logger.warning(f"Método {http_method} não suportado.")
            return {
                "statusCode": 405,
                "body": json.dumps({"error": f"Método {http_method} não permitido."})
            }

    except Exception as e:
        logger.error(f"Erro crítico no processamento: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Erro interno ao processar requisição de especialidades."})
        }