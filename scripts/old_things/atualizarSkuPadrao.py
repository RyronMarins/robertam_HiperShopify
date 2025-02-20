import logging
import shopify
import os

# Configuração do logging
logging.basicConfig(filename='./logs/atualizacao_skus.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Lista de produtos sem SKU
skuErrado = [
    "Bermuda Serena",
    "Blusa Alba",
    "Blusa Alma",
    "Blusa Camille",
    "Blusa Gabrielle Púrpura",
    "Boné Solange Marrom",
    "Boné Sunny Amarelo",
    "Camiseta Clara",
    "Quimono Alma",
    "Regata Vic",
    "Saia Rosita Vanilla",
    "Shorts Nice",
    "Shorts Spicy",
    "Shorts Sugar",
    "Shorts Yasmin",
    "Top Baobá",
    "Top Caterine Bege",
    "Top Caterine Off White",
    "Vestido Alma",
    "Vestido Camille",
    "Vestido Midi Maria",
    "Vestido Mini Gabrielle",
    "Vestido Yoko"
]

# Dicionário de SKUs corretos por produto e tamanho
skus_corretos = {
    "Bermuda Serena": {
        36: "C0700136",
        38: "C0700138",
        40: "C0700140",
        42: "C0700142"
    },
    "Blusa Alba": {
        36: "C0700236",
        38: "C0700238",
        40: "C0700240",
        42: "C0700242"
    },
    "Blusa Alma": {
        36: "C0700336",
        38: "C0700338",
        40: "C0700340",
        42: "C0700342"
    },
    "Blusa Camille": {
        36: "C0700436",
        38: "C0700438",
        40: "C0700440",
        42: "C0700442"
    },
    "Blusa Gabrielle Púrpura": {
        36: "C0700536",
        38: "C0700538",
        40: "C0700540",
        42: "C0700542"
    },
    "Boné Solange Marrom": {
        36: "C0700636",
        38: "C0700638",
        40: "C0700640",
        42: "C0700642"
    },
    "Boné Sunny Amarelo": {
        36: "C0700736",
        38: "C0700738",
        40: "C0700740",
        42: "C0700742"
    },
    "Camiseta Clara": {
        36: "C0700836",
        38: "C0700838",
        40: "C0700840",
        42: "C0700842"
    },
    "Quimono Alma": {
        36: "C0700936",
        38: "C0700938",
        40: "C0700940",
        42: "C0700942"
    },
    "Regata Vic": {
        36: "C0701036",
        38: "C0701038",
        40: "C0701040",
        42: "C0701042"
    },
    "Saia Rosita Vanilla": {
        36: "C0701136",
        38: "C0701138",
        40: "C0701140",
        42: "C0701142"
    },
    "Shorts Nice": {
        36: "C0701236",
        38: "C0701238",
        40: "C0701240",
        42: "C0701242"
    },
    "Shorts Spicy": {
        36: "C0701336",
        38: "C0701338",
        40: "C0701340",
        42: "C0701342"
    },
    "Shorts Sugar": {
        36: "C0701436",
        38: "C0701438",
        40: "C0701440",
        42: "C0701442"
    },
    "Shorts Yasmin": {
        36: "C0701536",
        38: "C0701538",
        40: "C0701540",
        42: "C0701542"
    },
    "Top Baobá": {
        36: "C0701636",
        38: "C0701638",
        40: "C0701640",
        42: "C0701642"
    },
    "Top Caterine Bege": {
        36: "C0701736",
        38: "C0701738",
        40: "C0701740",
        42: "C0701742"
    },
    "Top Caterine Off White": {
        36: "C0701836",
        38: "C0701838",
        40: "C0701840",
        42: "C0701842"
    },
    "Vestido Alma": {
        36: "C0701936",
        38: "C0701938",
        40: "C0701940",
        42: "C0701942"
    },
    "Vestido Camille": {
        36: "C0702036",
        38: "C0702038",
        40: "C0702040",
        42: "C0702042"
    },
    "Vestido Midi Maria": {
        36: "C0702136",
        38: "C0702138",
        40: "C0702140",
        42: "C0702142"
    },
    "Vestido Mini Gabrielle": {
        36: "C0702236",
        38: "C0702238",
        40: "C0702240",
        42: "C0702242"
    },
    "Vestido Yoko": {
        36: "C0702336",
        38: "C0702338",
        40: "C0702340",
        42: "C0702342"
    }
}

# Função para atualizar SKUs
def atualizar_skus(produtos):
    total_atualizados = 0
    for produto in produtos:
        for tamanho, sku in skus_corretos.get(produto, {}).items():
            try:
                # Verifica se o produto e tamanho existem
                if produto not in skus_corretos or tamanho not in skus_corretos[produto]:
                    logging.warning(f"Produto ou tamanho não encontrado: {produto}, {tamanho}")
                    continue

                # Implementação da lógica para verificar o SKU atual
                sku_atual = obter_sku_atual(produto, tamanho)  # Função para obter o SKU atual
                if sku_atual != sku:
                    corrigir_sku(produto, tamanho, sku)  # Função para corrigir o SKU
                    total_atualizados += 1
                    logging.info(f"SKU atualizado: {produto} tamanho {tamanho} de {sku_atual} para {sku}")
                else:
                    logging.info(f"SKU já está correto: {produto} tamanho {tamanho} ({sku_atual})")
            except Exception as e:
                logging.error(f"Erro ao atualizar SKU do {produto} tamanho {tamanho}: {e}")

    print(f"Total de SKUs atualizados: {total_atualizados}")
    logging.info(f"Total de SKUs atualizados: {total_atualizados}")

# Funções para obter e corrigir o SKU
def obter_sku_atual(produto, tamanho):
    # Aqui você deve implementar a lógica para obter o SKU atual do sistema
    produtos_shopify = shopify.Product.find(limit=250, published_status='any')
    for p in produtos_shopify:
        if p.title == produto:
            for variante in p.variants:
                if variante.option1 == str(tamanho):  # Supondo que o tamanho seja a primeira opção
                    return variante.sku
    return None  # Retorna None se não encontrar

def corrigir_sku(produto, tamanho, novo_sku):
    produtos_shopify = shopify.Product.find(limit=250, published_status='any')
    for p in produtos_shopify:
        if p.title == produto:
            for variante in p.variants:
                if variante.option1 == str(tamanho):  # Supondo que o tamanho seja a primeira opção
                    variante.sku = novo_sku
                    variante.save()  # Salva a alteração
                    logging.info(f"SKU do {produto} tamanho {tamanho} atualizado para {novo_sku}")
                    print(f"Atualizando SKU do {produto} tamanho {tamanho} para {novo_sku}")
                    return

# Chamada da função
if __name__ == "__main__":
    # Configurar Shopify antes de chamar a função
    api_key = os.getenv("API_KEY")
    password = os.getenv("PASSWORD")
    shop_name = os.getenv("SHOP_NAME")
    shop_url = f"https://{api_key}:{password}@{shop_name}/admin/api/2024-01"
    shopify.ShopifyResource.set_site(shop_url)

    atualizar_skus(skuErrado)
