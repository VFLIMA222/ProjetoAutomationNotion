import os
import asyncio
import requests
import time
import uvicorn
from datetime import datetime
import pytz
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

if not NOTION_TOKEN:
    print("ALERTA CRÍTICO: O código não conseguiu ler a variável 'NOTION_TOKEN' do Render!")
else:
    print(f"Sucesso: Token detectado pelo código (Tamanho: {len(NOTION_TOKEN)} caracteres)")



HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

SCRIPT_START_TIME = datetime.now(pytz.utc)

def obter_valor_status(propriedade):
    """Extrai o texto de campos do tipo Status ou Select de forma segura"""
    if not propriedade:
        return None
    tipo = propriedade.get("type")
    if tipo in ["status", "select"] and propriedade.get(tipo):
        return propriedade[tipo]["name"]
    return None

def obter_valor_texto(propriedade):
    """Extrai o texto de campos do tipo Rich Text (texto puro) de forma segura"""
    if propriedade and propriedade.get("type") == "rich_text":
        lista_texto = propriedade.get("rich_text", [])
        if lista_texto:
            return lista_texto[0].get("plain_text", "")
    return ""

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
    
    fuso_br = pytz.timezone('America/Sao_Paulo')

    for pagina in paginas:
        page_id = pagina["id"]

        last_edited_str = pagina.get("last_edited_time", "").replace("Z", "+00:00")
        data_ultima_edicao = datetime.fromisoformat(last_edited_str)

        if data_ultima_edicao < SCRIPT_START_TIME:
            continue  
            
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

        valor_duracao = obter_valor_texto(props.get("Duração do Vídeo"))
        
        def extrair_data(propriedade):
            if propriedade and propriedade.get("date"):
                return propriedade["date"].get("start")
            return None

        data_finalizado = extrair_data(props.get("Finalizado Em"))
        data_recebido = extrair_data(props.get("Recebido em"))

        alteracoes = {}

        # REGRAS DA AUTOMAÇÃO

        if not valor_entrega:
            alteracoes["Entrega"] = {tipo_entrega: {"name": "Não Iniciada"}}
            
            if not data_recebido:
                data_hoje = datetime.now(fuso_br).strftime("%Y-%m-%d")
                alteracoes["Recebido em"] = {"date": {"start": data_hoje}}
                print(f"Novo projeto '{nome_projeto}': Definido 'Não Iniciada' e data de recebimento salva.")
            else:
                print(f"Projeto '{nome_projeto}': Definido 'Não Iniciada' (Data de recebimento já existia e foi protegida).")

        if valor_entrega == "Concluído" and not data_finalizado:
            data_hoje = datetime.now(fuso_br).strftime("%Y-%m-%d")
            
            alteracoes["Status"] = {tipo_status: {"name": "Em andamento"}}  
            alteracoes["Finalizado Em"] = {"date": {"start": data_hoje}}
            print(f"Projeto '{nome_projeto}' concluído! Gravando data ({data_hoje}) e Status: 'Em andamento'.")

        if valor_status == "Postado":
            alteracoes["Arquivação"] = {tipo_arquivacao: {"name": "Aguardando"}}



        if valor_entrega == "Cancelado" and (valor_status != "Recusado" or valor_duracao != "Cancelado"):
            alteracoes["Status"] = {tipo_status: {"name": "Recusado"}}
            alteracoes["Arquivação"] = {tipo_arquivacao: {"name": "Cancelado"}}
            
            alteracoes["Duração do Vídeo"] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": "Cancelado"
                        }
                    }
                ]
            }
            print(f"Projeto '{nome_projeto}' cancelado! Alterando Status para 'Recusado' e escrevendo 'Cancelado' em Duração do Vídeo.")

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

@app.router("/", methods=["GET", "HEAD"])
def index(request):
    return {"status": "Automação rodando ativamente em segundo plano"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
