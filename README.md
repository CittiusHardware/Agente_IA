# Comparador de catálogo e descrição técnica

Aplicativo para comparar informações e quantidades de um catálogo PDF com uma descrição técnica PDF. O processamento é feito localmente no computador.

## Usar o aplicativo no Windows

Estas instruções são para quem recebeu a distribuição pronta do aplicativo. **Não é necessário instalar Python nem criar um ambiente virtual.**

1. Se recebeu um arquivo ZIP, extraia-o primeiro.
2. Mantenha a pasta `ComparadorPDF` inteira, inclusive a subpasta `_internal`.
3. Abra `ComparadorPDF.exe`. O aplicativo inicia e abre a interface no navegador.
4. Selecione o catálogo e a descrição técnica em PDF.
5. Escolha o nível do catálogo:
   - **Básico** associa ao **Lote 1 — Anos Iniciais**.
   - **Intermediário** associa ao **Lote 2 — Anos Finais**.
   - **Avançado** associa ao **Lote 3 — Ensino Médio**.
6. Se necessário, limite o intervalo de páginas da **descrição técnica**. O catálogo sempre é extraído por inteiro.
7. Clique em **Extrair e conferir**, revise os itens e as contagens e depois clique em **Comparar itens**.

A janela preta aberta junto com o aplicativo mantém o servidor local funcionando. Feche essa janela quando terminar de usar o aplicativo.

### Onde ficam os resultados

No aplicativo instalado ou distribuído, os arquivos ficam em:

```text
%LOCALAPPDATA%\AgenteComparadorPDF\saida\extraidos
```

Para abrir essa pasta, copie o caminho acima e cole-o na barra de endereços do Explorador de Arquivos. Os arquivos são:

- `itens_extraidos.json` e `auditoria_extracao.json`: atualizados ao clicar em **Extrair e conferir**.
- `divergencias.json`: atualizado ao clicar em **Comparar itens**.

Os PDFs enviados não são guardados nessa pasta. Durante o processamento, são mantidos em memória e em uma pasta temporária, removida ao terminar a extração. Os JSON podem conter informações dos documentos; cuide deles como arquivos confidenciais.

## Regras da comparação

- A descrição técnica serve de referência para conferir as informações do catálogo.
- Informações que aparecem somente na descrição não são consideradas divergência.
- Diferenças de quantidade, dimensões e informações conflitantes podem ser apontadas.
- O resultado apresenta somente divergências, com evidências e páginas disponíveis.
- A extração depende do texto disponível no PDF. Páginas digitalizadas como imagem podem precisar de OCR (reconhecimento óptico de caracteres); o aplicativo não executa OCR automaticamente.

## Desenvolvimento e recompilação

As instruções abaixo são para quem trabalha no código-fonte e precisa executar ou empacotar uma nova versão. **O usuário do aplicativo pronto pode ignorar esta seção.**

### Instalar o ambiente de desenvolvimento

No PowerShell, na pasta do projeto, com Python 3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[interface]"
```

### Executar a interface pelo código-fonte

```powershell
python -m streamlit run app.py
```

A interface abre no navegador, normalmente em `http://localhost:8501`.

### Usar a linha de comando

O comando opcional `agente-pdf` extrai e compara PDFs sem abrir a interface:

```powershell
agente-pdf --catalogo "C:\caminho\catalogo.pdf" --descricao "C:\caminho\descricao.pdf" --nivel basico
```

Níveis aceitos: `basico`, `intermediario` e `avancado`. Para ver as opções, use `agente-pdf --help`.

### Gerar a distribuição Windows

Em um computador Windows com Python 3.12 e acesso à internet, execute:

```powershell
.\build_windows.ps1
```

O script cria o ambiente de compilação `.venv-build` e gera a pasta `dist\ComparadorPDF`. Para distribuir, compartilhe a pasta inteira ou compacte-a em ZIP. No computador de destino, extraia o ZIP e execute `ComparadorPDF.exe`; não é necessário instalar Python.

### Arquivos do projeto

- `app.py`: interface e fluxo de extração/comparação.
- `src\agente_pdf`: leitura dos PDFs, extração, auditoria e comparação.
- `pyproject.toml`: dependências e metadados do pacote.
- `app_launcher.py` e `ComparadorPDF.spec`: lançador e configuração do PyInstaller.
- `build_windows.ps1`: script de compilação.
- `.venv` e `.venv-build`: ambientes Python locais; não distribuir.
- `*.egg-info` e `__pycache__`: metadados/cache gerados automaticamente.
- `saida`: resultados locais, potencialmente confidenciais; não incluir na distribuição.
