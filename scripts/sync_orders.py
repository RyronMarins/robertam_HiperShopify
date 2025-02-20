import os
import json
import time
import logging
import shopify
from datetime import datetime
from config import (
    configurar_shopify,
    setup_logging,
    LOG_DIR,
    BASE_DIR
)

# Configuração do arquivo de cache
CACHE_DIR = os.path.join(BASE_DIR, "cache")
ORDERS_CACHE_FILE = os.path.join(CACHE_DIR, "synced_orders.json")

def setup_cache():
    """Configura o diretório e arquivo de cache"""
    logger = logging.getLogger(__name__)
    logger.info("Configurando sistema de cache...")
    
    try:
        # Cria diretório de cache se não existir
        if not os.path.exists(CACHE_DIR):
            logger.info(f"Criando diretório de cache: {CACHE_DIR}")
            os.makedirs(CACHE_DIR)
            
        # Cria arquivo de cache se não existir
        if not os.path.exists(ORDERS_CACHE_FILE):
            logger.info(f"Criando arquivo de cache: {ORDERS_CACHE_FILE}")
            with open(ORDERS_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    "last_sync": None,
                    "synced_orders": []
                }, f, ensure_ascii=False, indent=2)
        else:
            logger.info("Arquivo de cache já existe")
                
        return True
    except Exception as e:
        logger.error(f"Erro ao configurar cache: {str(e)}")
        return False

def get_synced_orders():
    """Recupera lista de pedidos já sincronizados"""
    logger = logging.getLogger(__name__)
    
    try:
        with open(ORDERS_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
            
        synced_orders = cache.get("synced_orders", [])
        last_sync = cache.get("last_sync")
        
        logger.info(f"Cache carregado - Última sincronização: {last_sync}")
        logger.info(f"Total de pedidos em cache: {len(synced_orders)}")
        
        return synced_orders, last_sync
    except Exception as e:
        logger.error(f"Erro ao ler cache: {str(e)}")
        return [], None

def update_synced_orders(order_id):
    """Atualiza cache com novo pedido sincronizado"""
    logger = logging.getLogger(__name__)
    
    try:
        with open(ORDERS_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
            
        if order_id not in cache["synced_orders"]:
            logger.info(f"Adicionando pedido {order_id} ao cache")
            cache["synced_orders"].append(order_id)
            cache["last_sync"] = datetime.now().isoformat()
            
            with open(ORDERS_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Cache atualizado com sucesso")
            return True
        else:
            logger.info(f"Pedido {order_id} já existe no cache")
            return True
            
    except Exception as e:
        logger.error(f"Erro ao atualizar cache: {str(e)}")
        return False

def configurar_sessao_shopify(session_configured=False):
    """Configura a sessão da Shopify"""
    logger = logging.getLogger(__name__)
    
    try:
        if session_configured:
            return True
            
        # Obtém configurações da Shopify
        shop_url = configurar_shopify()  # Retorna o shop_name do config.py
        api_version = '2024-01'
        password = os.getenv("PASSWORD")
        
        if not shop_url or not password:
            logger.error("Credenciais da Shopify não encontradas")
            return False
            
        # Limpa sessão anterior
        shopify.ShopifyResource.clear_session()
        logger.info("Sessão anterior limpa")
        
        # Configura nova sessão
        session = shopify.Session(shop_url, api_version, password)
        shopify.ShopifyResource.activate_session(session)
        logger.info("Nova sessão Shopify ativada")
        
        # Testa a conexão
        test = shopify.Shop.current()
        if not test:
            logger.error("Não foi possível conectar à Shopify")
            return False
            
        logger.info("Conexão com Shopify estabelecida com sucesso")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao configurar sessão Shopify: {str(e)}")
        return False

def buscar_pedidos_shopify(session_configured=False, max_orders=None):
    """
    Busca pedidos da Shopify usando paginação
    
    Args:
        session_configured (bool): Se a sessão já está configurada
        max_orders (int): Número máximo de pedidos a buscar (opcional)
    """
    logger = logging.getLogger(__name__)
    logger.info("Iniciando busca de pedidos na Shopify...")
    
    try:
        # Configura sessão Shopify se necessário
        if not configurar_sessao_shopify(session_configured):
            logger.error("Falha ao configurar sessão Shopify")
            return []
            
        pedidos = []
        next_page_url = None
        limit = 250  # Limite máximo por página
        
        # Recupera pedidos já sincronizados
        synced_orders, last_sync = get_synced_orders()
        logger.info(f"Última sincronização: {last_sync}")
            
        while True:
            try:
                # Verifica se atingiu limite máximo de pedidos
                if max_orders and len(pedidos) >= max_orders:
                    logger.info(f"Limite máximo de pedidos atingido: {max_orders}")
                    break
                
                # Verifica limites de API
                if shopify.ShopifyResource.connection.response:
                    call_limit = shopify.ShopifyResource.connection.response.headers.get('X-Shopify-Shop-Api-Call-Limit')
                    if call_limit:
                        current, limit_max = map(int, call_limit.split('/'))
                        logger.debug(f"API Limit: {current}/{limit_max}")
                        if current >= limit_max - 5:  # Margem de segurança
                            logger.info("Aguardando reset do limite de API...")
                            time.sleep(2)
                
                # Primeira página ou próximas páginas
                if next_page_url:
                    logger.debug(f"Buscando próxima página: {next_page_url}")
                    batch = shopify.Order.find(from_=next_page_url)
                else:
                    logger.info("Buscando primeira página de pedidos...")
                    # Busca pedidos ordenados por data de criação (mais recentes primeiro)
                    batch = shopify.Order.find(
                        limit=limit,
                        order="created_at DESC",
                        status="any"  # Busca todos os status conforme solicitado
                    )
                
                if not batch:
                    logger.info("Nenhum pedido encontrado nesta página")
                    break
                    
                # Filtra pedidos já sincronizados
                for pedido in batch:
                    if str(pedido.id) not in synced_orders:
                        pedidos.append(pedido)
                        logger.info(f"Novo pedido encontrado: #{pedido.order_number} (ID: {pedido.id})")
                        
                        # Atualiza cache para cada pedido encontrado
                        if update_synced_orders(str(pedido.id)):
                            logger.info(f"Pedido #{pedido.order_number} adicionado ao cache")
                        
                        if max_orders and len(pedidos) >= max_orders:
                            break
                
                # Verifica se há próxima página
                response = shopify.ShopifyResource.connection.response
                if not response or 'Link' not in response.headers:
                    logger.info("Não há mais páginas para buscar")
                    break
                    
                # Extrai URL da próxima página
                link_header = response.headers['Link']
                if 'rel="next"' not in link_header:
                    logger.info("Não há link para próxima página")
                    break
                    
                next_page_url = None
                for link in link_header.split(','):
                    if 'rel="next"' in link:
                        next_page_url = link.split(';')[0].strip('<> ')
                        break
                
                if not next_page_url:
                    logger.info("Não foi possível extrair URL da próxima página")
                    break
                    
                logger.debug("Aguardando antes da próxima requisição...")
                time.sleep(0.5)  # Respeita rate limit
                
            except Exception as e:
                logger.error(f"Erro ao buscar lote de pedidos: {str(e)}")
                break
        
        logger.info(f"Total de novos pedidos encontrados: {len(pedidos)}")
        return pedidos
        
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos: {str(e)}")
        return []
    finally:
        if not session_configured:
            logger.info("Limpando sessão Shopify")
            shopify.ShopifyResource.clear_session()

def mapear_pedido_para_hiper(pedido_shopify):
    """
    Mapeia um pedido da Shopify para o formato do Hiper
    
    Args:
        pedido_shopify: Objeto Order da Shopify
    Returns:
        dict: Pedido no formato do Hiper
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Mapeando pedido #{pedido_shopify.order_number} para formato Hiper")
    
    try:
        # Obtém dados básicos com validações
        order_number = getattr(pedido_shopify, 'order_number', 'N/A')
        customer = getattr(pedido_shopify, 'customer', None)
        billing_address = getattr(pedido_shopify, 'billing_address', None)
        shipping_address = getattr(pedido_shopify, 'shipping_address', None)
        email = getattr(pedido_shopify, 'email', '')
        total_price = getattr(pedido_shopify, 'total_price', '0.00')
        
        # Log dos dados recebidos para debug
        logger.info("\nDados do pedido original:")
        logger.info(f"ID: {getattr(pedido_shopify, 'id', 'N/A')}")
        logger.info(f"Número: {order_number}")
        logger.info(f"Email: {email}")
        logger.info(f"Total: {total_price}")
        
        # Dados do cliente
        cliente = {
            "documento": "",
            "email": email,
            "inscricaoEstadual": "",
            "nomeDoCliente": "Cliente E-commerce",
            "nomeFantasia": ""
        }
        
        # Atualiza dados do cliente se disponível
        if customer:
            # Nome do cliente
            first_name = getattr(customer, 'first_name', '')
            last_name = getattr(customer, 'last_name', '')
            nome_completo = ' '.join(filter(None, [first_name, last_name]))
            if nome_completo:
                cliente["nomeDoCliente"] = nome_completo
                
            # Documento (usando telefone como fallback)
            phone = getattr(customer, 'phone', '')
            if phone:
                cliente["documento"] = phone.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
        
        # Endereço de cobrança
        endereco_cobranca = {
            "bairro": "",
            "cep": "",
            "codigoIbge": 0,
            "complemento": "",
            "logradouro": "",
            "numero": "S/N"
        }
        
        if billing_address:
            endereco_cobranca.update({
                "bairro": getattr(billing_address, 'district', ''),
                "cep": getattr(billing_address, 'zip', '').replace("-", ""),
                "complemento": getattr(billing_address, 'company', ''),
                "logradouro": getattr(billing_address, 'address1', ''),
                "numero": getattr(billing_address, 'address2', 'S/N') or 'S/N'
            })
        
        # Endereço de entrega
        endereco_entrega = {
            "bairro": "",
            "cep": "",
            "codigoIbge": 0,
            "complemento": "",
            "logradouro": "",
            "numero": "S/N"
        }
        
        if shipping_address:
            endereco_entrega.update({
                "bairro": getattr(shipping_address, 'district', ''),
                "cep": getattr(shipping_address, 'zip', '').replace("-", ""),
                "complemento": getattr(shipping_address, 'company', ''),
                "logradouro": getattr(shipping_address, 'address1', ''),
                "numero": getattr(shipping_address, 'address2', 'S/N') or 'S/N'
            })
        
        # Itens do pedido
        itens = []
        line_items = getattr(pedido_shopify, 'line_items', [])
        for item in line_items:
            preco = float(getattr(item, 'price', 0))
            quantidade = int(getattr(item, 'quantity', 0))
            desconto = float(getattr(item, 'total_discount', 0))
            
            item_hiper = {
                "produtoId": "",  # TODO: Implementar busca do ID do produto no Hiper
                "quantidade": quantidade,
                "precoUnitarioBruto": preco,
                "precoUnitarioLiquido": preco - (desconto / quantidade if quantidade > 0 else 0)
            }
            itens.append(item_hiper)
        
        # Meio de pagamento
        meios_pagamento = [{
            "idMeioDePagamento": 1,  # TODO: Mapear método de pagamento
            "parcelas": 1,
            "valor": float(total_price)
        }]
        
        # Valor do frete
        shipping_price = 0
        if hasattr(pedido_shopify, 'total_shipping_price_set'):
            shipping_price_set = getattr(pedido_shopify, 'total_shipping_price_set', {})
            if isinstance(shipping_price_set, dict):
                shop_money = shipping_price_set.get('shop_money', {})
                if isinstance(shop_money, dict):
                    shipping_price = float(shop_money.get('amount', 0))
        
        # Monta pedido completo
        pedido_hiper = {
            "cliente": cliente,
            "enderecoDeCobranca": endereco_cobranca,
            "enderecoDeEntrega": endereco_entrega,
            "itens": itens,
            "meiosDePagamento": meios_pagamento,
            "numeroPedidoDeVenda": str(order_number),
            "observacaoDoPedidoDeVenda": f"Pedido Shopify #{order_number}",
            "valorDoFrete": shipping_price,
            "Marketplace": {
                "Cnpj": "12605982000124",  # TODO: Configurar CNPJ correto
                "Nome": "Shopify"
            }
        }
        
        # Log do pedido completo mapeado
        logger.info("\nPedido mapeado com sucesso:")
        logger.info(json.dumps(pedido_hiper, indent=2, ensure_ascii=False))
        
        return pedido_hiper
        
    except Exception as e:
        logger.error(f"Erro ao mapear pedido #{getattr(pedido_shopify, 'order_number', 'N/A')}: {str(e)}")
        logger.exception("Detalhes do erro:")
        return None

def simular_envio_hiper(pedido_hiper):
    """
    Simula o envio de um pedido para o Hiper (dry-run)
    
    Args:
        pedido_hiper: Pedido no formato do Hiper
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Simula validações
        validacoes = []
        
        if not pedido_hiper["cliente"]["documento"]:
            validacoes.append("Documento do cliente não informado")
            
        if not pedido_hiper["cliente"]["email"]:
            validacoes.append("Email do cliente não informado")
            
        if not pedido_hiper["enderecoDeEntrega"]["cep"]:
            validacoes.append("CEP de entrega não informado")
            
        if not pedido_hiper["itens"]:
            validacoes.append("Pedido sem itens")
            
        # Simula o que seria enviado para API
        logger.info(f"[SIMULAÇÃO] Enviando pedido #{pedido_hiper['numeroPedidoDeVenda']} para Hiper")
        logger.info(f"[SIMULAÇÃO] URL: https://ms-ecommerce.hiper.com.br/api/v1/pedido-de-venda/")
        logger.info(f"[SIMULAÇÃO] Método: POST")
        logger.info(f"[SIMULAÇÃO] Headers: Content-Type: application/json")
        logger.info(f"[SIMULAÇÃO] Payload: {json.dumps(pedido_hiper, indent=2, ensure_ascii=False)}")
        
        if validacoes:
            logger.warning(f"[SIMULAÇÃO] Validações pendentes: {validacoes}")
        else:
            logger.info("[SIMULAÇÃO] Pedido válido para envio")
            
    except Exception as e:
        logger.error(f"Erro ao simular envio: {str(e)}")

def main():
    """Função principal que coordena o processo de sincronização"""
    try:
        # Configura logging
        if not setup_logging():
            print("Falha ao configurar logging")
            return False
            
        logger = logging.getLogger(__name__)
        logger.info("Iniciando processo de sincronização de pedidos...")
            
        # Configura cache
        if not setup_cache():
            logger.error("Falha ao configurar cache")
            return False
            
        # Configura Shopify e mantém a sessão ativa
        logger.info("Configurando sessão Shopify...")
        if not configurar_sessao_shopify():
            logger.error("Falha ao configurar Shopify")
            return False
            
        # Busca novos pedidos (limitando a 1 para teste)
        logger.info("Buscando pedidos novos...")
        pedidos = buscar_pedidos_shopify(session_configured=True, max_orders=1)
        
        if not pedidos:
            logger.info("Nenhum pedido novo encontrado")
            return True
            
        logger.info(f"Encontrados {len(pedidos)} pedidos para processar")
            
        # Processa cada pedido
        for pedido in pedidos:
            logger.info(f"\n{'='*50}")
            logger.info(f"Processando pedido #{pedido.order_number}")
            logger.info(f"{'='*50}\n")
            
            # Exibe informações do pedido original com validações
            logger.info("Dados do pedido Shopify:")
            logger.info(f"ID: {pedido.id}")
            
            # Dados do cliente com validações
            customer = getattr(pedido, 'customer', None)
            first_name = getattr(customer, 'first_name', 'N/A') if customer else 'N/A'
            last_name = getattr(customer, 'last_name', 'N/A') if customer else 'N/A'
            email = getattr(pedido, 'email', 'N/A')
            total_price = getattr(pedido, 'total_price', '0.00')
            line_items = getattr(pedido, 'line_items', [])
            
            logger.info(f"Cliente: {first_name} {last_name}")
            logger.info(f"Email: {email}")
            logger.info(f"Total: {total_price}")
            logger.info(f"Itens: {len(line_items)}")
            
            # Mapeia pedido para formato Hiper
            logger.info("\nIniciando mapeamento para Hiper...")
            pedido_hiper = mapear_pedido_para_hiper(pedido)
            if not pedido_hiper:
                logger.error(f"Falha ao mapear pedido #{pedido.order_number}")
                continue
                
            # Simula envio para Hiper
            logger.info("\nSimulando envio para Hiper...")
            simular_envio_hiper(pedido_hiper)
            
            logger.info(f"\n{'='*50}")
            
        logger.info("\nProcesso de sincronização concluído com sucesso")
        return True
        
    except Exception as e:
        logger.error(f"Erro fatal durante sincronização: {str(e)}")
        logger.exception("Detalhes do erro:")  # Adiciona stack trace para debug
        return False
    finally:
        shopify.ShopifyResource.clear_session()
        logger.info("Processo finalizado")

if __name__ == "__main__":
    main()
