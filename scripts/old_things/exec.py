import shopify
import requests
import os
from config import configurar_shopify, configurar_hiper
import pandas as pd
import csv
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

def comparar_produtos():
    # Configurar Shopify
    shop_url = configurar_shopify()
    session = shopify.Session(shop_url, '2024-01', os.getenv("PASSWORD"))
    shopify.ShopifyResource.activate_session(session)

    # Configurar Hiper
    config_hiper = configurar_hiper()

    # Consultar produtos da Hiper
    url_hiper = f"{config_hiper['url_base']}/produtos/pontoDeSincronizacao"
    response_hiper = requests.get(url_hiper, headers=config_hiper['headers'])
    response_hiper.raise_for_status()
    produtos_hiper = response_hiper.json()['produtos']

    # Consultar todos os produtos da Shopify, incluindo arquivados
    produtos_shopify = []
    has_next_page = True
    next_page_url = None

    while has_next_page:
        if next_page_url:
            produtos = shopify.Product.find(limit=250, page_info=next_page_url, published_status='any')
        else:
            produtos = shopify.Product.find(limit=250, published_status='any')

        produtos_shopify.extend(produtos)

        # Verificar se há uma próxima página
        if 'Link' in shopify.ShopifyResource.connection.response.headers:
            links = shopify.ShopifyResource.connection.response.headers['Link']
            if 'rel="next"' in links:
                next_page_url = links.split(';')[0].strip('<>')
            else:
                has_next_page = False
        else:
            has_next_page = False

    # Criar um conjunto de SKUs da Shopify
    skus_shopify = {variante.sku for produto in produtos_shopify for variante in produto.variants if variante.sku}

    # Contar quantos produtos do Hiper estão na Shopify
    produtos_encontrados = 0
    skus_nao_encontrados = []

    for produto in produtos_hiper:
        sku_original = produto['codigoDeBarras']
        
        # Verificar se o SKU original está na lista de SKUs da Shopify
        if sku_original in skus_shopify:
            produtos_encontrados += 1
        else:
            # Verificar também se o SKU com tamanho está presente
            encontrado = False
            for tamanho in ['34', '36', '38', '40', '42']:
                sku_com_tamanho = f"{sku_original}{tamanho}"
                if sku_com_tamanho in skus_shopify:
                    produtos_encontrados += 1
                    encontrado = True
                    break  # Se encontrar, não precisa verificar outros tamanhos
            
            if not encontrado:
                skus_nao_encontrados.append(sku_original)

    # Salvar SKUs não encontrados em um arquivo CSV
    with open('skus_nao_encontrados.csv', 'w', newline='') as csvfile:
        fieldnames = ['SKU']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for sku in skus_nao_encontrados:
            writer.writerow({'SKU': sku})

    # Exibir o resultado
    total_hiper = len(produtos_hiper)
    print(f"Total de produtos cadastrados no Hiper: {total_hiper}")
    print(f"Total de produtos cadastrados na Shopify que não são variantes: {len(produtos_shopify)}")
    print(f"Total de produtos do Hiper que estão cadastrados na Shopify: {produtos_encontrados}")
    print(f"Total de SKUs do Hiper não encontrados na Shopify: {len(skus_nao_encontrados)}")

if __name__ == "__main__":
    comparar_produtos()
    # analisar_csv()