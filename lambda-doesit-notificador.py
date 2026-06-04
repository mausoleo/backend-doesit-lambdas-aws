import json
import psycopg2
import os
import logging
import boto3

# Configuração de Log
logger = logging.getLogger()
logger.setLevel(logging.INFO)

ses = boto3.client('ses', region_name='sa-east-1')

def get_db_connection():
    logger.info("Tentando conectar ao banco de dados...")
    return psycopg2.connect(
        host=os.environ.get('DB_HOST'), database=os.environ.get('DB_NAME'),
        user=os.environ.get('DB_USER'), password=os.environ.get('DB_PASS'),
        port=5432, sslmode='verify-full', sslrootcert=os.path.join(os.getcwd(), 'global-bundle.pem')
    )

def gerar_textos_notificacao(status_id, nome_servico, nome_status, is_cliente):
    """
    Retorna o Título e a Mensagem customizados baseados no status e no destinatário.
    """
    if status_id == 1:  # PENDENTE (Nova Solicitação)
        if is_cliente:
            return f"Pedido Enviado: {nome_servico}", f"Seu pedido de {nome_servico} foi enviado com sucesso e está aguardando a confirmação do prestador."
        else:
            return f"Nova Solicitação de Serviço: {nome_servico}", f"Você recebeu um novo pedido de {nome_servico}! Acesse o aplicativo DoesIt para visualizar os detalhes e confirmar o agendamento."
            
    elif status_id == 2:  # AGENDADO (Confirmado pelo prestador)
        if is_cliente:
            return f"Agendamento Confirmado: {nome_servico}", f"Boa notícia! O prestador confirmou o seu pedido de {nome_servico}."
        else:
            return f"Serviço Confirmado: {nome_servico}", f"Você confirmou o agendamento para o serviço de {nome_servico}."
            
    elif status_id == 3:  # CONCLUIDO
        if is_cliente:
            return f"Serviço Concluído: {nome_servico}", f"O seu serviço de {nome_servico} foi marcado como concluído. Não se esqueça de avaliar o prestador!"
        else:
            return f"Serviço Finalizado: {nome_servico}", f"Você marcou o serviço de {nome_servico} como concluído. Bom trabalho!"
            
    elif status_id == 4:  # CANCELADO
        if is_cliente:
            return f"Pedido Cancelado: {nome_servico}", f"O pedido de {nome_servico} foi cancelado."
        else:
            return f"Serviço Cancelado: {nome_servico}", f"A solicitação para o serviço de {nome_servico} foi cancelada."
            
    # Fallback de segurança para status desconhecidos
    return f"Atualização do Pedido: {nome_servico}", f"O status do seu pedido de {nome_servico} foi alterado para: {nome_status}."

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            msg = json.loads(record['body'])
            id_sol = msg['id_solicitacao']
            novo_status_id = msg['novo_status_id']
            id_cliente = msg['id_cliente']
            id_prestador = msg['id_prestador']
            
            logger.info(f"--- INÍCIO: Processando pedido {id_sol} | Status: {novo_status_id} ---")
            
            conn = get_db_connection()
            cur = conn.cursor()
            
            # 1. Buscar nome do serviço e status
            cur.execute('''
                SELECT ts.nome_servico, s.nome_status
                FROM "tbl_solicitacao_servico" sol
                JOIN "tbl_tipo_servico" ts ON ts.id_tipo_servico = sol.id_tipo_servico
                JOIN "tbl_status_servico" s ON s.id_status = %s
                WHERE sol.id_solicitacao = %s
            ''', (novo_status_id, id_sol))
            
            servico_info = cur.fetchone()
            if not servico_info:
                logger.warning(f"Dados do serviço não encontrados para a solicitação {id_sol}")
                continue
                
            nome_servico, nome_status = servico_info
            
            # 2. Buscar dados (Nome e Email) do Cliente e do Prestador de uma vez só
            cur.execute('''
                SELECT u.id_usuario, u.nome_completo, e.email_usuario
                FROM "tbl_usuario" u
                JOIN "tbl_email_usuario" e ON u.id_usuario = e.id_usuario
                WHERE u.id_usuario IN (%s, %s)
            ''', (id_cliente, id_prestador))
            
            usuarios_data = cur.fetchall()
            
            # Mapear os resultados para facilitar a separação
            dados_cliente = next((u for u in usuarios_data if u[0] == id_cliente), None)
            dados_prestador = next((u for u in usuarios_data if u[0] == id_prestador), None)
            
            # Estrutura para iterar e notificar ambos
            destinatarios = [
                {"tipo": "Cliente", "dados": dados_cliente, "is_cliente": True},
                {"tipo": "Prestador", "dados": dados_prestador, "is_cliente": False}
            ]
            
            for dest in destinatarios:
                if not dest["dados"]:
                    logger.warning(f"Dados não encontrados para o {dest['tipo']} (ID na payload não bateu com tbl_usuario)")
                    continue
                    
                id_usuario, nome, email = dest["dados"]
                
                # Gerar textos com base no perfil (Cliente ou Prestador)
                titulo, mensagem_texto = gerar_textos_notificacao(novo_status_id, nome_servico, nome_status, dest["is_cliente"])
                
                logger.info(f"Processando notificação para {dest['tipo']}: {nome} ({email})")
                
                # 3. Registrar na tbl_notificacoes
                cur.execute(
                    'INSERT INTO "tbl_notificacoes" (id_usuario, id_solicitacao, titulo, mensagem) VALUES (%s, %s, %s, %s)',
                    (id_usuario, id_sol, titulo, mensagem_texto)
                )
                
                # 4. Enviar E-mail Elegante (HTML) via SES
                html_body = f"""
                <html>
                    <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
                        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
                            <div style="background-color: #2c3e50; padding: 20px; text-align: center;">
                                <h2 style="color: #ffffff; margin: 0;">DoesIt Notificações</h2>
                            </div>
                            <div style="padding: 30px;">
                                <h3 style="color: #2c3e50;">Olá, {nome}!</h3>
                                <p>{mensagem_texto}</p>
                                <div style="background-color: #f4f6f8; padding: 15px; border-radius: 5px; margin-top: 20px;">
                                    <p style="margin: 0;"><strong>Serviço:</strong> {nome_servico}</p>
                                    <p style="margin: 5px 0 0 0;"><strong>Status Atualizado:</strong> <span style="color: #d35400; font-weight: bold;">{nome_status}</span></p>
                                </div>
                            </div>
                            <div style="background-color: #f9f9f9; padding: 15px; text-align: center; font-size: 12px; color: #7f8c8d;">
                                <p style="margin: 0;">Equipe DoesIt &copy; 2026. Este é um e-mail automático, por favor não responda.</p>
                            </div>
                        </div>
                    </body>
                </html>
                """
                
                ses.send_email(
                    Source='doesittcc@gmail.com',
                    Destination={'ToAddresses': [email]},
                    Message={
                        'Subject': {'Data': titulo},
                        'Body': {'Html': {'Data': html_body}, 'Text': {'Data': mensagem_texto}}
                    }
                )
                logger.info(f"E-mail enviado e notificação salva para {dest['tipo']}.")
            
            # Commit de todas as inserções na tabela de notificações de uma vez
            conn.commit()
            
            cur.close()
            conn.close()
            logger.info(f"--- FIM: Processamento do pedido {id_sol} concluído ---")
            
        except Exception as e:
            logger.error(f"FALHA NO PROCESSAMENTO DA MENSAGEM: {str(e)}", exc_info=True)
            continue