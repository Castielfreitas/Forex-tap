#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de conexão WebSocket para o MetaTrader 5.
Este módulo fornece uma interface WebSocket para comunicação em tempo real com o MT5.
"""

import os
import json
import time
import logging
import threading
import asyncio
import websockets
import MetaTrader5 as mt5
from datetime import datetime

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_websocket.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5WebSocket")

class MT5WebSocketServer:
    """
    Classe para implementar um servidor WebSocket que se comunica com o MetaTrader 5.
    Fornece funcionalidades para receber comandos e enviar atualizações em tempo real.
    """
    
    def __init__(self, mt5_backend, host="0.0.0.0", port=8765):
        """
        Inicializa a classe MT5WebSocketServer.
        
        Args:
            mt5_backend: Instância de MT5Backend para comunicação com o MT5
            host (str): Endereço IP para o servidor WebSocket
            port (int): Porta para o servidor WebSocket
        """
        self.mt5_backend = mt5_backend
        self.host = host
        self.port = port
        self.server = None
        self.running = False
        self.clients = set()
        self.price_subscriptions = {}  # {symbol: set(websocket)}
        self.account_subscriptions = set()  # set(websocket)
        self.position_subscriptions = set()  # set(websocket)
        self.lock = threading.Lock()
    
    async def start_server(self):
        """
        Inicia o servidor WebSocket.
        
        Returns:
            bool: True se o servidor for iniciado com sucesso, False caso contrário
        """
        if self.running:
            logger.warning("Servidor WebSocket já está em execução")
            return True
        
        try:
            # Iniciar servidor WebSocket
            self.server = await websockets.serve(
                self.handle_client,
                self.host,
                self.port
            )
            
            self.running = True
            logger.info(f"Servidor WebSocket iniciado em ws://{self.host}:{self.port}")
            
            # Iniciar loop de atualização de preços
            asyncio.create_task(self.price_update_loop())
            
            # Iniciar loop de atualização de conta
            asyncio.create_task(self.account_update_loop())
            
            # Iniciar loop de atualização de posições
            asyncio.create_task(self.position_update_loop())
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao iniciar servidor WebSocket: {e}")
            return False
    
    async def stop_server(self):
        """
        Para o servidor WebSocket.
        
        Returns:
            bool: True se o servidor for parado com sucesso, False caso contrário
        """
        if not self.running:
            logger.warning("Servidor WebSocket não está em execução")
            return True
        
        try:
            # Fechar todas as conexões de clientes
            for client in self.clients:
                await client.close()
            
            # Parar servidor
            self.server.close()
            await self.server.wait_closed()
            
            self.running = False
            logger.info("Servidor WebSocket parado")
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao parar servidor WebSocket: {e}")
            return False
    
    async def handle_client(self, websocket, path):
        """
        Manipula a conexão de um cliente WebSocket.
        
        Args:
            websocket: Objeto WebSocket do cliente
            path: Caminho da requisição
        """
        try:
            # Adicionar cliente à lista
            with self.lock:
                self.clients.add(websocket)
            
            logger.info(f"Novo cliente conectado: {websocket.remote_address}")
            
            # Enviar mensagem de boas-vindas
            await websocket.send(json.dumps({
                "type": "welcome",
                "message": "Conectado ao servidor WebSocket do MT5",
                "timestamp": datetime.now().isoformat()
            }))
            
            # Processar mensagens do cliente
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.process_client_message(websocket, data)
                except json.JSONDecodeError:
                    logger.error(f"Mensagem inválida recebida: {message}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Formato de mensagem inválido. Esperado JSON.",
                        "timestamp": datetime.now().isoformat()
                    }))
        
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Cliente desconectado: {websocket.remote_address}")
        
        finally:
            # Remover cliente da lista e de todas as assinaturas
            with self.lock:
                self.clients.discard(websocket)
                self.account_subscriptions.discard(websocket)
                self.position_subscriptions.discard(websocket)
                
                for symbol, subscribers in list(self.price_subscriptions.items()):
                    subscribers.discard(websocket)
                    if not subscribers:
                        del self.price_subscriptions[symbol]
    
    async def process_client_message(self, websocket, data):
        """
        Processa uma mensagem recebida de um cliente.
        
        Args:
            websocket: Objeto WebSocket do cliente
            data (dict): Dados da mensagem
        """
        try:
            message_type = data.get("type")
            
            if message_type == "subscribe":
                await self.handle_subscription(websocket, data)
            
            elif message_type == "unsubscribe":
                await self.handle_unsubscription(websocket, data)
            
            elif message_type == "command":
                await self.handle_command(websocket, data)
            
            elif message_type == "ping":
                await websocket.send(json.dumps({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat()
                }))
            
            else:
                logger.warning(f"Tipo de mensagem desconhecido: {message_type}")
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": f"Tipo de mensagem desconhecido: {message_type}",
                    "timestamp": datetime.now().isoformat()
                }))
        
        except Exception as e:
            logger.error(f"Erro ao processar mensagem do cliente: {e}")
            await websocket.send(json.dumps({
                "type": "error",
                "message": f"Erro ao processar mensagem: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }))
    
    async def handle_subscription(self, websocket, data):
        """
        Processa uma solicitação de assinatura.
        
        Args:
            websocket: Objeto WebSocket do cliente
            data (dict): Dados da solicitação
        """
        channel = data.get("channel")
        
        if channel == "price":
            symbol = data.get("symbol")
            if not symbol:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Símbolo não especificado para assinatura de preço",
                    "timestamp": datetime.now().isoformat()
                }))
                return
            
            with self.lock:
                if symbol not in self.price_subscriptions:
                    self.price_subscriptions[symbol] = set()
                self.price_subscriptions[symbol].add(websocket)
            
            # Enviar preço atual imediatamente
            price = self.mt5_backend.get_last_price(symbol)
            if price:
                await websocket.send(json.dumps({
                    "type": "price",
                    "symbol": symbol,
                    "bid": price["bid"],
                    "ask": price["ask"],
                    "timestamp": datetime.now().isoformat()
                }))
            
            logger.info(f"Cliente {websocket.remote_address} assinou preços de {symbol}")
        
        elif channel == "account":
            with self.lock:
                self.account_subscriptions.add(websocket)
            
            # Enviar informações da conta imediatamente
            account_info = self.mt5_backend.get_account_info()
            if account_info:
                await websocket.send(json.dumps({
                    "type": "account",
                    "data": account_info,
                    "timestamp": datetime.now().isoformat()
                }))
            
            logger.info(f"Cliente {websocket.remote_address} assinou informações da conta")
        
        elif channel == "positions":
            with self.lock:
                self.position_subscriptions.add(websocket)
            
            # Enviar posições atuais imediatamente
            positions = self.mt5_backend.get_positions()
            if positions is not None:
                await websocket.send(json.dumps({
                    "type": "positions",
                    "data": positions,
                    "timestamp": datetime.now().isoformat()
                }))
            
            logger.info(f"Cliente {websocket.remote_address} assinou posições")
        
        else:
            await websocket.send(json.dumps({
                "type": "error",
                "message": f"Canal de assinatura desconhecido: {channel}",
                "timestamp": datetime.now().isoformat()
            }))
    
    async def handle_unsubscription(self, websocket, data):
        """
        Processa uma solicitação de cancelamento de assinatura.
        
        Args:
            websocket: Objeto WebSocket do cliente
            data (dict): Dados da solicitação
        """
        channel = data.get("channel")
        
        if channel == "price":
            symbol = data.get("symbol")
            if not symbol:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Símbolo não especificado para cancelamento de assinatura de preço",
                    "timestamp": datetime.now().isoformat()
                }))
                return
            
            with self.lock:
                if symbol in self.price_subscriptions:
                    self.price_subscriptions[symbol].discard(websocket)
                    if not self.price_subscriptions[symbol]:
                        del self.price_subscriptions[symbol]
            
            logger.info(f"Cliente {websocket.remote_address} cancelou assinatura de preços de {symbol}")
        
        elif channel == "account":
            with self.lock:
                self.account_subscriptions.discard(websocket)
            
            logger.info(f"Cliente {websocket.remote_address} cancelou assinatura de informações da conta")
        
        elif channel == "positions":
            with self.lock:
                self.position_subscriptions.discard(websocket)
            
            logger.info(f"Cliente {websocket.remote_address} cancelou assinatura de posições")
        
        else:
            await websocket.send(json.dumps({
                "type": "error",
                "message": f"Canal de assinatura desconhecido: {channel}",
                "timestamp": datetime.now().isoformat()
            }))
    
    async def handle_command(self, websocket, data):
        """
        Processa um comando recebido de um cliente.
        
        Args:
            websocket: Objeto WebSocket do cliente
            data (dict): Dados do comando
        """
        command = data.get("command")
        
        if command == "execute_order":
            # Extrair parâmetros da ordem
            action = data.get("action")
            symbol = data.get("symbol")
            volume = data.get("volume")
            sl = data.get("sl", 0.0)
            tp = data.get("tp", 0.0)
            comment = data.get("comment", "")
            
            # Validar parâmetros
            if not all([action, symbol, volume]):
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Parâmetros incompletos para execução de ordem",
                    "timestamp": datetime.now().isoformat()
                }))
                return
            
            # Executar ordem
            result = self.mt5_backend.execute_order(
                action=action,
                symbol=symbol,
                volume=float(volume),
                sl=float(sl),
                tp=float(tp),
                comment=comment
            )
            
            # Enviar resultado
            await websocket.send(json.dumps({
                "type": "order_result",
                "success": result is not None and result.get("success", False),
                "data": result,
                "timestamp": datetime.now().isoformat()
            }))
            
            logger.info(f"Cliente {websocket.remote_address} executou ordem: {action} {volume} {symbol}")
        
        elif command == "close_position":
            # Extrair parâmetros
            ticket = data.get("ticket")
            
            # Validar parâmetros
            if not ticket:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Ticket não especificado para fechamento de posição",
                    "timestamp": datetime.now().isoformat()
                }))
                return
            
            # Fechar posição
            result = self.mt5_backend.close_position(int(ticket))
            
            # Enviar resultado
            await websocket.send(json.dumps({
                "type": "close_result",
                "success": result is not None and result.get("success", False),
                "data": result,
                "timestamp": datetime.now().isoformat()
            }))
            
            logger.info(f"Cliente {websocket.remote_address} fechou posição: {ticket}")
        
        elif command == "get_symbols":
            # Obter símbolos disponíveis
            symbols = self.mt5_backend.get_symbols()
            
            # Enviar resultado
            await websocket.send(json.dumps({
                "type": "symbols",
                "data": symbols,
                "timestamp": datetime.now().isoformat()
            }))
            
            logger.info(f"Cliente {websocket.remote_address} solicitou lista de símbolos")
        
        elif command == "get_symbol_info":
            # Extrair parâmetros
            symbol = data.get("symbol")
            
            # Validar parâmetros
            if not symbol:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Símbolo não especificado para obter informações",
                    "timestamp": datetime.now().isoformat()
                }))
                return
            
            # Obter informações do símbolo
            symbol_info = self.mt5_backend.get_symbol_info(symbol)
            
            # Enviar resultado
            await websocket.send(json.dumps({
                "type": "symbol_info",
                "symbol": symbol,
                "data": symbol_info,
                "timestamp": datetime.now().isoformat()
            }))
            
            logger.info(f"Cliente {websocket.remote_address} solicitou informações do símbolo: {symbol}")
        
        else:
            await websocket.send(json.dumps({
                "type": "error",
                "message": f"Comando desconhecido: {command}",
                "timestamp": datetime.now().isoformat()
            }))
    
    async def price_update_loop(self):
        """
        Loop para enviar atualizações de preços para os clientes inscritos.
        """
        while self.running:
            try:
                with self.lock:
                    # Copiar dicionário para evitar modificações durante a iteração
                    subscriptions = {symbol: set(subscribers) for symbol, subscribers in self.price_subscriptions.items()}
                
                # Processar cada símbolo
                for symbol, subscribers in subscriptions.items():
                    if not subscribers:
                        continue
                    
                    # Obter preço atual
                    price = self.mt5_backend.get_last_price(symbol)
                    if not price:
                        continue
                    
                    # Preparar mensagem
                    message = json.dumps({
                        "type": "price",
                        "symbol": symbol,
                        "bid": price["bid"],
                        "ask": price["ask"],
                        "timestamp": datetime.now().isoformat()
                    })
                    
                    # Enviar para todos os assinantes
                    for websocket in subscribers:
                        try:
                            await websocket.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            # Cliente desconectado, será removido no próximo ciclo
                            pass
                
                # Aguardar próxima atualização
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Erro no loop de atualização de preços: {e}")
                await asyncio.sleep(5)  # Aguardar mais tempo em caso de erro
    
    async def account_update_loop(self):
        """
        Loop para enviar atualizações de informações da conta para os clientes inscritos.
        """
        while self.running:
            try:
                with self.lock:
                    # Copiar conjunto para evitar modificações durante a iteração
                    subscribers = set(self.account_subscriptions)
                
                if subscribers:
                    # Obter informações da conta
                    account_info = self.mt5_backend.get_account_info()
                    if account_info:
                        # Preparar mensagem
                        message = json.dumps({
                            "type": "account",
                            "data": account_info,
                            "timestamp": datetime.now().isoformat()
                        })
                        
                        # Enviar para todos os assinantes
                        for websocket in subscribers:
                            try:
                                await websocket.send(message)
                            except websockets.exceptions.ConnectionClosed:
                                # Cliente desconectado, será removido no próximo ciclo
                                pass
                
                # Aguardar próxima atualização
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Erro no loop de atualização de conta: {e}")
                await asyncio.sleep(10)  # Aguardar mais tempo em caso de erro
    
    async def position_update_loop(self):
        """
        Loop para enviar atualizações de posições para os clientes inscritos.
        """
        while self.running:
            try:
                with self.lock:
                    # Copiar conjunto para evitar modificações durante a iteração
                    subscribers = set(self.position_subscriptions)
                
                if subscribers:
                    # Obter posições
                    positions = self.mt5_backend.get_positions()
                    if positions is not None:
                        # Preparar mensagem
                        message = json.dumps({
                            "type": "positions",
                            "data": positions,
                            "timestamp": datetime.now().isoformat()
                        })
                        
                        # Enviar para todos os assinantes
                        for websocket in subscribers:
                            try:
                                await websocket.send(message)
                            except websockets.exceptions.ConnectionClosed:
                                # Cliente desconectado, será removido no próximo ciclo
                                pass
                
                # Aguardar próxima atualização
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Erro no loop de atualização de posições: {e}")
                await asyncio.sleep(5)  # Aguardar mais tempo em caso de erro


class MT5WebSocketClient:
    """
    Cliente WebSocket para comunicação com o servidor MT5WebSocket.
    """
    
    def __init__(self, url="ws://localhost:8765"):
        """
        Inicializa a classe MT5WebSocketClient.
        
        Args:
            url (str): URL do servidor WebSocket
        """
        self.url = url
        self.websocket = None
        self.connected = False
        self.callbacks = {
            "price": {},  # {symbol: callback}
            "account": None,
            "positions": None,
            "order_result": None,
            "close_result": None,
            "error": None,
            "connected": None,
            "disconnected": None
        }
        self.reconnect_task = None
        self.message_task = None
    
    async def connect(self):
        """
        Conecta ao servidor WebSocket.
        
        Returns:
            bool: True se a conexão for bem-sucedida, False caso contrário
        """
        if self.connected:
            logger.warning("Cliente WebSocket já está conectado")
            return True
        
        try:
            self.websocket = await websockets.connect(self.url)
            self.connected = True
            
            # Iniciar tarefa para processar mensagens
            self.message_task = asyncio.create_task(self.message_loop())
            
            # Notificar conexão
            if self.callbacks["connected"]:
                self.callbacks["connected"]()
            
            logger.info(f"Conectado ao servidor WebSocket: {self.url}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao conectar ao servidor WebSocket: {e}")
            return False
    
    async def disconnect(self):
        """
        Desconecta do servidor WebSocket.
        
        Returns:
            bool: True se a desconexão for bem-sucedida, False caso contrário
        """
        if not self.connected:
            logger.warning("Cliente WebSocket não está conectado")
            return True
        
        try:
            # Cancelar tarefas
            if self.message_task:
                self.message_task.cancel()
                self.message_task = None
            
            if self.reconnect_task:
                self.reconnect_task.cancel()
                self.reconnect_task = None
            
            # Fechar conexão
            await self.websocket.close()
            self.websocket = None
            self.connected = False
            
            # Notificar desconexão
            if self.callbacks["disconnected"]:
                self.callbacks["disconnected"]()
            
            logger.info("Desconectado do servidor WebSocket")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao desconectar do servidor WebSocket: {e}")
            return False
    
    async def message_loop(self):
        """
        Loop para processar mensagens recebidas do servidor.
        """
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self.process_message(data)
                except json.JSONDecodeError:
                    logger.error(f"Mensagem inválida recebida: {message}")
        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Conexão com o servidor WebSocket fechada")
            self.connected = False
            
            # Notificar desconexão
            if self.callbacks["disconnected"]:
                self.callbacks["disconnected"]()
            
            # Tentar reconectar automaticamente
            if not self.reconnect_task or self.reconnect_task.done():
                self.reconnect_task = asyncio.create_task(self.reconnect())
        
        except asyncio.CancelledError:
            # Tarefa cancelada, provavelmente devido a desconexão manual
            pass
        
        except Exception as e:
            logger.error(f"Erro no loop de mensagens: {e}")
            self.connected = False
            
            # Notificar desconexão
            if self.callbacks["disconnected"]:
                self.callbacks["disconnected"]()
    
    async def reconnect(self, max_attempts=5, delay=5):
        """
        Tenta reconectar ao servidor WebSocket.
        
        Args:
            max_attempts (int): Número máximo de tentativas
            delay (int): Atraso em segundos entre tentativas
        """
        attempts = 0
        
        while attempts < max_attempts and not self.connected:
            logger.info(f"Tentando reconectar ao servidor WebSocket (tentativa {attempts+1}/{max_attempts})...")
            
            try:
                await self.connect()
                if self.connected:
                    # Reinscrever em todos os canais
                    await self.resubscribe()
                    logger.info("Reconectado com sucesso")
                    return
            
            except Exception as e:
                logger.error(f"Erro ao reconectar: {e}")
            
            attempts += 1
            await asyncio.sleep(delay)
        
        logger.error(f"Falha ao reconectar após {max_attempts} tentativas")
    
    async def resubscribe(self):
        """
        Reinscreve em todos os canais após reconexão.
        """
        # Reinscrever em preços
        for symbol in self.callbacks["price"]:
            await self.subscribe_price(symbol)
        
        # Reinscrever em informações da conta
        if self.callbacks["account"]:
            await self.subscribe_account()
        
        # Reinscrever em posições
        if self.callbacks["positions"]:
            await self.subscribe_positions()
    
    async def process_message(self, data):
        """
        Processa uma mensagem recebida do servidor.
        
        Args:
            data (dict): Dados da mensagem
        """
        message_type = data.get("type")
        
        if message_type == "price":
            symbol = data.get("symbol")
            callback = self.callbacks["price"].get(symbol)
            if callback:
                callback(data)
        
        elif message_type == "account":
            if self.callbacks["account"]:
                self.callbacks["account"](data)
        
        elif message_type == "positions":
            if self.callbacks["positions"]:
                self.callbacks["positions"](data)
        
        elif message_type == "order_result":
            if self.callbacks["order_result"]:
                self.callbacks["order_result"](data)
        
        elif message_type == "close_result":
            if self.callbacks["close_result"]:
                self.callbacks["close_result"](data)
        
        elif message_type == "error":
            if self.callbacks["error"]:
                self.callbacks["error"](data)
        
        elif message_type == "welcome":
            logger.info(f"Mensagem de boas-vindas recebida: {data.get('message')}")
        
        elif message_type == "pong":
            # Resposta a ping, ignorar
            pass
        
        else:
            logger.warning(f"Tipo de mensagem desconhecido: {message_type}")
    
    async def send_message(self, data):
        """
        Envia uma mensagem para o servidor.
        
        Args:
            data (dict): Dados da mensagem
            
        Returns:
            bool: True se a mensagem for enviada com sucesso, False caso contrário
        """
        if not self.connected:
            logger.error("Não conectado ao servidor WebSocket")
            return False
        
        try:
            await self.websocket.send(json.dumps(data))
            return True
        
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")
            return False
    
    async def subscribe_price(self, symbol):
        """
        Assina atualizações de preço para um símbolo.
        
        Args:
            symbol (str): Símbolo para assinar
            
        Returns:
            bool: True se a assinatura for bem-sucedida, False caso contrário
        """
        return await self.send_message({
            "type": "subscribe",
            "channel": "price",
            "symbol": symbol
        })
    
    async def unsubscribe_price(self, symbol):
        """
        Cancela assinatura de atualizações de preço para um símbolo.
        
        Args:
            symbol (str): Símbolo para cancelar assinatura
            
        Returns:
            bool: True se o cancelamento for bem-sucedido, False caso contrário
        """
        return await self.send_message({
            "type": "unsubscribe",
            "channel": "price",
            "symbol": symbol
        })
    
    async def subscribe_account(self):
        """
        Assina atualizações de informações da conta.
        
        Returns:
            bool: True se a assinatura for bem-sucedida, False caso contrário
        """
        return await self.send_message({
            "type": "subscribe",
            "channel": "account"
        })
    
    async def unsubscribe_account(self):
        """
        Cancela assinatura de atualizações de informações da conta.
        
        Returns:
            bool: True se o cancelamento for bem-sucedido, False caso contrário
        """
        return await self.send_message({
            "type": "unsubscribe",
            "channel": "account"
        })
    
    async def subscribe_positions(self):
        """
        Assina atualizações de posições.
        
        Returns:
            bool: True se a assinatura for bem-sucedida, False caso contrário
        """
        return await self.send_message({
            "type": "subscribe",
            "channel": "positions"
        })
    
    async def unsubscribe_positions(self):
        """
        Cancela assinatura de atualizações de posições.
        
        Returns:
            bool: True se o cancelamento for bem-sucedido, False caso contrário
        """
        return await self.send_message({
            "type": "unsubscribe",
            "channel": "positions"
        })
    
    async def execute_order(self, action, symbol, volume, sl=0.0, tp=0.0, comment=""):
        """
        Envia um comando para executar uma ordem.
        
        Args:
            action (str): Tipo de ordem ("BUY" ou "SELL")
            symbol (str): Símbolo
            volume (float): Volume
            sl (float, optional): Stop Loss
            tp (float, optional): Take Profit
            comment (str, optional): Comentário
            
        Returns:
            bool: True se o comando for enviado com sucesso, False caso contrário
        """
        return await self.send_message({
            "type": "command",
            "command": "execute_order",
            "action": action,
            "symbol": symbol,
            "volume": volume,
            "sl": sl,
            "tp": tp,
            "comment": comment
        })
    
    async def close_position(self, ticket):
        """
        Envia um comando para fechar uma posição.
        
        Args:
            ticket (int): ID da posição
            
        Returns:
            bool: True se o comando for enviado com sucesso, False caso contrário
        """
        return await self.send_message({
            "type": "command",
            "command": "close_position",
            "ticket": ticket
        })
    
    async def get_symbols(self):
        """
        Envia um comando para obter a lista de símbolos disponíveis.
        
        Returns:
            bool: True se o comando for enviado com sucesso, False caso contrário
        """
        return await self.send_message({
            "type": "command",
            "command": "get_symbols"
        })
    
    async def get_symbol_info(self, symbol):
        """
        Envia um comando para obter informações de um símbolo.
        
        Args:
            symbol (str): Símbolo
            
        Returns:
            bool: True se o comando for enviado com sucesso, False caso contrário
        """
        return await self.send_message({
            "type": "command",
            "command": "get_symbol_info",
            "symbol": symbol
        })
    
    async def ping(self):
        """
        Envia um ping para o servidor.
        
        Returns:
            bool: True se o ping for enviado com sucesso, False caso contrário
        """
        return await self.send_message({
            "type": "ping",
            "timestamp": datetime.now().isoformat()
        })
    
    def set_price_callback(self, symbol, callback):
        """
        Define um callback para atualizações de preço de um símbolo.
        
        Args:
            symbol (str): Símbolo
            callback (callable): Função de callback
        """
        self.callbacks["price"][symbol] = callback
    
    def set_account_callback(self, callback):
        """
        Define um callback para atualizações de informações da conta.
        
        Args:
            callback (callable): Função de callback
        """
        self.callbacks["account"] = callback
    
    def set_positions_callback(self, callback):
        """
        Define um callback para atualizações de posições.
        
        Args:
            callback (callable): Função de callback
        """
        self.callbacks["positions"] = callback
    
    def set_order_result_callback(self, callback):
        """
        Define um callback para resultados de execução de ordens.
        
        Args:
            callback (callable): Função de callback
        """
        self.callbacks["order_result"] = callback
    
    def set_close_result_callback(self, callback):
        """
        Define um callback para resultados de fechamento de posições.
        
        Args:
            callback (callable): Função de callback
        """
        self.callbacks["close_result"] = callback
    
    def set_error_callback(self, callback):
        """
        Define um callback para erros.
        
        Args:
            callback (callable): Função de callback
        """
        self.callbacks["error"] = callback
    
    def set_connected_callback(self, callback):
        """
        Define um callback para evento de conexão.
        
        Args:
            callback (callable): Função de callback
        """
        self.callbacks["connected"] = callback
    
    def set_disconnected_callback(self, callback):
        """
        Define um callback para evento de desconexão.
        
        Args:
            callback (callable): Função de callback
        """
        self.callbacks["disconnected"] = callback


# Função para iniciar o servidor WebSocket
async def start_websocket_server(mt5_backend, host="0.0.0.0", port=8765):
    """
    Inicia o servidor WebSocket para o MT5.
    
    Args:
        mt5_backend: Instância de MT5Backend para comunicação com o MT5
        host (str): Endereço IP para o servidor WebSocket
        port (int): Porta para o servidor WebSocket
        
    Returns:
        MT5WebSocketServer: Instância do servidor WebSocket
    """
    server = MT5WebSocketServer(mt5_backend, host, port)
    await server.start_server()
    return server


# Exemplo de uso
if __name__ == "__main__":
    # Importar backend MT5
    import sys
    sys.path.append('.')
    from mt5_backend import MT5Backend
    
    # Função para iniciar o servidor
    async def run_server():
        # Criar instância do backend
        mt5_backend = MT5Backend()
        
        # Conectar ao MT5
        if mt5_backend.connect(12345678, "senha", "MetaQuotes-Demo", "DEMO"):
            print("Conectado ao MT5 com sucesso!")
            
            # Iniciar servidor WebSocket
            server = await start_websocket_server(mt5_backend)
            
            # Manter servidor em execução
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("Encerrando servidor...")
                await server.stop_server()
                mt5_backend.disconnect()
        else:
            print("Falha ao conectar ao MT5!")
    
    # Executar servidor
    asyncio.run(run_server())
