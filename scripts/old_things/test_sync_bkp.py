import os
import json
import time
import logging
import requests
import unicodedata
import re
import sys
from datetime import datetime
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

def normalizar_nome(nome):
    """Normaliza o nome do produto para comparação"""
    if not nome:
        return ""
        
    # Correções específicas de caracteres especiais
    nome = nome.replace("Cal?a", "Calca")
    nome = nome.replace("Calça", "Calca")
    nome = nome.replace("Ca?a", "Calca")
    nome = nome.replace("Bone", "Bone")  # Mantém consistência
    
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
    """Busca produtos do Hiper"""
    try:
        config_hiper = configurar_hiper()
        url_hiper = f"{config_hiper['url_base']}/produtos/pontoDeSincronizacao"
        response = requests.get(url_hiper, headers=config_hiper['headers'])
        response.raise_for_status()
        
        produtos = response.json()['produtos']
        produtos_processados = {}
        produtos_agrupados = {}
        
        # Primeiro, agrupa produtos por nome normalizado
        for produto in produtos:
            if not produto.get('codigoDeBarras'):
                continue
                
            nome_base = produto['nome'].split(' - ')[0] if ' - ' in produto['nome'] else produto['nome']
            nome_norm = normalizar_nome(nome_base)
            
            if nome_norm not in produtos_agrupados:
                produtos_agrupados[nome_norm] = []
            produtos_agrupados[nome_norm].append(produto)
        
        # Depois, processa cada grupo
        for nome_norm, grupo in produtos_agrupados.items():
            # Se houver apenas um produto no grupo, adiciona normalmente
            if len(grupo) == 1:
                produto = grupo[0]
                produtos_processados[produto['codigoDeBarras']] = {
                    'nome': produto['nome'],
                    'codigoDeBarras': produto['codigoDeBarras'],
                    'quantidadeEmEstoque': produto.get('quantidadeEmEstoque', 0),
                    'variantes': []  # Lista vazia de variantes
                }
                continue
            
            # Se houver múltiplos produtos, procura o SKU pai
            sku_pai = None
            produto_pai = None
            
            # Primeiro tenta encontrar pelo SKU numérico
            for p in grupo:
                if p['codigoDeBarras'].isdigit():
                    sku_pai = p['codigoDeBarras']
                    produto_pai = p
                    break
            
            # Se não encontrou SKU numérico, procura pelo padrão de SKU pai (sem tamanho)
            if not produto_pai:
                for p in grupo:
                    # Verifica se o SKU tem o formato esperado (letras + números sem tamanho)
                    sku = p['codigoDeBarras']
                    if sku and not sku[-2:].isdigit():  # Se os últimos 2 caracteres não são números
                        sku_pai = sku
                        produto_pai = p
                        break
            
            # Se ainda não encontrou, usa o primeiro produto
            if not produto_pai:
                produto_pai = grupo[0]
                sku_pai = produto_pai['codigoDeBarras']
            
            # Processa o produto pai e suas variantes
            produtos_processados[sku_pai] = {
                'nome': produto_pai['nome'].split(' - ')[0],  # Remove sufixo de tamanho
                'codigoDeBarras': sku_pai,
                'quantidadeEmEstoque': produto_pai.get('quantidadeEmEstoque', 0),
                'variantes': []
            }
            
            # Processa cada variante
            for p in grupo:
                if p == produto_pai:
                    continue
                    
                # Extrai tamanho do nome da variante
                nome_partes = p['nome'].split(' - ')
                tamanho = nome_partes[1] if len(nome_partes) > 1 else None
                
                if not tamanho:
                    # Tenta extrair tamanho do final do nome
                    tamanho = extrair_tamanho(p['nome'])
                    
                # Se ainda não tem tamanho, tenta extrair do SKU
                if not tamanho and len(p['codigoDeBarras']) >= 2:
                    tamanho_do_sku = p['codigoDeBarras'][-2:]
                    if tamanho_do_sku.isdigit():
                        tamanho = tamanho_do_sku
                
                produtos_processados[sku_pai]['variantes'].append({
                    'nome': p['nome'],
                    'codigoDeBarras': p['codigoDeBarras'],
                    'quantidadeEmEstoque': p.get('quantidadeEmEstoque', 0),
                    'tamanho': tamanho,
                    'sku_pai': sku_pai  # Adiciona referência ao SKU pai
                })
        
        # Log para debug
        for produto in produtos_processados.values():
            if "Maria" in produto['nome']:
                logging.info(f"Produto encontrado: {produto['nome']}")
                logging.info(f"SKU pai: {produto['codigoDeBarras']}")
                for var in produto['variantes']:
                    logging.info(f"Variante: {var['nome']} - SKU: {var['codigoDeBarras']} - Tamanho: {var['tamanho']}")
        
        return list(produtos_processados.values())
        
    except Exception as e:
        logging.error(f"Erro ao buscar produtos do Hiper: {str(e)}")
        return []

def buscar_produtos_shopify(session_configured=False):
    """Busca produtos usando paginação baseada em links"""
    try:
        if not session_configured and not configurar_sessao_shopify():
            return []
        
        produtos = []
        next_page_url = None
        limit = 250  # Limite máximo por página
        
        while True:
            try:
                # Verifica limites de API
                if shopify.ShopifyResource.connection.response:
                    call_limit = shopify.ShopifyResource.connection.response.headers.get('X-Shopify-Shop-Api-Call-Limit')
                    if call_limit:
                        current, limit_max = map(int, call_limit.split('/'))
                        if current >= limit_max - 5:  # Margem de segurança
                            time.sleep(2)  # Aguarda reset do limite
                
                # Primeira página ou próximas páginas
                if next_page_url:
                    batch = shopify.Product.find(from_=next_page_url)
                else:
                    batch = shopify.Product.find(limit=limit)
                
                if not batch:
                    break
                    
                produtos.extend(batch)
                
                # Verifica se há próxima página
                response = shopify.ShopifyResource.connection.response
                if not response or 'Link' not in response.headers:
                    break
                    
                # Extrai URL da próxima página
                link_header = response.headers['Link']
                if 'rel="next"' not in link_header:
                    break
                    
                next_page_url = None
                for link in link_header.split(','):
                    if 'rel="next"' in link:
                        next_page_url = link.split(';')[0].strip('<> ')
                        break
                
                if not next_page_url:
                    break
                    
                time.sleep(0.5)  # Respeita rate limit entre páginas
                
            except ShopifyValidationError as e:
                logging.error(f"Erro de validação: {str(e)}")
                break
            except Exception as e:
                logging.error(f"Erro ao buscar produtos: {str(e)}")
                break
        
        logging.info(f"Total de produtos encontrados na Shopify: {len(produtos)}")
        return produtos
        
    except Exception as e:
        logging.error(f"Erro ao buscar produtos: {str(e)}")
        return []
    finally:
        if not session_configured:
            shopify.ShopifyResource.clear_session()

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

def atualizar_estoque_shopify_por_id(inventory_item_id, novo_estoque, location_id, session_configured=False):
    """Atualiza estoque com retry e tratamento de erros"""
    logger = logging.getLogger(__name__)
    
    try:
        if not session_configured and not configurar_sessao_shopify():
            return False
            
        # Validações iniciais
        if not inventory_item_id or not location_id:
            logger.error(f"ID do item ({inventory_item_id}) ou location_id ({location_id}) inválidos")
            return False
            
        # Garante que novo_estoque seja um inteiro válido
        try:
            novo_estoque = int(float(novo_estoque))
            if novo_estoque < 0:
                novo_estoque = 0
        except (ValueError, TypeError):
            logger.error(f"Valor de estoque inválido: {novo_estoque}")
            return False
            
        def update_attempt():
            try:
                # Primeiro, busca o estoque atual para logging
                inventory_levels = shopify.InventoryLevel.find(
                    location_ids=str(location_id),
                    inventory_item_ids=str(inventory_item_id)
                )
                
                if not inventory_levels:
                    logger.error(f"Nível de estoque não encontrado para inventory_item_id: {inventory_item_id}")
                    return False
                
                estoque_atual = inventory_levels[0].available if inventory_levels else 0
                if estoque_atual == novo_estoque:
                    logger.info(f"Estoque já está correto: {estoque_atual}")
                    return True
                
                # Define o novo valor de estoque
                result = shopify.InventoryLevel.set(
                    location_id=str(location_id),
                    inventory_item_id=str(inventory_item_id),
                    available=novo_estoque
                )
                
                # Verifica se a atualização foi bem sucedida
                if result:
                    # Confirma se o estoque foi realmente atualizado
                    inventory_levels_apos = shopify.InventoryLevel.find(
                        location_ids=str(location_id),
                        inventory_item_ids=str(inventory_item_id)
                    )
                    
                    if inventory_levels_apos and inventory_levels_apos[0].available == novo_estoque:
                        logger.info(f"Estoque confirmado após atualização: {inventory_levels_apos[0].available}")
                        return True
                    else:
                        logger.error(f"Estoque não foi atualizado corretamente. Esperado: {novo_estoque}, Atual: {inventory_levels_apos[0].available if inventory_levels_apos else 'N/A'}")
                        return False
                
                return bool(result)
                
            except Exception as e:
                logger.error(f"Erro ao atualizar estoque: {str(e)}")
                raise
                
        return retry_operation(
            update_attempt,
            max_retries=3,
            delay=1
        )
        
    except Exception as e:
        logger.error(f"Erro ao atualizar estoque: {str(e)}")
        return False
    finally:
        if not session_configured:
            shopify.ShopifyResource.clear_session()

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

def mapear_skus_variantes(produtos_hiper, produtos_shopify):
    """
    Cria um mapeamento especial de SKUs considerando as peculiaridades do Hiper e Shopify.
    Retorna um dicionário com os SKUs das variantes e suas correspondências.
    """
    logger = logging.getLogger(__name__)
    mapeamento = {}
    
    # Primeiro, vamos criar um mapeamento por nome de produto
    produtos_por_nome = {}
    for produto in produtos_shopify:
        nome_base = normalizar_nome(produto.title.split(' - ')[0])
        if nome_base not in produtos_por_nome:
            produtos_por_nome[nome_base] = {
                'produto': produto,
                'variantes': []
            }
        for variant in produto.variants:
            if variant.sku:  # Só considera variantes com SKU
                tamanho = extrair_tamanho(variant.title)
                produtos_por_nome[nome_base]['variantes'].append({
                    'sku': variant.sku,
                    'tamanho': tamanho,
                    'variant': variant
                })
    
    # Agora vamos processar os produtos do Hiper
    for produto in produtos_hiper:
        nome_base = normalizar_nome(produto['nome'].split(' - ')[0])
        
        # Se encontrou produto correspondente no Shopify
        if nome_base in produtos_por_nome:
            shopify_info = produtos_por_nome[nome_base]
            
            # Para cada variante do Hiper
            for variante in produto.get('variantes', []):
                sku_hiper = variante.get('codigoDeBarras', '')
                if not sku_hiper:
                    continue
                    
                # Extrai o tamanho do SKU Hiper (últimos 2 dígitos)
                tamanho_hiper = sku_hiper[-2:] if len(sku_hiper) >= 2 and sku_hiper[-2:].isdigit() else None
                if not tamanho_hiper:
                    continue
                
                # Procura variante correspondente no Shopify
                for var_shopify in shopify_info['variantes']:
                    # Verifica se os tamanhos correspondem
                    if var_shopify['sku'][-2:] == tamanho_hiper:
                        mapeamento[sku_hiper] = {
                            'sku_shopify': var_shopify['sku'],
                            'variant': var_shopify['variant'],
                            'nome_produto': produto['nome'],
                            'tamanho': tamanho_hiper
                        }
                        logger.debug(f"Mapeamento encontrado: {sku_hiper} -> {var_shopify['sku']} ({produto['nome']} - {tamanho_hiper})")
                        break
    
    return mapeamento

def sincronizar_estoque():
    """Sincroniza o estoque entre Hiper e Shopify"""
    logger = logging.getLogger(__name__)
    logger.info("Iniciando sincronização de estoque...")
    
    try:
        # Configura a sessão Shopify uma única vez
        if not configurar_sessao_shopify():
            logger.error("Falha ao configurar sessão Shopify")
            return
            
        try:
            # Busca todos os produtos primeiro
            produtos_hiper = buscar_produtos_hiper()
            produtos_shopify = buscar_produtos_shopify(session_configured=True)
            
            if not produtos_hiper or not produtos_shopify:
                logger.error("Falha ao buscar produtos")
                return
            
            # Busca location_id
            locations = shopify.Location.find()
            if not locations:
                logger.error("Nenhuma location encontrada na Shopify")
                return
                
            location_id = locations[0].id
            if not location_id:
                logger.error("Location ID inválido")
                return
            
            # Cria mapeamento de SKUs
            mapeamento_skus = mapear_skus_variantes(produtos_hiper, produtos_shopify)
            
            # Estatísticas
            total_variantes = sum(len(p.get('variantes', [])) for p in produtos_hiper)
            produtos_nao_encontrados = []
            produtos_atualizados = []
            produtos_com_erro = []
            produtos_sem_divergencia = []
            
            logger.info(f"\nTotal de variantes para processar: {total_variantes}")
            
            # Processa cada produto e suas variantes
            for produto_hiper in produtos_hiper:
                nome_produto = produto_hiper.get('nome', '')
                if not nome_produto:
                    continue
                
                # Processa cada variante
                for variante in produto_hiper.get('variantes', []):
                    sku_hiper = variante.get('codigoDeBarras', '')
                    if not sku_hiper:
                        continue
                    
                    # Busca mapeamento da variante
                    info_variante = mapeamento_skus.get(sku_hiper)
                    if not info_variante:
                        logger.warning(f"Variante não encontrada - SKU Hiper: {sku_hiper} ({nome_produto})")
                        produtos_nao_encontrados.append(f"{nome_produto} (SKU: {sku_hiper})")
                        continue
                    
                    # Extrai informações da variante
                    variant = info_variante['variant']
                    estoque_hiper = int(float(variante.get('quantidadeEmEstoque', 0)))
                    
                    logger.info(f"\nProcessando variante: {nome_produto} - SKU: {sku_hiper}")
                    logger.info(f"SKU Shopify correspondente: {info_variante['sku_shopify']}")
                    logger.info(f"Estoque Hiper: {estoque_hiper}")
                    
                    # Atualiza estoque
                    try:
                        inventory_level = shopify.InventoryLevel.find(
                            inventory_item_ids=str(variant.inventory_item_id),
                            location_ids=str(location_id)
                        )
                        estoque_atual = inventory_level[0].available if inventory_level else 0
                        
                        if estoque_atual != estoque_hiper:
                            atualizado = atualizar_estoque_shopify_por_id(
                                variant.inventory_item_id,
                                estoque_hiper,
                                location_id,
                                session_configured=True
                            )
                            if atualizado:
                                produtos_atualizados.append(f"{nome_produto} (SKU: {sku_hiper})")
                                logger.info(f"✓ Estoque atualizado: {estoque_atual} → {estoque_hiper}")
                            else:
                                produtos_com_erro.append(f"{nome_produto} (SKU: {sku_hiper})")
                                logger.error(f"✗ Falha ao atualizar estoque")
                        else:
                            produtos_sem_divergencia.append(f"{nome_produto} (SKU: {sku_hiper})")
                            logger.info(f"• Estoque já correto: {estoque_atual}")
                            
                    except Exception as e:
                        produtos_com_erro.append(f"{nome_produto} (SKU: {sku_hiper})")
                        logger.error(f"Erro ao processar variante: {str(e)}")
                    
                    time.sleep(0.5)  # Pequena pausa entre variantes
            
            # Gera relatório final
            logger.info("\n=== RESUMO DA SINCRONIZAÇÃO ===")
            logger.info(f"Total de variantes processadas: {total_variantes}")
            logger.info(f"Variantes atualizadas: {len(produtos_atualizados)} ({len(produtos_atualizados)/total_variantes*100:.1f}%)")
            logger.info(f"Variantes não encontradas: {len(produtos_nao_encontrados)} ({len(produtos_nao_encontrados)/total_variantes*100:.1f}%)")
            logger.info(f"Variantes sem divergência: {len(produtos_sem_divergencia)} ({len(produtos_sem_divergencia)/total_variantes*100:.1f}%)")
            logger.info(f"Variantes com erro: {len(produtos_com_erro)} ({len(produtos_com_erro)/total_variantes*100:.1f}%)")
            
            if produtos_nao_encontrados:
                logger.info("\nVariantes não encontradas:")
                for p in sorted(produtos_nao_encontrados):
                    logger.info(f"- {p}")
                    
            if produtos_com_erro:
                logger.info("\nVariantes com erro:")
                for p in sorted(produtos_com_erro):
                    logger.info(f"- {p}")
            
            return {
                'atualizados': produtos_atualizados,
                'nao_encontrados': produtos_nao_encontrados,
                'sem_alteracao': produtos_sem_divergencia,
                'com_erro': produtos_com_erro
            }
            
        finally:
            shopify.ShopifyResource.clear_session()
            
    except Exception as e:
        logger.error(f"Erro fatal durante sincronização: {str(e)}")
        return False

def retry_operation(operation, max_retries=3, delay=1.0):
    """Executa uma operação com retry em caso de falha"""
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                sleep_time = delay * (attempt + 1)  # Backoff exponencial
                logging.warning(f"Tentativa {attempt + 1} falhou, aguardando {sleep_time}s para retry...")
                time.sleep(sleep_time)
            else:
                logging.error(f"Todas as {max_retries} tentativas falharam")
                
    if last_exception:
        raise last_exception

def main():
    """Função principal que coordena o processo de sincronização"""
    try:
        # Configura logging
        if not setup_logging():
            print("Falha ao configurar logging")
            return False
            
        logging.info("Iniciando processo de sincronização...")
        
        # Configura Shopify
        if not configurar_sessao_shopify():
            logging.error("Falha ao configurar Shopify")
            return False
            
        # Configura Hiper
        if not configurar_hiper():
            logging.error("Falha ao configurar Hiper")
            return False
            
        # Executa sincronização
        return sincronizar_estoque()
        
    except Exception as e:
        logging.error(f"Erro fatal durante sincronização: {str(e)}")
        return False
    finally:
        shopify.ShopifyResource.clear_session()
        logging.info("Processo de sincronização finalizado")

if __name__ == "__main__":
    main() 