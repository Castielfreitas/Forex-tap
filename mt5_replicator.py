#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de replicação de ordens para o MetaTrader 5.
Este módulo fornece funcionalidades para replicar ordens entre contas MT5.
"""

import os
import json
import time
import logging
import threading
import queue
from datetime import datetime, timedelta
import MetaTrader5 as mt5

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_replicator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5Replicator")

class MT5OrderReplicator:
    """
    Classe para replicar ordens entre contas do MetaTrader 5.
    Fornece funcionalidades para monitorar ordens em uma conta e replicá-las em outras contas.
    """
    
    def __init__(self, mt5_backend_source=None, mt5_backend_targets=None):
        """
        Inicializa a classe MT5OrderReplicator.
        
        Args:
            mt5_backend_source: Instância de MT5Backend para a conta de origem
            mt5_backend_targets: Lista de instâncias de MT5Backend para as contas de destino
        """
        self.mt5_backend_source = mt5_backend_source
        self.mt5_backend_targets = mt5_backend_targets or []
        self.running = False
        self.order_queue = queue.Queue()
        self.processed_orders = set()
        self.last_check_time = datetime.now()
        self.replication_thread = None
        self.monitor_thread = None
        self.lock = threading.Lock()
        self.replication_config = {
            "enabled": False,
            "volume_multiplier": 1.0,
            "reverse_direction": False,
            "symbols_filter": [],
            "max_volume": 0.0,
            "min_volume": 0.0,
            "delay_seconds": 0,
            "include_sl_tp": True,
            "adjust_sl_tp_percent": 0.0
        }
    
    def set_source_backend(self, mt5_backend):
        """
        Define o backend MT5 para a conta de origem.
        
        Args:
            mt5_backend: Instância de MT5Backend para a conta de origem
        """
        self.mt5_backend_source = mt5_backend
    
    def add_target_backend(self, mt5_backend):
        """
        Adiciona um backend MT5 para uma conta de destino.
        
        Args:
            mt5_backend: Instância de MT5Backend para a conta de destino
        """
        if mt5_backend not in self.mt5_backend_targets:
            self.mt5_backend_targets.append(mt5_backend)
    
    def remove_target_backend(self, mt5_backend):
        """
        Remove um backend MT5 da lista de contas de destino.
        
        Args:
            mt5_backend: Instância de MT5Backend para a conta de destino
        """
        if mt5_backend in self.mt5_backend_targets:
            self.mt5_backend_targets.remove(mt5_backend)
    
    def set_replication_config(self, config):
        """
        Define a configuração de replicação.
        
        Args:
            config (dict): Configuração de replicação
        """
        with self.lock:
            self.replication_config.update(config)
    
    def get_replication_config(self):
        """
        Obtém a configuração de replicação atual.
        
        Returns:
            dict: Configuração de replicação
        """
        with self.lock:
            return self.replication_config.copy()
    
    def start_replication(self):
        """
        Inicia o processo de replicação de ordens.
        
        Returns:
            bool: True se o processo for iniciado com sucesso, False caso contrário
        """
        if self.running:
            logger.warning("Replicação já está em execução")
            return True
        
        if not self.mt5_backend_source or not self.mt5_backend_source.check_connection():
            logger.error("Conta de origem não conectada")
            return False
        
        if not self.mt5_backend_targets:
            logger.error("Nenhuma conta de destino configurada")
            return False
        
        # Verificar conexão das contas de destino
        for i, target in enumerate(self.mt5_backend_targets):
            if not target.check_connection():
                logger.error(f"Conta de destino {i+1} não conectada")
                return False
        
        # Ativar replicação
        with self.lock:
            self.replication_config["enabled"] = True
            self.running = True
        
        # Iniciar thread de replicação
        self.replication_thread = threading.Thread(
            target=self._replication_loop,
            daemon=True
        )
        self.replication_thread.start()
        
        # Iniciar thread de monitoramento
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self.monitor_thread.start()
        
        logger.info("Replicação de ordens iniciada")
        return True
    
    def stop_replication(self):
        """
        Para o processo de replicação de ordens.
        
        Returns:
            bool: True se o processo for parado com sucesso, False caso contrário
        """
        if not self.running:
            logger.warning("Replicação não está em execução")
            return True
        
        # Desativar replicação
        with self.lock:
            self.replication_config["enabled"] = False
            self.running = False
        
        # Aguardar finalização das threads
        if self.replication_thread and self.replication_thread.is_alive():
            self.replication_thread.join(timeout=5)
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        logger.info("Replicação de ordens parada")
        return True
    
    def _monitor_loop(self):
        """
        Loop para monitorar novas ordens na conta de origem.
        """
        while self.running:
            try:
                # Verificar se a replicação está habilitada
                with self.lock:
                    if not self.replication_config["enabled"]:
                        time.sleep(1)
                        continue
                
                # Verificar conexão da conta de origem
                if not self.mt5_backend_source.check_connection():
                    logger.error("Conta de origem desconectada")
                    time.sleep(5)
                    continue
                
                # Obter histórico de ordens recentes
                current_time = datetime.now()
                from_time = self.last_check_time - timedelta(minutes=5)  # Overlap para garantir
                self.last_check_time = current_time
                
                orders = self.mt5_backend_source.get_orders_history(from_time)
                if orders is None:
                    logger.warning("Falha ao obter histórico de ordens")
                    time.sleep(5)
                    continue
                
                # Filtrar ordens não processadas
                new_orders = []
                for order in orders:
                    order_id = order.get("ticket")
                    if order_id and order_id not in self.processed_orders:
                        new_orders.append(order)
                        self.processed_orders.add(order_id)
                
                # Adicionar novas ordens à fila
                for order in new_orders:
                    self.order_queue.put(order)
                    logger.info(f"Nova ordem detectada: {order.get('ticket')} - {order.get('symbol')}")
                
                # Limitar tamanho do conjunto de ordens processadas
                if len(self.processed_orders) > 10000:
                    self.processed_orders = set(list(self.processed_orders)[-5000:])
                
                # Aguardar próxima verificação
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Erro no loop de monitoramento: {e}")
                time.sleep(5)
    
    def _replication_loop(self):
        """
        Loop para processar a fila de ordens e replicá-las nas contas de destino.
        """
        while self.running:
            try:
                # Obter próxima ordem da fila
                try:
                    order = self.order_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # Verificar se a replicação está habilitada
                with self.lock:
                    config = self.replication_config.copy()
                    if not config["enabled"]:
                        self.order_queue.task_done()
                        continue
                
                # Aplicar filtros de replicação
                if not self._should_replicate_order(order, config):
                    logger.info(f"Ordem {order.get('ticket')} ignorada pelos filtros")
                    self.order_queue.task_done()
                    continue
                
                # Aplicar delay se configurado
                if config["delay_seconds"] > 0:
                    time.sleep(config["delay_seconds"])
                
                # Replicar ordem em todas as contas de destino
                for i, target in enumerate(self.mt5_backend_targets):
                    try:
                        # Verificar conexão da conta de destino
                        if not target.check_connection():
                            logger.error(f"Conta de destino {i+1} desconectada")
                            continue
                        
                        # Replicar ordem
                        result = self._replicate_order(order, target, config)
                        
                        if result and result.get("success"):
                            logger.info(f"Ordem {order.get('ticket')} replicada com sucesso na conta de destino {i+1}")
                        else:
                            logger.error(f"Falha ao replicar ordem {order.get('ticket')} na conta de destino {i+1}: {result}")
                    
                    except Exception as e:
                        logger.error(f"Erro ao replicar ordem {order.get('ticket')} na conta de destino {i+1}: {e}")
                
                # Marcar tarefa como concluída
                self.order_queue.task_done()
                
            except Exception as e:
                logger.error(f"Erro no loop de replicação: {e}")
                time.sleep(5)
    
    def _should_replicate_order(self, order, config):
        """
        Verifica se uma ordem deve ser replicada com base nos filtros configurados.
        
        Args:
            order (dict): Dados da ordem
            config (dict): Configuração de replicação
            
        Returns:
            bool: True se a ordem deve ser replicada, False caso contrário
        """
        # Verificar filtro de símbolos
        symbol = order.get("symbol", "")
        if config["symbols_filter"] and symbol not in config["symbols_filter"]:
            return False
        
        # Verificar volume mínimo
        volume = order.get("volume", 0.0)
        if config["min_volume"] > 0 and volume < config["min_volume"]:
            return False
        
        # Verificar volume máximo
        if config["max_volume"] > 0 and volume > config["max_volume"]:
            return False
        
        return True
    
    def _replicate_order(self, order, target_backend, config):
        """
        Replica uma ordem em uma conta de destino.
        
        Args:
            order (dict): Dados da ordem
            target_backend: Instância de MT5Backend para a conta de destino
            config (dict): Configuração de replicação
            
        Returns:
            dict: Resultado da execução da ordem
        """
        try:
            # Extrair dados da ordem
            symbol = order.get("symbol", "")
            order_type = order.get("type", "")
            volume = order.get("volume", 0.0)
            price = order.get("price", 0.0)
            sl = order.get("sl", 0.0)
            tp = order.get("tp", 0.0)
            comment = order.get("comment", "")
            
            # Ajustar volume com multiplicador
            volume = volume * config["volume_multiplier"]
            
            # Limitar volume máximo
            if config["max_volume"] > 0:
                volume = min(volume, config["max_volume"])
            
            # Determinar ação (compra/venda)
            if order_type == 0:  # BUY
                action = "SELL" if config["reverse_direction"] else "BUY"
            elif order_type == 1:  # SELL
                action = "BUY" if config["reverse_direction"] else "SELL"
            else:
                logger.warning(f"Tipo de ordem não suportado: {order_type}")
                return {"success": False, "error": f"Tipo de ordem não suportado: {order_type}"}
            
            # Ajustar SL/TP se necessário
            if not config["include_sl_tp"]:
                sl = 0.0
                tp = 0.0
            elif config["adjust_sl_tp_percent"] != 0.0:
                if sl != 0.0:
                    if action == "BUY":
                        sl = sl * (1 - config["adjust_sl_tp_percent"] / 100)
                    else:
                        sl = sl * (1 + config["adjust_sl_tp_percent"] / 100)
                
                if tp != 0.0:
                    if action == "BUY":
                        tp = tp * (1 + config["adjust_sl_tp_percent"] / 100)
                    else:
                        tp = tp * (1 - config["adjust_sl_tp_percent"] / 100)
            
            # Adicionar prefixo ao comentário para identificar ordens replicadas
            comment = f"REP:{order.get('ticket')}:{comment}"
            
            # Executar ordem na conta de destino
            result = target_backend.execute_order(
                action=action,
                symbol=symbol,
                volume=volume,
                sl=sl,
                tp=tp,
                comment=comment
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Erro ao replicar ordem: {e}")
            return {"success": False, "error": str(e)}
    
    def get_replication_status(self):
        """
        Obtém o status atual da replicação.
        
        Returns:
            dict: Status da replicação
        """
        with self.lock:
            status = {
                "running": self.running,
                "enabled": self.replication_config["enabled"],
                "queue_size": self.order_queue.qsize(),
                "processed_orders": len(self.processed_orders),
                "source_connected": self.mt5_backend_source and self.mt5_backend_source.check_connection(),
                "targets_connected": [target.check_connection() for target in self.mt5_backend_targets],
                "config": self.replication_config.copy()
            }
        
        return status
    
    def save_replication_config(self, file_path):
        """
        Salva a configuração de replicação em um arquivo JSON.
        
        Args:
            file_path (str): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for salva com sucesso, False caso contrário
        """
        try:
            with self.lock:
                config = self.replication_config.copy()
            
            with open(file_path, "w") as f:
                json.dump(config, f, indent=4)
            
            logger.info(f"Configuração de replicação salva em {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao salvar configuração de replicação: {e}")
            return False
    
    def load_replication_config(self, file_path):
        """
        Carrega a configuração de replicação de um arquivo JSON.
        
        Args:
            file_path (str): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for carregada com sucesso, False caso contrário
        """
        if not os.path.exists(file_path):
            logger.warning(f"Arquivo de configuração não encontrado: {file_path}")
            return False
        
        try:
            with open(file_path, "r") as f:
                config = json.load(f)
            
            with self.lock:
                self.replication_config.update(config)
            
            logger.info(f"Configuração de replicação carregada de {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao carregar configuração de replicação: {e}")
            return False


class MT5MultiAccountReplicator:
    """
    Classe para gerenciar replicação de ordens entre múltiplas contas do MetaTrader 5.
    """
    
    def __init__(self, auth_module=None):
        """
        Inicializa a classe MT5MultiAccountReplicator.
        
        Args:
            auth_module: Instância de MT5Auth para autenticação
        """
        self.auth_module = auth_module
        self.replicators = {}  # {source_account_id: MT5OrderReplicator}
        self.backends = {}  # {account_id: MT5Backend}
        self.replication_groups = {}  # {group_name: {source: account_id, targets: [account_id]}}
    
    def add_account(self, account_id, mt5_backend):
        """
        Adiciona uma conta ao replicador.
        
        Args:
            account_id (str): Identificador único da conta
            mt5_backend: Instância de MT5Backend para a conta
            
        Returns:
            bool: True se a conta for adicionada com sucesso, False caso contrário
        """
        if account_id in self.backends:
            logger.warning(f"Conta {account_id} já existe")
            return False
        
        self.backends[account_id] = mt5_backend
        logger.info(f"Conta {account_id} adicionada")
        return True
    
    def remove_account(self, account_id):
        """
        Remove uma conta do replicador.
        
        Args:
            account_id (str): Identificador único da conta
            
        Returns:
            bool: True se a conta for removida com sucesso, False caso contrário
        """
        if account_id not in self.backends:
            logger.warning(f"Conta {account_id} não existe")
            return False
        
        # Remover conta de todos os grupos de replicação
        for group_name, group in list(self.replication_groups.items()):
            if group["source"] == account_id:
                self.remove_replication_group(group_name)
            elif account_id in group["targets"]:
                self.remove_target_from_group(group_name, account_id)
        
        # Remover backend
        del self.backends[account_id]
        logger.info(f"Conta {account_id} removida")
        return True
    
    def create_replication_group(self, group_name, source_account_id, target_account_ids=None):
        """
        Cria um novo grupo de replicação.
        
        Args:
            group_name (str): Nome do grupo
            source_account_id (str): Identificador da conta de origem
            target_account_ids (list, optional): Lista de identificadores das contas de destino
            
        Returns:
            bool: True se o grupo for criado com sucesso, False caso contrário
        """
        if group_name in self.replication_groups:
            logger.warning(f"Grupo de replicação {group_name} já existe")
            return False
        
        if source_account_id not in self.backends:
            logger.error(f"Conta de origem {source_account_id} não existe")
            return False
        
        # Validar contas de destino
        target_account_ids = target_account_ids or []
        valid_targets = []
        for target_id in target_account_ids:
            if target_id not in self.backends:
                logger.warning(f"Conta de destino {target_id} não existe e será ignorada")
            elif target_id == source_account_id:
                logger.warning(f"Conta de destino {target_id} é igual à conta de origem e será ignorada")
            else:
                valid_targets.append(target_id)
        
        # Criar grupo
        self.replication_groups[group_name] = {
            "source": source_account_id,
            "targets": valid_targets
        }
        
        # Criar replicador se necessário
        if source_account_id not in self.replicators:
            replicator = MT5OrderReplicator(
                mt5_backend_source=self.backends[source_account_id],
                mt5_backend_targets=[self.backends[target_id] for target_id in valid_targets]
            )
            self.replicators[source_account_id] = replicator
        else:
            # Atualizar replicador existente
            replicator = self.replicators[source_account_id]
            for target_id in valid_targets:
                replicator.add_target_backend(self.backends[target_id])
        
        logger.info(f"Grupo de replicação {group_name} criado com {len(valid_targets)} contas de destino")
        return True
    
    def remove_replication_group(self, group_name):
        """
        Remove um grupo de replicação.
        
        Args:
            group_name (str): Nome do grupo
            
        Returns:
            bool: True se o grupo for removido com sucesso, False caso contrário
        """
        if group_name not in self.replication_groups:
            logger.warning(f"Grupo de replicação {group_name} não existe")
            return False
        
        # Obter dados do grupo
        group = self.replication_groups[group_name]
        source_account_id = group["source"]
        
        # Remover grupo
        del self.replication_groups[group_name]
        
        # Verificar se a conta de origem ainda é usada em outros grupos
        is_source_used = False
        for other_group in self.replication_groups.values():
            if other_group["source"] == source_account_id:
                is_source_used = True
                break
        
        # Se a conta de origem não é mais usada, parar e remover replicador
        if not is_source_used and source_account_id in self.replicators:
            replicator = self.replicators[source_account_id]
            if replicator.running:
                replicator.stop_replication()
            del self.replicators[source_account_id]
        
        logger.info(f"Grupo de replicação {group_name} removido")
        return True
    
    def add_target_to_group(self, group_name, target_account_id):
        """
        Adiciona uma conta de destino a um grupo de replicação.
        
        Args:
            group_name (str): Nome do grupo
            target_account_id (str): Identificador da conta de destino
            
        Returns:
            bool: True se a conta for adicionada com sucesso, False caso contrário
        """
        if group_name not in self.replication_groups:
            logger.error(f"Grupo de replicação {group_name} não existe")
            return False
        
        if target_account_id not in self.backends:
            logger.error(f"Conta de destino {target_account_id} não existe")
            return False
        
        group = self.replication_groups[group_name]
        
        if target_account_id == group["source"]:
            logger.error(f"Conta de destino {target_account_id} é igual à conta de origem")
            return False
        
        if target_account_id in group["targets"]:
            logger.warning(f"Conta de destino {target_account_id} já está no grupo {group_name}")
            return True
        
        # Adicionar conta ao grupo
        group["targets"].append(target_account_id)
        
        # Adicionar backend ao replicador
        source_account_id = group["source"]
        if source_account_id in self.replicators:
            replicator = self.replicators[source_account_id]
            replicator.add_target_backend(self.backends[target_account_id])
        
        logger.info(f"Conta de destino {target_account_id} adicionada ao grupo {group_name}")
        return True
    
    def remove_target_from_group(self, group_name, target_account_id):
        """
        Remove uma conta de destino de um grupo de replicação.
        
        Args:
            group_name (str): Nome do grupo
            target_account_id (str): Identificador da conta de destino
            
        Returns:
            bool: True se a conta for removida com sucesso, False caso contrário
        """
        if group_name not in self.replication_groups:
            logger.error(f"Grupo de replicação {group_name} não existe")
            return False
        
        group = self.replication_groups[group_name]
        
        if target_account_id not in group["targets"]:
            logger.warning(f"Conta de destino {target_account_id} não está no grupo {group_name}")
            return True
        
        # Remover conta do grupo
        group["targets"].remove(target_account_id)
        
        # Verificar se a conta de destino ainda é usada em outros grupos com a mesma origem
        source_account_id = group["source"]
        is_target_used = False
        for other_group in self.replication_groups.values():
            if other_group["source"] == source_account_id and target_account_id in other_group["targets"]:
                is_target_used = True
                break
        
        # Se a conta de destino não é mais usada com esta origem, remover do replicador
        if not is_target_used and source_account_id in self.replicators:
            replicator = self.replicators[source_account_id]
            if target_account_id in self.backends:
                replicator.remove_target_backend(self.backends[target_account_id])
        
        logger.info(f"Conta de destino {target_account_id} removida do grupo {group_name}")
        return True
    
    def set_group_config(self, group_name, config):
        """
        Define a configuração de replicação para um grupo.
        
        Args:
            group_name (str): Nome do grupo
            config (dict): Configuração de replicação
            
        Returns:
            bool: True se a configuração for definida com sucesso, False caso contrário
        """
        if group_name not in self.replication_groups:
            logger.error(f"Grupo de replicação {group_name} não existe")
            return False
        
        group = self.replication_groups[group_name]
        source_account_id = group["source"]
        
        if source_account_id not in self.replicators:
            logger.error(f"Replicador para conta {source_account_id} não existe")
            return False
        
        # Definir configuração
        replicator = self.replicators[source_account_id]
        replicator.set_replication_config(config)
        
        logger.info(f"Configuração definida para o grupo {group_name}")
        return True
    
    def get_group_config(self, group_name):
        """
        Obtém a configuração de replicação de um grupo.
        
        Args:
            group_name (str): Nome do grupo
            
        Returns:
            dict: Configuração de replicação ou None em caso de erro
        """
        if group_name not in self.replication_groups:
            logger.error(f"Grupo de replicação {group_name} não existe")
            return None
        
        group = self.replication_groups[group_name]
        source_account_id = group["source"]
        
        if source_account_id not in self.replicators:
            logger.error(f"Replicador para conta {source_account_id} não existe")
            return None
        
        # Obter configuração
        replicator = self.replicators[source_account_id]
        return replicator.get_replication_config()
    
    def start_replication(self, group_name):
        """
        Inicia a replicação para um grupo.
        
        Args:
            group_name (str): Nome do grupo
            
        Returns:
            bool: True se a replicação for iniciada com sucesso, False caso contrário
        """
        if group_name not in self.replication_groups:
            logger.error(f"Grupo de replicação {group_name} não existe")
            return False
        
        group = self.replication_groups[group_name]
        source_account_id = group["source"]
        
        if source_account_id not in self.replicators:
            logger.error(f"Replicador para conta {source_account_id} não existe")
            return False
        
        # Iniciar replicação
        replicator = self.replicators[source_account_id]
        return replicator.start_replication()
    
    def stop_replication(self, group_name):
        """
        Para a replicação para um grupo.
        
        Args:
            group_name (str): Nome do grupo
            
        Returns:
            bool: True se a replicação for parada com sucesso, False caso contrário
        """
        if group_name not in self.replication_groups:
            logger.error(f"Grupo de replicação {group_name} não existe")
            return False
        
        group = self.replication_groups[group_name]
        source_account_id = group["source"]
        
        if source_account_id not in self.replicators:
            logger.error(f"Replicador para conta {source_account_id} não existe")
            return False
        
        # Verificar se a conta de origem é usada em outros grupos ativos
        is_source_active = False
        for other_group_name, other_group in self.replication_groups.items():
            if other_group_name != group_name and other_group["source"] == source_account_id:
                # Verificar se o outro grupo está ativo
                other_config = self.get_group_config(other_group_name)
                if other_config and other_config.get("enabled", False):
                    is_source_active = True
                    break
        
        # Se a conta de origem não é usada em outros grupos ativos, parar replicação
        replicator = self.replicators[source_account_id]
        if not is_source_active:
            return replicator.stop_replication()
        else:
            # Apenas desativar a replicação para este grupo
            config = replicator.get_replication_config()
            config["enabled"] = False
            replicator.set_replication_config(config)
            logger.info(f"Replicação desativada para o grupo {group_name}, mas o replicador continua ativo para outros grupos")
            return True
    
    def get_replication_status(self, group_name=None):
        """
        Obtém o status da replicação.
        
        Args:
            group_name (str, optional): Nome do grupo
            
        Returns:
            dict: Status da replicação ou None em caso de erro
        """
        if group_name:
            if group_name not in self.replication_groups:
                logger.error(f"Grupo de replicação {group_name} não existe")
                return None
            
            group = self.replication_groups[group_name]
            source_account_id = group["source"]
            
            if source_account_id not in self.replicators:
                logger.error(f"Replicador para conta {source_account_id} não existe")
                return None
            
            # Obter status
            replicator = self.replicators[source_account_id]
            status = replicator.get_replication_status()
            status["group"] = group_name
            status["source"] = source_account_id
            status["targets"] = group["targets"]
            
            return status
        else:
            # Obter status de todos os grupos
            all_status = {}
            for group_name in self.replication_groups:
                all_status[group_name] = self.get_replication_status(group_name)
            
            return all_status
    
    def save_configuration(self, file_path):
        """
        Salva a configuração completa do replicador em um arquivo JSON.
        
        Args:
            file_path (str): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for salva com sucesso, False caso contrário
        """
        try:
            # Preparar configuração
            config = {
                "groups": self.replication_groups,
                "group_configs": {}
            }
            
            # Adicionar configurações de cada grupo
            for group_name in self.replication_groups:
                group_config = self.get_group_config(group_name)
                if group_config:
                    config["group_configs"][group_name] = group_config
            
            # Salvar em arquivo
            with open(file_path, "w") as f:
                json.dump(config, f, indent=4)
            
            logger.info(f"Configuração salva em {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}")
            return False
    
    def load_configuration(self, file_path):
        """
        Carrega a configuração completa do replicador de um arquivo JSON.
        
        Args:
            file_path (str): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for carregada com sucesso, False caso contrário
        """
        if not os.path.exists(file_path):
            logger.warning(f"Arquivo de configuração não encontrado: {file_path}")
            return False
        
        try:
            # Carregar configuração
            with open(file_path, "r") as f:
                config = json.load(f)
            
            # Verificar formato
            if "groups" not in config:
                logger.error("Formato de configuração inválido")
                return False
            
            # Parar todos os replicadores ativos
            for replicator in self.replicators.values():
                if replicator.running:
                    replicator.stop_replication()
            
            # Limpar configuração atual
            self.replication_groups = {}
            self.replicators = {}
            
            # Recriar grupos
            for group_name, group in config["groups"].items():
                source_account_id = group["source"]
                target_account_ids = group["targets"]
                
                # Verificar se as contas existem
                if source_account_id not in self.backends:
                    logger.warning(f"Conta de origem {source_account_id} não existe e será ignorada")
                    continue
                
                # Criar grupo
                self.create_replication_group(group_name, source_account_id, target_account_ids)
                
                # Aplicar configuração
                if "group_configs" in config and group_name in config["group_configs"]:
                    self.set_group_config(group_name, config["group_configs"][group_name])
            
            logger.info(f"Configuração carregada de {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao carregar configuração: {e}")
            return False


# Exemplo de uso
if __name__ == "__main__":
    # Importar módulos necessários
    import sys
    sys.path.append('.')
    from mt5_backend import MT5Backend
    from mt5_auth import MT5Auth
    
    # Criar instância de autenticação
    auth = MT5Auth()
    
    # Criar instância do replicador multi-conta
    replicator = MT5MultiAccountReplicator(auth)
    
    # Criar backends para as contas
    source_backend = MT5Backend()
    target_backend = MT5Backend()
    
    # Conectar às contas
    if source_backend.connect(12345678, "senha_origem", "MetaQuotes-Demo", "DEMO"):
        print("Conta de origem conectada com sucesso!")
        
        if target_backend.connect(87654321, "senha_destino", "MetaQuotes-Demo", "DEMO"):
            print("Conta de destino conectada com sucesso!")
            
            # Adicionar contas ao replicador
            replicator.add_account("demo_origem", source_backend)
            replicator.add_account("demo_destino", target_backend)
            
            # Criar grupo de replicação
            replicator.create_replication_group("grupo_demo", "demo_origem", ["demo_destino"])
            
            # Configurar replicação
            config = {
                "volume_multiplier": 0.5,  # Replicar com metade do volume
                "reverse_direction": False,
                "symbols_filter": ["EURUSD", "GBPUSD"],  # Apenas estes símbolos
                "max_volume": 1.0,  # Volume máximo de 1 lote
                "include_sl_tp": True,  # Incluir Stop Loss e Take Profit
                "delay_seconds": 1  # Atraso de 1 segundo
            }
            replicator.set_group_config("grupo_demo", config)
            
            # Iniciar replicação
            if replicator.start_replication("grupo_demo"):
                print("Replicação iniciada com sucesso!")
                
                # Aguardar algum tempo
                import time
                time.sleep(60)
                
                # Verificar status
                status = replicator.get_replication_status("grupo_demo")
                print(f"Status da replicação: {status}")
                
                # Parar replicação
                replicator.stop_replication("grupo_demo")
                print("Replicação parada")
            else:
                print("Falha ao iniciar replicação!")
            
            # Desconectar
            source_backend.disconnect()
            target_backend.disconnect()
        else:
            print("Falha ao conectar à conta de destino!")
    else:
        print("Falha ao conectar à conta de origem!")
