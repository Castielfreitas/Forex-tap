#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Backend para comunicação com o MetaTrader 5 em ambiente de produção.
Este módulo fornece funções para conectar ao MT5, enviar ordens e replicar operações entre contas.
"""

import time
import json
import logging
from datetime import datetime
import MetaTrader5 as mt5

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_backend.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5Backend")

class MT5Backend:
    """
    Classe para gerenciar a comunicação com o MetaTrader 5.
    Fornece métodos para conectar, enviar ordens e replicar operações entre contas.
    """
    
    def __init__(self):
        """Inicializa a classe MT5Backend."""
        self.connected = False
        self.account_info = None
        self.account_type = None
        self.server = None
        
    def initialize(self):
        """Inicializa o terminal MT5."""
        if not mt5.initialize():
            logger.error(f"Falha ao inicializar o MT5: {mt5.last_error()}")
            return False
        
        logger.info(f"MT5 inicializado com sucesso. Versão: {mt5.version()}")
        return True
    
    def connect(self, account, password, server, account_type="REAL"):
        """
        Conecta ao servidor MT5 com as credenciais fornecidas.
        
        Args:
            account (int): Número da conta MT5
            password (str): Senha da conta
            server (str): Nome do servidor
            account_type (str): Tipo de conta (REAL ou DEMO)
            
        Returns:
            bool: True se a conexão for bem-sucedida, False caso contrário
        """
        if not self.initialize():
            return False
        
        # Verificar se já está conectado e desconectar
        if self.connected:
            mt5.shutdown()
            self.connected = False
        
        # Conectar à conta
        account_type = account_type.upper()
        if account_type not in ["REAL", "DEMO"]:
            logger.error(f"Tipo de conta inválido: {account_type}. Use 'REAL' ou 'DEMO'.")
            return False
        
        logger.info(f"Tentando conectar à conta {account} no servidor {server} (Tipo: {account_type})")
        
        # Autenticar no MT5
        authorized = mt5.login(account, password, server)
        if not authorized:
            error = mt5.last_error()
            logger.error(f"Falha ao conectar: {error}")
            return False
        
        # Obter informações da conta
        self.account_info = mt5.account_info()
        if self.account_info is None:
            logger.error("Falha ao obter informações da conta")
            mt5.shutdown()
            return False
        
        self.connected = True
        self.account_type = account_type
        self.server = server
        
        logger.info(f"Conectado com sucesso à conta {account} ({self.account_info.name})")
        logger.info(f"Saldo: {self.account_info.balance} {self.account_info.currency}")
        
        return True
    
    def disconnect(self):
        """Desconecta do terminal MT5."""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            self.account_info = None
            logger.info("Desconectado do MT5")
            return True
        return False
    
    def check_connection(self):
        """Verifica se a conexão com o MT5 está ativa."""
        if not self.connected:
            return False
        
        # Tentar obter informações da conta para verificar a conexão
        account_info = mt5.account_info()
        if account_info is None:
            self.connected = False
            logger.warning("Conexão com o MT5 perdida")
            return False
        
        return True
    
    def get_account_info(self):
        """Retorna informações da conta conectada."""
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        account_info = mt5.account_info()
        if account_info is None:
            logger.error(f"Falha ao obter informações da conta: {mt5.last_error()}")
            return None
        
        # Converter para dicionário
        info = {
            "login": account_info.login,
            "name": account_info.name,
            "server": account_info.server,
            "currency": account_info.currency,
            "balance": account_info.balance,
            "equity": account_info.equity,
            "margin": account_info.margin,
            "margin_free": account_info.margin_free,
            "margin_level": account_info.margin_level,
            "leverage": account_info.leverage,
            "type": self.account_type
        }
        
        return info
    
    def get_symbols(self):
        """Retorna a lista de símbolos disponíveis."""
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        symbols = mt5.symbols_get()
        if symbols is None:
            logger.error(f"Falha ao obter símbolos: {mt5.last_error()}")
            return None
        
        # Retornar apenas os nomes dos símbolos
        return [symbol.name for symbol in symbols]
    
    def get_symbol_info(self, symbol):
        """
        Retorna informações detalhadas sobre um símbolo.
        
        Args:
            symbol (str): Nome do símbolo (ex: "EURUSD")
            
        Returns:
            dict: Informações do símbolo ou None em caso de erro
        """
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.error(f"Falha ao obter informações do símbolo {symbol}: {mt5.last_error()}")
            return None
        
        # Converter para dicionário
        info = {
            "name": symbol_info.name,
            "description": symbol_info.description,
            "bid": symbol_info.bid,
            "ask": symbol_info.ask,
            "spread": symbol_info.spread,
            "digits": symbol_info.digits,
            "volume_min": symbol_info.volume_min,
            "volume_step": symbol_info.volume_step,
            "volume_max": symbol_info.volume_max,
            "trade_contract_size": symbol_info.trade_contract_size,
            "point": symbol_info.point
        }
        
        return info
    
    def get_last_price(self, symbol):
        """
        Retorna o último preço de um símbolo.
        
        Args:
            symbol (str): Nome do símbolo (ex: "EURUSD")
            
        Returns:
            dict: Preço de compra e venda ou None em caso de erro
        """
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        symbol_info = mt5.symbol_info_tick(symbol)
        if symbol_info is None:
            logger.error(f"Falha ao obter preço do símbolo {symbol}: {mt5.last_error()}")
            return None
        
        return {
            "bid": symbol_info.bid,
            "ask": symbol_info.ask,
            "time": symbol_info.time
        }
    
    def execute_order(self, action, symbol, volume, price=0.0, sl=0.0, tp=0.0, comment=""):
        """
        Executa uma ordem no MT5.
        
        Args:
            action (str): Tipo de ordem ("BUY" ou "SELL")
            symbol (str): Nome do símbolo (ex: "EURUSD")
            volume (float): Volume da ordem
            price (float, optional): Preço para ordens pendentes
            sl (float, optional): Stop Loss
            tp (float, optional): Take Profit
            comment (str, optional): Comentário da ordem
            
        Returns:
            dict: Resultado da execução da ordem ou None em caso de erro
        """
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        # Verificar tipo de ação
        action = action.upper()
        if action not in ["BUY", "SELL"]:
            logger.error(f"Tipo de ordem inválido: {action}. Use 'BUY' ou 'SELL'.")
            return None
        
        # Obter informações do símbolo
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.error(f"Símbolo {symbol} não encontrado")
            return None
        
        # Verificar se o símbolo está disponível para trading
        if not symbol_info.visible:
            logger.warning(f"Símbolo {symbol} não está visível, tentando adicionar")
            if not mt5.symbol_select(symbol, True):
                logger.error(f"Falha ao selecionar símbolo {symbol}: {mt5.last_error()}")
                return None
        
        # Obter o último preço
        last_price = self.get_last_price(symbol)
        if last_price is None:
            return None
        
        # Definir o tipo de ordem
        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        price = last_price["ask"] if action == "BUY" else last_price["bid"]
        
        # Preparar a requisição de ordem
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "sl": float(sl) if sl > 0 else 0.0,
            "tp": float(tp) if tp > 0 else 0.0,
            "deviation": 10,  # Desvio máximo do preço em pontos
            "magic": 123456,  # ID do Expert Advisor
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,  # Good Till Cancelled
            "type_filling": mt5.ORDER_FILLING_IOC,  # Immediate Or Cancel
        }
        
        # Enviar a ordem
        logger.info(f"Enviando ordem: {action} {volume} {symbol} @ {price}")
        result = mt5.order_send(request)
        
        if result is None:
            logger.error(f"Falha ao enviar ordem: {mt5.last_error()}")
            return None
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Falha ao executar ordem: {result.retcode} - {result.comment}")
            return {
                "success": False,
                "retcode": result.retcode,
                "comment": result.comment
            }
        
        logger.info(f"Ordem executada com sucesso: {result.order}")
        return {
            "success": True,
            "order_id": result.order,
            "volume": result.volume,
            "price": result.price,
            "comment": result.comment,
            "request": request
        }
    
    def get_positions(self):
        """
        Retorna as posições abertas.
        
        Returns:
            list: Lista de posições abertas ou None em caso de erro
        """
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        positions = mt5.positions_get()
        if positions is None:
            error = mt5.last_error()
            if error[0] == 0:  # Sem posições abertas
                return []
            logger.error(f"Falha ao obter posições: {error}")
            return None
        
        # Converter para lista de dicionários
        positions_list = []
        for position in positions:
            positions_list.append({
                "ticket": position.ticket,
                "time": position.time,
                "type": "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL",
                "symbol": position.symbol,
                "volume": position.volume,
                "price_open": position.price_open,
                "price_current": position.price_current,
                "sl": position.sl,
                "tp": position.tp,
                "profit": position.profit,
                "comment": position.comment
            })
        
        return positions_list
    
    def close_position(self, ticket):
        """
        Fecha uma posição aberta.
        
        Args:
            ticket (int): ID da posição
            
        Returns:
            dict: Resultado do fechamento da posição ou None em caso de erro
        """
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        # Obter informações da posição
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            logger.error(f"Posição {ticket} não encontrada: {mt5.last_error()}")
            return None
        
        position = position[0]
        
        # Definir o tipo de ordem oposto para fechar a posição
        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(position.symbol).bid if position.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(position.symbol).ask
        
        # Preparar a requisição de fechamento
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 10,
            "magic": 123456,
            "comment": f"Fechamento da posição #{ticket}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        # Enviar a ordem de fechamento
        logger.info(f"Fechando posição #{ticket}: {position.symbol} {position.volume}")
        result = mt5.order_send(request)
        
        if result is None:
            logger.error(f"Falha ao fechar posição: {mt5.last_error()}")
            return None
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Falha ao fechar posição: {result.retcode} - {result.comment}")
            return {
                "success": False,
                "retcode": result.retcode,
                "comment": result.comment
            }
        
        logger.info(f"Posição fechada com sucesso: {result.order}")
        return {
            "success": True,
            "order_id": result.order,
            "volume": result.volume,
            "price": result.price,
            "comment": result.comment
        }
    
    def get_orders_history(self, days=7):
        """
        Retorna o histórico de ordens.
        
        Args:
            days (int, optional): Número de dias para buscar o histórico
            
        Returns:
            list: Lista de ordens históricas ou None em caso de erro
        """
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        # Calcular o período
        now = datetime.now()
        from_date = now.timestamp() - (days * 24 * 60 * 60)  # Subtrair dias em segundos
        
        # Obter histórico de ordens
        orders = mt5.history_orders_get(from_date, now.timestamp())
        if orders is None:
            error = mt5.last_error()
            if error[0] == 0:  # Sem histórico
                return []
            logger.error(f"Falha ao obter histórico de ordens: {error}")
            return None
        
        # Converter para lista de dicionários
        orders_list = []
        for order in orders:
            orders_list.append({
                "ticket": order.ticket,
                "time_setup": order.time_setup,
                "time_done": order.time_done,
                "type": order.type,
                "state": order.state,
                "symbol": order.symbol,
                "volume_initial": order.volume_initial,
                "price_open": order.price_open,
                "sl": order.sl,
                "tp": order.tp,
                "comment": order.comment
            })
        
        return orders_list
    
    def get_deals_history(self, days=7):
        """
        Retorna o histórico de negociações.
        
        Args:
            days (int, optional): Número de dias para buscar o histórico
            
        Returns:
            list: Lista de negociações históricas ou None em caso de erro
        """
        if not self.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        # Calcular o período
        now = datetime.now()
        from_date = now.timestamp() - (days * 24 * 60 * 60)  # Subtrair dias em segundos
        
        # Obter histórico de negociações
        deals = mt5.history_deals_get(from_date, now.timestamp())
        if deals is None:
            error = mt5.last_error()
            if error[0] == 0:  # Sem histórico
                return []
            logger.error(f"Falha ao obter histórico de negociações: {error}")
            return None
        
        # Converter para lista de dicionários
        deals_list = []
        for deal in deals:
            deals_list.append({
                "ticket": deal.ticket,
                "order": deal.order,
                "time": deal.time,
                "type": deal.type,
                "entry": deal.entry,
                "symbol": deal.symbol,
                "volume": deal.volume,
                "price": deal.price,
                "profit": deal.profit,
                "commission": deal.commission,
                "swap": deal.swap,
                "fee": deal.fee,
                "comment": deal.comment
            })
        
        return deals_list


class MT5Replicator:
    """
    Classe para replicar ordens entre contas MT5.
    """
    
    def __init__(self):
        """Inicializa a classe MT5Replicator."""
        self.source_account = MT5Backend()
        self.target_account = MT5Backend()
        self.is_replicating = False
        self.last_positions = []
        self.volume_multiplier = 1.0
    
    def connect_source(self, account, password, server, account_type="REAL"):
        """
        Conecta à conta de origem.
        
        Args:
            account (int): Número da conta MT5
            password (str): Senha da conta
            server (str): Nome do servidor
            account_type (str): Tipo de conta (REAL ou DEMO)
            
        Returns:
            bool: True se a conexão for bem-sucedida, False caso contrário
        """
        return self.source_account.connect(account, password, server, account_type)
    
    def connect_target(self, account, password, server, account_type="DEMO"):
        """
        Conecta à conta de destino.
        
        Args:
            account (int): Número da conta MT5
            password (str): Senha da conta
            server (str): Nome do servidor
            account_type (str): Tipo de conta (REAL ou DEMO)
            
        Returns:
            bool: True se a conexão for bem-sucedida, False caso contrário
        """
        return self.target_account.connect(account, password, server, account_type)
    
    def set_volume_multiplier(self, multiplier):
        """
        Define o multiplicador de volume para replicação.
        
        Args:
            multiplier (float): Multiplicador de volume (ex: 0.5 para metade do volume)
        """
        self.volume_multiplier = float(multiplier)
        logger.info(f"Multiplicador de volume definido para {self.volume_multiplier}")
    
    def start_replication(self):
        """
        Inicia o processo de replicação de ordens.
        
        Returns:
            bool: True se a replicação for iniciada com sucesso, False caso contrário
        """
        if not self.source_account.check_connection():
            logger.error("Conta de origem não conectada")
            return False
        
        if not self.target_account.check_connection():
            logger.error("Conta de destino não conectada")
            return False
        
        self.is_replicating = True
        self.last_positions = self.source_account.get_positions() or []
        
        logger.info("Replicação de ordens iniciada")
        logger.info(f"Posições atuais na conta de origem: {len(self.last_positions)}")
        
        return True
    
    def stop_replication(self):
        """Para o processo de replicação de ordens."""
        self.is_replicating = False
        logger.info("Replicação de ordens parada")
    
    def check_and_replicate(self):
        """
        Verifica novas posições na conta de origem e as replica para a conta de destino.
        
        Returns:
            dict: Resultado da replicação
        """
        if not self.is_replicating:
            return {"status": "not_replicating"}
        
        if not self.source_account.check_connection() or not self.target_account.check_connection():
            logger.error("Uma das contas não está conectada")
            return {"status": "connection_error"}
        
        # Obter posições atuais
        current_positions = self.source_account.get_positions() or []
        
        # Verificar novas posições
        new_positions = []
        for position in current_positions:
            # Verificar se a posição já existia
            if not any(p["ticket"] == position["ticket"] for p in self.last_positions):
                new_positions.append(position)
        
        # Replicar novas posições
        replicated = []
        for position in new_positions:
            # Calcular volume ajustado
            adjusted_volume = position["volume"] * self.volume_multiplier
            
            # Executar ordem na conta de destino
            result = self.target_account.execute_order(
                action=position["type"],
                symbol=position["symbol"],
                volume=adjusted_volume,
                sl=position["sl"],
                tp=position["tp"],
                comment=f"Replicado de #{position['ticket']}"
            )
            
            if result and result.get("success"):
                logger.info(f"Posição replicada com sucesso: {position['symbol']} {position['type']} {adjusted_volume}")
                replicated.append({
                    "source_ticket": position["ticket"],
                    "target_order": result["order_id"],
                    "symbol": position["symbol"],
                    "type": position["type"],
                    "volume": adjusted_volume,
                    "original_volume": position["volume"]
                })
            else:
                logger.error(f"Falha ao replicar posição: {position['symbol']} {position['type']} {adjusted_volume}")
        
        # Atualizar lista de posições
        self.last_positions = current_positions
        
        return {
            "status": "success",
            "new_positions": len(new_positions),
            "replicated": replicated
        }
    
    def replicate_loop(self, interval=5):
        """
        Executa o loop de replicação de ordens.
        
        Args:
            interval (int, optional): Intervalo em segundos entre verificações
        """
        if not self.start_replication():
            return
        
        logger.info(f"Iniciando loop de replicação com intervalo de {interval} segundos")
        
        try:
            while self.is_replicating:
                result = self.check_and_replicate()
                if result["status"] == "connection_error":
                    logger.error("Erro de conexão, tentando reconectar...")
                    # Tentar reconectar (implementação depende do caso de uso)
                
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Loop de replicação interrompido pelo usuário")
        except Exception as e:
            logger.error(f"Erro no loop de replicação: {e}")
        finally:
            self.stop_replication()


# Exemplo de uso
if __name__ == "__main__":
    # Exemplo de uso do backend
    mt5_backend = MT5Backend()
    
    # Conectar ao MT5
    if mt5_backend.connect(12345678, "senha", "MetaQuotes-Demo", "DEMO"):
        print("Conectado com sucesso!")
        
        # Obter informações da conta
        account_info = mt5_backend.get_account_info()
        print(f"Conta: {account_info['login']} - {account_info['name']}")
        print(f"Saldo: {account_info['balance']} {account_info['currency']}")
        
        # Obter símbolos disponíveis
        symbols = mt5_backend.get_symbols()
        print(f"Símbolos disponíveis: {len(symbols)}")
        
        # Obter preço atual do EURUSD
        price = mt5_backend.get_last_price("EURUSD")
        print(f"EURUSD: Compra: {price['bid']}, Venda: {price['ask']}")
        
        # Desconectar
        mt5_backend.disconnect()
    else:
        print("Falha ao conectar!")
