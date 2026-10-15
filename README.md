# Comparador de catálogo e descrição técnica

Aplicativo local para extrair e comparar as informações de um catálogo PDF com uma descrição técnica PDF. A interface mostra a conferência da extração e, depois, as divergências encontradas.

## Regras de associação

- **Básico**: compara com **Lote 1 — Anos Iniciais**.
- **Intermediário**: compara com **Lote 2 — Anos Finais**.
- **Avançado**: compara com **Lote 3 — Ensino Médio**.
- O catálogo é extraído por inteiro. O intervalo de páginas opcional limita somente a descrição técnica.
- A descrição técnica é a referência para validar as informações do catálogo.
- Detalhes que aparecem somente na descrição não são divergências.
- Diferenças de quantidade, dimensões e informações conflitantes podem ser apontadas.
- O resultado deve apresentar as divergências com as evidências e páginas disponíveis.

## Privacidade e arquivos

A interface processa os PDFs nesta máquina. Os arquivos enviados ficam em memória durante a sessão e são copiados para uma pasta temporária enquanto ocorre a extração; essa pasta temporária é removida ao final do processamento. Os PDFs originais não são copiados.

Na interface, `itens_extraidos.json` é gravado em `saida\extraidos` quando você clica em **Extrair e conferir**. O arquivo de divergências é oferecido para download depois de **Comparar itens**. O comando de linha de comando também grava auditoria, divergências e textos extraídos em `saida\extraidos`. 

## Instalação no Windows

É recomendado usar um ambiente virtual para manter as dependências deste projeto separadas de outros programas Python.

No PowerShell, a partir da pasta do projeto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[interface]"
```

Se o comando `py -3.12` não estiver disponível, use uma versão instalada do Python 3.11 ou superior para criar o ambiente, por exemplo `python -m venv .venv`.

## Abrir a interface

Com o ambiente virtual ativado:

```powershell
python -m streamlit run app.py
```

O Streamlit abre a interface no navegador, normalmente em `http://localhost:8501`.

1. Selecione o catálogo e a descrição técnica em PDF.
2. Escolha o nível do catálogo. O aplicativo associa automaticamente o lote correspondente.
3. Se necessário, limite as páginas da **descrição técnica**. O catálogo continua sendo extraído por inteiro.
4. Clique em **Extrair e conferir** e revise as contagens e os arquivos extraídos.
5. Clique em **Comparar itens** para gerar o resultado.

## Arquivos gerados

No desenvolvimento, a interface cria `saida\extraidos` na pasta do projeto. No aplicativo empacotado, usa `%LOCALAPPDATA%\AgenteComparadorPDF\saida\extraidos`. Ao clicar em **Extrair e conferir**, grava/atualiza `itens_extraidos.json` e `auditoria_extracao.json`. Ao clicar em **Comparar itens**, grava/atualiza `divergencias.json` e também mostra o resultado na página. O botão **Baixar divergências em JSON** permite salvar uma cópia em outro local.

O comando de linha de comando `agente-pdf` também grava em `saida\extraidos` os arquivos `itens_extraidos.json`, `auditoria_extracao.json`, `divergencias.json`, `catalogo.txt` e `descricao_tecnica.txt`. A extração é baseada no texto disponível no PDF. Páginas digitalizadas como imagem podem exigir OCR (reconhecimento óptico de caracteres); o aplicativo não executa OCR automaticamente.

## Comando opcional de linha de comando

O comando `agente-pdf` faz a extração e a comparação sem abrir a interface:

```powershell
agente-pdf --catalogo "C:\caminho\catalogo.pdf" --descricao "C:\caminho\descricao.pdf" --nivel basico
```

Níveis aceitos: `basico`, `intermediario` e `avancado`. Para ver as opções:

```powershell
agente-pdf --help
```

## O que cada pasta e arquivo faz

- `app.py`: interface Streamlit.
- `src\agente_pdf`: leitura dos PDFs, extração, auditoria e comparação.
- `pyproject.toml`: metadados, dependências e comando `agente-pdf`.
- `.venv`: ambiente Python local usado no desenvolvimento. Não é necessário distribuir essa pasta junto com o aplicativo empacotado.
- `.venv-build`: ambiente isolado criado pelo script para preparar a distribuição Windows.
- `src\agente_comparador_pdf.egg-info`: metadados gerados pela instalação editável do pacote, como nome, dependências e comandos. Não é código-fonte e não precisa ser incluído na distribuição; não edite manualmente.
- `app_launcher.py` e `ComparadorPDF.spec`: iniciador local e configuração do PyInstaller.
- `build_windows.ps1`: instala as dependências em `.venv-build` e gera a pasta de distribuição.
- `__pycache__`: cache criado pelo Python; pode ser recriado automaticamente.
- Os PDFs são selecionados na interface; não é necessária uma pasta fixa de entrada.
- `saida`: resultados gerados localmente, que podem conter informações confidenciais. Não deve ser incluída na distribuição do executável.

## Empacotamento para outros computadores Windows

A primeira distribuição é uma pasta Windows autocontida criada com PyInstaller. Ela inclui o aplicativo e suas dependências, mas não inclui PDFs de amostra, arquivos de `saida`, o ambiente virtual nem caches. O executável inicia o servidor Streamlit somente em `127.0.0.1` e abre a interface no navegador. Os resultados da versão instalada ficam em `%LOCALAPPDATA%\AgenteComparadorPDF\saida\extraidos`.

Para preparar a pasta de distribuição em um computador Windows com Python 3.12 instalado, execute no PowerShell:

```powershell
.\build_windows.ps1
```

O script cria um ambiente separado `.venv-build`, instala as dependências e gera `dist\ComparadorPDF`. A primeira execução pode levar alguns minutos e requer acesso à internet para baixar os pacotes. Depois de gerar a pasta, copie a pasta `dist\ComparadorPDF` inteira para outro computador Windows e execute `ComparadorPDF.exe`. O instalador será uma etapa posterior, depois de validar essa pasta em outra máquina.
