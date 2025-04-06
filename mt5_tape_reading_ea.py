#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Expert Advisor (EA) automatizado baseado em Tape Reading para MetaTrader 5.
Este EA utiliza técnicas de Tape Reading para identificar oportunidades de negociação.
"""

import os
import time
import json
import logging
import threading
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import MetaTrader5 as mt5

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_tape_reading_ea.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5TapeReadingEA")

class MT5TapeReadingEA:
    """
    Expert Advisor automatizado baseado em Tape Reading para MetaTrader 5.
    """
    
    def __init__(self, config_file=None):
        """
        Inicializa o EA de Tape Reading.
        
        Args:
            config_file (str, optional): Caminho para o arquivo de configuração
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.running = False
        self.connected = False
        self.symbols = []
        self.symbol_data = {}
        self.positions = {}
        self.orders = {}
        self.trade_history = []
        self.last_tick_time = {}
        self.volume_profile = {}
        self.price_levels = {}
        self.market_depth = {}
        self.trade_signals = {}
        self.performance_metrics = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_profit": 0.0,
            "total_loss": 0.0,
            "max_drawdown": 0.0,
            "current_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "risk_reward_ratio": 0.0
        }
        self.lock = threading.Lock()
    
    def _load_config(self):
        """
        Carrega a configuração do EA.
        
        Returns:
            dict: Configuração do EA
        """
        default_config = {
            "account": {
                "login": "",
                "password": "",
                "server": "",
                "type": "DEMO"  # "DEMO" ou "REAL"
            },
            "symbols": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
            "timeframes": {
                "analysis": "M1",  # Timeframe para análise (M1, M5, M15, etc.)
                "execution": "M1"  # Timeframe para execução
            },
            "tape_reading": {
                "volume_threshold": 10.0,  # Volume mínimo para considerar relevante
                "price_levels": 10,  # Número de níveis de preço para monitorar
                "tick_window": 1000,  # Número de ticks para análise
                "volume_imbalance_threshold": 2.0,  # Razão de desequilíbrio de volume
                "delta_threshold": 0.5,  # Limiar de delta (diferença entre compra/venda)
                "footprint_levels": 5,  # Níveis para análise de footprint
                "cumulative_delta_period": 20,  # Período para delta cumulativo
                "vwap_period": 20,  # Período para VWAP
                "market_depth_levels": 10  # Níveis de profundidade de mercado
            },
            "risk_management": {
                "max_risk_percent": 1.0,  # Risco máximo por operação (%)
                "max_daily_loss": 3.0,  # Perda máxima diária (%)
                "max_open_positions": 5,  # Número máximo de posições abertas
                "position_sizing": "risk",  # "fixed", "risk", "equity"
                "fixed_lot_size": 0.01,  # Tamanho fixo de lote
                "stop_loss_pips": 20,  # Stop loss em pips
                "take_profit_pips": 40,  # Take profit em pips
                "trailing_stop": True,  # Usar stop móvel
                "trailing_stop_start_pips": 15,  # Pips de lucro para ativar stop móvel
                "trailing_stop_distance_pips": 10,  # Distância do stop móvel
                "break_even": True,  # Mover stop para break even
                "break_even_pips": 10,  # Pips de lucro para mover para break even
                "time_filter": {
                    "enabled": True,
                    "start_hour": 8,  # Hora de início (UTC)
                    "end_hour": 20,  # Hora de término (UTC)
                    "trade_monday": True,
                    "trade_tuesday": True,
                    "trade_wednesday": True,
                    "trade_thursday": True,
                    "trade_friday": True,
                    "trade_saturday": False,
                    "trade_sunday": False
                }
            },
            "execution": {
                "order_type": "MARKET",  # "MARKET", "LIMIT", "STOP"
                "slippage_pips": 3,  # Slippage máximo em pips
                "max_spread_pips": 5,  # Spread máximo para operar
                "retry_attempts": 3,  # Tentativas de execução
                "retry_delay_seconds": 1  # Atraso entre tentativas
            },
            "notifications": {
                "enabled": True,
                "trade_opened": True,
                "trade_closed": True,
                "stop_hit": True,
                "take_profit_hit": True,
                "error": True
            },
            "backtest": {
                "enabled": False,
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
                "initial_deposit": 10000,
                "leverage": 100
            }
        }
        
        if not self.config_file or not os.path.exists(self.config_file):
            logger.warning(f"Arquivo de configuração não encontrado, usando configuração padrão")
            return default_config
        
        try:
            with open(self.config_file, "r") as f:
                config = json.load(f)
            
            # Mesclar com configuração padrão para garantir que todos os campos existam
            merged_config = default_config.copy()
            
            # Função recursiva para mesclar dicionários
            def merge_dict(d1, d2):
                for k, v in d2.items():
                    if k in d1 and isinstance(d1[k], dict) and isinstance(v, dict):
                        merge_dict(d1[k], v)
                    else:
                        d1[k] = v
            
            merge_dict(merged_config, config)
            
            logger.info(f"Configuração carregada de {self.config_file}")
            return merged_config
        except Exception as e:
            logger.error(f"Erro ao carregar configuração: {e}")
            return default_config
    
    def save_config(self, file_path=None):
        """
        Salva a configuração do EA em um arquivo JSON.
        
        Args:
            file_path (str, optional): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for salva com sucesso, False caso contrário
        """
        if not file_path:
            file_path = self.config_file or "mt5_tape_reading_ea_config.json"
        
        try:
            with open(file_path, "w") as f:
                json.dump(self.config, f, indent=4)
            
            logger.info(f"Configuração salva em {file_path}")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}")
            return False
    
    def connect(self):
        """
        Conecta ao terminal MetaTrader 5.
        
        Returns:
            bool: True se a conexão for bem-sucedida, False caso contrário
        """
        if self.connected:
            logger.info("Já conectado ao MetaTrader 5")
            return True
        
        try:
            # Inicializar MT5
            if not mt5.initialize():
                logger.error(f"Falha ao inicializar MetaTrader 5: {mt5.last_error()}")
                return False
            
            # Verificar se há credenciais configuradas
            account_config = self.config["account"]
            if account_config["login"] and account_config["password"] and account_config["server"]:
                # Fazer login
                login = int(account_config["login"])
                password = account_config["password"]
                server = account_config["server"]
                
                logger.info(f"Tentando fazer login na conta {login} no servidor {server}")
                
                if not mt5.login(login, password, server):
                    logger.error(f"Falha ao fazer login: {mt5.last_error()}")
                    mt5.shutdown()
                    return False
            
            # Verificar se o login foi bem-sucedido
            account_info = mt5.account_info()
            if account_info is None:
                logger.error("Falha ao obter informações da conta")
                mt5.shutdown()
                return False
            
            # Verificar tipo de conta
            account_type = "REAL" if account_info.trade_mode == 0 else "DEMO"
            logger.info(f"Conectado à conta {account_info.login} ({account_type}) - {account_info.server}")
            
            # Verificar se o tipo de conta corresponde ao configurado
            if account_config["type"] != account_type:
                logger.warning(f"Tipo de conta configurado ({account_config['type']}) difere do tipo real ({account_type})")
            
            # Atualizar configuração com informações da conta
            account_config["login"] = str(account_info.login)
            account_config["server"] = account_info.server
            account_config["type"] = account_type
            
            # Inicializar símbolos
            self.symbols = self.config["symbols"]
            for symbol in self.symbols:
                # Verificar se o símbolo existe
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    logger.warning(f"Símbolo {symbol} não encontrado, removendo da lista")
                    self.symbols.remove(symbol)
                    continue
                
                # Habilitar símbolo para trading
                if not symbol_info.visible:
                    logger.info(f"Habilitando símbolo {symbol} para trading")
                    if not mt5.symbol_select(symbol, True):
                        logger.warning(f"Falha ao habilitar símbolo {symbol}: {mt5.last_error()}")
                
                # Inicializar dados do símbolo
                self.symbol_data[symbol] = {
                    "point": symbol_info.point,
                    "digits": symbol_info.digits,
                    "tick_value": symbol_info.trade_tick_value,
                    "contract_size": symbol_info.trade_contract_size,
                    "volume_min": symbol_info.volume_min,
                    "volume_max": symbol_info.volume_max,
                    "volume_step": symbol_info.volume_step
                }
                
                # Inicializar estruturas de dados para análise
                self.last_tick_time[symbol] = datetime.now()
                self.volume_profile[symbol] = {}
                self.price_levels[symbol] = []
                self.market_depth[symbol] = {"bid": [], "ask": []}
                self.trade_signals[symbol] = {"action": "NONE", "strength": 0.0, "timestamp": datetime.now()}
            
            self.connected = True
            logger.info("Conexão com MetaTrader 5 estabelecida com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao conectar ao MetaTrader 5: {e}")
            if mt5.initialize():
                mt5.shutdown()
            return False
    
    def disconnect(self):
        """
        Desconecta do terminal MetaTrader 5.
        
        Returns:
            bool: True se a desconexão for bem-sucedida, False caso contrário
        """
        if not self.connected:
            logger.info("Não conectado ao MetaTrader 5")
            return True
        
        try:
            # Parar EA se estiver em execução
            if self.running:
                self.stop()
            
            # Desconectar do MT5
            mt5.shutdown()
            
            self.connected = False
            logger.info("Desconectado do MetaTrader 5")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar do MetaTrader 5: {e}")
            return False
    
    def start(self):
        """
        Inicia o EA de Tape Reading.
        
        Returns:
            bool: True se o EA for iniciado com sucesso, False caso contrário
        """
        if self.running:
            logger.warning("EA já está em execução")
            return True
        
        if not self.connected:
            logger.error("Não conectado ao MetaTrader 5")
            return False
        
        try:
            # Iniciar threads de análise e execução
            self.running = True
            
            # Thread de análise de Tape Reading
            self.analysis_thread = threading.Thread(
                target=self._analysis_loop,
                daemon=True
            )
            self.analysis_thread.start()
            
            # Thread de execução de ordens
            self.execution_thread = threading.Thread(
                target=self._execution_loop,
                daemon=True
            )
            self.execution_thread.start()
            
            # Thread de gerenciamento de posições
            self.position_thread = threading.Thread(
                target=self._position_management_loop,
                daemon=True
            )
            self.position_thread.start()
            
            logger.info("EA de Tape Reading iniciado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao iniciar EA: {e}")
            self.running = False
            return False
    
    def stop(self):
        """
        Para o EA de Tape Reading.
        
        Returns:
            bool: True se o EA for parado com sucesso, False caso contrário
        """
        if not self.running:
            logger.warning("EA não está em execução")
            return True
        
        try:
            # Parar threads
            self.running = False
            
            # Aguardar finalização das threads
            if hasattr(self, 'analysis_thread') and self.analysis_thread.is_alive():
                self.analysis_thread.join(timeout=5)
            
            if hasattr(self, 'execution_thread') and self.execution_thread.is_alive():
                self.execution_thread.join(timeout=5)
            
            if hasattr(self, 'position_thread') and self.position_thread.is_alive():
                self.position_thread.join(timeout=5)
            
            logger.info("EA de Tape Reading parado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao parar EA: {e}")
            return False
    
    def _analysis_loop(self):
        """
        Loop principal de análise de Tape Reading.
        """
        logger.info("Iniciando loop de análise de Tape Reading")
        
        while self.running:
            try:
                # Processar cada símbolo
                for symbol in self.symbols:
                    # Verificar se é hora de trading
                    if not self._check_trading_time():
                        continue
                    
                    # Obter dados de mercado
                    self._update_market_data(symbol)
                    
                    # Analisar Tape Reading
                    self._analyze_tape_reading(symbol)
                
                # Aguardar próxima análise
                time.sleep(0.1)  # 100ms
                
            except Exception as e:
                logger.error(f"Erro no loop de análise: {e}")
                time.sleep(1)
    
    def _execution_loop(self):
        """
        Loop principal de execução de ordens.
        """
        logger.info("Iniciando loop de execução de ordens")
        
        while self.running:
            try:
                # Processar cada símbolo
                for symbol in self.symbols:
                    # Verificar se é hora de trading
                    if not self._check_trading_time():
                        continue
                    
                    # Verificar sinais de negociação
                    self._check_trade_signals(symbol)
                
                # Aguardar próxima verificação
                time.sleep(0.5)  # 500ms
                
            except Exception as e:
                logger.error(f"Erro no loop de execução: {e}")
                time.sleep(1)
    
    def _position_management_loop(self):
        """
        Loop principal de gerenciamento de posições.
        """
        logger.info("Iniciando loop de gerenciamento de posições")
        
        while self.running:
            try:
                # Atualizar posições abertas
                self._update_positions()
                
                # Gerenciar posições abertas
                self._manage_positions()
                
                # Atualizar métricas de desempenho
                self._update_performance_metrics()
                
                # Aguardar próxima verificação
                time.sleep(1)  # 1s
                
            except Exception as e:
                logger.error(f"Erro no loop de gerenciamento de posições: {e}")
                time.sleep(1)
    
    def _update_market_data(self, symbol):
        """
        Atualiza dados de mercado para um símbolo.
        
        Args:
            symbol (str): Símbolo para atualizar
        """
        try:
            # Obter último tick
            last_tick = mt5.symbol_info_tick(symbol)
            if last_tick is None:
                logger.warning(f"Falha ao obter tick para {symbol}: {mt5.last_error()}")
                return
            
            # Converter para datetime
            tick_time = datetime.fromtimestamp(last_tick.time)
            
            # Verificar se é um novo tick
            if symbol in self.last_tick_time and tick_time <= self.last_tick_time[symbol]:
                return
            
            # Atualizar último tick
            self.last_tick_time[symbol] = tick_time
            
            # Obter profundidade de mercado (book de ofertas)
            depth = mt5.market_book_get(symbol)
            if depth is None:
                logger.debug(f"Profundidade de mercado não disponível para {symbol}")
            else:
                # Processar profundidade de mercado
                self._process_market_depth(symbol, depth)
            
            # Obter ticks recentes
            tape_config = self.config["tape_reading"]
            ticks = mt5.copy_ticks_from(symbol, tick_time - timedelta(minutes=5), 
                                        tape_config["tick_window"], mt5.COPY_TICKS_ALL)
            
            if ticks is None or len(ticks) == 0:
                logger.warning(f"Falha ao obter ticks para {symbol}: {mt5.last_error()}")
                return
            
            # Processar ticks para análise de Tape Reading
            self._process_ticks(symbol, ticks)
            
            # Obter dados de timeframe para análise
            timeframe = self._get_mt5_timeframe(self.config["timeframes"]["analysis"])
            rates = mt5.copy_rates_from(symbol, timeframe, tick_time, 100)
            
            if rates is None or len(rates) == 0:
                logger.warning(f"Falha ao obter rates para {symbol}: {mt5.last_error()}")
                return
            
            # Processar rates para análise
            self._process_rates(symbol, rates)
            
        except Exception as e:
            logger.error(f"Erro ao atualizar dados de mercado para {symbol}: {e}")
    
    def _process_market_depth(self, symbol, depth):
        """
        Processa dados de profundidade de mercado (book de ofertas).
        
        Args:
            symbol (str): Símbolo
            depth (list): Dados de profundidade de mercado
        """
        try:
            # Limpar dados anteriores
            self.market_depth[symbol] = {"bid": [], "ask": []}
            
            # Processar cada nível
            for item in depth:
                # Converter para dicionário
                level = {
                    "type": item.type,
                    "price": item.price,
                    "volume": item.volume,
                    "volume_dbl": item.volume_dbl
                }
                
                # Adicionar ao lado apropriado
                if item.type == mt5.BOOK_TYPE_SELL:
                    self.market_depth[symbol]["ask"].append(level)
                elif item.type == mt5.BOOK_TYPE_BUY:
                    self.market_depth[symbol]["bid"].append(level)
            
            # Ordenar níveis
            self.market_depth[symbol]["bid"].sort(key=lambda x: x["price"], reverse=True)
            self.market_depth[symbol]["ask"].sort(key=lambda x: x["price"])
            
            # Limitar número de níveis
            max_levels = self.config["tape_reading"]["market_depth_levels"]
            self.market_depth[symbol]["bid"] = self.market_depth[symbol]["bid"][:max_levels]
            self.market_depth[symbol]["ask"] = self.market_depth[symbol]["ask"][:max_levels]
            
            # Calcular desequilíbrio de volume
            self._calculate_volume_imbalance(symbol)
            
        except Exception as e:
            logger.error(f"Erro ao processar profundidade de mercado para {symbol}: {e}")
    
    def _process_ticks(self, symbol, ticks):
        """
        Processa ticks para análise de Tape Reading.
        
        Args:
            symbol (str): Símbolo
            ticks (list): Lista de ticks
        """
        try:
            # Converter para DataFrame
            df = pd.DataFrame(ticks)
            
            # Converter timestamp para datetime
            df["time"] = pd.to_datetime(df["time"], unit="s")
            
            # Calcular delta (diferença entre volume de compra e venda)
            df["delta"] = 0
            buy_mask = df["flags"] & mt5.TICK_FLAG_BUY != 0
            sell_mask = df["flags"] & mt5.TICK_FLAG_SELL != 0
            df.loc[buy_mask, "delta"] = df.loc[buy_mask, "volume"]
            df.loc[sell_mask, "delta"] = -df.loc[sell_mask, "volume"]
            
            # Calcular delta cumulativo
            df["cum_delta"] = df["delta"].cumsum()
            
            # Calcular VWAP (Volume Weighted Average Price)
            df["volume_price"] = df["volume"] * (df["bid"] + df["ask"]) / 2
            df["vwap"] = df["volume_price"].cumsum() / df["volume"].cumsum()
            
            # Identificar níveis de preço importantes
            price_levels = self._identify_price_levels(df)
            self.price_levels[symbol] = price_levels
            
            # Construir perfil de volume
            self._build_volume_profile(symbol, df)
            
            # Calcular footprint
            self._calculate_footprint(symbol, df)
            
        except Exception as e:
            logger.error(f"Erro ao processar ticks para {symbol}: {e}")
    
    def _process_rates(self, symbol, rates):
        """
        Processa rates para análise técnica.
        
        Args:
            symbol (str): Símbolo
            rates (list): Lista de rates
        """
        try:
            # Converter para DataFrame
            df = pd.DataFrame(rates)
            
            # Converter timestamp para datetime
            df["time"] = pd.to_datetime(df["time"], unit="s")
            
            # Calcular indicadores técnicos
            # (Estes podem ser usados em conjunto com a análise de Tape Reading)
            
            # Médias móveis
            df["sma20"] = df["close"].rolling(window=20).mean()
            df["sma50"] = df["close"].rolling(window=50).mean()
            
            # Bandas de Bollinger
            df["sma20"] = df["close"].rolling(window=20).mean()
            df["std20"] = df["close"].rolling(window=20).std()
            df["upper_band"] = df["sma20"] + 2 * df["std20"]
            df["lower_band"] = df["sma20"] - 2 * df["std20"]
            
            # RSI
            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            avg_gain = gain.rolling(window=14).mean()
            avg_loss = loss.rolling(window=14).mean()
            rs = avg_gain / avg_loss
            df["rsi"] = 100 - (100 / (1 + rs))
            
            # Armazenar dados processados
            self.symbol_data[symbol]["rates"] = df
            
        except Exception as e:
            logger.error(f"Erro ao processar rates para {symbol}: {e}")
    
    def _identify_price_levels(self, df):
        """
        Identifica níveis de preço importantes com base no volume.
        
        Args:
            df (DataFrame): DataFrame de ticks
            
        Returns:
            list: Lista de níveis de preço importantes
        """
        try:
            # Arredondar preços para identificar níveis
            digits = self.symbol_data[df.iloc[0]["symbol"]]["digits"]
            price_precision = 10 ** -digits
            
            df["price_level"] = np.round((df["bid"] + df["ask"]) / 2 / price_precision) * price_precision
            
            # Agrupar por nível de preço e somar volume
            volume_by_price = df.groupby("price_level")["volume"].sum().reset_index()
            
            # Ordenar por volume
            volume_by_price = volume_by_price.sort_values("volume", ascending=False)
            
            # Selecionar os níveis com maior volume
            top_levels = volume_by_price.head(self.config["tape_reading"]["price_levels"])
            
            # Converter para lista de dicionários
            price_levels = []
            for _, row in top_levels.iterrows():
                price_levels.append({
                    "price": row["price_level"],
                    "volume": row["volume"]
                })
            
            return price_levels
            
        except Exception as e:
            logger.error(f"Erro ao identificar níveis de preço: {e}")
            return []
    
    def _build_volume_profile(self, symbol, df):
        """
        Constrói perfil de volume para análise de Tape Reading.
        
        Args:
            symbol (str): Símbolo
            df (DataFrame): DataFrame de ticks
        """
        try:
            # Arredondar preços para criar perfil de volume
            digits = self.symbol_data[symbol]["digits"]
            price_precision = 10 ** -digits
            
            df["price_level"] = np.round((df["bid"] + df["ask"]) / 2 / price_precision) * price_precision
            
            # Separar volume de compra e venda
            buy_volume = df[df["flags"] & mt5.TICK_FLAG_BUY != 0].groupby("price_level")["volume"].sum()
            sell_volume = df[df["flags"] & mt5.TICK_FLAG_SELL != 0].groupby("price_level")["volume"].sum()
            
            # Criar perfil de volume
            volume_profile = {}
            for price in set(buy_volume.index) | set(sell_volume.index):
                volume_profile[price] = {
                    "buy_volume": buy_volume.get(price, 0),
                    "sell_volume": sell_volume.get(price, 0),
                    "total_volume": buy_volume.get(price, 0) + sell_volume.get(price, 0),
                    "delta": buy_volume.get(price, 0) - sell_volume.get(price, 0)
                }
            
            # Armazenar perfil de volume
            self.volume_profile[symbol] = volume_profile
            
        except Exception as e:
            logger.error(f"Erro ao construir perfil de volume para {symbol}: {e}")
    
    def _calculate_footprint(self, symbol, df):
        """
        Calcula footprint (impressão de volume) para análise de Tape Reading.
        
        Args:
            symbol (str): Símbolo
            df (DataFrame): DataFrame de ticks
        """
        try:
            # Agrupar por tempo (em intervalos de 1 minuto) e nível de preço
            df["minute"] = df["time"].dt.floor("1min")
            
            # Arredondar preços
            digits = self.symbol_data[symbol]["digits"]
            price_precision = 10 ** -digits
            df["price_level"] = np.round((df["bid"] + df["ask"]) / 2 / price_precision) * price_precision
            
            # Calcular volume de compra e venda por minuto e nível de preço
            buy_volume = df[df["flags"] & mt5.TICK_FLAG_BUY != 0].groupby(["minute", "price_level"])["volume"].sum()
            sell_volume = df[df["flags"] & mt5.TICK_FLAG_SELL != 0].groupby(["minute", "price_level"])["volume"].sum()
            
            # Criar footprint
            footprint = {}
            for (minute, price) in set(buy_volume.index) | set(sell_volume.index):
                if minute not in footprint:
                    footprint[minute] = {}
                
                footprint[minute][price] = {
                    "buy_volume": buy_volume.get((minute, price), 0),
                    "sell_volume": sell_volume.get((minute, price), 0),
                    "total_volume": buy_volume.get((minute, price), 0) + sell_volume.get((minute, price), 0),
                    "delta": buy_volume.get((minute, price), 0) - sell_volume.get((minute, price), 0)
                }
            
            # Armazenar footprint
            self.symbol_data[symbol]["footprint"] = footprint
            
        except Exception as e:
            logger.error(f"Erro ao calcular footprint para {symbol}: {e}")
    
    def _calculate_volume_imbalance(self, symbol):
        """
        Calcula desequilíbrio de volume com base na profundidade de mercado.
        
        Args:
            symbol (str): Símbolo
        """
        try:
            depth = self.market_depth[symbol]
            
            # Verificar se há dados suficientes
            if not depth["bid"] or not depth["ask"]:
                return
            
            # Calcular volume total de compra e venda
            bid_volume = sum(level["volume"] for level in depth["bid"])
            ask_volume = sum(level["volume"] for level in depth["ask"])
            
            # Calcular razão de desequilíbrio
            if ask_volume > 0:
                buy_sell_ratio = bid_volume / ask_volume
            else:
                buy_sell_ratio = float('inf')
            
            # Armazenar razão
            self.symbol_data[symbol]["volume_imbalance"] = buy_sell_ratio
            
            # Calcular pressão de compra/venda
            if bid_volume + ask_volume > 0:
                buy_pressure = bid_volume / (bid_volume + ask_volume)
                sell_pressure = ask_volume / (bid_volume + ask_volume)
            else:
                buy_pressure = 0.5
                sell_pressure = 0.5
            
            self.symbol_data[symbol]["buy_pressure"] = buy_pressure
            self.symbol_data[symbol]["sell_pressure"] = sell_pressure
            
        except Exception as e:
            logger.error(f"Erro ao calcular desequilíbrio de volume para {symbol}: {e}")
    
    def _analyze_tape_reading(self, symbol):
        """
        Analisa dados de Tape Reading para identificar sinais de negociação.
        
        Args:
            symbol (str): Símbolo
        """
        try:
            # Verificar se temos dados suficientes
            if (symbol not in self.volume_profile or 
                symbol not in self.price_levels or 
                symbol not in self.market_depth):
                return
            
            # Obter configuração de Tape Reading
            tape_config = self.config["tape_reading"]
            
            # Obter último tick
            last_tick = mt5.symbol_info_tick(symbol)
            if last_tick is None:
                return
            
            current_price = (last_tick.bid + last_tick.ask) / 2
            
            # Inicializar pontuação de sinal
            buy_score = 0
            sell_score = 0
            
            # 1. Análise de desequilíbrio de volume
            if "volume_imbalance" in self.symbol_data[symbol]:
                imbalance = self.symbol_data[symbol]["volume_imbalance"]
                threshold = tape_config["volume_imbalance_threshold"]
                
                if imbalance > threshold:
                    # Mais compradores que vendedores
                    buy_score += min(imbalance / threshold, 3)  # Limitar pontuação
                elif imbalance < 1/threshold:
                    # Mais vendedores que compradores
                    sell_score += min((1/imbalance) / threshold, 3)  # Limitar pontuação
            
            # 2. Análise de pressão de compra/venda
            if "buy_pressure" in self.symbol_data[symbol] and "sell_pressure" in self.symbol_data[symbol]:
                buy_pressure = self.symbol_data[symbol]["buy_pressure"]
                sell_pressure = self.symbol_data[symbol]["sell_pressure"]
                
                if buy_pressure > 0.65:  # Forte pressão de compra
                    buy_score += (buy_pressure - 0.5) * 10
                elif sell_pressure > 0.65:  # Forte pressão de venda
                    sell_score += (sell_pressure - 0.5) * 10
            
            # 3. Análise de perfil de volume
            volume_profile = self.volume_profile[symbol]
            
            # Encontrar níveis próximos ao preço atual
            nearby_levels = []
            for price, data in volume_profile.items():
                if abs(price - current_price) < 10 * self.symbol_data[symbol]["point"]:
                    nearby_levels.append((price, data))
            
            # Analisar delta de volume nos níveis próximos
            for price, data in nearby_levels:
                delta = data["delta"]
                total_volume = data["total_volume"]
                
                if total_volume > tape_config["volume_threshold"]:
                    # Calcular razão delta/volume
                    delta_ratio = delta / total_volume if total_volume > 0 else 0
                    
                    if delta_ratio > tape_config["delta_threshold"]:
                        # Forte compra neste nível
                        if price < current_price:  # Suporte
                            buy_score += delta_ratio * 2
                        else:  # Resistência sendo testada
                            buy_score += delta_ratio
                    elif delta_ratio < -tape_config["delta_threshold"]:
                        # Forte venda neste nível
                        if price > current_price:  # Resistência
                            sell_score += -delta_ratio * 2
                        else:  # Suporte sendo testado
                            sell_score += -delta_ratio
            
            # 4. Análise de footprint
            if "footprint" in self.symbol_data[symbol]:
                footprint = self.symbol_data[symbol]["footprint"]
                
                # Obter últimos minutos
                recent_minutes = sorted(footprint.keys())[-tape_config["footprint_levels"]:]
                
                # Analisar tendência recente
                cumulative_delta = 0
                for minute in recent_minutes:
                    minute_data = footprint[minute]
                    for price, data in minute_data.items():
                        cumulative_delta += data["delta"]
                
                # Adicionar pontuação com base no delta cumulativo
                if cumulative_delta > 0:
                    buy_score += min(cumulative_delta / 100, 2)  # Limitar pontuação
                else:
                    sell_score += min(-cumulative_delta / 100, 2)  # Limitar pontuação
            
            # 5. Análise de níveis de preço importantes
            price_levels = self.price_levels[symbol]
            
            # Verificar proximidade a níveis importantes
            for level in price_levels:
                price = level["price"]
                volume = level["volume"]
                
                # Verificar se o preço atual está próximo a um nível importante
                if abs(price - current_price) < 5 * self.symbol_data[symbol]["point"]:
                    # Verificar direção do preço
                    if "rates" in self.symbol_data[symbol]:
                        rates = self.symbol_data[symbol]["rates"]
                        if len(rates) > 1:
                            last_close = rates.iloc[-1]["close"]
                            prev_close = rates.iloc[-2]["close"]
                            
                            if last_close > prev_close and price > current_price:
                                # Preço subindo em direção a um nível importante
                                if volume > tape_config["volume_threshold"]:
                                    # Nível com alto volume (possível resistência)
                                    sell_score += 1
                            elif last_close < prev_close and price < current_price:
                                # Preço caindo em direção a um nível importante
                                if volume > tape_config["volume_threshold"]:
                                    # Nível com alto volume (possível suporte)
                                    buy_score += 1
            
            # 6. Análise técnica complementar
            if "rates" in self.symbol_data[symbol]:
                rates = self.symbol_data[symbol]["rates"]
                if len(rates) > 50:  # Garantir que temos dados suficientes
                    last_row = rates.iloc[-1]
                    
                    # Verificar tendência das médias móveis
                    if "sma20" in rates.columns and "sma50" in rates.columns:
                        if last_row["sma20"] > last_row["sma50"]:
                            # Tendência de alta
                            buy_score += 0.5
                        else:
                            # Tendência de baixa
                            sell_score += 0.5
                    
                    # Verificar RSI
                    if "rsi" in rates.columns:
                        rsi = last_row["rsi"]
                        if rsi < 30:  # Sobrevendido
                            buy_score += 1
                        elif rsi > 70:  # Sobrecomprado
                            sell_score += 1
                    
                    # Verificar Bandas de Bollinger
                    if all(col in rates.columns for col in ["upper_band", "lower_band"]):
                        if last_row["close"] < last_row["lower_band"]:
                            # Preço abaixo da banda inferior
                            buy_score += 1
                        elif last_row["close"] > last_row["upper_band"]:
                            # Preço acima da banda superior
                            sell_score += 1
            
            # Determinar sinal final
            signal = {"action": "NONE", "strength": 0.0, "timestamp": datetime.now()}
            
            # Definir limiar para sinal
            signal_threshold = 3.0  # Ajustar conforme necessário
            
            if buy_score > sell_score and buy_score > signal_threshold:
                signal["action"] = "BUY"
                signal["strength"] = buy_score
            elif sell_score > buy_score and sell_score > signal_threshold:
                signal["action"] = "SELL"
                signal["strength"] = sell_score
            
            # Armazenar sinal
            self.trade_signals[symbol] = signal
            
            logger.debug(f"Análise de {symbol}: BUY={buy_score:.2f}, SELL={sell_score:.2f}, Sinal={signal['action']}")
            
        except Exception as e:
            logger.error(f"Erro ao analisar Tape Reading para {symbol}: {e}")
    
    def _check_trade_signals(self, symbol):
        """
        Verifica sinais de negociação e executa ordens se necessário.
        
        Args:
            symbol (str): Símbolo
        """
        try:
            # Verificar se temos um sinal
            if symbol not in self.trade_signals:
                return
            
            signal = self.trade_signals[symbol]
            
            # Verificar se o sinal é recente (menos de 5 segundos)
            if (datetime.now() - signal["timestamp"]).total_seconds() > 5:
                return
            
            # Verificar se temos uma ação
            if signal["action"] == "NONE":
                return
            
            # Verificar se já temos uma posição aberta para este símbolo
            positions = self._get_positions(symbol)
            
            # Verificar limites de posições abertas
            max_positions = self.config["risk_management"]["max_open_positions"]
            total_positions = len(self._get_positions())
            
            if total_positions >= max_positions:
                logger.info(f"Limite de posições abertas atingido ({max_positions})")
                return
            
            # Verificar spread
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return
            
            current_spread = (symbol_info.ask - symbol_info.bid) / symbol_info.point
            max_spread = self.config["execution"]["max_spread_pips"]
            
            if current_spread > max_spread:
                logger.info(f"Spread muito alto para {symbol}: {current_spread} > {max_spread}")
                return
            
            # Verificar se já temos uma posição na mesma direção
            has_buy_position = any(pos["type"] == mt5.POSITION_TYPE_BUY for pos in positions)
            has_sell_position = any(pos["type"] == mt5.POSITION_TYPE_SELL for pos in positions)
            
            # Executar ordem com base no sinal
            if signal["action"] == "BUY" and not has_buy_position:
                self._execute_order(symbol, "BUY")
            elif signal["action"] == "SELL" and not has_sell_position:
                self._execute_order(symbol, "SELL")
            
        except Exception as e:
            logger.error(f"Erro ao verificar sinais de negociação para {symbol}: {e}")
    
    def _execute_order(self, symbol, action):
        """
        Executa uma ordem de compra ou venda.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            
        Returns:
            bool: True se a ordem for executada com sucesso, False caso contrário
        """
        try:
            # Verificar se é hora de trading
            if not self._check_trading_time():
                logger.info(f"Fora do horário de trading, ordem não executada")
                return False
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return False
            
            # Obter último tick
            last_tick = mt5.symbol_info_tick(symbol)
            if last_tick is None:
                logger.warning(f"Falha ao obter tick para {symbol}")
                return False
            
            # Determinar preço
            if action == "BUY":
                price = last_tick.ask
                position_type = mt5.ORDER_TYPE_BUY
            else:  # SELL
                price = last_tick.bid
                position_type = mt5.ORDER_TYPE_SELL
            
            # Calcular tamanho da posição
            volume = self._calculate_position_size(symbol, action)
            
            if volume <= 0:
                logger.warning(f"Volume calculado inválido: {volume}")
                return False
            
            # Calcular stop loss e take profit
            sl, tp = self._calculate_sl_tp(symbol, action, price)
            
            # Preparar solicitação de negociação
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": position_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": self.config["execution"]["slippage_pips"],
                "magic": 123456,  # Identificador do EA
                "comment": "MT5 Tape Reading EA",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            
            # Enviar ordem
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Falha ao executar ordem: {result.retcode} - {result.comment}")
                return False
            
            # Registrar ordem executada
            logger.info(f"Ordem executada: {action} {volume} {symbol} @ {price}, SL: {sl}, TP: {tp}")
            
            # Adicionar à lista de ordens
            order_info = {
                "ticket": result.order,
                "symbol": symbol,
                "type": position_type,
                "volume": volume,
                "price": price,
                "sl": sl,
                "tp": tp,
                "time": datetime.now()
            }
            
            self.orders[result.order] = order_info
            
            # Enviar notificação
            if self.config["notifications"]["enabled"] and self.config["notifications"]["trade_opened"]:
                self._send_notification(f"Nova ordem: {action} {volume} {symbol} @ {price}")
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao executar ordem: {e}")
            return False
    
    def _calculate_position_size(self, symbol, action):
        """
        Calcula o tamanho da posição com base na gestão de risco.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            
        Returns:
            float: Tamanho da posição
        """
        try:
            # Obter configuração de gestão de risco
            risk_config = self.config["risk_management"]
            position_sizing = risk_config["position_sizing"]
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return 0
            
            # Obter informações da conta
            account_info = mt5.account_info()
            if account_info is None:
                logger.warning("Falha ao obter informações da conta")
                return 0
            
            # Obter último tick
            last_tick = mt5.symbol_info_tick(symbol)
            if last_tick is None:
                logger.warning(f"Falha ao obter tick para {symbol}")
                return 0
            
            # Determinar preço
            if action == "BUY":
                price = last_tick.ask
            else:  # SELL
                price = last_tick.bid
            
            # Calcular tamanho da posição com base no método selecionado
            if position_sizing == "fixed":
                # Tamanho fixo de lote
                volume = risk_config["fixed_lot_size"]
            
            elif position_sizing == "risk":
                # Baseado no risco por operação
                risk_percent = risk_config["max_risk_percent"]
                stop_loss_pips = risk_config["stop_loss_pips"]
                
                # Calcular valor em risco
                risk_amount = account_info.balance * (risk_percent / 100)
                
                # Calcular valor do pip
                pip_value = symbol_info.trade_tick_value * (10 ** (symbol_info.digits - 4))
                
                # Calcular volume baseado no risco
                if stop_loss_pips > 0 and pip_value > 0:
                    volume = risk_amount / (stop_loss_pips * pip_value)
                else:
                    volume = risk_config["fixed_lot_size"]
            
            elif position_sizing == "equity":
                # Baseado em percentual do patrimônio
                equity_percent = risk_config["max_risk_percent"]
                
                # Calcular valor baseado no patrimônio
                position_value = account_info.equity * (equity_percent / 100)
                
                # Calcular volume
                if price > 0:
                    volume = position_value / (price * symbol_info.trade_contract_size)
                else:
                    volume = risk_config["fixed_lot_size"]
            
            else:
                # Método desconhecido, usar tamanho fixo
                volume = risk_config["fixed_lot_size"]
            
            # Ajustar volume para os limites do símbolo
            volume = max(volume, symbol_info.volume_min)
            volume = min(volume, symbol_info.volume_max)
            
            # Arredondar para o passo de volume
            volume_step = symbol_info.volume_step
            volume = round(volume / volume_step) * volume_step
            
            return volume
            
        except Exception as e:
            logger.error(f"Erro ao calcular tamanho da posição: {e}")
            return self.config["risk_management"]["fixed_lot_size"]
    
    def _calculate_sl_tp(self, symbol, action, price):
        """
        Calcula níveis de stop loss e take profit.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            price (float): Preço de entrada
            
        Returns:
            tuple: (stop_loss, take_profit)
        """
        try:
            # Obter configuração de gestão de risco
            risk_config = self.config["risk_management"]
            stop_loss_pips = risk_config["stop_loss_pips"]
            take_profit_pips = risk_config["take_profit_pips"]
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return (0, 0)
            
            # Obter valor do pip
            point = symbol_info.point
            
            # Calcular stop loss e take profit
            if action == "BUY":
                sl = price - stop_loss_pips * 10 * point if stop_loss_pips > 0 else 0
                tp = price + take_profit_pips * 10 * point if take_profit_pips > 0 else 0
            else:  # SELL
                sl = price + stop_loss_pips * 10 * point if stop_loss_pips > 0 else 0
                tp = price - take_profit_pips * 10 * point if take_profit_pips > 0 else 0
            
            # Arredondar para a precisão do símbolo
            digits = symbol_info.digits
            sl = round(sl, digits)
            tp = round(tp, digits)
            
            return (sl, tp)
            
        except Exception as e:
            logger.error(f"Erro ao calcular stop loss e take profit: {e}")
            return (0, 0)
    
    def _update_positions(self):
        """
        Atualiza a lista de posições abertas.
        """
        try:
            # Obter posições abertas
            positions = mt5.positions_get()
            
            if positions is None:
                logger.debug("Nenhuma posição aberta")
                self.positions = {}
                return
            
            # Atualizar dicionário de posições
            new_positions = {}
            for position in positions:
                # Converter para dicionário
                pos_dict = {
                    "ticket": position.ticket,
                    "symbol": position.symbol,
                    "type": position.type,
                    "volume": position.volume,
                    "open_price": position.price_open,
                    "current_price": position.price_current,
                    "sl": position.sl,
                    "tp": position.tp,
                    "profit": position.profit,
                    "swap": position.swap,
                    "time": position.time,
                    "magic": position.magic,
                    "comment": position.comment
                }
                
                new_positions[position.ticket] = pos_dict
            
            # Atualizar posições
            self.positions = new_positions
            
        except Exception as e:
            logger.error(f"Erro ao atualizar posições: {e}")
    
    def _get_positions(self, symbol=None):
        """
        Obtém posições abertas.
        
        Args:
            symbol (str, optional): Símbolo para filtrar
            
        Returns:
            list: Lista de posições
        """
        try:
            if symbol:
                # Filtrar por símbolo
                return [pos for pos in self.positions.values() if pos["symbol"] == symbol]
            else:
                # Todas as posições
                return list(self.positions.values())
        except Exception as e:
            logger.error(f"Erro ao obter posições: {e}")
            return []
    
    def _manage_positions(self):
        """
        Gerencia posições abertas (trailing stop, break even, etc.).
        """
        try:
            # Verificar se há posições para gerenciar
            if not self.positions:
                return
            
            # Obter configuração de gestão de risco
            risk_config = self.config["risk_management"]
            
            # Processar cada posição
            for ticket, position in self.positions.items():
                symbol = position["symbol"]
                position_type = position["type"]
                open_price = position["open_price"]
                current_price = position["current_price"]
                sl = position["sl"]
                tp = position["tp"]
                
                # Obter informações do símbolo
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    continue
                
                # Obter valor do pip
                point = symbol_info.point
                
                # Calcular lucro em pips
                if position_type == mt5.POSITION_TYPE_BUY:
                    profit_pips = (current_price - open_price) / (10 * point)
                else:  # SELL
                    profit_pips = (open_price - current_price) / (10 * point)
                
                # Verificar break even
                if risk_config["break_even"] and sl != 0:
                    break_even_pips = risk_config["break_even_pips"]
                    
                    if profit_pips >= break_even_pips:
                        # Verificar se já está em break even
                        if position_type == mt5.POSITION_TYPE_BUY and sl < open_price:
                            # Mover stop loss para break even
                            new_sl = open_price
                            self._modify_position(ticket, new_sl, tp)
                            logger.info(f"Stop loss movido para break even: {ticket} {symbol}")
                        
                        elif position_type == mt5.POSITION_TYPE_SELL and sl > open_price:
                            # Mover stop loss para break even
                            new_sl = open_price
                            self._modify_position(ticket, new_sl, tp)
                            logger.info(f"Stop loss movido para break even: {ticket} {symbol}")
                
                # Verificar trailing stop
                if risk_config["trailing_stop"] and sl != 0:
                    trailing_start = risk_config["trailing_stop_start_pips"]
                    trailing_distance = risk_config["trailing_stop_distance_pips"]
                    
                    if profit_pips >= trailing_start:
                        if position_type == mt5.POSITION_TYPE_BUY:
                            # Calcular novo stop loss
                            new_sl = current_price - trailing_distance * 10 * point
                            
                            # Verificar se é melhor que o atual
                            if new_sl > sl:
                                self._modify_position(ticket, new_sl, tp)
                                logger.info(f"Trailing stop atualizado: {ticket} {symbol} {new_sl}")
                        
                        elif position_type == mt5.POSITION_TYPE_SELL:
                            # Calcular novo stop loss
                            new_sl = current_price + trailing_distance * 10 * point
                            
                            # Verificar se é melhor que o atual
                            if new_sl < sl or sl == 0:
                                self._modify_position(ticket, new_sl, tp)
                                logger.info(f"Trailing stop atualizado: {ticket} {symbol} {new_sl}")
            
        except Exception as e:
            logger.error(f"Erro ao gerenciar posições: {e}")
    
    def _modify_position(self, ticket, sl, tp):
        """
        Modifica uma posição aberta.
        
        Args:
            ticket (int): Ticket da posição
            sl (float): Novo stop loss
            tp (float): Novo take profit
            
        Returns:
            bool: True se a modificação for bem-sucedida, False caso contrário
        """
        try:
            # Preparar solicitação de modificação
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl": sl,
                "tp": tp
            }
            
            # Enviar solicitação
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Falha ao modificar posição: {result.retcode} - {result.comment}")
                return False
            
            # Atualizar posição na lista
            if ticket in self.positions:
                self.positions[ticket]["sl"] = sl
                self.positions[ticket]["tp"] = tp
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao modificar posição: {e}")
            return False
    
    def _close_position(self, ticket):
        """
        Fecha uma posição aberta.
        
        Args:
            ticket (int): Ticket da posição
            
        Returns:
            bool: True se o fechamento for bem-sucedido, False caso contrário
        """
        try:
            # Verificar se a posição existe
            if ticket not in self.positions:
                logger.warning(f"Posição {ticket} não encontrada")
                return False
            
            position = self.positions[ticket]
            
            # Obter informações do símbolo
            symbol = position["symbol"]
            symbol_info = mt5.symbol_info(symbol)
            
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return False
            
            # Obter último tick
            last_tick = mt5.symbol_info_tick(symbol)
            if last_tick is None:
                logger.warning(f"Falha ao obter tick para {symbol}")
                return False
            
            # Determinar preço
            if position["type"] == mt5.POSITION_TYPE_BUY:
                price = last_tick.bid
                position_type = mt5.ORDER_TYPE_SELL
            else:  # SELL
                price = last_tick.ask
                position_type = mt5.ORDER_TYPE_BUY
            
            # Preparar solicitação de fechamento
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": position["volume"],
                "type": position_type,
                "position": ticket,
                "price": price,
                "deviation": self.config["execution"]["slippage_pips"],
                "magic": 123456,
                "comment": "MT5 Tape Reading EA - Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            
            # Enviar solicitação
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Falha ao fechar posição: {result.retcode} - {result.comment}")
                return False
            
            # Registrar fechamento
            logger.info(f"Posição fechada: {ticket} {symbol} @ {price}")
            
            # Remover da lista de posições
            if ticket in self.positions:
                # Adicionar ao histórico de negociações
                trade = self.positions[ticket].copy()
                trade["close_price"] = price
                trade["close_time"] = datetime.now()
                trade["profit_final"] = position["profit"]
                self.trade_history.append(trade)
                
                # Remover da lista de posições
                del self.positions[ticket]
            
            # Enviar notificação
            if self.config["notifications"]["enabled"] and self.config["notifications"]["trade_closed"]:
                self._send_notification(f"Posição fechada: {ticket} {symbol} @ {price}")
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao fechar posição: {e}")
            return False
    
    def _update_performance_metrics(self):
        """
        Atualiza métricas de desempenho.
        """
        try:
            # Verificar se há histórico de negociações
            if not self.trade_history:
                return
            
            # Calcular métricas
            total_trades = len(self.trade_history)
            winning_trades = sum(1 for trade in self.trade_history if trade["profit_final"] > 0)
            losing_trades = sum(1 for trade in self.trade_history if trade["profit_final"] <= 0)
            
            total_profit = sum(trade["profit_final"] for trade in self.trade_history if trade["profit_final"] > 0)
            total_loss = sum(abs(trade["profit_final"]) for trade in self.trade_history if trade["profit_final"] <= 0)
            
            # Calcular taxa de acerto
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            
            # Calcular fator de lucro
            profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf')
            
            # Calcular média de ganho e perda
            avg_win = (total_profit / winning_trades) if winning_trades > 0 else 0
            avg_loss = (total_loss / losing_trades) if losing_trades > 0 else 0
            
            # Calcular razão risco/recompensa
            risk_reward_ratio = (avg_win / avg_loss) if avg_loss > 0 else float('inf')
            
            # Calcular drawdown
            # (Implementação simplificada, uma análise mais precisa exigiria um histórico de patrimônio)
            account_info = mt5.account_info()
            if account_info is not None:
                balance = account_info.balance
                equity = account_info.equity
                current_drawdown = balance - equity
                max_drawdown = max(self.performance_metrics["max_drawdown"], current_drawdown)
            else:
                current_drawdown = 0
                max_drawdown = self.performance_metrics["max_drawdown"]
            
            # Atualizar métricas
            self.performance_metrics = {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "total_profit": total_profit,
                "total_loss": total_loss,
                "max_drawdown": max_drawdown,
                "current_drawdown": current_drawdown,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "risk_reward_ratio": risk_reward_ratio
            }
            
        except Exception as e:
            logger.error(f"Erro ao atualizar métricas de desempenho: {e}")
    
    def _check_trading_time(self):
        """
        Verifica se é hora de trading.
        
        Returns:
            bool: True se for hora de trading, False caso contrário
        """
        try:
            # Obter configuração de filtro de tempo
            time_filter = self.config["risk_management"]["time_filter"]
            
            # Verificar se o filtro está habilitado
            if not time_filter["enabled"]:
                return True
            
            # Obter data e hora atual
            now = datetime.now()
            
            # Verificar dia da semana
            weekday = now.weekday()  # 0 = Segunda, 6 = Domingo
            
            if weekday == 0 and not time_filter["trade_monday"]:
                return False
            elif weekday == 1 and not time_filter["trade_tuesday"]:
                return False
            elif weekday == 2 and not time_filter["trade_wednesday"]:
                return False
            elif weekday == 3 and not time_filter["trade_thursday"]:
                return False
            elif weekday == 4 and not time_filter["trade_friday"]:
                return False
            elif weekday == 5 and not time_filter["trade_saturday"]:
                return False
            elif weekday == 6 and not time_filter["trade_sunday"]:
                return False
            
            # Verificar hora
            hour = now.hour
            
            if hour < time_filter["start_hour"] or hour >= time_filter["end_hour"]:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao verificar hora de trading: {e}")
            return True  # Em caso de erro, permitir trading
    
    def _send_notification(self, message):
        """
        Envia uma notificação.
        
        Args:
            message (str): Mensagem da notificação
        """
        try:
            # Enviar notificação para o terminal MT5
            mt5.terminal_info()  # Verificar se o terminal está disponível
            
            # Enviar notificação
            mt5.send_notification(message)
            
            logger.info(f"Notificação enviada: {message}")
            
        except Exception as e:
            logger.error(f"Erro ao enviar notificação: {e}")
    
    def _get_mt5_timeframe(self, timeframe_str):
        """
        Converte string de timeframe para constante do MT5.
        
        Args:
            timeframe_str (str): String de timeframe (M1, M5, H1, etc.)
            
        Returns:
            int: Constante de timeframe do MT5
        """
        timeframes = {
            "M1": mt5.TIMEFRAME_M1,
            "M2": mt5.TIMEFRAME_M2,
            "M3": mt5.TIMEFRAME_M3,
            "M4": mt5.TIMEFRAME_M4,
            "M5": mt5.TIMEFRAME_M5,
            "M6": mt5.TIMEFRAME_M6,
            "M10": mt5.TIMEFRAME_M10,
            "M12": mt5.TIMEFRAME_M12,
            "M15": mt5.TIMEFRAME_M15,
            "M20": mt5.TIMEFRAME_M20,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H2": mt5.TIMEFRAME_H2,
            "H3": mt5.TIMEFRAME_H3,
            "H4": mt5.TIMEFRAME_H4,
            "H6": mt5.TIMEFRAME_H6,
            "H8": mt5.TIMEFRAME_H8,
            "H12": mt5.TIMEFRAME_H12,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1
        }
        
        return timeframes.get(timeframe_str, mt5.TIMEFRAME_M1)
    
    def get_performance_report(self):
        """
        Obtém um relatório de desempenho.
        
        Returns:
            dict: Relatório de desempenho
        """
        try:
            # Obter informações da conta
            account_info = mt5.account_info()
            if account_info is None:
                logger.warning("Falha ao obter informações da conta")
                account_data = {}
            else:
                account_data = {
                    "login": account_info.login,
                    "server": account_info.server,
                    "balance": account_info.balance,
                    "equity": account_info.equity,
                    "margin": account_info.margin,
                    "free_margin": account_info.margin_free,
                    "margin_level": account_info.margin_level,
                    "leverage": account_info.leverage
                }
            
            # Criar relatório
            report = {
                "account": account_data,
                "performance": self.performance_metrics,
                "positions": len(self.positions),
                "trade_history": len(self.trade_history),
                "symbols": len(self.symbols),
                "running": self.running,
                "connected": self.connected,
                "timestamp": datetime.now().isoformat()
            }
            
            return report
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório de desempenho: {e}")
            return {}
    
    def save_trade_history(self, file_path):
        """
        Salva o histórico de negociações em um arquivo JSON.
        
        Args:
            file_path (str): Caminho para o arquivo
            
        Returns:
            bool: True se o histórico for salvo com sucesso, False caso contrário
        """
        try:
            # Converter histórico para formato serializável
            serializable_history = []
            
            for trade in self.trade_history:
                # Converter objetos datetime para strings
                trade_copy = trade.copy()
                if "time" in trade_copy and isinstance(trade_copy["time"], datetime):
                    trade_copy["time"] = trade_copy["time"].isoformat()
                if "close_time" in trade_copy and isinstance(trade_copy["close_time"], datetime):
                    trade_copy["close_time"] = trade_copy["close_time"].isoformat()
                
                serializable_history.append(trade_copy)
            
            # Salvar em arquivo JSON
            with open(file_path, "w") as f:
                json.dump(serializable_history, f, indent=4)
            
            logger.info(f"Histórico de negociações salvo em {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao salvar histórico de negociações: {e}")
            return False
    
    def load_trade_history(self, file_path):
        """
        Carrega o histórico de negociações de um arquivo JSON.
        
        Args:
            file_path (str): Caminho para o arquivo
            
        Returns:
            bool: True se o histórico for carregado com sucesso, False caso contrário
        """
        if not os.path.exists(file_path):
            logger.warning(f"Arquivo de histórico não encontrado: {file_path}")
            return False
        
        try:
            # Carregar de arquivo JSON
            with open(file_path, "r") as f:
                serialized_history = json.load(f)
            
            # Converter strings para objetos datetime
            history = []
            
            for trade in serialized_history:
                # Converter strings para datetime
                if "time" in trade and isinstance(trade["time"], str):
                    trade["time"] = datetime.fromisoformat(trade["time"])
                if "close_time" in trade and isinstance(trade["close_time"], str):
                    trade["close_time"] = datetime.fromisoformat(trade["close_time"])
                
                history.append(trade)
            
            # Atualizar histórico
            self.trade_history = history
            
            # Atualizar métricas de desempenho
            self._update_performance_metrics()
            
            logger.info(f"Histórico de negociações carregado de {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao carregar histórico de negociações: {e}")
            return False


# Função principal
def main():
    """
    Função principal para executar o EA.
    """
    # Verificar argumentos
    import argparse
    parser = argparse.ArgumentParser(description="Expert Advisor de Tape Reading para MetaTrader 5")
    parser.add_argument("--config", help="Caminho para o arquivo de configuração")
    args = parser.parse_args()
    
    # Criar EA
    ea = MT5TapeReadingEA(args.config)
    
    try:
        # Conectar ao MT5
        if not ea.connect():
            logger.error("Falha ao conectar ao MetaTrader 5")
            return
        
        # Iniciar EA
        if not ea.start():
            logger.error("Falha ao iniciar EA")
            ea.disconnect()
            return
        
        # Manter em execução
        logger.info("EA em execução. Pressione Ctrl+C para parar.")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário")
    
    finally:
        # Parar EA
        if ea.running:
            ea.stop()
        
        # Desconectar
        if ea.connected:
            ea.disconnect()
        
        # Salvar histórico
        ea.save_trade_history("trade_history.json")
        
        logger.info("EA finalizado")


# Executar se for o script principal
if __name__ == "__main__":
    main()
