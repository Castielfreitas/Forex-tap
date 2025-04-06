# Instruções para Implantação no PythonAnywhere

## Pré-requisitos

- Conta no PythonAnywhere (https://www.pythonanywhere.com)
- Conhecimentos básicos de Python e Flask

## Passos para Implantação

1. **Criar uma conta no PythonAnywhere**

   - Acesse https://www.pythonanywhere.com/registration/register/beginner/
   - Preencha o formulário de registro
   - Confirme seu e-mail

2. **Fazer upload dos arquivos**

   - Faça login no PythonAnywhere
   - Vá para a aba "Files"
   - Crie um novo diretório: `mt5_tape_reading_ea`
   - Faça upload de todos os arquivos deste pacote para o diretório criado

   Alternativamente, você pode usar o console Bash do PythonAnywhere:
   
   ```bash
   mkdir -p ~/mt5_tape_reading_ea
   cd ~/mt5_tape_reading_ea
   git clone https://github.com/seu-usuario/mt5-tape-reading-ea.git .
   ```

3. **Configurar o ambiente virtual (opcional, mas recomendado)**

   - Vá para a aba "Consoles"
   - Inicie um novo console Bash
   - Execute os seguintes comandos:

   ```bash
   cd ~/mt5_tape_reading_ea
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Configurar a aplicação web**

   - Vá para a aba "Web"
   - Clique em "Add a new web app"
   - Escolha "Manual configuration"
   - Selecione a versão do Python (3.8 ou superior)
   - Defina o caminho para o diretório da aplicação: `/home/mt5tapereading/mt5_tape_reading_ea`
   - Defina o caminho para o arquivo WSGI: `/home/mt5tapereading/mt5_tape_reading_ea/mt5_tape_reading_ea_wsgi.py`
   - Clique em "Next"

5. **Configurar o arquivo WSGI**

   - Na aba "Web", clique no link para editar o arquivo WSGI
   - Substitua o conteúdo pelo seguinte:

   ```python
   import sys
   import os

   # Adiciona o diretório da aplicação ao path
   path = '/home/mt5tapereading/mt5_tape_reading_ea'
   if path not in sys.path:
       sys.path.append(path)

   # Importa a aplicação Flask
   from flask_app import app as application
   ```

6. **Configurar o ambiente virtual (se criado)**

   - Na aba "Web", na seção "Virtualenv", insira o caminho: `/home/mt5tapereading/mt5_tape_reading_ea/venv`
   - Clique em "Save"

7. **Configurar arquivos estáticos (opcional)**

   - Na aba "Web", na seção "Static files", adicione:
     - URL: `/static/`
     - Directory: `/home/mt5tapereading/mt5_tape_reading_ea/static`
   - Clique em "Save"

8. **Reiniciar a aplicação**

   - Na aba "Web", clique no botão "Reload"
   - Aguarde a aplicação reiniciar

9. **Acessar a aplicação**

   - Sua aplicação estará disponível em: `https://mt5tapereading.pythonanywhere.com/`

## Notas Importantes

- O plano gratuito do PythonAnywhere tem limitações, incluindo CPU e largura de banda
- A aplicação estará sempre online, sem necessidade de manter seu computador ligado
- O PythonAnywhere não suporta a execução direta do MetaTrader 5, então a aplicação funcionará em modo de simulação
- Para conexão real com o MT5, você precisará configurar um servidor proxy em um VPS que tenha o MT5 instalado

## Solução de Problemas

- Se a aplicação não iniciar, verifique os logs na aba "Web" do PythonAnywhere
- Certifique-se de que todas as dependências estão instaladas corretamente
- Verifique se o arquivo WSGI está configurado corretamente
- Se necessário, reinicie a aplicação clicando no botão "Reload"
