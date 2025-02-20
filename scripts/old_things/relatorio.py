from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def gerar_relatorio_pdf(relatorio_atualizacoes, nome_arquivo="relatorio_atualizacoes.pdf"):
    c = canvas.Canvas(nome_arquivo, pagesize=letter)
    c.setFont("Helvetica", 12)
    c.drawString(100, 750, "Relatório de Produtos que Precisam de Atualização")
    c.drawString(100, 730, "-" * 50)

    y = 710
    for item in relatorio_atualizacoes:
        c.drawString(100, y, f"SKU: {item['SKU']}")
        c.drawString(100, y - 15, f"Nome: {item['Nome']}")
        c.drawString(100, y - 30, f"Categoria: {item['Categoria']}")
        preco_formatado = float(item['Preco']) if isinstance(item['Preco'], str) else item['Preco']
        c.drawString(100, y - 45, f"Preço: R$ {preco_formatado:.2f}")
        c.drawString(100, y - 60, f"Quantidade Hiper: {item['Quantidade Hiper']}")
        c.drawString(100, y - 75, f"Quantidade Shopify: {item['Quantidade Shopify']}")
        c.drawString(100, y - 90, f"Necessita Atualização: {item['Necessita Atualização']}")
        c.drawString(100, y - 105, "-" * 50)
        y -= 120  # Espaço entre os produtos

    c.save()
