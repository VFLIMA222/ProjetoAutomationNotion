import os
import asyncio
import requests
import time
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI

async def loop_automacao():
    while True:
        try:
            checar_e_atualizar_projetos()
        except Exception as e:
            print(f"Erro detectado no loop: {e}")
        
        await asyncio.sleep(20)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(loop_automacao())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def obter_valor_status(propriedade):
    """Extrai o texto de campos do tipo Status ou Select de forma segura"""
    if not propriedade:
        return None
    tipo = propriedade.get("type")
    if tipo in ["status", "select"] and propriedade.get(tipo):
        return propriedade[tipo]["name"]
    return None

def obter_tipo_propriedade(propriedade):
    """Identifica se a coluna foi criada como 'status' ou 'select' no Notion"""
    return propriedade.get("type") if propriedade else "status"

def checar_e_atualizar_projetos():
    url_query = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    
    try:
        response = requests.post(url_query, headers=HEADERS)
        if response.status_code != 200:
            print(f"Erro ao acessar o Notion ({response.status_code}): {response.text}")
            return
        paginas = response.json().get("results", [])
    except Exception as e:
        print(f"Erro de conexão: {e}")
        return

    for pagina in paginas:
        page_id = pagina["id"]
        props = pagina["properties"]

        nome_projeto = ""
        if "Projeto" in props and props["Projeto"]["title"]:
            nome_projeto = props["Projeto"]["title"][0]["text"]["content"]

        if not nome_projeto:
            continue  

        tipo_entrega = obter_tipo_propriedade(props.get("Entrega"))
        valor_entrega = obter_valor_status(props.get("Entrega"))

        tipo_status = obter_tipo_propriedade(props.get("Status"))
        valor_status = obter_valor_status(props.get("Status"))

        tipo_arquivacao = obter_tipo_propriedade(props.get("Arquivação"))
        valor_arquivacao = obter_valor_status(props.get("Arquivação"))
        
        data_finalizado = props["Finalizado em"]["date"]["start"] if "Finalizado em" in props and props["Finalizado em"]["date"] else None
        data_recebido = props["Recebido"]["date"]["start"] if "Recebido" in props and props["Recebido"]["date"] else None

        alteracoes = {}

        # REGRAS DA SUA AUTOMAÇÃO

        # REGRA 1: Nome do projeto criado, mas a coluna 'Entrega' está vazia
        # Ação: Muda 'Entrega' para 'Não Iniciada' E insere a data de hoje em 'Recebido'
        if not valor_entrega:
            data_hoje = datetime.now().strftime("%Y-%m-%d")
            
            alteracoes["Entrega"] = {tipo_entrega: {"name": "Não Iniciada"}}
            alteracoes["Recebido em"] = {"date": {"start": data_hoje}}
            print(f"Novo projeto detectado: '{nome_projeto}'. Definindo como 'Não Iniciado' e salvando data de recebimento.")

        # REGRA 2: Se a coluna 'Entrega' foi marcada como 'Concluído' e a data de finalização está vazia
        # Ação: Registra a data atual automaticamente em 'Finalizado em'
        if valor_entrega == "Concluído" and not data_finalizado:
            data_hoje = datetime.now().strftime("%Y-%m-%d")
            alteracoes["Status"] = {tipo_entrega: {"name": "Em Andamento"}}  # Garante que o status também seja atualizado para 'Em Andamento'
            alteracoes["Finalizado em"] = {"date": {"start": data_hoje}}
            print(f"Projeto '{nome_projeto}' finalizado! Gravando a data de conclusão ({data_hoje} e Status: 'Em Andamento').")

        # REGRA 3: Se a coluna 'Status' foi marcada como 'Postado'
        # Ação: Altera a coluna 'Arquivação' para 'Aguardando'
        if valor_status == "Postado":
            alteracoes["Arquivação"] = {tipo_arquivacao: {"name": "Aguardando"}}

        # REGRA 4: Se a coluna 'Status' foi marcada como 'Recusado'
        # Ação: Altera a coluna 'Arquivação' para 'Cancelado'
        if valor_status == "Recusado":
            alteracoes["Arquivação"] = {tipo_arquivacao: {"name": "Cancelado"}}


        # ENVIO DAS ATUALIZAÇÕES PARA A API DO NOTION

        if alteracoes:
            url_update = f"https://api.notion.com/v1/pages/{page_id}"
            try:
                res_update = requests.patch(url_update, headers=HEADERS, json={"properties": alteracoes})
                if res_update.status_code == 200:
                    print(f"Projeto '{nome_projeto}' sincronizado com sucesso!")
                else:
                    print(f"Erro ao atualizar '{nome_projeto}': {res_update.text}")
            except Exception as e:
                print(f"Falha de comunicação no projeto '{nome_projeto}': {e}")

@app.get("/")
def index():
    return {"status": "Automação rodando ativamente em segundo plano a cada 20 segundos"}
