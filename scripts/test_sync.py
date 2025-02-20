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
    """Busca produtos da Shopify e armazena em cache"""
    global _cache
    if (datetime.now() - _cache['last_update_shopify']) < timedelta(minutes=10):
        logging.info("Usando cache de produtos da Shopify.")
        return _cache['produtos_shopify']

    logging.info("Buscando produtos da Shopify...")
    produtos_shopify = shopify.Product.find()
    _cache['produtos_shopify'] = produtos_shopify
    _cache['last_update_shopify'] = datetime.now()
    return produtos_shopify

def buscar_estoque_em_lote(variants, location_id, max_retries=3, delay=1.0):
    """Busca estoque em lote para uma lista de variantes"""
    logger = logging.getLogger(__name__)
    
    if not variants:
        return {}
    
    def fetch_batch():
        inventory_item_ids = [str(v.inventory_item_id) for v in variants]
        inventory_levels = shopify.InventoryLevel.find(
            inventory_item_ids=','.join(inventory_item_ids),
            location_ids=location_id
        )
        return {level.inventory_item_id: level.available for level in inventory_levels}

    try:
        return retry_operation(fetch_batch, max_retries, delay)
    except Exception as e:
        logger.error(f"Erro ao buscar estoque em lote: {str(e)}")
        return {}

def atualizar_estoque_shopify(variant_id, location_id, novo_estoque):
    """Atualiza o estoque de uma variante na Shopify"""
    logger = logging.getLogger(__name__)
    try:
        with PerformanceMetric('shopify_calls'):
            inventory_level = get_cached_inventory_level(variant_id, location_id)
            if not inventory_level:
                logger.error(f"Nível de estoque não encontrado para variant_id {variant_id}")
                return False
            
            estoque_atual = inventory_level.available
            if estoque_atual != novo_estoque:
                retry_operation(
                    lambda: inventory_level.set(
                        location_id=location_id,
                        inventory_item_id=variant_id,
                        available=novo_estoque
                    ),
                    operation_name=f'update_inventory_{variant_id}'
                )
                logger.info(f"Estoque atualizado: {estoque_atual} -> {novo_estoque}")
                return True
            else:
                logger.info(f"Estoque já está correto: {estoque_atual}")
                return True
    except Exception as e:
        logger.error(f"Erro ao atualizar estoque da variante {variant_id}: {str(e)}")
        return False

def mapear_variantes_shopify(produtos_shopify):
    """Mapeia variantes da Shopify para facilitar a busca"""
    mapeamento = {
        'por_sku': {},
        'por_nome': {},
        'por_nome_tamanho': {},
        'todas_variantes': []
    }
    
    for produto in produtos_shopify:
        nome_base_produto = normalizar_nome(produto.title.split(' - ')[0])  # Remove sufixo de tamanho se existir
        
        # Adiciona produto base apenas uma vez
        if nome_base_produto not in mapeamento['por_nome']:
            mapeamento['por_nome'][nome_base_produto] = produto
        
        for variant in produto.variants:
            if variant.sku:
                # Mapeia por SKU original
                mapeamento['por_sku'][variant.sku] = {
                    'variant': variant,
                    'produto': produto,
                    'nome_base': nome_base_produto
                }
            
            # Mapeia por nome + tamanho
            tamanho = extrair_tamanho(variant.title)
            if tamanho:
                chave = f"{nome_base_produto}_{tamanho}"
                mapeamento['por_nome_tamanho'][chave] = {
                    'variant': variant,
                    'produto': produto,
                    'nome_base': nome_base_produto
                }
                
            mapeamento['todas_variantes'].append({
                'variant': variant,
                'produto': produto,
                'nome_base': nome_base_produto
            })
    
    return mapeamento

def encontrar_variante_correspondente(sku_hiper, nome_produto_hiper, tamanho_hiper, mapeamento_shopify):
    """Encontra a variante correspondente no Shopify"""
    logger = logging.getLogger(__name__)
    
    nome_base_hiper = normalizar_nome(nome_produto_hiper.split(' - ')[0])  # Remove sufixo de tamanho se existir
    
    # Tenta encontrar por SKU original
    if sku_hiper in mapeamento_shopify['por_sku']:
        return mapeamento_shopify['por_sku'][sku_hiper]
        
    # Tenta encontrar por nome e tamanho
    tamanho_normalizado = extrair_tamanho(tamanho_hiper) if tamanho_hiper else None
    
    chave_nome_tamanho = f"{nome_base_hiper}_{tamanho_normalizado}" if tamanho_normalizado else nome_base_hiper
    if chave_nome_tamanho in mapeamento_shopify['por_nome_tamanho']:
        return mapeamento_shopify['por_nome_tamanho'][chave_nome_tamanho]
    
    return None

def validar_sku(sku):
    """
    Valida se o SKU está no formato correto (ignorando códigos internos)
    
    Args:
        sku: SKU a ser validado
    Returns:
        bool: True se o SKU é válido, False caso contrário
    """
    if not sku:
        return False
        
    # Valida formato do SKU (deve começar com C e ter pelo menos 5 caracteres)
    if not sku.startswith('C') or len(sku) < 5:
        # Verifica se é um EAN-13 válido (13 dígitos começando com 999)
        if len(sku) == 13 and sku.isdigit() and sku.startswith('999'):
            return True
        return False
        
    # Verifica se os caracteres após o C são numéricos
    codigo_numerico = sku[1:6]
    if not codigo_numerico.isdigit():
        return False
        
    return True

def get_cached_inventory_level(variant_id, location_id):
    """Busca inventory level do cache ou da API"""
    cache_key = f"{variant_id}_{location_id}"
    
    # Tenta buscar do cache
    if cache_key in _cache['inventory_levels']:
        _metrics['cache_hits'] += 1
        return _cache['inventory_levels'][cache_key]
    
    _metrics['cache_misses'] += 1
    
    # Se não está no cache, busca da API
    with PerformanceMetric('shopify_calls'):
        inventory_level = retry_operation(
            lambda: shopify.InventoryLevel.find_first(
                inventory_item_ids=variant_id,
                location_ids=location_id
            )
        )
        
        if inventory_level:
            _cache['inventory_levels'][cache_key] = inventory_level
            
        return inventory_level

def retry_operation(operation, max_retries=3, delay=1.0, operation_name=None):
    """Executa uma operação com retry em caso de falha"""
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            _metrics['api_calls'] += 1
            return operation()
        except Exception as e:
            last_exception = e
            _metrics['retries'] += 1
            _metrics['errors'].append({
                'operation': operation_name or 'unknown',
                'attempt': attempt + 1,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            
            if attempt < max_retries - 1:
                sleep_time = delay * (2 ** attempt)  # Backoff exponencial
                logging.warning(f"Tentativa {attempt + 1} falhou, aguardando {sleep_time}s para retry...")
                time.sleep(sleep_time)
            else:
                logging.error(f"Todas as {max_retries} tentativas falharam")
                
    if last_exception:
        raise last_exception

def log_metrics():
    """Registra métricas de performance no log"""
    logger = logging.getLogger(__name__)
    
    if not _metrics['start_time']:
        return
        
    duration = time.time() - _metrics['start_time']
    
    logger.info("\n=== Métricas de Performance ===")
    logger.info(f"Duração total: {duration:.2f}s")
    logger.info(f"Chamadas de API: {_metrics['api_calls']}")
    logger.info(f"Cache hits: {_metrics['cache_hits']}")
    logger.info(f"Cache misses: {_metrics['cache_misses']}")
    logger.info(f"Retries: {_metrics['retries']}")
    
    if _metrics['errors']:
        logger.info("\nErros encontrados:")
        for error in _metrics['errors']:
            logger.error(f"[{error['timestamp']}] {error['operation']}: {error['error']}")
            
    logger.info("\nTempo médio por operação:")
    for operation, timings in _metrics['timing'].items():
        if timings:
            avg_time = sum(t['duration'] for t in timings) / len(timings)
            logger.info(f"{operation}: {avg_time:.2f}s")

def mapear_skus_variantes(produtos_hiper, produtos_shopify):
    """
    Cria um mapeamento direto entre variantes do Hiper e Shopify.
    Prioriza produtos Saphira e usa tanto SKU quanto código de barras para matching.
    """
    logger = logging.getLogger(__name__)
    mapeamento = {}
    
    with PerformanceMetric('mapping_operations'):
        # Filtra apenas produtos Saphira do Shopify
        produtos_saphira = [p for p in produtos_shopify if "Saphira" in p.title]
        logger.info(f"\nTotal de produtos Saphira encontrados: {len(produtos_saphira)}")
        
        # Cria índices para busca eficiente
        indices_shopify = {
            'sku': {},
            'barcode': {},
            'nome': {}
        }
        
        # Popula índices
        for produto in produtos_saphira:
            nome_normalizado = normalizar_nome(produto.title)
            indices_shopify['nome'][nome_normalizado] = produto
            
            for variant in produto.variants:
                if variant.sku:
                    indices_shopify['sku'][variant.sku] = {
                        'variant': variant,
                        'produto': produto
                    }
                if variant.barcode:
                    indices_shopify['barcode'][variant.barcode] = {
                        'variant': variant,
                        'produto': produto
                    }
        
        # Processa produtos Saphira do Hiper
        produtos_saphira_hiper = [p for p in produtos_hiper if "Saphira" in p['nome']]
        logger.info(f"\nTotal de produtos Saphira no Hiper: {len(produtos_saphira_hiper)}")
        
        for produto in produtos_saphira_hiper:
            logger.info(f"\nProcessando produto Hiper: {produto['nome']}")
            
            for variante in produto.get('variantes', []):
                codigo = variante.get('codigoDeBarras', '')
                if not codigo:
                    continue
                    
                # Tenta encontrar por SKU ou código de barras
                variant_info = indices_shopify['sku'].get(codigo) or indices_shopify['barcode'].get(codigo)
                
                if variant_info:
                    variant = variant_info['variant']
                    produto_shopify = variant_info['produto']
                    
                    mapeamento[codigo] = {
                        'variant_shopify': variant,
                        'variant_id': variant.id,
                        'nome_produto': produto_shopify.title,
                        'estoque_hiper': int(float(variante.get('quantidadeEmEstoque', 0)))
                    }
                    
                    logger.info(f"  ✓ Match encontrado: {codigo} -> {produto_shopify.title}")
                    logger.info(f"    Estoque Hiper: {mapeamento[codigo]['estoque_hiper']}")
                else:
                    logger.warning(f"  ✗ Variante não encontrada: {codigo} ({produto['nome']})")
    
    return mapeamento

def extrair_caracteristicas_saphira(produto_hiper):
    """
    Extrai características relevantes de um produto Saphira do Hiper
    """
    logger = logging.getLogger(__name__)
    
    try:
        caracteristicas = {
            'nome': produto_hiper.get('nome', ''),
            'codigo': produto_hiper.get('codigo', ''),
            'marca': produto_hiper.get('marca', {}).get('nome', ''),
            'categoria': produto_hiper.get('categoria', {}).get('nome', ''),
            'caracteristicas': {},
            'variantes': []
        }
        
        # Extrai características específicas
        for caracteristica in produto_hiper.get('caracteristicas', []):
            nome = caracteristica.get('nome', '').lower()
            valor = caracteristica.get('valor', '')
            caracteristicas['caracteristicas'][nome] = valor
            
        # Processa variantes
        for variante in produto_hiper.get('variantes', []):
            info_variante = {
                'sku': variante.get('codigo', ''),
                'barcode': variante.get('codigoDeBarras', ''),
                'estoque': int(float(variante.get('quantidadeEmEstoque', 0))),
                'caracteristicas': {}
            }
            
            # Extrai características da variante
            for caracteristica in variante.get('caracteristicas', []):
                nome = caracteristica.get('nome', '').lower()
                valor = caracteristica.get('valor', '')
                info_variante['caracteristicas'][nome] = valor
                
            caracteristicas['variantes'].append(info_variante)
            
        return caracteristicas
        
    except Exception as e:
        logger.error(f"Erro ao extrair características do produto {produto_hiper.get('nome', 'N/A')}: {str(e)}")
        return None

def processar_produtos_saphira(produtos_hiper):
    """
    Processa produtos Saphira do Hiper extraindo características relevantes
    """
    logger = logging.getLogger(__name__)
    produtos_processados = []
    
    try:
        # Filtra produtos Saphira
        produtos_saphira = [p for p in produtos_hiper if "Saphira" in p.get('nome', '')]
        logger.info(f"\nTotal de produtos Saphira encontrados no Hiper: {len(produtos_saphira)}")
        
        for produto in produtos_saphira:
            logger.info(f"\nProcessando produto: {produto.get('nome', 'N/A')}")
            
            caracteristicas = extrair_caracteristicas_saphira(produto)
            if caracteristicas:
                produtos_processados.append(caracteristicas)
                logger.info("Características extraídas:")
                logger.info(f"  Nome: {caracteristicas['nome']}")
                logger.info(f"  Marca: {caracteristicas['marca']}")
                logger.info(f"  Categoria: {caracteristicas['categoria']}")
                logger.info(f"  Total de variantes: {len(caracteristicas['variantes'])}")
                
                # Log detalhado das características
                for nome, valor in caracteristicas['caracteristicas'].items():
                    logger.info(f"  {nome}: {valor}")
                    
                # Log das variantes
                for variante in caracteristicas['variantes']:
                    logger.info(f"\n  Variante:")
                    logger.info(f"    SKU: {variante['sku']}")
                    logger.info(f"    Barcode: {variante['barcode']}")
                    logger.info(f"    Estoque: {variante['estoque']}")
                    for nome, valor in variante['caracteristicas'].items():
                        logger.info(f"    {nome}: {valor}")
            
        return produtos_processados
        
    except Exception as e:
        logger.error(f"Erro ao processar produtos Saphira: {str(e)}")
        return []

class ProdutoSaphira:
    """Classe para representar um produto Saphira com suas variantes"""
    def __init__(self, nome, codigo=None):
        self.nome = nome
        self.codigo = codigo
        self.variantes = {}  # SKU/Barcode -> {estoque, caracteristicas}
        
    def adicionar_variante(self, sku, barcode, estoque, caracteristicas=None):
        """Adiciona ou atualiza uma variante"""
        if sku:
            self.variantes[sku] = {
                'sku': sku,
                'barcode': barcode,
                'estoque': estoque,
                'caracteristicas': caracteristicas or {}
            }
        if barcode:
            self.variantes[barcode] = {
                'sku': sku,
                'barcode': barcode,
                'estoque': estoque,
                'caracteristicas': caracteristicas or {}
            }

class GerenciadorProdutos:
    """Gerenciador central de produtos Saphira"""
    def __init__(self):
        self.produtos_hiper = {}  # nome -> ProdutoSaphira
        self.produtos_shopify = {}  # nome -> ProdutoSaphira
        self.mapeamento_skus = {}  # SKU/Barcode Hiper -> SKU/Barcode Shopify
        self.location_id = None
        
    def processar_produtos_hiper(self, produtos_hiper):
        """Processa produtos do Hiper uma única vez"""
        logger = logging.getLogger(__name__)
        
        for produto in produtos_hiper:
            nome_norm = normalizar_nome(produto.get('nome', ''))
            if "saphira" not in nome_norm:
                continue
                
            nome = produto.get('nome', '').strip()
            codigo = produto.get('codigo', '')
            logger.info(f"\nProcessando produto Hiper: {nome}")
            
            if nome not in self.produtos_hiper:
                self.produtos_hiper[nome] = ProdutoSaphira(nome, codigo)
                
            # Processa variantes
            for variante in produto.get('variantes', []):
                sku = variante.get('codigo', '')
                barcode = variante.get('codigoDeBarras', '')
                estoque = int(float(variante.get('quantidadeEmEstoque', 0)))
                
                logger.info(f"  Variante Hiper: SKU={sku}, Barcode={barcode}, Estoque={estoque}")
                self.produtos_hiper[nome].adicionar_variante(
                    sku=sku,
                    barcode=barcode,
                    estoque=estoque
                )
                
        logger.info(f"\nTotal de produtos Saphira processados do Hiper: {len(self.produtos_hiper)}")

    def processar_produtos_shopify(self, produtos_shopify):
        """Processa produtos da Shopify uma única vez"""
        logger = logging.getLogger(__name__)
        
        for produto in produtos_shopify:
            # Verifica se é produto Saphira de forma mais flexível
            nome_norm = normalizar_nome(produto.title)
            if "saphira" not in nome_norm:
                continue
                
            nome = produto.title.strip()
            logger.info(f"Processando produto Shopify: {nome}")
            
            if nome not in self.produtos_shopify:
                self.produtos_shopify[nome] = ProdutoSaphira(nome)
                
            # Processa variantes
            for variant in produto.variants:
                logger.info(f"  Variante encontrada: SKU={variant.sku}, Barcode={variant.barcode}")
                self.produtos_shopify[nome].adicionar_variante(
                    sku=variant.sku,
                    barcode=variant.barcode,
                    estoque=0,  # Será atualizado depois
                    caracteristicas={'variant_id': variant.id}
                )
                
        logger.info(f"Total de produtos Saphira processados da Shopify: {len(self.produtos_shopify)}")
        
    def mapear_produtos(self):
        """Cria mapeamento entre produtos Hiper e Shopify"""
        logger = logging.getLogger(__name__)
        
        # Debug: Lista todos os produtos
        logger.info("\nProdutos no Hiper:")
        for nome, produto in self.produtos_hiper.items():
            logger.info(f"  - {nome}")
            for id_var, var in produto.variantes.items():
                logger.info(f"    SKU={var['sku']}, Barcode={var['barcode']}")
            
        logger.info("\nProdutos na Shopify:")
        for nome, produto in self.produtos_shopify.items():
            logger.info(f"  - {nome}")
            for id_var, var in produto.variantes.items():
                logger.info(f"    SKU={var['sku']}, Barcode={var['barcode']}")
        
        # Cria índices para busca eficiente
        indices_shopify = {
            'sku': {},
            'barcode': {},
            'nome_norm': {}
        }
        
        # Popula índices Shopify
        for nome, produto in self.produtos_shopify.items():
            nome_norm = normalizar_nome(nome)
            indices_shopify['nome_norm'][nome_norm] = produto
            
            for var in produto.variantes.values():
                if var['sku']:
                    indices_shopify['sku'][var['sku']] = (produto, var)
                if var['barcode']:
                    indices_shopify['barcode'][var['barcode']] = (produto, var)
        
        # Mapeia produtos
        for nome_hiper, produto_hiper in self.produtos_hiper.items():
            logger.info(f"\nProcessando produto Hiper: {nome_hiper}")
            nome_norm = normalizar_nome(nome_hiper)
            logger.info(f"Nome normalizado: {nome_norm}")
            
            # Mapeia variantes
            for identificador, variante_hiper in produto_hiper.variantes.items():
                sku = variante_hiper['sku']
                barcode = variante_hiper['barcode']
                
                # Tenta encontrar por SKU ou barcode
                match = None
                if sku and sku in indices_shopify['sku']:
                    match = indices_shopify['sku'][sku]
                elif barcode and barcode in indices_shopify['barcode']:
                    match = indices_shopify['barcode'][barcode]
                
                if match:
                    produto_shopify, variante_shopify = match
                    self.mapeamento_skus[identificador] = {
                        'sku': variante_shopify['sku'],
                        'barcode': variante_shopify['barcode'],
                        'caracteristicas': variante_shopify['caracteristicas'],
                        'nome_produto': produto_shopify.nome
                    }
                    logger.info(f"✓ Match encontrado: {nome_hiper}")
                    logger.info(f"  Hiper: SKU={sku}, Barcode={barcode}")
                    logger.info(f"  Shopify: SKU={variante_shopify['sku']}, Barcode={variante_shopify['barcode']}")
                else:
                    logger.warning(f"✗ Variante não encontrada: SKU={sku}, Barcode={barcode}")
        
        logger.info(f"\nTotal de variantes mapeadas: {len(self.mapeamento_skus)}")
        
        # Debug: Mostra mapeamentos realizados
        if self.mapeamento_skus:
            logger.info("\nMapeamentos realizados:")
            for id_hiper, var_shopify in self.mapeamento_skus.items():
                logger.info(f"Hiper: {id_hiper} -> Shopify: {var_shopify['sku']}")

    def atualizar_estoques(self):
        """Atualiza estoques na Shopify"""
        logger = logging.getLogger(__name__)
        atualizados = []
        nao_encontrados = []
        
        if not self.location_id:
            locations = shopify.Location.find()
            if not locations:
                logger.error("Nenhuma location encontrada na Shopify")
                return
            self.location_id = locations[0].id
        
        # Atualiza estoque para cada variante mapeada
        for identificador_hiper, variante_shopify in self.mapeamento_skus.items():
            try:
                # Encontra estoque no Hiper
                estoque_hiper = None
                for produto in self.produtos_hiper.values():
                    if identificador_hiper in produto.variantes:
                        estoque_hiper = produto.variantes[identificador_hiper]['estoque']
                        break
                
                if estoque_hiper is None:
                    logger.warning(f"Estoque não encontrado no Hiper para: {identificador_hiper}")
                    nao_encontrados.append(identificador_hiper)
                    continue
                
                # Atualiza estoque na Shopify
                variant_id = variante_shopify['caracteristicas']['variant_id']
                nome_produto = variante_shopify['nome_produto']
                
                logger.info(f"\nAtualizando estoque: {nome_produto}")
                logger.info(f"  SKU: {variante_shopify['sku']}")
                logger.info(f"  Estoque Hiper: {estoque_hiper}")
                
                if atualizar_estoque_shopify(variant_id, self.location_id, estoque_hiper):
                    atualizados.append(identificador_hiper)
                    logger.info(f"  ✓ Estoque atualizado com sucesso")
                    
            except Exception as e:
                logger.error(f"Erro ao atualizar estoque de {identificador_hiper}: {str(e)}")
        
        return {
            'atualizados': atualizados,
            'nao_encontrados': nao_encontrados
        }

def sincronizar_estoque():
    """Sincroniza o estoque entre Hiper e Shopify"""
    logger = logging.getLogger(__name__)
    logger.info("Iniciando sincronização de estoque...")
    
    try:
        # Busca produtos uma única vez
        produtos_hiper = buscar_produtos_hiper()
        produtos_shopify = buscar_produtos_shopify()
        
        if not produtos_hiper or not produtos_shopify:
            logger.error("Falha ao buscar produtos")
            return
            
        # Inicializa gerenciador
        gerenciador = GerenciadorProdutos()
        
        # Processa produtos
        gerenciador.processar_produtos_hiper(produtos_hiper)
        gerenciador.processar_produtos_shopify(produtos_shopify)
        
        # Cria mapeamento
        gerenciador.mapear_produtos()
        
        # Atualiza estoques
        resultados = gerenciador.atualizar_estoques()
        
        # Log dos resultados
        logger.info("\n=== Resumo da Sincronização ===")
        logger.info(f"Total de produtos Hiper: {len(gerenciador.produtos_hiper)}")
        logger.info(f"Total de produtos Shopify: {len(gerenciador.produtos_shopify)}")
        logger.info(f"Variantes atualizadas: {len(resultados['atualizados'])}")
        logger.info(f"Variantes não encontradas: {len(resultados['nao_encontrados'])}")
        
        return resultados
        
    except Exception as e:
        logger.error(f"Erro durante sincronização: {str(e)}")
        return None

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