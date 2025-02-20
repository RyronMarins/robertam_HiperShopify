import requests
import shopify
import logging
import os
import json
from dotenv import load_dotenv
from config import configurar_shopify, configurar_hiper

# Configuração do logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sincronizacao.log'),
        logging.StreamHandler()
    ]
)

def buscar_produtos_shopify():
    """Busca todos os produtos da Shopify, incluindo variantes"""
    produtos = []
    page_info = None
    
    while True:
        if page_info:
            batch = shopify.Product.find(limit=250, page_info=page_info, published_status='any')
        else:
            batch = shopify.Product.find(limit=250, published_status='any')
            
        produtos.extend(batch)
        
        # Verificar próxima página
        if not hasattr(shopify.ShopifyResource.connection.response, 'headers') or \
           'Link' not in shopify.ShopifyResource.connection.response.headers or \
           'next' not in shopify.ShopifyResource.connection.response.headers['Link']:
            break
            
        page_info = shopify.ShopifyResource.connection.response.headers['Link']
    
    return produtos

def analisar_produtos():
    """Analisa e compara produtos entre Hiper e Shopify"""
    logging.info("Iniciando análise de produtos...")
    
    # Configurar Shopify
    shop_url = configurar_shopify()
    session = shopify.Session(shop_url, '2024-01', os.getenv("PASSWORD"))
    shopify.ShopifyResource.activate_session(session)
    
    # Buscar produtos Hiper
    config_hiper = configurar_hiper()
    url_hiper = f"{config_hiper['url_base']}/produtos/pontoDeSincronizacao"
    response_hiper = requests.get(url_hiper, headers=config_hiper['headers'])
    response_hiper.raise_for_status()
    produtos_hiper = response_hiper.json()['produtos']
    
    # Buscar produtos Shopify
    produtos_shopify = buscar_produtos_shopify()
    
    # Mapear produtos por SKU
    produtos_hiper_map = {
        p['codigoDeBarras']: {
            'nome': p['nome'],
            'sku': p['codigoDeBarras'],
            'preco': p.get('preco', 0),
            'estoque': p.get('quantidadeEmEstoque', 0)
        } for p in produtos_hiper if not str(p['codigoDeBarras']).isdigit()  # Excluir SKUs numéricos
    }
    
    produtos_shopify_map = {}
    for p in produtos_shopify:
        for v in p.variants:
            if v.sku:
                sku_base = v.sku[:-2] if len(v.sku) > 2 else v.sku
                produtos_shopify_map[sku_base] = {
                    'nome': p.title,
                    'sku': sku_base,
                    'id': p.id,
                    'preco': float(v.price) if v.price else 0
                }
    
    # Análise comparativa
    em_ambos = []
    apenas_hiper = []
    apenas_shopify = []
    
    # Verificar produtos em ambos e apenas no Hiper
    for sku, produto in produtos_hiper_map.items():
        if sku in produtos_shopify_map:
            em_ambos.append({
                'sku': sku,
                'nome_hiper': produto['nome'],
                'nome_shopify': produtos_shopify_map[sku]['nome'],
                'preco_hiper': produto['preco'],
                'preco_shopify': produtos_shopify_map[sku]['preco']
            })
        else:
            apenas_hiper.append({
                'sku': sku,
                'nome': produto['nome'],
                'preco': produto['preco']
            })
    
    # Verificar produtos apenas na Shopify
    for sku, produto in produtos_shopify_map.items():
        if sku not in produtos_hiper_map:
            apenas_shopify.append({
                'sku': sku,
                'nome': produto['nome'],
                'preco': produto['preco'],
                'id': produto['id']
            })
    
    # Gerar relatório
    relatorio = {
        'resumo': {
            'total_hiper': len(produtos_hiper_map),
            'total_shopify': len(produtos_shopify_map),
            'em_ambos': len(em_ambos),
            'apenas_hiper': len(apenas_hiper),
            'apenas_shopify': len(apenas_shopify)
        },
        'produtos_em_ambos': em_ambos,
        'produtos_apenas_hiper': apenas_hiper,
        'produtos_apenas_shopify': apenas_shopify
    }
    
    # Salvar relatório
    with open('relatorio_sincronizacao.json', 'w', encoding='utf-8') as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)
    
    # Exibir resumo
    logging.info("\n=== RESUMO DA ANÁLISE ===")
    logging.info(f"Total de produtos no Hiper: {relatorio['resumo']['total_hiper']}")
    logging.info(f"Total de produtos na Shopify: {relatorio['resumo']['total_shopify']}")
    logging.info(f"Produtos em ambas plataformas: {relatorio['resumo']['em_ambos']}")
    logging.info(f"Produtos apenas no Hiper: {relatorio['resumo']['apenas_hiper']}")
    logging.info(f"Produtos apenas na Shopify: {relatorio['resumo']['apenas_shopify']}")
    logging.info("\nRelatório detalhado salvo em 'relatorio_sincronizacao.json'")
    
    return relatorio

if __name__ == "__main__":
    load_dotenv()
    analisar_produtos()