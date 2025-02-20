import requests
import shopify
import logging
import os
from dotenv import load_dotenv
from .config import configurar_shopify, configurar_hiper

# Configuração do logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sync_stock.log'),
        logging.StreamHandler()
    ]
)

def verificar_estoque(sku_teste="C0800542"):
    """Verifica o estoque de um produto específico no Hiper e na Shopify"""
    logging.info(f"Verificando estoque para SKU {sku_teste}...")
    
    # Configurar Shopify
    shop_url = configurar_shopify()
    session = shopify.Session(shop_url, '2024-01', os.getenv("PASSWORD"))
    shopify.ShopifyResource.activate_session(session)
    
    try:
        # Configurar Hiper
        config_hiper = configurar_hiper()
        
        # Buscar produto no Hiper
        url_hiper = f"{config_hiper['url_base']}/produtos/pontoDeSincronizacao"
        response_hiper = requests.get(url_hiper, headers=config_hiper['headers'])
        response_hiper.raise_for_status()
        produtos_hiper = response_hiper.json()['produtos']
        
        # Encontrar produto específico no Hiper
        produto_hiper = next(
            (p for p in produtos_hiper if p['codigoDeBarras'] == sku_teste),
            None
        )
        
        if produto_hiper:
            estoque_hiper = produto_hiper.get('quantidadeEmEstoque', 0)
            nome_produto = produto_hiper.get('nome', 'Nome não encontrado')
            logging.info(f"Hiper - Produto: {nome_produto}")
            logging.info(f"Hiper - Estoque: {estoque_hiper}")
        else:
            logging.error(f"Produto {sku_teste} não encontrado no Hiper")
            return
            
        # Buscar produto na Shopify
        produtos_shopify = shopify.Product.find()
        produto_encontrado = False
        
        for produto in produtos_shopify:
            for variante in produto.variants:
                if variante.sku == sku_teste:
                    produto_encontrado = True
                    logging.info(f"Shopify - Produto: {produto.title} - Variante: {variante.title}")
                    
                    # Verificar estoque na Shopify
                    inventory_item_id = variante.inventory_item_id
                    locations = shopify.Location.find()
                    if locations:
                        try:
                            inventory_level = shopify.InventoryLevel.find(
                                inventory_item_ids=inventory_item_id,
                                location_ids=locations[0].id
                            )
                            if inventory_level:
                                estoque_shopify = inventory_level[0].available
                                logging.info(f"Shopify - Estoque: {estoque_shopify}")
                                
                                # Comparar estoques
                                if estoque_hiper != estoque_shopify:
                                    logging.warning(f"Divergência de estoque detectada!")
                                    logging.warning(f"Hiper: {estoque_hiper} | Shopify: {estoque_shopify}")
                                else:
                                    logging.info("Estoques estão sincronizados!")
                                    
                        except Exception as e:
                            logging.error(f"Erro ao verificar estoque na Shopify: {str(e)}")
                    break
            
            if produto_encontrado:
                break
                
        if not produto_encontrado:
            logging.error(f"Produto {sku_teste} não encontrado na Shopify")
        
    except Exception as e:
        logging.error(f"Erro durante a verificação: {str(e)}")
    finally:
        shopify.ShopifyResource.clear_session()

def sincronizar_estoque(sku_teste="C0800542"):
    """Sincroniza o estoque entre Hiper e Shopify para um produto específico"""
    logging.info(f"Iniciando sincronização de estoque para SKU {sku_teste}...")
    
    # Configurar Shopify
    shop_url = configurar_shopify()
    session = shopify.Session(shop_url, '2024-01', os.getenv("PASSWORD"))
    shopify.ShopifyResource.activate_session(session)
    
    try:
        # Configurar Hiper
        config_hiper = configurar_hiper()
        
        # Buscar produtos do Hiper
        url_hiper = f"{config_hiper['url_base']}/produtos/pontoDeSincronizacao"
        response_hiper = requests.get(url_hiper, headers=config_hiper['headers'])
        response_hiper.raise_for_status()
        produtos_hiper = response_hiper.json()['produtos']
        
        # Encontrar produto específico no Hiper
        produto_hiper = next(
            (p for p in produtos_hiper if p['codigoDeBarras'] == sku_teste),
            None
        )
        
        if not produto_hiper:
            logging.error(f"Produto {sku_teste} não encontrado no Hiper")
            return
            
        novo_estoque = produto_hiper.get('quantidadeEmEstoque', 0)
        logging.info(f"Estoque no Hiper: {novo_estoque}")
        
        # Buscar produto na Shopify
        produtos_shopify = shopify.Product.find()
        produto_encontrado = False
        
        for produto in produtos_shopify:
            for variante in produto.variants:
                if variante.sku == sku_teste:
                    produto_encontrado = True
                    logging.info(f"Produto encontrado na Shopify: {produto.title} - Variante: {variante.title}")
                    
                    # Atualizar estoque na Shopify
                    inventory_item_id = variante.inventory_item_id
                    locations = shopify.Location.find()
                    if locations:
                        try:
                            shopify.InventoryLevel.set(
                                location_id=locations[0].id,
                                inventory_item_id=inventory_item_id,
                                available=novo_estoque
                            )
                            logging.info(f"Estoque atualizado com sucesso para {novo_estoque} unidades")
                        except Exception as e:
                            logging.error(f"Erro ao atualizar estoque: {str(e)}")
                    break
            
            if produto_encontrado:
                break
                
        if not produto_encontrado:
            logging.error(f"Produto {sku_teste} não encontrado na Shopify")
        
    except Exception as e:
        logging.error(f"Erro durante a sincronização: {str(e)}")
    finally:
        shopify.ShopifyResource.clear_session()

if __name__ == "__main__":
    load_dotenv()
    # Primeiro verifica o estoque atual
    verificar_estoque()
    # Depois sincroniza se necessário
    sincronizar_estoque() 