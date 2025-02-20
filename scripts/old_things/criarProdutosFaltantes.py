import shopify
import requests
import os
import pandas as pd
from dotenv import load_dotenv
from config import configurar_shopify, configurar_hiper
import logging
import re
from datetime import datetime
import time
import json

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('criacao_produtos.log'),
        logging.StreamHandler()
    ]
)

def verificar_produto_existente(sku_base):
    """
    Verifica se já existe um produto com o SKU base informado
    """
    try:
        # Buscar produtos com o SKU base
        produtos = shopify.Product.find(vendor="Marca não especificada")
        for produto in produtos:
            for variante in produto.variants:
                if variante.sku and variante.sku.startswith(sku_base):
                    return True, produto.id
        return False, None
    except Exception as e:
        logging.error(f"Erro ao verificar produto existente: {str(e)}")
        return False, None

def criar_produto_shopify(produto_hiper):
    """
    Cria um produto na Shopify baseado nos dados do Hiper
    """
    try:
        # Verificar se o produto já existe
        sku_base = produto_hiper['codigoDeBarras']
        produto_existe, produto_id = verificar_produto_existente(sku_base)
        
        if produto_existe:
            return {
                'sucesso': False,
                'erro': f"Produto já existe (ID: {produto_id})",
                'ja_existe': True
            }

        # Criar produto base
        novo_produto = shopify.Product()
        novo_produto.title = produto_hiper['nome']
        novo_produto.body_html = produto_hiper.get('descricao', '')
        novo_produto.vendor = produto_hiper.get('marca', 'Marca não especificada')
        novo_produto.product_type = produto_hiper.get('categoria', 'Categoria não especificada')
        
        # Configurar variantes
        tamanhos = ['36', '38', '40', '42']  # Tamanhos padrão
        
        novo_produto.options = [
            {
                "name": "Tamanho",
                "values": tamanhos
            }
        ]
        
        # Criar variantes
        variantes = []
        preco = float(produto_hiper.get('preco', 0))
        
        for tamanho in tamanhos:
            variante = shopify.Variant({
                "option1": tamanho,
                "sku": f"{sku_base}{tamanho}",
                "price": preco,
                "inventory_management": "shopify",
                "inventory_quantity": 0,  # Estoque inicial zero
                "requires_shipping": True
            })
            variantes.append(variante)
        
        novo_produto.variants = variantes
        
        # Salvar produto
        if novo_produto.save():
            return {
                'sucesso': True,
                'produto': {
                    'id': novo_produto.id,
                    'title': novo_produto.title,
                    'sku_base': sku_base,
                    'variantes': [v.sku for v in novo_produto.variants]
                }
            }
        else:
            return {
                'sucesso': False,
                'erro': novo_produto.errors.full_messages()
            }
            
    except Exception as e:
        return {
            'sucesso': False,
            'erro': str(e)
        }

def criar_todos_produtos():
    """
    Cria todos os produtos do Hiper na Shopify, exceto SKUs numéricos
    """
    try:
        inicio = time.time()
        logging.info("\n=== INICIANDO CRIAÇÃO DE PRODUTOS ===")
        
        # Configurar Shopify
        shop_url = configurar_shopify()
        session = shopify.Session(shop_url, '2024-01', os.getenv("PASSWORD"))
        shopify.ShopifyResource.activate_session(session)
        
        # Configurar Hiper
        config_hiper = configurar_hiper()
        
        # Buscar produtos do Hiper
        url_hiper = f"{config_hiper['url_base']}/produtos/pontoDeSincronizacao"
        response_hiper = requests.get(url_hiper, headers=config_hiper['headers'])
        response_hiper.raise_for_status()
        produtos_hiper = response_hiper.json()['produtos']
        
        # Filtrar produtos (remover SKUs numéricos)
        produtos_validos = [p for p in produtos_hiper if not str(p['codigoDeBarras']).isdigit()]
        
        logging.info(f"\nTotal de produtos no Hiper: {len(produtos_hiper)}")
        logging.info(f"Produtos válidos para criar: {len(produtos_validos)}")
        
        # Resultados
        resultados = {
            'criados': [],
            'erros': [],
            'ja_existentes': [],
            'total': len(produtos_validos),
            'sucesso': 0,
            'falha': 0,
            'duplicatas': 0
        }
        
        # Criar produtos
        for i, produto in enumerate(produtos_validos, 1):
            logging.info(f"\nProcessando produto {i}/{len(produtos_validos)}: {produto['nome']} (SKU: {produto['codigoDeBarras']})")
            
            resultado = criar_produto_shopify(produto)
            if resultado['sucesso']:
                resultados['criados'].append(resultado['produto'])
                resultados['sucesso'] += 1
                logging.info(f"✅ Produto criado com sucesso!")
            elif resultado.get('ja_existe'):
                resultados['ja_existentes'].append({
                    'sku': produto['codigoDeBarras'],
                    'nome': produto['nome']
                })
                resultados['duplicatas'] += 1
                logging.info(f"⚠️ Produto já existe na Shopify")
            else:
                resultados['erros'].append({
                    'sku': produto['codigoDeBarras'],
                    'nome': produto['nome'],
                    'erro': resultado['erro']
                })
                resultados['falha'] += 1
                logging.error(f"❌ Erro ao criar produto: {resultado['erro']}")
            
            # Salvar progresso a cada 10 produtos
            if i % 10 == 0:
                with open('progresso_criacao.json', 'w') as f:
                    json.dump(resultados, f, indent=2)
        
        # Relatório final
        tempo_total = time.time() - inicio
        logging.info("\n=== RELATÓRIO FINAL ===")
        logging.info(f"Tempo total: {tempo_total:.2f} segundos")
        logging.info(f"Total de produtos processados: {len(produtos_validos)}")
        logging.info(f"Produtos criados com sucesso: {resultados['sucesso']}")
        logging.info(f"Produtos já existentes: {resultados['duplicatas']}")
        logging.info(f"Falhas: {resultados['falha']}")
        
        if resultados['erros']:
            logging.info("\nErros encontrados:")
            for erro in resultados['erros']:
                logging.info(f"  - {erro['nome']} (SKU: {erro['sku']})")
                logging.info(f"    Erro: {erro['erro']}")
        
        # Salvar relatório final
        with open('relatorio_criacao.json', 'w') as f:
            json.dump(resultados, f, indent=2)
            
        return resultados
        
    except Exception as e:
        logging.error(f"Erro durante o processo: {str(e)}")
        logging.error("Stack trace:", exc_info=True)
        return None

if __name__ == "__main__":
    load_dotenv()
    criar_todos_produtos()