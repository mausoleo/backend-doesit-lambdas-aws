import json
import psycopg2
import os
import logging
import h3
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("Iniciando busca de profissionais qualificados...")

    try:
        sub = event['requestContext']['authorizer']['jwt']['claims']['sub']
        
        # Recebendo o payload via POST (Body)
        body = json.loads(event.get('body', '{}'))
        
        id_servico = body.get('id_servico')
        id_endereco = body.get('id_endereco')
        filtro_mulher = body.get('filtro_mulher', False)
        is_for_now = body.get('is_for_now', True)
        descricao_servico = body.get('descricao_servico', '')
        agendamento = body.get('agendamento', {})

        if not id_servico or not id_endereco:
            return {"statusCode": 400, "body": json.dumps({"error": "Parâmetros id_servico e id_endereco são obrigatórios."})}

        # Validação e montagem de timestamp para agendamento
        dt_agendamento_str = None
        if not is_for_now:
            data = agendamento.get('data')
            horario = agendamento.get('horario')
            if not data or not horario:
                return {"statusCode": 400, "body": json.dumps({"error": "Data e horário são obrigatórios para agendamentos."})}
            dt_agendamento_str = f"{data} {horario}:00"

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
            port=5432
        )
        cur = conn.cursor()

        # 1. Buscar H3 Index do Endereço do Cliente
        cur.execute("""
            SELECT h3_index 
            FROM tbl_endereco 
            WHERE id_endereco = %s AND id_usuario = (SELECT id_usuario FROM tbl_usuario WHERE sub_cognito = %s)
        """, (id_endereco, sub))
        
        resultado_endereco = cur.fetchone()
        if not resultado_endereco or not resultado_endereco[0]:
            cur.close()
            conn.close()
            return {"statusCode": 400, "body": json.dumps({"error": "Endereço do cliente não encontrado ou sem H3 Index mapeado."})}
        
        h3_cliente = resultado_endereco[0]
        logger.info(f"H3 do Cliente encontrado: {h3_cliente}. Iniciando varredura k-ring...")

        profissionais_map = {}
        
        # 2. Loop de expansão do H3 (k-ring de 0 a 5)
        for k in range(0, 6):
            hexagonos = list(h3.grid_disk(h3_cliente, k))
            logger.info(f"Testando anel K={k} com {len(hexagonos)} hexágonos...")
            
            # Montagem dinâmica das regras de JOIN e WHERE baseadas no payload
            join_clause = ""
            where_clauses = ["ps.id_tipo_servico = %(id_servico)s"]
            
            if is_for_now:
                # Lógica imediata: olha pra onde o prestador está agora
                where_clauses.append("up.h3_index = ANY(%(hexagonos)s)")
                where_clauses.append("up.disponibilidade = TRUE")
            else:
                # Lógica agendada: olha pra casa do prestador e checa agenda
                join_clause = "JOIN tbl_endereco end_p ON u.id_usuario = end_p.id_usuario"
                where_clauses.append("end_p.h3_index = ANY(%(hexagonos)s)")
                where_clauses.append("""
                    NOT EXISTS (
                        SELECT 1 FROM tbl_solicitacao_servico ss 
                        WHERE ss.id_usuario_prestador = ps.id_usuario_prestador 
                        AND ss.dt_agendamento = %(dt_agendamento)s 
                        AND ss.id_status IN (1, 2) 
                    )
                """)

            if filtro_mulher:
                where_clauses.append("u.id_tipo_genero = (SELECT id_tipo_genero FROM tbl_tipo_genero WHERE nome_genero = 'Feminino')")

            where_sql = " AND ".join(where_clauses)

            query = f"""
                SELECT 
                    u.id_usuario, 
                    u.nome_completo, 
                    up.media_avaliacao, 
                    (SELECT COUNT(*) FROM tbl_solicitacao_servico WHERE id_usuario_prestador = ps.id_usuario_prestador AND id_status = 3) as total_servicos,
                    ps.preco_base,
                    (SELECT ARRAY_AGG(nome_servico) FROM (
                        SELECT ts.nome_servico, (ts.id_tipo_servico = %(id_servico)s) as is_requested
                        FROM tbl_prestador_servico ps2 
                        JOIN tbl_tipo_servico ts ON ps2.id_tipo_servico = ts.id_tipo_servico 
                        WHERE ps2.id_usuario_prestador = ps.id_usuario_prestador
                        ORDER BY is_requested DESC, ts.nome_servico ASC
                        LIMIT 3
                    ) as sub) as lista_servicos
                FROM tbl_prestador_servico ps
                JOIN tbl_usuario u ON ps.id_usuario_prestador = u.id_usuario
                JOIN tbl_usuario_prestador up ON ps.id_usuario_prestador = up.id_usuario_prestador
                {join_clause}
                WHERE {where_sql};
            """
            
            cur.execute(query, {
                'id_servico': id_servico,
                'hexagonos': hexagonos,
                'dt_agendamento': dt_agendamento_str
            })
            
            resultados = cur.fetchall()
            logger.info(f"Anel K={k} encontrou {len(resultados)} possíveis candidatos.")
            
            # 3. Mapeamento e construção do payload auxiliar para o app
            for r in resultados:
                u_id = r[0]
                preco_base = float(r[4]) if r[4] else 0.0

                if u_id not in profissionais_map and len(profissionais_map) < 5:
                    profissionais_map[u_id] = {
                        "id_prestador": u_id,
                        "nome": r[1], 
                        "nota": float(r[2]) if r[2] else 0.0, 
                        "total_servicos": r[3] or 0,
                        "valor": preco_base, 
                        "servicos_que_faz": r[5],
                        "dados_solicitacao": {
                            "id_tipo_servico": id_servico,
                            "id_endereco": id_endereco,
                            "is_for_now": is_for_now,
                            "is_woman_filter": filtro_mulher,
                            "descricao_servico": descricao_servico,
                            "dt_agendamento": dt_agendamento_str,
                            "valor_servico": preco_base
                        }
                    }
            
            if len(profissionais_map) >= 5:
                logger.info("Limite de 5 prestadores atingido. Encerrando expansão do k-ring.")
                break

        cur.close()
        conn.close()
        
        logger.info(f"Busca concluída. {len(profissionais_map)} prestadores finais retornados.")
        
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": json.dumps({"profissionais": list(profissionais_map.values())}, ensure_ascii=False)
        }

    except Exception as e:
        logger.error(f"Erro ao buscar profissionais: {str(e)}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Erro interno no processamento da busca"})}