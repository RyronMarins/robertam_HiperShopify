import os
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
load_dotenv()

# Configurações de diretório
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

def configurar_shopify():
    """Configura as credenciais da Shopify"""
    api_key = os.getenv("API_KEY")
    password = os.getenv("PASSWORD")
    shop_name = os.getenv("SHOP_NAME")
    
    return shop_name  # Retorna apenas o nome da loja

def configurar_hiper():
    """Configura as credenciais e conexão com o Hiper"""
    try:
        security_key = os.getenv('SECURITY_KEY')
        if not security_key:
            logging.error("Chave de segurança do Hiper não encontrada")
            return None
            
        url_base = 'https://ms-ecommerce.hiper.com.br/api/v1'
        url_token = f"{url_base}/auth/gerar-token/{security_key}"
        
        headers_token = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {security_key}"
        }
        
        # Tenta gerar o token
        response = requests.get(url_token, headers=headers_token)
        if response.status_code != 200:
            logging.error(f"Erro ao gerar token Hiper: {response.status_code}")
            return None
            
        token = response.json().get('token')
        if not token:
            logging.error("Token não encontrado na resposta do Hiper")
            return None
            
        config = {
            'url_base': url_base,
            'headers': {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        }
        
        # Testa conexão
        test_url = f"{url_base}/produtos/pontoDeSincronizacao"
        test_response = requests.get(test_url, headers=config['headers'])
        if test_response.status_code != 200:
            logging.error(f"Erro ao validar conexão Hiper: {test_response.status_code}")
            return None
            
        logging.info("Conexão com Hiper estabelecida com sucesso")
        return config
        
    except Exception as e:
        logging.error(f"Erro ao configurar Hiper: {str(e)}")
        return None

def setup_logging():
    """Configura o sistema de logging"""
    try:
        # Nome do arquivo de log com timestamp
        log_file = os.path.join(
            LOG_DIR,
            f"sync_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        
        # Configura formato do log
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        
        logging.info(f"Log configurado: {log_file}")
        return True
        
    except Exception as e:
        print(f"Erro ao configurar logging: {str(e)}")
        return False
