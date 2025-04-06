#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de integração entre o EA de Tape Reading e o sistema de replicação de ordens.
Este módulo permite que o EA de Tape Reading seja integrado com o sistema existente.
"""

import os
import json
import logging
import threading
import time
from datetime import datetime
import MetaTrader5 as mt5

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_integration.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5Integration")

class MT5Integration:
    """
    Classe para integrar o EA de Tape Reading com o sistema de replicação de ordens.
    """
    
    def __init__(self, ea_instance=None, replicator_instance=None, config_file=None):
        """
        Inicializa o módulo de integração.
        
        Args:
            ea_instance: Instância do EA de Tape Reading
            replicator_instance: Instância do replicador de ordens
            config_file (str, optional): Caminho para o arquivo de configuração
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.ea = ea_instance
        self.replicator = replicator_instance
        self.running = False
        self.sync_thread = None
        self.order_queue = []
        self.position_queue = []
        self.last_sync_time = datetime.now()
        self.sync_lock = threading.Lock()
    
    def _load_config(self):
        """
        Carrega a configuração do módulo de integração.
        
        Returns:
            dict: Configuração do módulo de integração
        """
        default_config = {
            "integration": {
                "enabled": True,
                "sync_interval_seconds": 1,
                "order_sync": True,
                "position_sync": True,
                "performance_sync": True,
                "bidirectional": False,
                "source_priority": "ea",  # "ea" ou "replicator"
                "conflict_resolution": "newer",  # "newer", "ea", "replicator"
                "max_queue_size": 100,
                "retry_attempts": 3,
                "retry_delay_seconds": 1
            },
            "ea_config": {
                "instance_id": "primary",
                "symbols": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
                "magic_number": 123456
            },
            "replicator_config": {
                "group_name": "tape_reading_group",
                "source_account": "primary",
                "target_accounts": ["secondary"],
                "volume_multiplier": 1.0,
                "reverse_direction": False,
                "symbols_filter": [],
                "max_volume": 0.0,
                "min_volume": 0.0,
                "delay_seconds": 0,
                "include_sl_tp": True,
                "adjust_sl_tp_percent": 0.0
            },
            "websocket": {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 8765,
                "auth_required": True,
                "username": "admin",
                "password": "password"
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
        Salva a configuração do módulo de integração em um arquivo JSON.
        
        Args:
            file_path (str, optional): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for salva com sucesso, False caso contrário
        """
        if not file_path:
            file_path = self.config_file or "mt5_integration_config.json"
        
        try:
            with open(file_path, "w") as f:
                json.dump(self.config, f, indent=4)
            
            logger.info(f"Configuração salva em {file_path}")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}")
            return False
    
    def set_ea(self, ea_instance):
        """
        Define a instância do EA de Tape Reading.
        
        Args:
            ea_instance: Instância do EA de Tape Reading
        """
        self.ea = ea_instance
    
    def set_replicator(self, replicator_instance):
        """
        Define a instância do replicador de ordens.
        
        Args:
            replicator_instance: Instância do replicador de ordens
        """
        self.replicator = replicator_instance
    
    def start(self):
        """
        Inicia o módulo de integração.
        
        Returns:
            bool: True se o módulo for iniciado com sucesso, False caso contrário
        """
        if self.running:
            logger.warning("Módulo de integração já está em execução")
            return True
        
        try:
            # Verificar se temos instâncias do EA e do replicador
            if not self.ea:
                logger.error("Instância do EA não definida")
                return False
            
            if not self.replicator:
                logger.error("Instância do replicador não definida")
                return False
            
            # Verificar se a integração está habilitada
            if not self.config["integration"]["enabled"]:
                logger.warning("Integração desabilitada na configuração")
                return False
            
            # Iniciar thread de sincronização
            self.running = True
            self.sync_thread = threading.Thread(
                target=self._sync_loop,
                daemon=True
            )
            self.sync_thread.start()
            
            logger.info("Módulo de integração iniciado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao iniciar módulo de integração: {e}")
            self.running = False
            return False
    
    def stop(self):
        """
        Para o módulo de integração.
        
        Returns:
            bool: True se o módulo for parado com sucesso, False caso contrário
        """
        if not self.running:
            logger.warning("Módulo de integração não está em execução")
            return True
        
        try:
            # Parar thread de sincronização
            self.running = False
            
            # Aguardar finalização da thread
            if self.sync_thread and self.sync_thread.is_alive():
                self.sync_thread.join(timeout=5)
            
            logger.info("Módulo de integração parado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao parar módulo de integração: {e}")
            return False
    
    def _sync_loop(self):
        """
        Loop principal de sincronização.
        """
        logger.info("Iniciando loop de sincronização")
        
        while self.running:
            try:
                # Obter intervalo de sincronização
                sync_interval = self.config["integration"]["sync_interval_seconds"]
                
                # Sincronizar ordens
                if self.config["integration"]["order_sync"]:
                    self._sync_orders()
                
                # Sincronizar posições
                if self.config["integration"]["position_sync"]:
                    self._sync_positions()
                
                # Sincronizar desempenho
                if self.config["integration"]["performance_sync"]:
                    self._sync_performance()
                
                # Processar filas
                self._process_order_queue()
                self._process_position_queue()
                
                # Atualizar tempo de sincronização
                self.last_sync_time = datetime.now()
                
                # Aguardar próxima sincronização
                time.sleep(sync_interval)
                
            except Exception as e:
                logger.error(f"Erro no loop de sincronização: {e}")
                time.sleep(1)
    
    def _sync_orders(self):
        """
        Sincroniza ordens entre o EA e o replicador.
        """
        try:
            # Verificar prioridade de origem
            source_priority = self.config["integration"]["source_priority"]
            
            if source_priority == "ea":
                # Sincronizar do EA para o replicador
                self._sync_orders_ea_to_replicator()
                
                # Sincronizar do replicador para o EA (se bidirecional)
                if self.config["integration"]["bidirectional"]:
                    self._sync_orders_replicator_to_ea()
            else:
                # Sincronizar do replicador para o EA
                self._sync_orders_replicator_to_ea()
                
                # Sincronizar do EA para o replicador (se bidirecional)
                if self.config["integration"]["bidirectional"]:
                    self._sync_orders_ea_to_replicator()
            
        except Exception as e:
            logger.error(f"Erro ao sincronizar ordens: {e}")
    
    def _sync_orders_ea_to_replicator(self):
        """
        Sincroniza ordens do EA para o replicador.
        """
        try:
            # Obter ordens do EA
            ea_orders = self.ea.orders if hasattr(self.ea, "orders") else {}
            
            # Verificar se há ordens para sincronizar
            if not ea_orders:
                return
            
            # Obter configuração do replicador
            replicator_config = self.config["replicator_config"]
            group_name = replicator_config["group_name"]
            
            # Processar cada ordem
            for order_id, order in ea_orders.items():
                # Verificar se a ordem já foi sincronizada
                if self._is_order_synced(order_id):
                    continue
                
                # Verificar filtro de símbolos
                symbol = order["symbol"]
                symbols_filter = replicator_config["symbols_filter"]
                
                if symbols_filter and symbol not in symbols_filter:
                    continue
                
                # Adicionar à fila de ordens
                self._add_to_order_queue({
                    "source": "ea",
                    "order_id": order_id,
                    "order": order,
                    "group_name": group_name
                })
            
        except Exception as e:
            logger.error(f"Erro ao sincronizar ordens do EA para o replicador: {e}")
    
    def _sync_orders_replicator_to_ea(self):
        """
        Sincroniza ordens do replicador para o EA.
        """
        try:
            # Obter ordens do replicador
            replicator_orders = {}
            
            # Verificar se o replicador tem método para obter ordens
            if hasattr(self.replicator, "get_orders"):
                replicator_orders = self.replicator.get_orders()
            
            # Verificar se há ordens para sincronizar
            if not replicator_orders:
                return
            
            # Obter configuração do EA
            ea_config = self.config["ea_config"]
            magic_number = ea_config["magic_number"]
            
            # Processar cada ordem
            for order_id, order in replicator_orders.items():
                # Verificar se a ordem já foi sincronizada
                if self._is_order_synced(order_id):
                    continue
                
                # Verificar filtro de símbolos
                symbol = order["symbol"]
                symbols_filter = ea_config["symbols"]
                
                if symbols_filter and symbol not in symbols_filter:
                    continue
                
                # Adicionar à fila de ordens
                self._add_to_order_queue({
                    "source": "replicator",
                    "order_id": order_id,
                    "order": order,
                    "magic_number": magic_number
                })
            
        except Exception as e:
            logger.error(f"Erro ao sincronizar ordens do replicador para o EA: {e}")
    
    def _sync_positions(self):
        """
        Sincroniza posições entre o EA e o replicador.
        """
        try:
            # Verificar prioridade de origem
            source_priority = self.config["integration"]["source_priority"]
            
            if source_priority == "ea":
                # Sincronizar do EA para o replicador
                self._sync_positions_ea_to_replicator()
                
                # Sincronizar do replicador para o EA (se bidirecional)
                if self.config["integration"]["bidirectional"]:
                    self._sync_positions_replicator_to_ea()
            else:
                # Sincronizar do replicador para o EA
                self._sync_positions_replicator_to_ea()
                
                # Sincronizar do EA para o replicador (se bidirecional)
                if self.config["integration"]["bidirectional"]:
                    self._sync_positions_ea_to_replicator()
            
        except Exception as e:
            logger.error(f"Erro ao sincronizar posições: {e}")
    
    def _sync_positions_ea_to_replicator(self):
        """
        Sincroniza posições do EA para o replicador.
        """
        try:
            # Obter posições do EA
            ea_positions = self.ea.positions if hasattr(self.ea, "positions") else {}
            
            # Verificar se há posições para sincronizar
            if not ea_positions:
                return
            
            # Obter configuração do replicador
            replicator_config = self.config["replicator_config"]
            group_name = replicator_config["group_name"]
            
            # Processar cada posição
            for position_id, position in ea_positions.items():
                # Verificar se a posição já foi sincronizada
                if self._is_position_synced(position_id):
                    continue
                
                # Verificar filtro de símbolos
                symbol = position["symbol"]
                symbols_filter = replicator_config["symbols_filter"]
                
                if symbols_filter and symbol not in symbols_filter:
                    continue
                
                # Adicionar à fila de posições
                self._add_to_position_queue({
                    "source": "ea",
                    "position_id": position_id,
                    "position": position,
                    "group_name": group_name
                })
            
        except Exception as e:
            logger.error(f"Erro ao sincronizar posições do EA para o replicador: {e}")
    
    def _sync_positions_replicator_to_ea(self):
        """
        Sincroniza posições do replicador para o EA.
        """
        try:
            # Obter posições do replicador
            replicator_positions = {}
            
            # Verificar se o replicador tem método para obter posições
            if hasattr(self.replicator, "get_positions"):
                replicator_positions = self.replicator.get_positions()
            
            # Verificar se há posições para sincronizar
            if not replicator_positions:
                return
            
            # Obter configuração do EA
            ea_config = self.config["ea_config"]
            magic_number = ea_config["magic_number"]
            
            # Processar cada posição
            for position_id, position in replicator_positions.items():
                # Verificar se a posição já foi sincronizada
                if self._is_position_synced(position_id):
                    continue
                
                # Verificar filtro de símbolos
                symbol = position["symbol"]
                symbols_filter = ea_config["symbols"]
                
                if symbols_filter and symbol not in symbols_filter:
                    continue
                
                # Adicionar à fila de posições
                self._add_to_position_queue({
                    "source": "replicator",
                    "position_id": position_id,
                    "position": position,
                    "magic_number": magic_number
                })
            
        except Exception as e:
            logger.error(f"Erro ao sincronizar posições do replicador para o EA: {e}")
    
    def _sync_performance(self):
        """
        Sincroniza dados de desempenho entre o EA e o replicador.
        """
        try:
            # Obter dados de desempenho do EA
            ea_performance = {}
            
            if hasattr(self.ea, "performance_metrics"):
                ea_performance = self.ea.performance_metrics
            elif hasattr(self.ea, "get_performance_report"):
                ea_performance = self.ea.get_performance_report()
            
            # Obter dados de desempenho do replicador
            replicator_performance = {}
            
            if hasattr(self.replicator, "performance_metrics"):
                replicator_performance = self.replicator.performance_metrics
            elif hasattr(self.replicator, "get_performance_report"):
                replicator_performance = self.replicator.get_performance_report()
            
            # Verificar se há dados para sincronizar
            if not ea_performance and not replicator_performance:
                return
            
            # Sincronizar dados de desempenho
            # (Implementação simplificada, em um sistema real seria necessário
            # implementar lógica mais complexa para sincronização de desempenho)
            
            # Verificar prioridade de origem
            source_priority = self.config["integration"]["source_priority"]
            
            if source_priority == "ea" and ea_performance:
                # Sincronizar do EA para o replicador
                if hasattr(self.replicator, "update_performance_metrics"):
                    self.replicator.update_performance_metrics(ea_performance)
            elif replicator_performance:
                # Sincronizar do replicador para o EA
                if hasattr(self.ea, "update_performance_metrics"):
                    self.ea.update_performance_metrics(replicator_performance)
            
        except Exception as e:
            logger.error(f"Erro ao sincronizar desempenho: {e}")
    
    def _process_order_queue(self):
        """
        Processa a fila de ordens.
        """
        try:
            # Verificar se há ordens na fila
            if not self.order_queue:
                return
            
            # Obter configuração
            retry_attempts = self.config["integration"]["retry_attempts"]
            retry_delay = self.config["integration"]["retry_delay_seconds"]
            
            # Processar cada ordem na fila
            with self.sync_lock:
                queue_copy = self.order_queue.copy()
                self.order_queue = []
            
            for order_item in queue_copy:
                success = False
                attempts = 0
                
                while not success and attempts < retry_attempts:
                    attempts += 1
                    
                    try:
                        if order_item["source"] == "ea":
                            # Replicar ordem do EA para o replicador
                            success = self._replicate_ea_order(order_item)
                        else:
                            # Replicar ordem do replicador para o EA
                            success = self._replicate_replicator_order(order_item)
                    except Exception as e:
                        logger.error(f"Erro ao processar ordem {order_item['order_id']}: {e}")
                        success = False
                    
                    if not success and attempts < retry_attempts:
                        time.sleep(retry_delay)
                
                if not success:
                    # Adicionar de volta à fila
                    with self.sync_lock:
                        self.order_queue.append(order_item)
                    
                    logger.warning(f"Falha ao processar ordem {order_item['order_id']} após {retry_attempts} tentativas")
            
        except Exception as e:
            logger.error(f"Erro ao processar fila de ordens: {e}")
    
    def _process_position_queue(self):
        """
        Processa a fila de posições.
        """
        try:
            # Verificar se há posições na fila
            if not self.position_queue:
                return
            
            # Obter configuração
            retry_attempts = self.config["integration"]["retry_attempts"]
            retry_delay = self.config["integration"]["retry_delay_seconds"]
            
            # Processar cada posição na fila
            with self.sync_lock:
                queue_copy = self.position_queue.copy()
                self.position_queue = []
            
            for position_item in queue_copy:
                success = False
                attempts = 0
                
                while not success and attempts < retry_attempts:
                    attempts += 1
                    
                    try:
                        if position_item["source"] == "ea":
                            # Replicar posição do EA para o replicador
                            success = self._replicate_ea_position(position_item)
                        else:
                            # Replicar posição do replicador para o EA
                            success = self._replicate_replicator_position(position_item)
                    except Exception as e:
                        logger.error(f"Erro ao processar posição {position_item['position_id']}: {e}")
                        success = False
                    
                    if not success and attempts < retry_attempts:
                        time.sleep(retry_delay)
                
                if not success:
                    # Adicionar de volta à fila
                    with self.sync_lock:
                        self.position_queue.append(position_item)
                    
                    logger.warning(f"Falha ao processar posição {position_item['position_id']} após {retry_attempts} tentativas")
            
        except Exception as e:
            logger.error(f"Erro ao processar fila de posições: {e}")
    
    def _replicate_ea_order(self, order_item):
        """
        Replica uma ordem do EA para o replicador.
        
        Args:
            order_item (dict): Item da fila de ordens
            
        Returns:
            bool: True se a replicação for bem-sucedida, False caso contrário
        """
        try:
            # Obter dados da ordem
            order_id = order_item["order_id"]
            order = order_item["order"]
            group_name = order_item["group_name"]
            
            # Verificar se o replicador tem método para replicar ordens
            if not hasattr(self.replicator, "replicate_order"):
                logger.warning("Replicador não tem método para replicar ordens")
                return False
            
            # Replicar ordem
            success = self.replicator.replicate_order(order, group_name)
            
            if success:
                logger.info(f"Ordem {order_id} replicada com sucesso do EA para o replicador")
            else:
                logger.warning(f"Falha ao replicar ordem {order_id} do EA para o replicador")
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao replicar ordem do EA para o replicador: {e}")
            return False
    
    def _replicate_replicator_order(self, order_item):
        """
        Replica uma ordem do replicador para o EA.
        
        Args:
            order_item (dict): Item da fila de ordens
            
        Returns:
            bool: True se a replicação for bem-sucedida, False caso contrário
        """
        try:
            # Obter dados da ordem
            order_id = order_item["order_id"]
            order = order_item["order"]
            magic_number = order_item["magic_number"]
            
            # Verificar se o EA tem método para executar ordens
            if not hasattr(self.ea, "_execute_order"):
                logger.warning("EA não tem método para executar ordens")
                return False
            
            # Adaptar ordem para o formato do EA
            symbol = order["symbol"]
            action = "BUY" if order["type"] == mt5.ORDER_TYPE_BUY else "SELL"
            volume = order["volume"]
            
            # Executar ordem
            success = self.ea._execute_order(symbol, action, volume=volume, magic=magic_number)
            
            if success:
                logger.info(f"Ordem {order_id} replicada com sucesso do replicador para o EA")
            else:
                logger.warning(f"Falha ao replicar ordem {order_id} do replicador para o EA")
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao replicar ordem do replicador para o EA: {e}")
            return False
    
    def _replicate_ea_position(self, position_item):
        """
        Replica uma posição do EA para o replicador.
        
        Args:
            position_item (dict): Item da fila de posições
            
        Returns:
            bool: True se a replicação for bem-sucedida, False caso contrário
        """
        try:
            # Obter dados da posição
            position_id = position_item["position_id"]
            position = position_item["position"]
            group_name = position_item["group_name"]
            
            # Verificar se o replicador tem método para replicar posições
            if not hasattr(self.replicator, "replicate_position"):
                logger.warning("Replicador não tem método para replicar posições")
                return False
            
            # Replicar posição
            success = self.replicator.replicate_position(position, group_name)
            
            if success:
                logger.info(f"Posição {position_id} replicada com sucesso do EA para o replicador")
            else:
                logger.warning(f"Falha ao replicar posição {position_id} do EA para o replicador")
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao replicar posição do EA para o replicador: {e}")
            return False
    
    def _replicate_replicator_position(self, position_item):
        """
        Replica uma posição do replicador para o EA.
        
        Args:
            position_item (dict): Item da fila de posições
            
        Returns:
            bool: True se a replicação for bem-sucedida, False caso contrário
        """
        try:
            # Obter dados da posição
            position_id = position_item["position_id"]
            position = position_item["position"]
            magic_number = position_item["magic_number"]
            
            # Verificar se o EA tem método para executar ordens
            if not hasattr(self.ea, "_execute_order"):
                logger.warning("EA não tem método para executar ordens")
                return False
            
            # Adaptar posição para o formato do EA
            symbol = position["symbol"]
            action = "BUY" if position["type"] == mt5.POSITION_TYPE_BUY else "SELL"
            volume = position["volume"]
            sl = position["sl"]
            tp = position["tp"]
            
            # Executar ordem
            success = self.ea._execute_order(symbol, action, volume=volume, sl=sl, tp=tp, magic=magic_number)
            
            if success:
                logger.info(f"Posição {position_id} replicada com sucesso do replicador para o EA")
            else:
                logger.warning(f"Falha ao replicar posição {position_id} do replicador para o EA")
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao replicar posição do replicador para o EA: {e}")
            return False
    
    def _add_to_order_queue(self, order_item):
        """
        Adiciona um item à fila de ordens.
        
        Args:
            order_item (dict): Item da fila de ordens
        """
        try:
            with self.sync_lock:
                # Verificar tamanho máximo da fila
                max_queue_size = self.config["integration"]["max_queue_size"]
                
                if len(self.order_queue) >= max_queue_size:
                    logger.warning(f"Fila de ordens cheia, removendo item mais antigo")
                    self.order_queue.pop(0)
                
                # Adicionar à fila
                self.order_queue.append(order_item)
            
        except Exception as e:
            logger.error(f"Erro ao adicionar à fila de ordens: {e}")
    
    def _add_to_position_queue(self, position_item):
        """
        Adiciona um item à fila de posições.
        
        Args:
            position_item (dict): Item da fila de posições
        """
        try:
            with self.sync_lock:
                # Verificar tamanho máximo da fila
                max_queue_size = self.config["integration"]["max_queue_size"]
                
                if len(self.position_queue) >= max_queue_size:
                    logger.warning(f"Fila de posições cheia, removendo item mais antigo")
                    self.position_queue.pop(0)
                
                # Adicionar à fila
                self.position_queue.append(position_item)
            
        except Exception as e:
            logger.error(f"Erro ao adicionar à fila de posições: {e}")
    
    def _is_order_synced(self, order_id):
        """
        Verifica se uma ordem já foi sincronizada.
        
        Args:
            order_id: ID da ordem
            
        Returns:
            bool: True se a ordem já foi sincronizada, False caso contrário
        """
        # Verificar se a ordem está na fila
        with self.sync_lock:
            for item in self.order_queue:
                if item["order_id"] == order_id:
                    return True
        
        return False
    
    def _is_position_synced(self, position_id):
        """
        Verifica se uma posição já foi sincronizada.
        
        Args:
            position_id: ID da posição
            
        Returns:
            bool: True se a posição já foi sincronizada, False caso contrário
        """
        # Verificar se a posição está na fila
        with self.sync_lock:
            for item in self.position_queue:
                if item["position_id"] == position_id:
                    return True
        
        return False
    
    def execute_order(self, symbol, action, volume=None, sl=None, tp=None, comment=None):
        """
        Executa uma ordem e a replica para o sistema de replicação.
        
        Args:
            symbol (str): Símbolo
            action (str): Ação ("BUY" ou "SELL")
            volume (float, optional): Volume
            sl (float, optional): Stop loss
            tp (float, optional): Take profit
            comment (str, optional): Comentário
            
        Returns:
            bool: True se a ordem for executada com sucesso, False caso contrário
        """
        try:
            # Verificar se o EA está disponível
            if not self.ea:
                logger.error("EA não disponível")
                return False
            
            # Verificar se o EA tem método para executar ordens
            if not hasattr(self.ea, "_execute_order"):
                logger.error("EA não tem método para executar ordens")
                return False
            
            # Executar ordem no EA
            result = self.ea._execute_order(symbol, action, volume=volume, sl=sl, tp=tp, comment=comment)
            
            if not result:
                logger.error(f"Falha ao executar ordem {symbol} {action}")
                return False
            
            # A sincronização com o replicador será feita automaticamente pelo loop de sincronização
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao executar ordem: {e}")
            return False
    
    def close_position(self, ticket):
        """
        Fecha uma posição e replica o fechamento para o sistema de replicação.
        
        Args:
            ticket (int): Ticket da posição
            
        Returns:
            bool: True se a posição for fechada com sucesso, False caso contrário
        """
        try:
            # Verificar se o EA está disponível
            if not self.ea:
                logger.error("EA não disponível")
                return False
            
            # Verificar se o EA tem método para fechar posições
            if not hasattr(self.ea, "_close_position"):
                logger.error("EA não tem método para fechar posições")
                return False
            
            # Fechar posição no EA
            result = self.ea._close_position(ticket)
            
            if not result:
                logger.error(f"Falha ao fechar posição {ticket}")
                return False
            
            # A sincronização com o replicador será feita automaticamente pelo loop de sincronização
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao fechar posição: {e}")
            return False
    
    def modify_position(self, ticket, sl, tp):
        """
        Modifica uma posição e replica a modificação para o sistema de replicação.
        
        Args:
            ticket (int): Ticket da posição
            sl (float): Novo stop loss
            tp (float): Novo take profit
            
        Returns:
            bool: True se a posição for modificada com sucesso, False caso contrário
        """
        try:
            # Verificar se o EA está disponível
            if not self.ea:
                logger.error("EA não disponível")
                return False
            
            # Verificar se o EA tem método para modificar posições
            if not hasattr(self.ea, "_modify_position"):
                logger.error("EA não tem método para modificar posições")
                return False
            
            # Modificar posição no EA
            result = self.ea._modify_position(ticket, sl, tp)
            
            if not result:
                logger.error(f"Falha ao modificar posição {ticket}")
                return False
            
            # A sincronização com o replicador será feita automaticamente pelo loop de sincronização
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao modificar posição: {e}")
            return False
    
    def get_status(self):
        """
        Obtém o status do módulo de integração.
        
        Returns:
            dict: Status do módulo de integração
        """
        try:
            # Criar relatório de status
            status = {
                "running": self.running,
                "last_sync_time": self.last_sync_time.isoformat(),
                "order_queue_size": len(self.order_queue),
                "position_queue_size": len(self.position_queue),
                "ea_connected": self.ea is not None and hasattr(self.ea, "connected") and self.ea.connected,
                "replicator_connected": self.replicator is not None,
                "config": self.config,
                "timestamp": datetime.now().isoformat()
            }
            
            return status
            
        except Exception as e:
            logger.error(f"Erro ao obter status: {e}")
            return {
                "running": self.running,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


# Função principal
def main():
    """
    Função principal para testar o módulo de integração.
    """
    # Verificar argumentos
    import argparse
    parser = argparse.ArgumentParser(description="Módulo de integração para MetaTrader 5")
    parser.add_argument("--config", help="Caminho para o arquivo de configuração")
    parser.add_argument("--ea-config", help="Caminho para o arquivo de configuração do EA")
    parser.add_argument("--replicator-config", help="Caminho para o arquivo de configuração do replicador")
    args = parser.parse_args()
    
    try:
        # Importar módulos
        from mt5_tape_reading_ea import MT5TapeReadingEA
        from mt5_replicator import MT5MultiAccountReplicator
        from mt5_auth import MT5Auth
        
        # Inicializar MT5
        if not mt5.initialize():
            print(f"Falha ao inicializar MetaTrader 5: {mt5.last_error()}")
            return
        
        # Criar instâncias
        ea = MT5TapeReadingEA(args.ea_config)
        auth = MT5Auth()
        replicator = MT5MultiAccountReplicator(auth)
        
        # Conectar EA
        if not ea.connect():
            print("Falha ao conectar EA")
            mt5.shutdown()
            return
        
        # Criar módulo de integração
        integration = MT5Integration(ea, replicator, args.config)
        
        # Iniciar módulo de integração
        if not integration.start():
            print("Falha ao iniciar módulo de integração")
            ea.disconnect()
            mt5.shutdown()
            return
        
        print("Módulo de integração iniciado com sucesso")
        print("Pressione Ctrl+C para parar")
        
        # Manter em execução
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("Interrompido pelo usuário")
    
    finally:
        # Parar módulo de integração
        if 'integration' in locals() and integration.running:
            integration.stop()
        
        # Desconectar EA
        if 'ea' in locals() and ea.connected:
            ea.disconnect()
        
        # Finalizar MT5
        if mt5.initialize():
            mt5.shutdown()
        
        print("Módulo de integração finalizado")


# Executar se for o script principal
if __name__ == "__main__":
    main()
