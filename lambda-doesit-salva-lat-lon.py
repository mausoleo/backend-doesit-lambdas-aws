import json
import psycopg2
import os
import logging
import h3  

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuração da conexão
db_host = os.environ.get('DB_HOST')
db_name = os.environ.get('DB_NAME')
db_user = os.environ.get('DB_USER')
db_pass = os.environ.get('DB_PASS')

def get_db_connection():
    return psycopg2.connect(
        host=db_host, database=db_name, user=db_user, password=db_pass, port=5432
    )

def lambda_handler(event, context):
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        for record in event['Records']:
            body = json.loads(record['body'])
            endereco_id = body['id_endereco'] 
            
            # Conversão explícita para float para evitar o erro de tipagem
            try:
                lat = float(body['lat'])
                lon = float(body['lon'])
                
                # Cálculo do índice H3 (Resolução 8)
                h3_index = h3.latlng_to_cell(lat, lon, 8)
                
            except (ValueError, TypeError) as e:
                logger.error(f"Erro de formato nos dados geográficos para id_endereco {endereco_id}: {e}")
                continue 

            cur.execute("""
                UPDATE "doesit_schema"."tbl_endereco" 
                SET "latitude" = %s, "longitude" = %s, "h3_index" = %s
                WHERE "id_endereco" = %s
            """, (lat, lon, h3_index, endereco_id))
            
            if cur.rowcount == 0:
                logger.warning(f"Nenhum endereço encontrado para o id_endereco {endereco_id}")
            else:
                logger.info(f"Coordenadas e H3 ({h3_index}) atualizados com sucesso para o id_endereco {endereco_id}")
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao atualizar coordenadas e H3 no banco: {e}")
        raise e
    finally:
        cur.close()
        conn.close()
    
    return {"status": "success"}