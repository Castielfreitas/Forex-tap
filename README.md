# MT5 Tape Reading EA - Implantação no PythonAnywhere

Este repositório contém os arquivos necessários para implantar o MT5 Tape Reading EA na plataforma PythonAnywhere.

## Visão Geral

O MT5 Tape Reading EA é um Expert Advisor para o MetaTrader 5 que utiliza técnicas de Tape Reading para identificar oportunidades de negociação. Esta implantação permite acessar o EA através de uma interface web, sem necessidade de instalação local.

## Funcionalidades

- Interface web para monitoramento e controle do EA
- Visualização de desempenho de negociação
- Gráficos de evolução do patrimônio
- Estatísticas de operações (lucro/prejuízo, taxa de acerto, etc.)
- Monitoramento de posições abertas e ordens pendentes
- Histórico de operações

## Requisitos

- Conta no PythonAnywhere (https://www.pythonanywhere.com)
- Conhecimentos básicos de Python e Flask

## Arquivos Principais

- `flask_app.py`: Aplicativo Flask principal
- `mt5_tape_reading_ea_wsgi.py`: Arquivo WSGI para configuração no PythonAnywhere
- `mt5_web_interface.html`: Interface web do EA
- `mt5_*.py`: Módulos do sistema MT5 Tape Reading EA

## Modo de Demonstração

Por padrão, a aplicação é executada em modo de demonstração, utilizando dados simulados. Para conectar a um terminal MT5 real, é necessário configurar um servidor proxy em um VPS que tenha o MT5 instalado.
