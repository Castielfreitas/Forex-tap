#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import threading
import time
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from flask_socketio import SocketIO

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='mt5_tape_reading_ea.log'
)
logger = logging.getLogger("MT5TapeReadingEA")

# Inicializa o aplicativo Flask
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mt5-tape-reading-ea-secret')
socketio = SocketIO(app, cors_allowed_origins="*")

# Importa os módulos do sistema
try:
    import mt5_backend
    import mt5_performance
    import mt5_websocket
    import mt5_replicator
    import mt5_tape_reading_ea
    import mt5_monitoring
    MODULES_LOADED = True
except ImportError as e:
    logger.error(f"Erro ao importar módulos: {e}")
    MODULES_LOADED = False

# Variáveis globais
ea_thread = None
ea_running = False
monitoring_thread = None
monitoring_running = False

# Dados simulados para demonstração
DEMO_MODE = True
demo_account_info = {
    "login": 12345678,
    "server": "MetaQuotes-Demo",
    "balance": 10000.00,
    "equity": 10120.50,
    "margin": 270.20,
    "margin_free": 9850.30,
    "margin_level": 98.5,
    "currency": "USD"
}

demo_positions = [
    {
        "ticket": 1234567,
        "symbol": "EURUSD",
        "type": "BUY",
        "volume": 0.1,
        "open_price": 1.10250,
        "current_price": 1.10350,
        "sl": 1.10150,
        "tp": 1.10450,
        "profit": 10.00,
        "swap": 0.00,
        "time": "2025-04-06 08:30:15"
    },
    {
        "ticket": 1234568,
        "symbol": "GBPUSD",
        "type": "SELL",
        "volume": 0.2,
        "open_price": 1.25800,
        "current_price": 1.25750,
        "sl": 1.25900,
        "tp": 1.25600,
        "profit": 10.00,
        "swap": -0.50,
        "time": "2025-04-06 09:15:22"
    }
]

demo_orders = [
    {
        "ticket": 2345678,
        "symbol": "USDJPY",
        "type": "BUY_LIMIT",
        "volume": 0.3,
        "price": 115.500,
        "sl": 115.300,
        "tp": 115.800,
        "time_setup": "2025-04-06 10:05:30"
    }
]

demo_history = [
    {
        "ticket": 1234560,
        "symbol": "EURUSD",
        "type": "BUY",
        "volume": 0.1,
        "price_open": 1.10150,
        "price_close": 1.10250,
        "sl": 1.10050,
        "tp": 1.10350,
        "profit": 10.00,
        "time_setup": "2025-04-05 14:30:15",
        "time_done": "2025-04-05 16:45:22",
        "state": "FILLED"
    },
    {
        "ticket": 1234561,
        "symbol": "GBPUSD",
        "type": "SELL",
        "volume": 0.2,
        "price_open": 1.25700,
        "price_close": 1.25600,
        "sl": 1.25800,
        "tp": 1.25500,
        "profit": 20.00,
        "time_setup": "2025-04-05 15:10:30",
        "time_done": "2025-04-05 17:20:45",
        "state": "FILLED"
    }
]

demo_performance = {
    "account": {
        "balance": 10000.00,
        "equity": 10120.50,
        "margin": 270.20,
        "margin_free": 9850.30,
        "margin_level": 98.5
    },
    "daily": {
        "profit": 120.50,
        "trades": 5,
        "win_rate": 65.0,
        "drawdown": 85.20
    },
    "equity_chart": [
        {"date": "Dia 1", "value": 10000.00},
        {"date": "Dia 4", "value": 10020.00},
        {"date": "Dia 7", "value": 10050.00},
        {"date": "Dia 10", "value": 10080.00},
        {"date": "Dia 13", "value": 10100.00},
        {"date": "Dia 16", "value": 10130.00},
        {"date": "Dia 19", "value": 10150.00},
        {"date": "Dia 22", "value": 10180.00},
        {"date": "Dia 25", "value": 10200.00},
        {"date": "Dia 28", "value": 10120.50}
    ]
}

# Rotas da API
@app.route('/')
def index():
    return send_from_directory('.', 'mt5_web_interface.html')

@app.route('/index.html')
def index_html():
    return send_from_directory('.', 'index.html')

@app.route('/api/status')
def get_status():
    return jsonify({
        "server_status": "online",
        "ea_running": ea_running,
        "monitoring_running": monitoring_running,
        "modules_loaded": MODULES_LOADED,
        "demo_mode": DEMO_MODE
    })

@app.route('/api/start_ea', methods=['POST'])
def start_ea():
    global ea_thread, ea_running
    
    if ea_running:
        return jsonify({"status": "error", "message": "EA já está em execução"})
    
    try:
        config = request.json
        
        # Inicia o EA em uma thread separada
        ea_thread = threading.Thread(
            target=start_ea_thread,
            args=(config,)
        )
        ea_thread.daemon = True
        ea_thread.start()
        
        ea_running = True
        
        return jsonify({"status": "success", "message": "EA iniciado com sucesso"})
    except Exception as e:
        logger.error(f"Erro ao iniciar EA: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/stop_ea', methods=['POST'])
def stop_ea():
    global ea_running
    
    if not ea_running:
        return jsonify({"status": "error", "message": "EA não está em execução"})
    
    try:
        # Sinaliza para parar o EA
        ea_running = False
        
        return jsonify({"status": "success", "message": "EA parado com sucesso"})
    except Exception as e:
        logger.error(f"Erro ao parar EA: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/start_monitoring', methods=['POST'])
def start_monitoring():
    global monitoring_thread, monitoring_running
    
    if monitoring_running:
        return jsonify({"status": "error", "message": "Monitoramento já está em execução"})
    
    try:
        config = request.json
        
        # Inicia o monitoramento em uma thread separada
        monitoring_thread = threading.Thread(
            target=start_monitoring_thread,
            args=(config,)
        )
        monitoring_thread.daemon = True
        monitoring_thread.start()
        
        monitoring_running = True
        
        return jsonify({"status": "success", "message": "Monitoramento iniciado com sucesso"})
    except Exception as e:
        logger.error(f"Erro ao iniciar monitoramento: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/stop_monitoring', methods=['POST'])
def stop_monitoring():
    global monitoring_running
    
    if not monitoring_running:
        return jsonify({"status": "error", "message": "Monitoramento não está em execução"})
    
    try:
        # Sinaliza para parar o monitoramento
        monitoring_running = False
        
        return jsonify({"status": "success", "message": "Monitoramento parado com sucesso"})
    except Exception as e:
        logger.error(f"Erro ao parar monitoramento: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/performance', methods=['GET'])
def get_performance():
    try:
        if DEMO_MODE:
            return jsonify({"status": "success", "data": demo_performance})
        
        if not MODULES_LOADED:
            return jsonify({"status": "error", "message": "Módulos não carregados"})
        
        # Obtém dados de desempenho
        performance_data = mt5_performance.get_performance_data()
        
        return jsonify({"status": "success", "data": performance_data})
    except Exception as e:
        logger.error(f"Erro ao obter dados de desempenho: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/positions', methods=['GET'])
def get_positions():
    try:
        if DEMO_MODE:
            return jsonify({"status": "success", "data": demo_positions})
        
        if not MODULES_LOADED:
            return jsonify({"status": "error", "message": "Módulos não carregados"})
        
        # Obtém posições abertas
        positions = mt5_backend.get_positions()
        
        return jsonify({"status": "success", "data": positions})
    except Exception as e:
        logger.error(f"Erro ao obter posições: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/orders', methods=['GET'])
def get_orders():
    try:
        if DEMO_MODE:
            return jsonify({"status": "success", "data": demo_orders})
        
        if not MODULES_LOADED:
            return jsonify({"status": "error", "message": "Módulos não carregados"})
        
        # Obtém ordens pendentes
        orders = mt5_backend.get_orders()
        
        return jsonify({"status": "success", "data": orders})
    except Exception as e:
        logger.error(f"Erro ao obter ordens: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/history', methods=['GET'])
def get_history():
    try:
        if DEMO_MODE:
            return jsonify({"status": "success", "data": demo_history})
        
        if not MODULES_LOADED:
            return jsonify({"status": "error", "message": "Módulos não carregados"})
        
        # Obtém histórico de ordens
        days = request.args.get('days', default=7, type=int)
        history = mt5_backend.get_history(days)
        
        return jsonify({"status": "success", "data": history})
    except Exception as e:
        logger.error(f"Erro ao obter histórico: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/account_info', methods=['GET'])
def get_account_info():
    try:
        if DEMO_MODE:
            return jsonify({"status": "success", "data": demo_account_info})
        
        if not MODULES_LOADED:
            return jsonify({"status": "error", "message": "Módulos não carregados"})
        
        # Obtém informações da conta
        account_info = mt5_backend.get_account_info()
        
        return jsonify({"status": "success", "data": account_info})
    except Exception as e:
        logger.error(f"Erro ao obter informações da conta: {e}")
        return jsonify({"status": "error", "message": str(e)})

# Funções auxiliares
def start_ea_thread(config):
    try:
        logger.info("Iniciando thread do EA")
        
        if DEMO_MODE:
            # Simula a execução do EA
            while ea_running:
                time.sleep(1)
            
            logger.info("Thread do EA encerrada (modo demo)")
            return
        
        # Configura o EA
        mt5_tape_reading_ea.configure(config)
        
        # Inicia o EA
        while ea_running:
            mt5_tape_reading_ea.run_cycle()
            time.sleep(1)
        
        logger.info("Thread do EA encerrada")
    except Exception as e:
        logger.error(f"Erro na thread do EA: {e}")
        global ea_running
        ea_running = False

def start_monitoring_thread(config):
    try:
        logger.info("Iniciando thread de monitoramento")
        
        if DEMO_MODE:
            # Simula o monitoramento
            while monitoring_running:
                time.sleep(1)
            
            logger.info("Thread de monitoramento encerrada (modo demo)")
            return
        
        # Configura o monitoramento
        monitoring_system = mt5_monitoring.MonitoringSystem()
        
        # Inicia o monitoramento
        monitoring_system.start()
        
        # Mantém o monitoramento em execução
        while monitoring_running:
            time.sleep(1)
        
        # Para o monitoramento
        monitoring_system.stop()
        
        logger.info("Thread de monitoramento encerrada")
    except Exception as e:
        logger.error(f"Erro na thread de monitoramento: {e}")
        global monitoring_running
        monitoring_running = False

# Eventos do Socket.IO
@socketio.on('connect')
def handle_connect():
    logger.info(f"Cliente conectado: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Cliente desconectado: {request.sid}")

@socketio.on('start_ea')
def handle_start_ea(config):
    result = start_ea().get_json()
    socketio.emit('ea_status', result)

@socketio.on('stop_ea')
def handle_stop_ea():
    result = stop_ea().get_json()
    socketio.emit('ea_status', result)

# Inicialização do servidor
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
