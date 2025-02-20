import requests
import shopify
import os
import logging
from config import configurar_shopify, configurar_hiper
import pandas as pd

# Configuração do logging
logging.basicConfig(filename='./logs/criacao_produtos.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Função para buscar todos os produtos na Hiper
def buscar_todos_produtos_hiper(config_hiper):
    url = f"{config_hiper['url_base']}/produtos/pontoDeSincronizacao"
    response = requests.get(url, headers=config_hiper['headers'])
    response.raise_for_status()
    return response.json()  # Retorna a lista de produtos

# Função para criar um novo produto na Shopify
def criar_produto_na_shopify(detalhes_hiper):
    produto_novo = shopify.Product()
    produto_novo.title = detalhes_hiper['nome']
    produto_novo.body_html = detalhes_hiper.get('descricao', 'Descrição não disponível')
    produto_novo.vendor = detalhes_hiper.get('marca', 'Fornecedor Desconhecido')
    produto_novo.product_type = detalhes_hiper.get('categoria', 'Tipo Desconhecido')

    # Cria uma nova variante
    nova_variante = shopify.Variant()
    nova_variante.title = "Size"
    nova_variante.option1 = detalhes_hiper['tamanho']  # Tamanho ou outra opção
    nova_variante.price = detalhes_hiper['preco']  # Preço da variante
    nova_variante.sku = detalhes_hiper['codigoDeBarras']  # SKU da variante
    nova_variante.inventory_quantity = detalhes_hiper['quantidadeEmEstoque']  # Estoque da variante

    # Adiciona a variante ao produto
    produto_novo.variants = [nova_variante]  # Adiciona a variante ao produto

    # Salvar o produto
    if produto_novo.save():
        logging.info(f"Produto {produto_novo.title} criado com sucesso.")
    else:
        logging.error(f"Erro ao criar produto: {produto_novo.errors.full_messages()}")

# Função para carregar SKUs existentes na Shopify
def carregar_skus_existentes():
    produtos_existentes = shopify.Product.find()
    skus_existentes = {produto.variants[0].sku for produto in produtos_existentes if produto.variants}
    return skus_existentes

# Função para carregar SKUs válidos do arquivo CSV
def carregar_skus_validos():
    skus_validos = set()
    df = pd.read_csv('./skus_nao_encontrados.csv')
    for sku in df['SKU']:
        if isinstance(sku, str) and sku.startswith('C'):
            skus_validos.add(sku)
    return skus_validos

# Função principal para criar um único produto
def criar_um_produto(config_hiper):
    try:
        dados_hiper = buscar_todos_produtos_hiper(config_hiper)
        produtos_hiper = dados_hiper.get('produtos', [])
        
        # Carregar SKUs existentes na Shopify
        skus_existentes = carregar_skus_existentes()
        # Carregar SKUs válidos
        skus_validos = carregar_skus_validos()

        for produto in produtos_hiper:
            sku = produto['codigoDeBarras']
            if sku and sku in skus_validos and sku not in skus_existentes:  # Verifica se o SKU é válido e não existe
                criar_produto_na_shopify(produto)  # Cria o produto na Shopify
                break  # Para após criar o primeiro produto válido
            else:
                logging.info(f"Produto com SKU {sku} é inválido ou já existe na Shopify. Ignorando.")

    except Exception as e:
        logging.error(f"Erro ao criar produtos: {e}")

# Chamada da função
if __name__ == "__main__":
    # Configurar Shopify e Hiper antes de chamar a função
    shop_url = configurar_shopify()  # Chama a função para configurar a Shopify
    config_hiper = configurar_hiper()  # Chama a função para configurar a Hiper

    # Ativar a sessão da Shopify
    session = shopify.Session(shop_url, '2024-07', os.getenv("PASSWORD"))  # Use a senha do aplicativo privado
    shopify.ShopifyResource.activate_session(session)

    criar_um_produto(config_hiper)  # Chama a função para criar um único produto
