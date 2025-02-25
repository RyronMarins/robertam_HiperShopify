import os
import json
import time
import logging
import requests
import unicodedata
import re
import sys
from datetime import datetime, timedelta
import shopify
from shopify.base import ShopifyConnection
from shopify.resources import *  # Importa todos os recursos
from shopify.session import ValidationException as ShopifyValidationError
from config import (
    configurar_shopify,
    configurar_hiper,
    setup_logging,
    LOG_DIR,
    BASE_DIR
)

# Cache para produtos e estoque
_cache = {
    'produtos_hiper': {},
    'produtos_shopify': {},
    'last_update_hiper': datetime.min,
    'last_update_shopify': datetime.min
}

# Métricas de performance
_metrics = {
    'start_time': None,
    'api_calls': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'retries': 0,
    'errors': [],
    'timing': {
        'shopify_calls': [],
        'hiper_calls': [],
        'mapping_operations': []
    }
}

class PerformanceMetric:
    """Context manager para medir performance de operações"""
    def __init__(self, operation_name):
        self.operation_name = operation_name
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        _metrics['timing'][self.operation_name].append({
            'duration': duration,
            'timestamp': datetime.now().isoformat(),
            'error': str(exc_val) if exc_val else None
        })
        if exc_val:
            _metrics['errors'].append({
                'operation': self.operation_name,
                'error': str(exc_val),
                'timestamp': datetime.now().isoformat()
            })

def normalizar_nome(nome):
    """Normaliza o nome do produto para comparação"""
    if not nome:
        return ""
        
    # Correções específicas de caracteres especiais
    nome = nome.replace("Cal?a", "Calca")
    nome = nome.replace("Calça", "Calca")
    nome = nome.replace("Ca?a", "Calca")
    nome = nome.replace("Bone", "Bone")  # Mantém consistência
    nome = nome.replace("jacquard", "jaquard")  # Normaliza variações de grafia
    nome = nome.replace("jaquard", "jaquard")  # Garante consistência
    
    # Remove sufixos e informações adicionais
    sufixos_para_remover = [
        " + PAC",
        " PAC",
        " - Tamanho Unico",
        " - Kit bone + ecobag",
        " - Kit",
        " - ",
    ]
    
    for sufixo in sufixos_para_remover:
        if nome.endswith(sufixo):
            nome = nome[:-len(sufixo)]
    
    # Remove caracteres especiais e acentos
    nome = unicodedata.normalize('NFKD', nome).encode('ASCII', 'ignore').decode('ASCII')
    
    # Converte para minúsculas
    nome = nome.lower()
    
    # Remove espaços extras e caracteres especiais
    nome = ' '.join(filter(None, nome.split()))
    
    # Remove caracteres não alfanuméricos (exceto espaços)
    nome = ''.join(c for c in nome if c.isalnum() or c.isspace())
    
    # Remove espaços extras entre palavras
    nome = ' '.join(nome.split())
    
    return nome

def mapear_tamanho(tamanho):
    """Mapeia diferentes formatos de tamanho para um formato padrão"""
    if not tamanho:
        return None
        
    # Normaliza o tamanho para comparação
    tamanho = str(tamanho).upper().strip()
    
    # Mapeamento de tamanhos
    mapeamento = {
        # Tamanhos numéricos
        '34': '34', '36': '36', '38': '38', '40': '40', '42': '42', '44': '44', '46': '46',
        # Tamanhos literais
        'P': 'P', 'M': 'M', 'G': 'G', 'GG': 'GG',
        # Variações
        'PP': 'PP', 'XG': 'XG', 'XGG': 'XGG',
        # Mapeamento de números para letras (se necessário)
        '1P': 'P', '1M': 'M', '1G': 'G',
        '2P': 'P', '2M': 'M', '2G': 'G',
        '3P': 'P', '3M': 'M', '3G': 'G',
        # Tamanho único
        'U': 'U', 'UNICO': 'U', 'ÚNICO': 'U', 'UNIVERSAL': 'U'
    }
    
    return mapeamento.get(tamanho, tamanho)

def extrair_tamanho(texto):
    """Extrai e padroniza o tamanho do texto"""
    if not texto:
        return None
        
    # Converte para maiúsculo e remove espaços extras
    texto = texto.upper().strip()
    
    # Padrões comuns de tamanho
    padroes = {
        'PP': ['PP', 'XS', 'EXTRA SMALL'],
        'P': ['P', 'S', 'SMALL', '1P', '2P', '3P'],
        'M': ['M', 'MEDIUM', '1M', '2M', '3M'],
        'G': ['G', 'L', 'LARGE', '1G', '2G', '3G'],
        'GG': ['GG', 'XL', 'EXTRA LARGE', 'XG'],
        'XGG': ['XGG', 'XXL', 'EXTRA EXTRA LARGE', 'XXG'],
        'U': ['U', 'UNICO', 'ÚNICO', 'UNIVERSAL', 'TAMANHO UNICO', 'TAMANHO ÚNICO']
    }
    
    # Números comuns de tamanho
    numeros = ['34', '36', '38', '40', '42', '44', '46', '48', '50']
    
    # Primeiro tenta encontrar números
    for num in numeros:
        if num in texto:
            return num
            
    # Depois tenta encontrar letras
    for padrao, variantes in padroes.items():
        for variante in variantes:
            if variante in texto:
                return padrao
                
    return texto

def configurar_sessao_shopify():
    """Configura a sessão da Shopify"""
    try:
        shop_url = os.getenv("SHOP_NAME")
        api_version = '2024-01'
        password = os.getenv("PASSWORD")
        
        logging.info(f"Tentando configurar sessão Shopify...")
        logging.info(f"Shop URL: {shop_url if shop_url else 'Não encontrado'}")
        logging.info(f"API Version: {api_version}")
        logging.info(f"Password: {'Encontrado' if password else 'Não encontrado'}")
        
        if not shop_url or not password:
            logging.error("Credenciais da Shopify não encontradas nas variáveis de ambiente")
            return False
        
        shopify.ShopifyResource.clear_session()
        logging.info("Sessão anterior limpa")
        
        session = shopify.Session(shop_url, api_version, password)
        logging.info("Sessão criada")
        
        shopify.ShopifyResource.activate_session(session)
        logging.info("Sessão ativada")
        
        # Testa a conexão
        test = shopify.Shop.current()
        if not test:
            logging.error("Não foi possível conectar à Shopify")
            return False
            
        logging.info("Conexão com Shopify estabelecida com sucesso")
        return True
        
    except Exception as e:
        logging.error(f"Erro ao configurar sessão Shopify: {str(e)}")
        logging.error(f"Tipo do erro: {type(e)}")
        return False

def buscar_produtos_hiper():
    """Busca produtos do Hiper e armazena em cache"""
    global _cache
    if (datetime.now() - _cache['last_update_hiper']) < timedelta(minutes=10):
        logging.info("Usando cache de produtos do Hiper.")
        return _cache['produtos_hiper']

    logging.info("Buscando produtos do Hiper...")
    config_hiper = configurar_hiper()
    url_hiper = f"{config_hiper['url_base']}/produtos/pontoDeSincronizacao"
    response = requests.get(url_hiper, headers=config_hiper['headers'])
    response.raise_for_status()
    
    produtos = response.json()['produtos']
    _cache['produtos_hiper'] = produtos
    _cache['last_update_hiper'] = datetime.now()
    return produtos

def buscar_produtos_shopify():
    """Busca todos os produtos da Shopify usando paginação baseada em links"""
    logger = logging.getLogger(__name__)
    todos_produtos = []
    
    # Primeira requisição
    produtos = shopify.Product.find(limit=250)
    todos_produtos.extend(produtos)
    logger.info(f"Produtos encontrados: {len(produtos)}")
    
    # Continua buscando enquanto houver próxima página
    while produtos.has_next_page():
        produtos = produtos.next_page()
        todos_produtos.extend(produtos)
        logger.info(f"Produtos encontrados na próxima página: {len(produtos)}")
    
    logger.info(f"Total de produtos encontrados: {len(todos_produtos)}")
    return todos_produtos

def processar_produtos_hiper(produtos_hiper):
    """Processa produtos do Hiper"""
    logger = logging.getLogger(__name__)
    produtos_filtrados = {}  # Usando dicionário para evitar duplicatas
    
    for produto in produtos_hiper:
        nome = produto.get('nome', '').strip().lower()
        sku = produto.get('codigoDeBarras')  # Campo correto do Hiper
        
        # Filtra produtos Saphira ou Olive (case insensitive)
        if any(marca in nome for marca in ["saphira", "olive", "chloe"]):
            if sku not in produtos_filtrados:
                logger.info(f"Produto Hiper encontrado: {nome} (SKU: {sku})")
                produtos_filtrados[sku] = produto
    
    logger.info(f"Total de produtos filtrados no Hiper: {len(produtos_filtrados)}")
    return list(produtos_filtrados.values())

def processar_produtos_shopify(produtos_shopify):
    """Processa produtos da Shopify"""
    logger = logging.getLogger(__name__)
    produtos_filtrados = []
    
    for produto in produtos_shopify:
        nome = produto.title.strip().lower()
        
        # Filtra produtos Saphira ou Olive (case insensitive)
        if any(marca in nome for marca in ["saphira", "olive"]):
            logger.info(f"Produto Shopify encontrado: {produto.title}")
            produtos_filtrados.append(produto)
    
    logger.info(f"Total de produtos filtrados na Shopify: {len(produtos_filtrados)}")
    return produtos_filtrados

def atualizar_estoque_shopify(produtos_hiper, produtos_shopify):
    """Atualiza o estoque dos produtos Shopify baseado no Hiper"""
    logger = logging.getLogger(__name__)
    logger.info("Iniciando atualização de estoque...")
    
    # Criar dicionário de SKUs do Hiper para fácil acesso
    estoque_hiper = {}
    for produto in produtos_hiper:
        sku = produto.get('codigoDeBarras')
        quantidade = int(produto.get('quantidadeEmEstoque', 0))
        
        if sku:
            estoque_hiper[sku] = quantidade
            logger.info(f"Estoque Hiper - SKU: {sku}, Quantidade: {quantidade}")

    # Contadores para o relatório
    atualizados = 0
    sem_alteracao = 0
    
    # Atualizar estoque na Shopify
    for produto in produtos_shopify:
        for variant in produto.variants:
            sku = variant.sku
            if sku in estoque_hiper:
                quantidade_hiper = estoque_hiper[sku]
                quantidade_atual = int(variant.inventory_quantity or 0)
                
                # Só atualiza se houver diferença no estoque
                if quantidade_atual != quantidade_hiper:
                    try:
                        # Busca o location_id
                        inventory_levels = shopify.InventoryLevel.find(
                            inventory_item_ids=variant.inventory_item_id
                        )
                        
                        if inventory_levels:
                            location_id = inventory_levels[0].location_id
                            
                            # Atualiza o estoque
                            result = shopify.InventoryLevel.set(
                                location_id=location_id,
                                inventory_item_id=variant.inventory_item_id,
                                available=quantidade_hiper
                            )
                            
                            if result:
                                logger.info(f"Atualizado: {produto.title} - {variant.title}")
                                logger.info(f"SKU: {sku}")
                                logger.info(f"Quantidade anterior: {quantidade_atual}")
                                logger.info(f"Nova quantidade: {quantidade_hiper}")
                                atualizados += 1
                                
                    except Exception as e:
                        logger.error(f"Erro ao atualizar {sku}: {str(e)}")
                else:
                    sem_alteracao += 1
                    logger.debug(f"Sem alteração necessária: {produto.title} - {variant.title} (SKU: {sku}, Quantidade: {quantidade_atual})")
    
    logger.info(f"\n=== Resumo de Atualizações ===")
    logger.info(f"Variantes atualizadas: {atualizados}")
    logger.info(f"Variantes sem alteração: {sem_alteracao}")
    logger.info(f"Total de variantes verificadas: {atualizados + sem_alteracao}")
    
    return atualizados

def sincronizar_estoque():
    """Função principal com atualização de estoque"""
    logger = logging.getLogger(__name__)
    logger.info("Iniciando sincronização...")
    
    try:
        # Busca produtos
        produtos_hiper = buscar_produtos_hiper()
        produtos_shopify = buscar_produtos_shopify()
        
        # Processa produtos
        saphira_hiper = processar_produtos_hiper(produtos_hiper)
        saphira_shopify = processar_produtos_shopify(produtos_shopify)
        
        # Atualiza estoque
        total_atualizados = atualizar_estoque_shopify(saphira_hiper, saphira_shopify)
        
        # Log do resumo
        logger.info("\n=== Resumo ===")
        logger.info(f"Total de produtos no Hiper: {len(saphira_hiper)}")
        logger.info(f"Total de produtos na Shopify: {len(saphira_shopify)}")
        logger.info(f"Total de variantes atualizadas: {total_atualizados}")
        
    except Exception as e:
        logger.error(f"Erro durante processamento: {str(e)}")

def main():
    """Função principal que coordena o processo de sincronização"""
    try:
        if not setup_logging():
            print("Falha ao configurar logging")
            return False

        logger = logging.getLogger(__name__)
        logger.info("Iniciando processo de sincronização...")
        
        if not configurar_sessao_shopify():
            logger.error("Falha ao configurar Shopify")
            return False
        
        sincronizar_estoque()
        
    except Exception as e:
        logger.error(f"Erro fatal durante sincronização: {str(e)}")
    finally:
        shopify.ShopifyResource.clear_session()
        logger.info("Processo de sincronização finalizado")

if __name__ == "__main__":
    main() 