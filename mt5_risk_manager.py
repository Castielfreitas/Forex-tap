#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de gerenciamento de risco avançado para o EA de Tape Reading.
Este módulo fornece funcionalidades avançadas de gerenciamento de risco para o EA.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import MetaTrader5 as mt5

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_risk_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5RiskManager")

class MT5RiskManager:
    """
    Gerenciador de risco avançado para o EA de Tape Reading.
    """
    
    def __init__(self, config_file=None):
        """
        Inicializa o gerenciador de risco.
        
        Args:
            config_file (str, optional): Caminho para o arquivo de configuração
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.account_info = None
        self.positions = {}
        self.trade_history = []
        self.daily_stats = {}
        self.weekly_stats = {}
        self.monthly_stats = {}
        self.risk_limits = {
            "daily_loss_reached": False,
            "weekly_loss_reached": False,
            "monthly_loss_reached": False,
            "max_positions_reached": False,
            "max_drawdown_reached": False,
            "max_risk_per_trade_reached": False,
            "max_risk_per_symbol_reached": {},
            "correlation_risk_high": False
        }
        self.position_sizing_models = {
            "fixed": self._fixed_position_size,
            "risk": self._risk_based_position_size,
            "equity": self._equity_based_position_size,
            "kelly": self._kelly_criterion_position_size,
            "martingale": self._martingale_position_size,
            "anti_martingale": self._anti_martingale_position_size,
            "volatility": self._volatility_based_position_size
        }
    
    def _load_config(self):
        """
        Carrega a configuração do gerenciador de risco.
        
        Returns:
            dict: Configuração do gerenciador de risco
        """
        default_config = {
            "risk_limits": {
                "max_daily_loss_percent": 3.0,  # Perda máxima diária (%)
                "max_weekly_loss_percent": 7.0,  # Perda máxima semanal (%)
                "max_monthly_loss_percent": 15.0,  # Perda máxima mensal (%)
                "max_drawdown_percent": 20.0,  # Drawdown máximo (%)
                "max_open_positions": 5,  # Número máximo de posições abertas
                "max_positions_per_symbol": 2,  # Número máximo de posições por símbolo
                "max_risk_per_trade_percent": 1.0,  # Risco máximo por operação (%)
                "max_risk_per_symbol_percent": 3.0,  # Risco máximo por símbolo (%)
                "max_daily_trades": 10,  # Número máximo de operações diárias
                "max_consecutive_losses": 3,  # Número máximo de perdas consecutivas
                "correlation_threshold": 0.7  # Limiar de correlação para risco
            },
            "position_sizing": {
                "method": "risk",  # "fixed", "risk", "equity", "kelly", "martingale", "anti_martingale", "volatility"
                "fixed_lot_size": 0.01,  # Tamanho fixo de lote
                "risk_percent": 1.0,  # Percentual de risco por operação
                "equity_percent": 2.0,  # Percentual do patrimônio
                "kelly_fraction": 0.5,  # Fração do critério de Kelly
                "martingale_factor": 2.0,  # Fator de multiplicação para martingale
                "anti_martingale_factor": 1.5,  # Fator de multiplicação para anti-martingale
                "volatility_factor": 1.0,  # Fator de multiplicação para volatilidade
                "atr_period": 14,  # Período para ATR
                "position_size_rounding": "down"  # "up", "down", "nearest"
            },
            "stop_loss": {
                "method": "fixed",  # "fixed", "atr", "support_resistance", "volatility", "percent"
                "fixed_pips": 20,  # Stop loss fixo em pips
                "atr_multiple": 1.5,  # Múltiplo de ATR
                "atr_period": 14,  # Período para ATR
                "percent_risk": 1.0,  # Percentual de risco
                "min_pips": 10,  # Mínimo de pips para stop loss
                "max_pips": 100  # Máximo de pips para stop loss
            },
            "take_profit": {
                "method": "risk_reward",  # "fixed", "atr", "resistance_support", "volatility", "risk_reward"
                "fixed_pips": 40,  # Take profit fixo em pips
                "atr_multiple": 2.5,  # Múltiplo de ATR
                "atr_period": 14,  # Período para ATR
                "risk_reward_ratio": 2.0,  # Razão risco/recompensa
                "min_pips": 15,  # Mínimo de pips para take profit
                "max_pips": 200  # Máximo de pips para take profit
            },
            "trailing_stop": {
                "enabled": True,  # Usar stop móvel
                "activation_pips": 15,  # Pips de lucro para ativar stop móvel
                "distance_pips": 10,  # Distância do stop móvel
                "step_pips": 5,  # Passo para ajuste do stop móvel
                "atr_multiple": 1.0,  # Múltiplo de ATR
                "atr_period": 14  # Período para ATR
            },
            "break_even": {
                "enabled": True,  # Mover stop para break even
                "activation_pips": 10,  # Pips de lucro para mover para break even
                "offset_pips": 2  # Offset em pips (positivo = lucro garantido)
            },
            "partial_close": {
                "enabled": True,  # Fechamento parcial de posições
                "levels": [
                    {"profit_pips": 15, "close_percent": 25},
                    {"profit_pips": 30, "close_percent": 25},
                    {"profit_pips": 45, "close_percent": 25}
                ]
            },
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
                "trade_sunday": False,
                "avoid_high_impact_news": True,
                "news_buffer_minutes": 30
            },
            "correlation_risk": {
                "enabled": True,
                "check_period": "D1",  # Timeframe para verificação
                "lookback_periods": 20,  # Períodos para olhar para trás
                "threshold": 0.7,  # Limiar de correlação
                "max_correlated_positions": 2  # Máximo de posições correlacionadas
            },
            "volatility_filter": {
                "enabled": True,
                "atr_period": 14,  # Período para ATR
                "min_atr_multiple": 0.5,  # Mínimo múltiplo de ATR
                "max_atr_multiple": 3.0  # Máximo múltiplo de ATR
            },
            "recovery_mode": {
                "enabled": True,
                "trigger_consecutive_losses": 3,  # Perdas consecutivas para ativar
                "risk_reduction_percent": 50,  # Redução de risco (%)
                "min_win_streak_to_reset": 2,  # Vitórias consecutivas para resetar
                "max_recovery_days": 5  # Dias máximos em modo de recuperação
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
        Salva a configuração do gerenciador de risco em um arquivo JSON.
        
        Args:
            file_path (str, optional): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for salva com sucesso, False caso contrário
        """
        if not file_path:
            file_path = self.config_file or "mt5_risk_manager_config.json"
        
        try:
            with open(file_path, "w") as f:
                json.dump(self.config, f, indent=4)
            
            logger.info(f"Configuração salva em {file_path}")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}")
            return False
    
    def update_account_info(self):
        """
        Atualiza informações da conta.
        
        Returns:
            bool: True se as informações forem atualizadas com sucesso, False caso contrário
        """
        try:
            # Obter informações da conta
            account_info = mt5.account_info()
            if account_info is None:
                logger.warning("Falha ao obter informações da conta")
                return False
            
            # Converter para dicionário
            self.account_info = {
                "login": account_info.login,
                "server": account_info.server,
                "currency": account_info.currency,
                "leverage": account_info.leverage,
                "balance": account_info.balance,
                "equity": account_info.equity,
                "margin": account_info.margin,
                "free_margin": account_info.margin_free,
                "margin_level": account_info.margin_level,
                "profit": account_info.profit
            }
            
            # Calcular drawdown
            if self.account_info["balance"] > 0:
                self.account_info["drawdown_percent"] = (1 - self.account_info["equity"] / self.account_info["balance"]) * 100
            else:
                self.account_info["drawdown_percent"] = 0
            
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar informações da conta: {e}")
            return False
    
    def update_positions(self):
        """
        Atualiza a lista de posições abertas.
        
        Returns:
            bool: True se as posições forem atualizadas com sucesso, False caso contrário
        """
        try:
            # Obter posições abertas
            positions = mt5.positions_get()
            
            if positions is None:
                logger.debug("Nenhuma posição aberta")
                self.positions = {}
                return True
            
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
            
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar posições: {e}")
            return False
    
    def update_trade_history(self, days=30):
        """
        Atualiza o histórico de negociações.
        
        Args:
            days (int): Número de dias para buscar histórico
            
        Returns:
            bool: True se o histórico for atualizado com sucesso, False caso contrário
        """
        try:
            # Definir período
            from_date = datetime.now() - timedelta(days=days)
            to_date = datetime.now()
            
            # Obter histórico de negociações
            history = mt5.history_deals_get(from_date, to_date)
            
            if history is None:
                logger.debug("Nenhuma negociação no histórico")
                return True
            
            # Processar histórico
            trades = []
            current_trade = None
            
            for deal in history:
                # Verificar se é uma negociação válida
                if deal.entry == mt5.DEAL_ENTRY_IN:
                    # Nova negociação
                    current_trade = {
                        "ticket": deal.ticket,
                        "symbol": deal.symbol,
                        "type": deal.type,
                        "volume": deal.volume,
                        "open_price": deal.price,
                        "open_time": datetime.fromtimestamp(deal.time),
                        "close_price": 0,
                        "close_time": None,
                        "profit": 0,
                        "swap": 0,
                        "commission": deal.commission,
                        "magic": deal.magic,
                        "comment": deal.comment
                    }
                elif deal.entry == mt5.DEAL_ENTRY_OUT and current_trade is not None:
                    # Fechamento de negociação
                    current_trade["close_price"] = deal.price
                    current_trade["close_time"] = datetime.fromtimestamp(deal.time)
                    current_trade["profit"] = deal.profit
                    current_trade["swap"] = deal.swap
                    
                    # Adicionar à lista
                    trades.append(current_trade)
                    current_trade = None
            
            # Atualizar histórico
            self.trade_history = trades
            
            # Atualizar estatísticas
            self._update_statistics()
            
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar histórico de negociações: {e}")
            return False
    
    def _update_statistics(self):
        """
        Atualiza estatísticas de negociação.
        """
        try:
            # Verificar se há histórico
            if not self.trade_history:
                return
            
            # Converter para DataFrame
            df = pd.DataFrame(self.trade_history)
            
            # Adicionar colunas de data
            df["date"] = df["close_time"].dt.date
            df["week"] = df["close_time"].dt.isocalendar().week
            df["month"] = df["close_time"].dt.month
            df["year"] = df["close_time"].dt.year
            
            # Adicionar resultado (win/loss)
            df["result"] = df["profit"].apply(lambda x: "win" if x > 0 else "loss")
            
            # Estatísticas diárias
            daily_stats = df.groupby("date").agg({
                "ticket": "count",
                "profit": "sum",
                "result": lambda x: (x == "win").sum()
            }).rename(columns={"ticket": "trades", "result": "wins"})
            
            daily_stats["losses"] = daily_stats["trades"] - daily_stats["wins"]
            daily_stats["win_rate"] = daily_stats["wins"] / daily_stats["trades"] * 100
            
            # Estatísticas semanais
            weekly_stats = df.groupby(["year", "week"]).agg({
                "ticket": "count",
                "profit": "sum",
                "result": lambda x: (x == "win").sum()
            }).rename(columns={"ticket": "trades", "result": "wins"})
            
            weekly_stats["losses"] = weekly_stats["trades"] - weekly_stats["wins"]
            weekly_stats["win_rate"] = weekly_stats["wins"] / weekly_stats["trades"] * 100
            
            # Estatísticas mensais
            monthly_stats = df.groupby(["year", "month"]).agg({
                "ticket": "count",
                "profit": "sum",
                "result": lambda x: (x == "win").sum()
            }).rename(columns={"ticket": "trades", "result": "wins"})
            
            monthly_stats["losses"] = monthly_stats["trades"] - monthly_stats["wins"]
            monthly_stats["win_rate"] = monthly_stats["wins"] / monthly_stats["trades"] * 100
            
            # Atualizar estatísticas
            self.daily_stats = daily_stats.to_dict("index")
            self.weekly_stats = weekly_stats.to_dict("index")
            self.monthly_stats = monthly_stats.to_dict("index")
            
        except Exception as e:
            logger.error(f"Erro ao atualizar estatísticas: {e}")
    
    def check_risk_limits(self):
        """
        Verifica limites de risco.
        
        Returns:
            bool: True se todos os limites estiverem OK, False caso contrário
        """
        try:
            # Atualizar informações
            self.update_account_info()
            self.update_positions()
            
            # Resetar limites
            self.risk_limits = {
                "daily_loss_reached": False,
                "weekly_loss_reached": False,
                "monthly_loss_reached": False,
                "max_positions_reached": False,
                "max_drawdown_reached": False,
                "max_risk_per_trade_reached": False,
                "max_risk_per_symbol_reached": {},
                "correlation_risk_high": False
            }
            
            # Verificar limites
            all_ok = True
            
            # 1. Verificar drawdown
            if self.account_info and "drawdown_percent" in self.account_info:
                max_drawdown = self.config["risk_limits"]["max_drawdown_percent"]
                current_drawdown = self.account_info["drawdown_percent"]
                
                if current_drawdown > max_drawdown:
                    self.risk_limits["max_drawdown_reached"] = True
                    all_ok = False
                    logger.warning(f"Limite de drawdown atingido: {current_drawdown:.2f}% > {max_drawdown:.2f}%")
            
            # 2. Verificar número máximo de posições
            max_positions = self.config["risk_limits"]["max_open_positions"]
            current_positions = len(self.positions)
            
            if current_positions >= max_positions:
                self.risk_limits["max_positions_reached"] = True
                all_ok = False
                logger.warning(f"Limite de posições abertas atingido: {current_positions} >= {max_positions}")
            
            # 3. Verificar perda diária
            today = datetime.now().date()
            if today in self.daily_stats:
                max_daily_loss = self.config["risk_limits"]["max_daily_loss_percent"]
                daily_profit = self.daily_stats[today]["profit"]
                
                if self.account_info and daily_profit < 0:
                    daily_loss_percent = abs(daily_profit) / self.account_info["balance"] * 100
                    
                    if daily_loss_percent > max_daily_loss:
                        self.risk_limits["daily_loss_reached"] = True
                        all_ok = False
                        logger.warning(f"Limite de perda diária atingido: {daily_loss_percent:.2f}% > {max_daily_loss:.2f}%")
            
            # 4. Verificar perda semanal
            current_week = (datetime.now().year, datetime.now().isocalendar()[1])
            if current_week in self.weekly_stats:
                max_weekly_loss = self.config["risk_limits"]["max_weekly_loss_percent"]
                weekly_profit = self.weekly_stats[current_week]["profit"]
                
                if self.account_info and weekly_profit < 0:
                    weekly_loss_percent = abs(weekly_profit) / self.account_info["balance"] * 100
                    
                    if weekly_loss_percent > max_weekly_loss:
                        self.risk_limits["weekly_loss_reached"] = True
                        all_ok = False
                        logger.warning(f"Limite de perda semanal atingido: {weekly_loss_percent:.2f}% > {max_weekly_loss:.2f}%")
            
            # 5. Verificar perda mensal
            current_month = (datetime.now().year, datetime.now().month)
            if current_month in self.monthly_stats:
                max_monthly_loss = self.config["risk_limits"]["max_monthly_loss_percent"]
                monthly_profit = self.monthly_stats[current_month]["profit"]
                
                if self.account_info and monthly_profit < 0:
                    monthly_loss_percent = abs(monthly_profit) / self.account_info["balance"] * 100
                    
                    if monthly_loss_percent > max_monthly_loss:
                        self.risk_limits["monthly_loss_reached"] = True
                        all_ok = False
                        logger.warning(f"Limite de perda mensal atingido: {monthly_loss_percent:.2f}% > {max_monthly_loss:.2f}%")
            
            # 6. Verificar risco por símbolo
            symbols = {}
            for position in self.positions.values():
                symbol = position["symbol"]
                if symbol not in symbols:
                    symbols[symbol] = 0
                symbols[symbol] += 1
            
            max_positions_per_symbol = self.config["risk_limits"]["max_positions_per_symbol"]
            for symbol, count in symbols.items():
                if count >= max_positions_per_symbol:
                    self.risk_limits["max_risk_per_symbol_reached"][symbol] = True
                    all_ok = False
                    logger.warning(f"Limite de posições por símbolo atingido para {symbol}: {count} >= {max_positions_per_symbol}")
            
            # 7. Verificar risco de correlação
            if self.config["correlation_risk"]["enabled"]:
                correlation_risk = self._check_correlation_risk()
                if correlation_risk:
                    self.risk_limits["correlation_risk_high"] = True
                    all_ok = False
                    logger.warning("Risco de correlação alto detectado")
            
            return all_ok
            
        except Exception as e:
            logger.error(f"Erro ao verificar limites de risco: {e}")
            return False
    
    def _check_correlation_risk(self):
        """
        Verifica risco de correlação entre símbolos.
        
        Returns:
            bool: True se o risco de correlação for alto, False caso contrário
        """
        try:
            # Verificar se há posições suficientes
            if len(self.positions) < 2:
                return False
            
            # Obter símbolos das posições abertas
            symbols = [pos["symbol"] for pos in self.positions.values()]
            unique_symbols = list(set(symbols))
            
            if len(unique_symbols) < 2:
                return False
            
            # Obter configuração
            correlation_config = self.config["correlation_risk"]
            threshold = correlation_config["threshold"]
            lookback = correlation_config["lookback_periods"]
            timeframe = self._get_mt5_timeframe(correlation_config["check_period"])
            
            # Obter dados de preço para cada símbolo
            price_data = {}
            for symbol in unique_symbols:
                rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, lookback)
                if rates is not None and len(rates) > 0:
                    df = pd.DataFrame(rates)
                    price_data[symbol] = df["close"]
            
            # Verificar se temos dados suficientes
            if len(price_data) < 2:
                return False
            
            # Calcular matriz de correlação
            df = pd.DataFrame(price_data)
            corr_matrix = df.corr()
            
            # Verificar correlações
            high_correlation = False
            for i in range(len(unique_symbols)):
                for j in range(i+1, len(unique_symbols)):
                    symbol1 = unique_symbols[i]
                    symbol2 = unique_symbols[j]
                    
                    if symbol1 in corr_matrix.index and symbol2 in corr_matrix.columns:
                        correlation = corr_matrix.loc[symbol1, symbol2]
                        
                        # Verificar correlação positiva alta
                        if correlation > threshold:
                            # Verificar se as posições são na mesma direção
                            pos1_type = [pos["type"] for pos in self.positions.values() if pos["symbol"] == symbol1]
                            pos2_type = [pos["type"] for pos in self.positions.values() if pos["symbol"] == symbol2]
                            
                            if any(t1 == t2 for t1 in pos1_type for t2 in pos2_type):
                                logger.warning(f"Alta correlação positiva entre {symbol1} e {symbol2}: {correlation:.2f}")
                                high_correlation = True
                        
                        # Verificar correlação negativa alta
                        elif correlation < -threshold:
                            # Verificar se as posições são em direções opostas
                            pos1_type = [pos["type"] for pos in self.positions.values() if pos["symbol"] == symbol1]
                            pos2_type = [pos["type"] for pos in self.positions.values() if pos["symbol"] == symbol2]
                            
                            if any(t1 != t2 for t1 in pos1_type for t2 in pos2_type):
                                logger.warning(f"Alta correlação negativa entre {symbol1} e {symbol2}: {correlation:.2f}")
                                high_correlation = True
            
            return high_correlation
            
        except Exception as e:
            logger.error(f"Erro ao verificar risco de correlação: {e}")
            return False
    
    def check_trading_allowed(self, symbol=None):
        """
        Verifica se a negociação é permitida.
        
        Args:
            symbol (str, optional): Símbolo para verificar
            
        Returns:
            bool: True se a negociação for permitida, False caso contrário
        """
        try:
            # Verificar limites de risco
            if not self.check_risk_limits():
                return False
            
            # Verificar filtro de tempo
            if not self._check_trading_time():
                return False
            
            # Verificar limites específicos do símbolo
            if symbol:
                # Verificar número máximo de posições por símbolo
                symbol_positions = [pos for pos in self.positions.values() if pos["symbol"] == symbol]
                max_positions_per_symbol = self.config["risk_limits"]["max_positions_per_symbol"]
                
                if len(symbol_positions) >= max_positions_per_symbol:
                    logger.warning(f"Limite de posições para {symbol} atingido: {len(symbol_positions)} >= {max_positions_per_symbol}")
                    return False
                
                # Verificar se o símbolo está na lista de risco por símbolo
                if symbol in self.risk_limits["max_risk_per_symbol_reached"] and self.risk_limits["max_risk_per_symbol_reached"][symbol]:
                    logger.warning(f"Limite de risco para {symbol} atingido")
                    return False
                
                # Verificar filtro de volatilidade
                if self.config["volatility_filter"]["enabled"]:
                    if not self._check_volatility_filter(symbol):
                        logger.warning(f"Filtro de volatilidade não passou para {symbol}")
                        return False
            
            # Verificar modo de recuperação
            if self.config["recovery_mode"]["enabled"]:
                if self._check_recovery_mode():
                    logger.warning("Modo de recuperação ativo, negociação com risco reduzido")
                    # Não impede a negociação, apenas reduz o risco
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao verificar permissão de negociação: {e}")
            return False
    
    def _check_trading_time(self):
        """
        Verifica se é hora de trading.
        
        Returns:
            bool: True se for hora de trading, False caso contrário
        """
        try:
            # Obter configuração de filtro de tempo
            time_filter = self.config["time_filter"]
            
            # Verificar se o filtro está habilitado
            if not time_filter["enabled"]:
                return True
            
            # Obter data e hora atual
            now = datetime.now()
            
            # Verificar dia da semana
            weekday = now.weekday()  # 0 = Segunda, 6 = Domingo
            
            if weekday == 0 and not time_filter["trade_monday"]:
                logger.debug("Negociação não permitida às segundas-feiras")
                return False
            elif weekday == 1 and not time_filter["trade_tuesday"]:
                logger.debug("Negociação não permitida às terças-feiras")
                return False
            elif weekday == 2 and not time_filter["trade_wednesday"]:
                logger.debug("Negociação não permitida às quartas-feiras")
                return False
            elif weekday == 3 and not time_filter["trade_thursday"]:
                logger.debug("Negociação não permitida às quintas-feiras")
                return False
            elif weekday == 4 and not time_filter["trade_friday"]:
                logger.debug("Negociação não permitida às sextas-feiras")
                return False
            elif weekday == 5 and not time_filter["trade_saturday"]:
                logger.debug("Negociação não permitida aos sábados")
                return False
            elif weekday == 6 and not time_filter["trade_sunday"]:
                logger.debug("Negociação não permitida aos domingos")
                return False
            
            # Verificar hora
            hour = now.hour
            
            if hour < time_filter["start_hour"] or hour >= time_filter["end_hour"]:
                logger.debug(f"Fora do horário de negociação: {hour} não está entre {time_filter['start_hour']} e {time_filter['end_hour']}")
                return False
            
            # Verificar notícias de alto impacto
            if time_filter["avoid_high_impact_news"]:
                if self._check_high_impact_news():
                    logger.debug("Notícias de alto impacto próximas")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao verificar hora de trading: {e}")
            return True  # Em caso de erro, permitir trading
    
    def _check_high_impact_news(self):
        """
        Verifica se há notícias de alto impacto próximas.
        
        Returns:
            bool: True se houver notícias de alto impacto próximas, False caso contrário
        """
        # Implementação simplificada, em um sistema real seria necessário
        # integrar com um serviço de calendário econômico
        return False
    
    def _check_volatility_filter(self, symbol):
        """
        Verifica filtro de volatilidade para um símbolo.
        
        Args:
            symbol (str): Símbolo para verificar
            
        Returns:
            bool: True se passar no filtro, False caso contrário
        """
        try:
            # Obter configuração
            volatility_config = self.config["volatility_filter"]
            atr_period = volatility_config["atr_period"]
            min_atr = volatility_config["min_atr_multiple"]
            max_atr = volatility_config["max_atr_multiple"]
            
            # Obter dados do símbolo
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, atr_period + 1)
            
            if rates is None or len(rates) < atr_period + 1:
                logger.warning(f"Dados insuficientes para calcular ATR para {symbol}")
                return True  # Permitir em caso de dados insuficientes
            
            # Calcular ATR
            df = pd.DataFrame(rates)
            df["high_low"] = df["high"] - df["low"]
            df["high_close"] = abs(df["high"] - df["close"].shift(1))
            df["low_close"] = abs(df["low"] - df["close"].shift(1))
            df["tr"] = df[["high_low", "high_close", "low_close"]].max(axis=1)
            atr = df["tr"].rolling(window=atr_period).mean().iloc[-1]
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return True  # Permitir em caso de erro
            
            # Calcular ATR em pips
            point = symbol_info.point
            atr_pips = atr / (10 * point)
            
            # Verificar limites
            if atr_pips < min_atr:
                logger.debug(f"Volatilidade muito baixa para {symbol}: ATR = {atr_pips:.2f} pips < {min_atr}")
                return False
            
            if atr_pips > max_atr:
                logger.debug(f"Volatilidade muito alta para {symbol}: ATR = {atr_pips:.2f} pips > {max_atr}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao verificar filtro de volatilidade para {symbol}: {e}")
            return True  # Permitir em caso de erro
    
    def _check_recovery_mode(self):
        """
        Verifica se o modo de recuperação está ativo.
        
        Returns:
            bool: True se o modo de recuperação estiver ativo, False caso contrário
        """
        try:
            # Obter configuração
            recovery_config = self.config["recovery_mode"]
            trigger_losses = recovery_config["trigger_consecutive_losses"]
            min_wins_to_reset = recovery_config["min_win_streak_to_reset"]
            max_days = recovery_config["max_recovery_days"]
            
            # Verificar se há histórico suficiente
            if len(self.trade_history) < trigger_losses:
                return False
            
            # Obter últimas negociações
            recent_trades = sorted(self.trade_history, key=lambda x: x["close_time"], reverse=True)
            
            # Verificar perdas consecutivas
            consecutive_losses = 0
            for trade in recent_trades:
                if trade["profit"] < 0:
                    consecutive_losses += 1
                else:
                    break
                
                if consecutive_losses >= trigger_losses:
                    break
            
            # Verificar se atingiu o gatilho
            if consecutive_losses >= trigger_losses:
                # Verificar se já passou o período máximo
                if recent_trades[0]["close_time"] - recent_trades[trigger_losses-1]["close_time"] > timedelta(days=max_days):
                    return False
                
                # Modo de recuperação ativo
                return True
            
            # Verificar se está em recuperação e teve vitórias suficientes para resetar
            if hasattr(self, "_recovery_active") and self._recovery_active:
                consecutive_wins = 0
                for trade in recent_trades:
                    if trade["profit"] > 0:
                        consecutive_wins += 1
                    else:
                        break
                    
                    if consecutive_wins >= min_wins_to_reset:
                        self._recovery_active = False
                        return False
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Erro ao verificar modo de recuperação: {e}")
            return False
    
    def calculate_position_size(self, symbol, action, stop_loss_pips=None):
        """
        Calcula o tamanho da posição com base na gestão de risco.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            stop_loss_pips (float, optional): Stop loss em pips
            
        Returns:
            float: Tamanho da posição
        """
        try:
            # Verificar se a negociação é permitida
            if not self.check_trading_allowed(symbol):
                logger.warning(f"Negociação não permitida para {symbol}")
                return 0
            
            # Obter configuração
            position_sizing = self.config["position_sizing"]
            method = position_sizing["method"]
            
            # Verificar modo de recuperação
            risk_reduction = 1.0
            if self.config["recovery_mode"]["enabled"] and self._check_recovery_mode():
                risk_reduction = 1.0 - (self.config["recovery_mode"]["risk_reduction_percent"] / 100)
                logger.info(f"Modo de recuperação ativo, redução de risco: {risk_reduction:.2f}")
            
            # Calcular stop loss em pips se não fornecido
            if stop_loss_pips is None:
                stop_loss_pips = self._calculate_stop_loss_pips(symbol, action)
            
            # Usar método apropriado
            if method in self.position_sizing_models:
                volume = self.position_sizing_models[method](symbol, action, stop_loss_pips)
            else:
                logger.warning(f"Método de dimensionamento de posição desconhecido: {method}, usando fixo")
                volume = self._fixed_position_size(symbol, action, stop_loss_pips)
            
            # Aplicar redução de risco se em modo de recuperação
            volume *= risk_reduction
            
            # Ajustar volume para os limites do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return 0
            
            volume = max(volume, symbol_info.volume_min)
            volume = min(volume, symbol_info.volume_max)
            
            # Arredondar para o passo de volume
            volume_step = symbol_info.volume_step
            
            # Método de arredondamento
            rounding = position_sizing["position_size_rounding"]
            if rounding == "up":
                volume = np.ceil(volume / volume_step) * volume_step
            elif rounding == "down":
                volume = np.floor(volume / volume_step) * volume_step
            else:  # nearest
                volume = np.round(volume / volume_step) * volume_step
            
            logger.info(f"Tamanho da posição calculado para {symbol} ({action}): {volume}")
            return volume
            
        except Exception as e:
            logger.error(f"Erro ao calcular tamanho da posição: {e}")
            return self.config["position_sizing"]["fixed_lot_size"]
    
    def _fixed_position_size(self, symbol, action, stop_loss_pips):
        """
        Calcula tamanho da posição fixo.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            stop_loss_pips (float): Stop loss em pips
            
        Returns:
            float: Tamanho da posição
        """
        return self.config["position_sizing"]["fixed_lot_size"]
    
    def _risk_based_position_size(self, symbol, action, stop_loss_pips):
        """
        Calcula tamanho da posição baseado no risco.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            stop_loss_pips (float): Stop loss em pips
            
        Returns:
            float: Tamanho da posição
        """
        try:
            # Obter configuração
            risk_percent = self.config["position_sizing"]["risk_percent"]
            
            # Verificar se temos informações da conta
            if not self.account_info:
                self.update_account_info()
            
            if not self.account_info:
                logger.warning("Falha ao obter informações da conta")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Calcular valor em risco
            risk_amount = self.account_info["balance"] * (risk_percent / 100)
            
            # Calcular valor do pip
            pip_value = symbol_info.trade_tick_value * (10 ** (symbol_info.digits - 4))
            
            # Calcular volume baseado no risco
            if stop_loss_pips > 0 and pip_value > 0:
                volume = risk_amount / (stop_loss_pips * pip_value)
            else:
                volume = self.config["position_sizing"]["fixed_lot_size"]
            
            return volume
            
        except Exception as e:
            logger.error(f"Erro ao calcular tamanho da posição baseado no risco: {e}")
            return self.config["position_sizing"]["fixed_lot_size"]
    
    def _equity_based_position_size(self, symbol, action, stop_loss_pips):
        """
        Calcula tamanho da posição baseado no patrimônio.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            stop_loss_pips (float): Stop loss em pips
            
        Returns:
            float: Tamanho da posição
        """
        try:
            # Obter configuração
            equity_percent = self.config["position_sizing"]["equity_percent"]
            
            # Verificar se temos informações da conta
            if not self.account_info:
                self.update_account_info()
            
            if not self.account_info:
                logger.warning("Falha ao obter informações da conta")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Obter último tick
            last_tick = mt5.symbol_info_tick(symbol)
            if last_tick is None:
                logger.warning(f"Falha ao obter tick para {symbol}")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Determinar preço
            if action == "BUY":
                price = last_tick.ask
            else:  # SELL
                price = last_tick.bid
            
            # Calcular valor baseado no patrimônio
            position_value = self.account_info["equity"] * (equity_percent / 100)
            
            # Calcular volume
            if price > 0:
                volume = position_value / (price * symbol_info.trade_contract_size)
            else:
                volume = self.config["position_sizing"]["fixed_lot_size"]
            
            return volume
            
        except Exception as e:
            logger.error(f"Erro ao calcular tamanho da posição baseado no patrimônio: {e}")
            return self.config["position_sizing"]["fixed_lot_size"]
    
    def _kelly_criterion_position_size(self, symbol, action, stop_loss_pips):
        """
        Calcula tamanho da posição usando o critério de Kelly.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            stop_loss_pips (float): Stop loss em pips
            
        Returns:
            float: Tamanho da posição
        """
        try:
            # Obter configuração
            kelly_fraction = self.config["position_sizing"]["kelly_fraction"]
            
            # Verificar se temos histórico suficiente
            if len(self.trade_history) < 10:
                logger.warning("Histórico insuficiente para critério de Kelly")
                return self._risk_based_position_size(symbol, action, stop_loss_pips)
            
            # Calcular taxa de vitória
            wins = sum(1 for trade in self.trade_history if trade["profit"] > 0)
            total = len(self.trade_history)
            win_rate = wins / total if total > 0 else 0.5
            
            # Calcular média de ganho e perda
            avg_win = np.mean([trade["profit"] for trade in self.trade_history if trade["profit"] > 0]) if wins > 0 else 1
            avg_loss = np.mean([abs(trade["profit"]) for trade in self.trade_history if trade["profit"] <= 0]) if total - wins > 0 else 1
            
            # Calcular odds
            odds = avg_win / avg_loss if avg_loss > 0 else 1
            
            # Calcular fração de Kelly
            kelly = win_rate - ((1 - win_rate) / odds)
            
            # Aplicar fração de Kelly (para reduzir risco)
            kelly *= kelly_fraction
            
            # Limitar a valores positivos
            kelly = max(0, kelly)
            
            # Calcular volume baseado em Kelly
            if not self.account_info:
                self.update_account_info()
            
            if not self.account_info:
                logger.warning("Falha ao obter informações da conta")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Calcular valor em risco
            risk_amount = self.account_info["balance"] * kelly
            
            # Calcular valor do pip
            pip_value = symbol_info.trade_tick_value * (10 ** (symbol_info.digits - 4))
            
            # Calcular volume baseado no risco
            if stop_loss_pips > 0 and pip_value > 0:
                volume = risk_amount / (stop_loss_pips * pip_value)
            else:
                volume = self.config["position_sizing"]["fixed_lot_size"]
            
            return volume
            
        except Exception as e:
            logger.error(f"Erro ao calcular tamanho da posição usando critério de Kelly: {e}")
            return self._risk_based_position_size(symbol, action, stop_loss_pips)
    
    def _martingale_position_size(self, symbol, action, stop_loss_pips):
        """
        Calcula tamanho da posição usando estratégia de martingale.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            stop_loss_pips (float): Stop loss em pips
            
        Returns:
            float: Tamanho da posição
        """
        try:
            # Obter configuração
            martingale_factor = self.config["position_sizing"]["martingale_factor"]
            base_lot = self.config["position_sizing"]["fixed_lot_size"]
            
            # Verificar se há histórico
            if not self.trade_history:
                return base_lot
            
            # Obter última negociação para o símbolo
            symbol_trades = [trade for trade in self.trade_history if trade["symbol"] == symbol]
            
            if not symbol_trades:
                return base_lot
            
            # Ordenar por data de fechamento
            last_trade = sorted(symbol_trades, key=lambda x: x["close_time"], reverse=True)[0]
            
            # Verificar resultado
            if last_trade["profit"] <= 0:
                # Perda, aumentar tamanho
                return last_trade["volume"] * martingale_factor
            else:
                # Ganho, voltar ao tamanho base
                return base_lot
            
        except Exception as e:
            logger.error(f"Erro ao calcular tamanho da posição usando martingale: {e}")
            return self.config["position_sizing"]["fixed_lot_size"]
    
    def _anti_martingale_position_size(self, symbol, action, stop_loss_pips):
        """
        Calcula tamanho da posição usando estratégia de anti-martingale.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            stop_loss_pips (float): Stop loss em pips
            
        Returns:
            float: Tamanho da posição
        """
        try:
            # Obter configuração
            anti_martingale_factor = self.config["position_sizing"]["anti_martingale_factor"]
            base_lot = self.config["position_sizing"]["fixed_lot_size"]
            
            # Verificar se há histórico
            if not self.trade_history:
                return base_lot
            
            # Obter última negociação para o símbolo
            symbol_trades = [trade for trade in self.trade_history if trade["symbol"] == symbol]
            
            if not symbol_trades:
                return base_lot
            
            # Ordenar por data de fechamento
            last_trade = sorted(symbol_trades, key=lambda x: x["close_time"], reverse=True)[0]
            
            # Verificar resultado
            if last_trade["profit"] > 0:
                # Ganho, aumentar tamanho
                return last_trade["volume"] * anti_martingale_factor
            else:
                # Perda, voltar ao tamanho base
                return base_lot
            
        except Exception as e:
            logger.error(f"Erro ao calcular tamanho da posição usando anti-martingale: {e}")
            return self.config["position_sizing"]["fixed_lot_size"]
    
    def _volatility_based_position_size(self, symbol, action, stop_loss_pips):
        """
        Calcula tamanho da posição baseado na volatilidade.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            stop_loss_pips (float): Stop loss em pips
            
        Returns:
            float: Tamanho da posição
        """
        try:
            # Obter configuração
            volatility_factor = self.config["position_sizing"]["volatility_factor"]
            atr_period = self.config["position_sizing"]["atr_period"]
            risk_percent = self.config["position_sizing"]["risk_percent"]
            
            # Verificar se temos informações da conta
            if not self.account_info:
                self.update_account_info()
            
            if not self.account_info:
                logger.warning("Falha ao obter informações da conta")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Obter dados do símbolo
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, atr_period + 1)
            
            if rates is None or len(rates) < atr_period + 1:
                logger.warning(f"Dados insuficientes para calcular ATR para {symbol}")
                return self._risk_based_position_size(symbol, action, stop_loss_pips)
            
            # Calcular ATR
            df = pd.DataFrame(rates)
            df["high_low"] = df["high"] - df["low"]
            df["high_close"] = abs(df["high"] - df["close"].shift(1))
            df["low_close"] = abs(df["low"] - df["close"].shift(1))
            df["tr"] = df[["high_low", "high_close", "low_close"]].max(axis=1)
            atr = df["tr"].rolling(window=atr_period).mean().iloc[-1]
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return self.config["position_sizing"]["fixed_lot_size"]
            
            # Calcular ATR em pips
            point = symbol_info.point
            atr_pips = atr / (10 * point)
            
            # Calcular valor em risco
            risk_amount = self.account_info["balance"] * (risk_percent / 100)
            
            # Calcular valor do pip
            pip_value = symbol_info.trade_tick_value * (10 ** (symbol_info.digits - 4))
            
            # Calcular volume baseado na volatilidade
            if atr_pips > 0 and pip_value > 0:
                # Usar ATR como stop loss
                volume = risk_amount / (atr_pips * volatility_factor * pip_value)
            else:
                volume = self.config["position_sizing"]["fixed_lot_size"]
            
            return volume
            
        except Exception as e:
            logger.error(f"Erro ao calcular tamanho da posição baseado na volatilidade: {e}")
            return self._risk_based_position_size(symbol, action, stop_loss_pips)
    
    def calculate_stop_loss(self, symbol, action, entry_price=None):
        """
        Calcula nível de stop loss.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            entry_price (float, optional): Preço de entrada
            
        Returns:
            float: Nível de stop loss
        """
        try:
            # Obter preço de entrada se não fornecido
            if entry_price is None:
                last_tick = mt5.symbol_info_tick(symbol)
                if last_tick is None:
                    logger.warning(f"Falha ao obter tick para {symbol}")
                    return 0
                
                if action == "BUY":
                    entry_price = last_tick.ask
                else:  # SELL
                    entry_price = last_tick.bid
            
            # Calcular stop loss em pips
            stop_loss_pips = self._calculate_stop_loss_pips(symbol, action)
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return 0
            
            # Calcular nível de stop loss
            point = symbol_info.point
            
            if action == "BUY":
                sl = entry_price - stop_loss_pips * 10 * point
            else:  # SELL
                sl = entry_price + stop_loss_pips * 10 * point
            
            # Arredondar para a precisão do símbolo
            digits = symbol_info.digits
            sl = round(sl, digits)
            
            return sl
            
        except Exception as e:
            logger.error(f"Erro ao calcular stop loss: {e}")
            return 0
    
    def _calculate_stop_loss_pips(self, symbol, action):
        """
        Calcula stop loss em pips.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            
        Returns:
            float: Stop loss em pips
        """
        try:
            # Obter configuração
            sl_config = self.config["stop_loss"]
            method = sl_config["method"]
            
            # Método fixo
            if method == "fixed":
                return sl_config["fixed_pips"]
            
            # Método baseado em ATR
            elif method == "atr":
                atr_period = sl_config["atr_period"]
                atr_multiple = sl_config["atr_multiple"]
                
                # Obter dados do símbolo
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, atr_period + 1)
                
                if rates is None or len(rates) < atr_period + 1:
                    logger.warning(f"Dados insuficientes para calcular ATR para {symbol}")
                    return sl_config["fixed_pips"]
                
                # Calcular ATR
                df = pd.DataFrame(rates)
                df["high_low"] = df["high"] - df["low"]
                df["high_close"] = abs(df["high"] - df["close"].shift(1))
                df["low_close"] = abs(df["low"] - df["close"].shift(1))
                df["tr"] = df[["high_low", "high_close", "low_close"]].max(axis=1)
                atr = df["tr"].rolling(window=atr_period).mean().iloc[-1]
                
                # Obter informações do símbolo
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                    return sl_config["fixed_pips"]
                
                # Calcular ATR em pips
                point = symbol_info.point
                atr_pips = atr / (10 * point)
                
                # Calcular stop loss em pips
                sl_pips = atr_pips * atr_multiple
                
                # Limitar aos valores mínimo e máximo
                sl_pips = max(sl_pips, sl_config["min_pips"])
                sl_pips = min(sl_pips, sl_config["max_pips"])
                
                return sl_pips
            
            # Método baseado em suporte/resistência
            elif method == "support_resistance":
                # Implementação simplificada, em um sistema real seria necessário
                # implementar detecção de níveis de suporte e resistência
                return sl_config["fixed_pips"]
            
            # Método baseado em percentual
            elif method == "percent":
                percent_risk = sl_config["percent_risk"]
                
                # Obter último tick
                last_tick = mt5.symbol_info_tick(symbol)
                if last_tick is None:
                    logger.warning(f"Falha ao obter tick para {symbol}")
                    return sl_config["fixed_pips"]
                
                # Determinar preço
                if action == "BUY":
                    price = last_tick.ask
                else:  # SELL
                    price = last_tick.bid
                
                # Calcular stop loss em percentual
                sl_price = price * (1 - percent_risk / 100) if action == "BUY" else price * (1 + percent_risk / 100)
                
                # Obter informações do símbolo
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                    return sl_config["fixed_pips"]
                
                # Calcular diferença em pips
                point = symbol_info.point
                sl_pips = abs(price - sl_price) / (10 * point)
                
                # Limitar aos valores mínimo e máximo
                sl_pips = max(sl_pips, sl_config["min_pips"])
                sl_pips = min(sl_pips, sl_config["max_pips"])
                
                return sl_pips
            
            # Método desconhecido
            else:
                logger.warning(f"Método de stop loss desconhecido: {method}, usando fixo")
                return sl_config["fixed_pips"]
            
        except Exception as e:
            logger.error(f"Erro ao calcular stop loss em pips: {e}")
            return self.config["stop_loss"]["fixed_pips"]
    
    def calculate_take_profit(self, symbol, action, entry_price=None, stop_loss=None):
        """
        Calcula nível de take profit.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            entry_price (float, optional): Preço de entrada
            stop_loss (float, optional): Nível de stop loss
            
        Returns:
            float: Nível de take profit
        """
        try:
            # Obter preço de entrada se não fornecido
            if entry_price is None:
                last_tick = mt5.symbol_info_tick(symbol)
                if last_tick is None:
                    logger.warning(f"Falha ao obter tick para {symbol}")
                    return 0
                
                if action == "BUY":
                    entry_price = last_tick.ask
                else:  # SELL
                    entry_price = last_tick.bid
            
            # Obter configuração
            tp_config = self.config["take_profit"]
            method = tp_config["method"]
            
            # Método fixo
            if method == "fixed":
                # Obter informações do símbolo
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                    return 0
                
                # Calcular nível de take profit
                point = symbol_info.point
                tp_pips = tp_config["fixed_pips"]
                
                if action == "BUY":
                    tp = entry_price + tp_pips * 10 * point
                else:  # SELL
                    tp = entry_price - tp_pips * 10 * point
                
                # Arredondar para a precisão do símbolo
                digits = symbol_info.digits
                tp = round(tp, digits)
                
                return tp
            
            # Método baseado em ATR
            elif method == "atr":
                atr_period = tp_config["atr_period"]
                atr_multiple = tp_config["atr_multiple"]
                
                # Obter dados do símbolo
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, atr_period + 1)
                
                if rates is None or len(rates) < atr_period + 1:
                    logger.warning(f"Dados insuficientes para calcular ATR para {symbol}")
                    return 0
                
                # Calcular ATR
                df = pd.DataFrame(rates)
                df["high_low"] = df["high"] - df["low"]
                df["high_close"] = abs(df["high"] - df["close"].shift(1))
                df["low_close"] = abs(df["low"] - df["close"].shift(1))
                df["tr"] = df[["high_low", "high_close", "low_close"]].max(axis=1)
                atr = df["tr"].rolling(window=atr_period).mean().iloc[-1]
                
                # Obter informações do símbolo
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                    return 0
                
                # Calcular nível de take profit
                point = symbol_info.point
                tp_pips = atr / (10 * point) * atr_multiple
                
                # Limitar aos valores mínimo e máximo
                tp_pips = max(tp_pips, tp_config["min_pips"])
                tp_pips = min(tp_pips, tp_config["max_pips"])
                
                if action == "BUY":
                    tp = entry_price + tp_pips * 10 * point
                else:  # SELL
                    tp = entry_price - tp_pips * 10 * point
                
                # Arredondar para a precisão do símbolo
                digits = symbol_info.digits
                tp = round(tp, digits)
                
                return tp
            
            # Método baseado em razão risco/recompensa
            elif method == "risk_reward":
                # Verificar se temos stop loss
                if stop_loss is None:
                    stop_loss = self.calculate_stop_loss(symbol, action, entry_price)
                
                if stop_loss == 0:
                    logger.warning(f"Stop loss inválido para {symbol}")
                    return 0
                
                # Obter razão risco/recompensa
                risk_reward_ratio = tp_config["risk_reward_ratio"]
                
                # Calcular distância do stop loss
                sl_distance = abs(entry_price - stop_loss)
                
                # Calcular nível de take profit
                if action == "BUY":
                    tp = entry_price + sl_distance * risk_reward_ratio
                else:  # SELL
                    tp = entry_price - sl_distance * risk_reward_ratio
                
                # Obter informações do símbolo
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info is None:
                    logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                    return 0
                
                # Arredondar para a precisão do símbolo
                digits = symbol_info.digits
                tp = round(tp, digits)
                
                return tp
            
            # Método desconhecido
            else:
                logger.warning(f"Método de take profit desconhecido: {method}, usando fixo")
                return 0
            
        except Exception as e:
            logger.error(f"Erro ao calcular take profit: {e}")
            return 0
    
    def manage_position(self, ticket):
        """
        Gerencia uma posição aberta (trailing stop, break even, etc.).
        
        Args:
            ticket (int): Ticket da posição
            
        Returns:
            bool: True se a posição for gerenciada com sucesso, False caso contrário
        """
        try:
            # Verificar se a posição existe
            if ticket not in self.positions:
                logger.warning(f"Posição {ticket} não encontrada")
                return False
            
            position = self.positions[ticket]
            symbol = position["symbol"]
            position_type = position["type"]
            open_price = position["open_price"]
            current_price = position["current_price"]
            sl = position["sl"]
            tp = position["tp"]
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return False
            
            # Obter valor do pip
            point = symbol_info.point
            
            # Calcular lucro em pips
            if position_type == mt5.POSITION_TYPE_BUY:
                profit_pips = (current_price - open_price) / (10 * point)
            else:  # SELL
                profit_pips = (open_price - current_price) / (10 * point)
            
            # Verificar break even
            if self.config["break_even"]["enabled"] and sl != 0:
                break_even_pips = self.config["break_even"]["activation_pips"]
                offset_pips = self.config["break_even"]["offset_pips"]
                
                if profit_pips >= break_even_pips:
                    # Verificar se já está em break even
                    if position_type == mt5.POSITION_TYPE_BUY and sl < open_price:
                        # Mover stop loss para break even + offset
                        new_sl = open_price + offset_pips * 10 * point
                        
                        # Verificar se é melhor que o atual
                        if new_sl > sl:
                            if self._modify_position(ticket, new_sl, tp):
                                logger.info(f"Stop loss movido para break even: {ticket} {symbol}")
                                return True
                    
                    elif position_type == mt5.POSITION_TYPE_SELL and sl > open_price:
                        # Mover stop loss para break even + offset
                        new_sl = open_price - offset_pips * 10 * point
                        
                        # Verificar se é melhor que o atual
                        if new_sl < sl or sl == 0:
                            if self._modify_position(ticket, new_sl, tp):
                                logger.info(f"Stop loss movido para break even: {ticket} {symbol}")
                                return True
            
            # Verificar trailing stop
            if self.config["trailing_stop"]["enabled"] and sl != 0:
                trailing_start = self.config["trailing_stop"]["activation_pips"]
                trailing_distance = self.config["trailing_stop"]["distance_pips"]
                trailing_step = self.config["trailing_stop"]["step_pips"]
                
                if profit_pips >= trailing_start:
                    if position_type == mt5.POSITION_TYPE_BUY:
                        # Calcular novo stop loss
                        new_sl = current_price - trailing_distance * 10 * point
                        
                        # Verificar se é melhor que o atual
                        if new_sl > sl + trailing_step * 10 * point:
                            if self._modify_position(ticket, new_sl, tp):
                                logger.info(f"Trailing stop atualizado: {ticket} {symbol} {new_sl}")
                                return True
                    
                    elif position_type == mt5.POSITION_TYPE_SELL:
                        # Calcular novo stop loss
                        new_sl = current_price + trailing_distance * 10 * point
                        
                        # Verificar se é melhor que o atual
                        if new_sl < sl - trailing_step * 10 * point or sl == 0:
                            if self._modify_position(ticket, new_sl, tp):
                                logger.info(f"Trailing stop atualizado: {ticket} {symbol} {new_sl}")
                                return True
            
            # Verificar fechamento parcial
            if self.config["partial_close"]["enabled"]:
                levels = self.config["partial_close"]["levels"]
                
                for level in levels:
                    profit_level = level["profit_pips"]
                    close_percent = level["close_percent"]
                    
                    if profit_pips >= profit_level:
                        # Verificar se já foi fechado parcialmente neste nível
                        level_key = f"partial_close_{profit_level}"
                        
                        if level_key not in position:
                            # Fechar parcialmente
                            if self._partial_close_position(ticket, close_percent):
                                logger.info(f"Posição fechada parcialmente: {ticket} {symbol} {close_percent}%")
                                
                                # Marcar como fechado parcialmente neste nível
                                self.positions[ticket][level_key] = True
                                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Erro ao gerenciar posição: {e}")
            return False
    
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
    
    def _partial_close_position(self, ticket, close_percent):
        """
        Fecha parcialmente uma posição aberta.
        
        Args:
            ticket (int): Ticket da posição
            close_percent (float): Percentual a fechar
            
        Returns:
            bool: True se o fechamento parcial for bem-sucedido, False caso contrário
        """
        try:
            # Verificar se a posição existe
            if ticket not in self.positions:
                logger.warning(f"Posição {ticket} não encontrada")
                return False
            
            position = self.positions[ticket]
            symbol = position["symbol"]
            position_type = position["type"]
            volume = position["volume"]
            
            # Calcular volume a fechar
            close_volume = volume * (close_percent / 100)
            
            # Obter informações do símbolo
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"Falha ao obter informações do símbolo {symbol}")
                return False
            
            # Ajustar volume para os limites do símbolo
            close_volume = max(close_volume, symbol_info.volume_min)
            close_volume = min(close_volume, volume)
            
            # Arredondar para o passo de volume
            volume_step = symbol_info.volume_step
            close_volume = np.floor(close_volume / volume_step) * volume_step
            
            # Verificar se o volume é válido
            if close_volume <= 0 or close_volume > volume:
                logger.warning(f"Volume inválido para fechamento parcial: {close_volume}")
                return False
            
            # Obter último tick
            last_tick = mt5.symbol_info_tick(symbol)
            if last_tick is None:
                logger.warning(f"Falha ao obter tick para {symbol}")
                return False
            
            # Determinar preço
            if position_type == mt5.POSITION_TYPE_BUY:
                price = last_tick.bid
                close_type = mt5.ORDER_TYPE_SELL
            else:  # SELL
                price = last_tick.ask
                close_type = mt5.ORDER_TYPE_BUY
            
            # Preparar solicitação de fechamento parcial
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": close_volume,
                "type": close_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "magic": 123456,
                "comment": "Partial close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            
            # Enviar solicitação
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Falha ao fechar parcialmente posição: {result.retcode} - {result.comment}")
                return False
            
            # Atualizar posição na lista
            self.update_positions()
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao fechar parcialmente posição: {e}")
            return False
    
    def close_position(self, ticket):
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
            symbol = position["symbol"]
            position_type = position["type"]
            volume = position["volume"]
            
            # Obter último tick
            last_tick = mt5.symbol_info_tick(symbol)
            if last_tick is None:
                logger.warning(f"Falha ao obter tick para {symbol}")
                return False
            
            # Determinar preço
            if position_type == mt5.POSITION_TYPE_BUY:
                price = last_tick.bid
                close_type = mt5.ORDER_TYPE_SELL
            else:  # SELL
                price = last_tick.ask
                close_type = mt5.ORDER_TYPE_BUY
            
            # Preparar solicitação de fechamento
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": close_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "magic": 123456,
                "comment": "Close position",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            
            # Enviar solicitação
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Falha ao fechar posição: {result.retcode} - {result.comment}")
                return False
            
            # Remover da lista de posições
            if ticket in self.positions:
                del self.positions[ticket]
            
            # Atualizar histórico
            self.update_trade_history()
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao fechar posição: {e}")
            return False
    
    def close_all_positions(self):
        """
        Fecha todas as posições abertas.
        
        Returns:
            bool: True se todas as posições forem fechadas com sucesso, False caso contrário
        """
        try:
            # Verificar se há posições
            if not self.positions:
                logger.info("Nenhuma posição para fechar")
                return True
            
            # Fechar cada posição
            success = True
            for ticket in list(self.positions.keys()):
                if not self.close_position(ticket):
                    success = False
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao fechar todas as posições: {e}")
            return False
    
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
    
    def get_risk_report(self):
        """
        Obtém um relatório de risco.
        
        Returns:
            dict: Relatório de risco
        """
        try:
            # Atualizar informações
            self.update_account_info()
            self.update_positions()
            self.check_risk_limits()
            
            # Criar relatório
            report = {
                "account": self.account_info,
                "positions": len(self.positions),
                "risk_limits": self.risk_limits,
                "daily_stats": self.daily_stats.get(datetime.now().date(), {}),
                "recovery_mode": self._check_recovery_mode(),
                "timestamp": datetime.now().isoformat()
            }
            
            return report
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório de risco: {e}")
            return {}


# Função principal
def main():
    """
    Função principal para testar o gerenciador de risco.
    """
    # Verificar argumentos
    import argparse
    parser = argparse.ArgumentParser(description="Gerenciador de risco para MetaTrader 5")
    parser.add_argument("--config", help="Caminho para o arquivo de configuração")
    args = parser.parse_args()
    
    # Inicializar MT5
    if not mt5.initialize():
        print(f"Falha ao inicializar MetaTrader 5: {mt5.last_error()}")
        return
    
    try:
        # Criar gerenciador de risco
        risk_manager = MT5RiskManager(args.config)
        
        # Atualizar informações
        risk_manager.update_account_info()
        risk_manager.update_positions()
        risk_manager.update_trade_history()
        
        # Verificar limites de risco
        risk_allowed = risk_manager.check_risk_limits()
        
        print(f"Negociação permitida: {risk_allowed}")
        
        # Obter relatório de risco
        report = risk_manager.get_risk_report()
        
        print("\n=== RELATÓRIO DE RISCO ===")
        print(f"Conta: {report['account']}")
        print(f"Posições: {report['positions']}")
        print(f"Limites de risco: {report['risk_limits']}")
        print(f"Estatísticas diárias: {report['daily_stats']}")
        print(f"Modo de recuperação: {report['recovery_mode']}")
        
        # Testar cálculo de tamanho de posição
        symbol = "EURUSD"
        action = "BUY"
        
        volume = risk_manager.calculate_position_size(symbol, action)
        sl = risk_manager.calculate_stop_loss(symbol, action)
        tp = risk_manager.calculate_take_profit(symbol, action, stop_loss=sl)
        
        print(f"\nTamanho da posição para {symbol} ({action}): {volume}")
        print(f"Stop loss: {sl}")
        print(f"Take profit: {tp}")
        
    finally:
        # Finalizar MT5
        mt5.shutdown()


# Executar se for o script principal
if __name__ == "__main__":
    main()
