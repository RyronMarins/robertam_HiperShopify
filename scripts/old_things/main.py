import shopify
from config import configurar_shopify, configurar_hiper
from sincronizacao import gerar_relatorio_atualizacoes

if __name__ == "__main__":
    # Configurar Shopify
    shop_url = configurar_shopify()
    shopify.ShopifyResource.set_site(shop_url)

    # Configurar Hiper e gerar relatório
    config_hiper = configurar_hiper()
    gerar_relatorio_atualizacoes(config_hiper)