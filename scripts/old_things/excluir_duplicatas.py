import json
import shopify
import os
import traceback
import time
import requests
from dotenv import load_dotenv
from config import configurar_shopify

def inicializar_shopify():
    """
    Inicializa a conexão com a Shopify usando as configurações do arquivo config.py
    """
    shop_url = configurar_shopify()
    session = shopify.Session(shop_url, '2024-01', os.getenv('PASSWORD'))
    shopify.ShopifyResource.activate_session(session)
    return shop_url

def deletar_produto_graphql(shop_url, produto_id, access_token):
    """
    Deleta um produto usando a API GraphQL do Shopify
    """
    headers = {
        'Content-Type': 'application/json',
        'X-Shopify-Access-Token': access_token
    }
    
    query = """
    mutation {
        productDelete(input: {id: "gid://shopify/Product/%s"}) {
            deletedProductId
            userErrors {
                field
                message
            }
        }
    }
    """ % produto_id
    
    url = f"https://{shop_url}/admin/api/2024-01/graphql.json"
    response = requests.post(url, headers=headers, json={'query': query})
    return response.json()

def excluir_produtos():
    try:
        with open('relatorio_criacao.json', 'r', encoding='utf-8') as f:
            relatorio = json.load(f)
            
        produtos_excluidos = []
        erros = []
        
        # Criar conjunto de SKUs do relatório para verificação rápida
        skus_para_excluir = {produto['sku_base'] for produto in relatorio['criados']}
        
        print(f"Iniciando exclusão de {len(relatorio['criados'])} produtos...")
        print(f"SKUs a serem excluídos: {len(skus_para_excluir)}")
        
        shop_url = configurar_shopify()
        access_token = os.getenv('PASSWORD')
        
        for produto in relatorio['criados']:
            try:
                produto_id = produto['id']
                sku_base = produto['sku_base']
                
                # Verificação adicional de segurança
                if not sku_base in skus_para_excluir:
                    print(f"⚠️ SKU {sku_base} não está na lista para exclusão. Pulando...")
                    continue
                
                resultado = deletar_produto_graphql(shop_url, produto_id, access_token)
                
                if 'data' in resultado and resultado['data']['productDelete']['deletedProductId']:
                    produtos_excluidos.append({
                        'id': produto_id,
                        'title': produto['title'],
                        'sku_base': sku_base
                    })
                    print(f"✅ Produto excluído com sucesso: {sku_base} - {produto['title']} (ID: {produto_id})")
                else:
                    erros_graphql = resultado.get('data', {}).get('productDelete', {}).get('userErrors', [])
                    mensagem_erro = '; '.join([e['message'] for e in erros_graphql]) if erros_graphql else 'Erro desconhecido'
                    raise Exception(mensagem_erro)
                
                time.sleep(0.5)  # Delay para evitar limitação da API
                    
            except Exception as e:
                erro = {
                    'id': produto_id,
                    'title': produto['title'],
                    'erro': str(e)
                }
                erros.append(erro)
                print(f"❌ Erro ao excluir produto {produto['title']}: {str(e)}")
        
        # Salvar relatório de exclusão
        relatorio_exclusao = {
            'produtos_excluidos': produtos_excluidos,
            'erros': erros,
            'total_processado': len(relatorio['criados']),
            'total_excluido': len(produtos_excluidos),
            'total_erros': len(erros)
        }
        
        with open('relatorio_exclusao.json', 'w', encoding='utf-8') as f:
            json.dump(relatorio_exclusao, f, ensure_ascii=False, indent=2)
            
        print(f"\n=== RELATÓRIO FINAL ===")
        print(f"Total processado: {len(relatorio['criados'])}")
        print(f"Produtos excluídos com sucesso: {len(produtos_excluidos)}")
        print(f"Erros: {len(erros)}")
        print("Relatório detalhado salvo em 'relatorio_exclusao.json'")
            
    except Exception as e:
        print(f"Erro ao processar exclusão: {str(e)}")
        print("Stack trace:")
        print(traceback.format_exc())

if __name__ == "__main__":
    load_dotenv()
    inicializar_shopify()
    excluir_produtos() 