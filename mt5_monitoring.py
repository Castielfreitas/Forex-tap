#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sistema de Monitoramento 24/7 para MT5 Tape Reading EA
=====================================================

Este script implementa um sistema de monitoramento 24/7 para o MT5 Tape Reading EA,
garantindo que o sistema esteja sempre funcionando corretamente e alertando sobre
quaisquer problemas.

Funcionalidades:
- Monitoramento contínuo do status do EA
- Verificação de conectividade com o MT5
- Monitoramento de recursos do sistema (CPU, memória, disco)
- Detecção de falhas e erros
- Alertas em tempo real (e-mail, Telegram, SMS)
- Dashboard de monitoramento web
- Reinicialização automática em caso de falhas
- Logs detalhados para análise posterior

Autor: Manus AI
Data: 06/04/2025
"""

import os
import sys
import time
import datetime
import logging
import json
import threading
import queue
import socket
import subprocess
import psutil
import requests
import schedule
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Union, Any
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import MetaTrader5 as mt5

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("monitoring_system.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5MonitoringSystem")

class MonitoringConfig:
    """Classe para gerenciar configurações de monitoramento"""
    
    def __init__(self, config_file: str = "monitoring_config.json"):
        """Inicializa a configuração de monitoramento"""
        self.config_file = config_file
        self.config = self._load_config()
        
    def _load_config(self) -> Dict:
        """Carrega configuração do arquivo JSON"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            else:
                # Configuração padrão
                default_config = {
                    "monitoring": {
                        "enabled": True,
                        "check_interval": 60,  # segundos
                        "mt5": {
                            "enabled": True,
                            "connection_check": {
                                "enabled": True,
                                "interval": 60,  # segundos
                                "timeout": 30,  # segundos
                                "retry_count": 3
                            },
                            "ea_check": {
                                "enabled": True,
                                "interval": 120,  # segundos
                                "magic_numbers": [123456]
                            },
                            "order_check": {
                                "enabled": True,
                                "interval": 300,  # segundos
                                "max_inactive_time": 3600  # segundos
                            }
                        },
                        "system": {
                            "enabled": True,
                            "cpu_check": {
                                "enabled": True,
                                "interval": 60,  # segundos
                                "threshold": 90  # percentual
                            },
                            "memory_check": {
                                "enabled": True,
                                "interval": 60,  # segundos
                                "threshold": 90  # percentual
                            },
                            "disk_check": {
                                "enabled": True,
                                "interval": 300,  # segundos
                                "threshold": 90  # percentual
                            },
                            "network_check": {
                                "enabled": True,
                                "interval": 60,  # segundos
                                "hosts": ["8.8.8.8", "1.1.1.1"]
                            }
                        },
                        "process_check": {
                            "enabled": True,
                            "interval": 60,  # segundos
                            "processes": ["terminal64.exe", "python3", "mt5_tape_reading_ea.py"]
                        }
                    },
                    "alerts": {
                        "enabled": True,
                        "email": {
                            "enabled": True,
                            "smtp_server": "",
                            "smtp_port": 587,
                            "username": "",
                            "password": "",
                            "from": "",
                            "to": []
                        },
                        "telegram": {
                            "enabled": True,
                            "token": "",
                            "chat_id": ""
                        },
                        "sms": {
                            "enabled": False,
                            "provider": "twilio",
                            "account_sid": "",
                            "auth_token": "",
                            "from_number": "",
                            "to_numbers": []
                        },
                        "webhook": {
                            "enabled": False,
                            "url": "",
                            "method": "POST",
                            "headers": {}
                        },
                        "throttling": {
                            "enabled": True,
                            "min_interval": 300,  # segundos
                            "max_alerts_per_hour": 10
                        }
                    },
                    "actions": {
                        "auto_restart": {
                            "enabled": True,
                            "conditions": {
                                "connection_lost": True,
                                "ea_not_running": True,
                                "high_cpu_usage": False,
                                "high_memory_usage": False
                            },
                            "max_restarts_per_day": 5
                        },
                        "auto_recovery": {
                            "enabled": True,
                            "scripts": {
                                "restart_mt5": "/home/ubuntu/scripts/restart_mt5.sh",
                                "restart_ea": "/home/ubuntu/scripts/restart_ea.sh",
                                "restart_system": "/home/ubuntu/scripts/restart_system.sh"
                            }
                        }
                    },
                    "dashboard": {
                        "enabled": True,
                        "port": 5000,
                        "host": "0.0.0.0",
                        "refresh_interval": 5,  # segundos
                        "history_retention": 7,  # dias
                        "authentication": {
                            "enabled": True,
                            "username": "admin",
                            "password": "admin"
                        }
                    }
                }
                
                # Salva a configuração padrão
                with open(self.config_file, 'w') as f:
                    json.dump(default_config, f, indent=4)
                
                return default_config
        except Exception as e:
            logger.error(f"Erro ao carregar configuração: {e}")
            raise
    
    def save_config(self) -> None:
        """Salva a configuração atual no arquivo JSON"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.info(f"Configuração salva em {self.config_file}")
        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}")
            raise
    
    def get_config(self) -> Dict:
        """Retorna a configuração atual"""
        return self.config
    
    def update_config(self, new_config: Dict) -> None:
        """Atualiza a configuração com novos valores"""
        self.config = new_config
        self.save_config()
        logger.info("Configuração atualizada")

class MT5Monitor:
    """Classe para monitorar o MetaTrader 5"""
    
    def __init__(self, config: Dict):
        """Inicializa o monitor do MT5"""
        self.config = config
        self.mt5_config = config["monitoring"]["mt5"]
        self.enabled = self.mt5_config["enabled"]
        self.connection_status = False
        self.ea_status = False
        self.last_order_time = None
        self.last_check_time = datetime.datetime.now()
        self.retry_count = 0
        self.max_retry_count = self.mt5_config["connection_check"]["retry_count"]
        
    def check_connection(self) -> bool:
        """Verifica a conexão com o MT5"""
        if not self.enabled or not self.mt5_config["connection_check"]["enabled"]:
            return True
        
        try:
            # Tenta inicializar o MT5
            if not mt5.initialize():
                logger.error(f"Falha ao inicializar o MT5: {mt5.last_error()}")
                self.connection_status = False
                self.retry_count += 1
                
                if self.retry_count >= self.max_retry_count:
                    logger.critical(f"Falha na conexão com o MT5 após {self.retry_count} tentativas")
                    return False
                
                return False
            
            # Verifica se está conectado ao servidor
            if not mt5.terminal_info().connected:
                logger.error("MT5 não está conectado ao servidor")
                self.connection_status = False
                self.retry_count += 1
                
                if self.retry_count >= self.max_retry_count:
                    logger.critical(f"MT5 não conectado ao servidor após {self.retry_count} tentativas")
                    return False
                
                return False
            
            # Conexão bem-sucedida
            self.connection_status = True
            self.retry_count = 0
            logger.info("Conexão com o MT5 verificada com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao verificar conexão com o MT5: {e}")
            self.connection_status = False
            self.retry_count += 1
            
            if self.retry_count >= self.max_retry_count:
                logger.critical(f"Erro na verificação de conexão com o MT5 após {self.retry_count} tentativas")
                return False
            
            return False
    
    def check_ea_running(self) -> bool:
        """Verifica se o EA está em execução"""
        if not self.enabled or not self.mt5_config["ea_check"]["enabled"]:
            return True
        
        try:
            if not self.connection_status:
                if not self.check_connection():
                    logger.error("Não é possível verificar o EA sem conexão com o MT5")
                    return False
            
            # Verifica se há posições abertas com o magic number do EA
            magic_numbers = self.mt5_config["ea_check"]["magic_numbers"]
            positions = mt5.positions_get()
            
            if positions is None:
                positions = []
            
            # Verifica se há ordens pendentes com o magic number do EA
            orders = mt5.orders_get()
            
            if orders is None:
                orders = []
            
            # Verifica se o EA está ativo através de magic numbers
            ea_active = False
            
            for magic in magic_numbers:
                for position in positions:
                    if position.magic == magic:
                        ea_active = True
                        break
                
                if ea_active:
                    break
                
                for order in orders:
                    if order.magic == magic:
                        ea_active = True
                        break
                
                if ea_active:
                    break
            
            # Verifica através de outros métodos se o EA está ativo
            if not ea_active:
                # Verifica se o EA está na lista de programas em execução
                programs = mt5.terminal_info().experts
                
                if programs > 0:
                    ea_active = True
            
            self.ea_status = ea_active
            
            if ea_active:
                logger.info("EA verificado e está em execução")
            else:
                logger.warning("EA não parece estar em execução")
            
            return ea_active
        except Exception as e:
            logger.error(f"Erro ao verificar se o EA está em execução: {e}")
            return False
    
    def check_order_activity(self) -> bool:
        """Verifica se houve atividade de ordens recentemente"""
        if not self.enabled or not self.mt5_config["order_check"]["enabled"]:
            return True
        
        try:
            if not self.connection_status:
                if not self.check_connection():
                    logger.error("Não é possível verificar atividade de ordens sem conexão com o MT5")
                    return False
            
            # Obtém o histórico de ordens recente
            from_date = datetime.datetime.now() - datetime.timedelta(days=1)
            history_orders = mt5.history_orders_get(from_date, datetime.datetime.now())
            
            if history_orders is None or len(history_orders) == 0:
                # Nenhuma ordem recente
                if self.last_order_time is None:
                    # Primeira verificação, define o tempo atual
                    self.last_order_time = datetime.datetime.now()
                    return True
                
                # Verifica se passou muito tempo desde a última ordem
                max_inactive_time = self.mt5_config["order_check"]["max_inactive_time"]
                time_since_last_order = (datetime.datetime.now() - self.last_order_time).total_seconds()
                
                if time_since_last_order > max_inactive_time:
                    logger.warning(f"Nenhuma atividade de ordens nas últimas {time_since_last_order:.0f} segundos")
                    return False
                
                return True
            
            # Atualiza o tempo da última ordem
            latest_order_time = max(order.time_done for order in history_orders if order.time_done)
            self.last_order_time = datetime.datetime.fromtimestamp(latest_order_time)
            
            logger.info(f"Última atividade de ordem detectada em {self.last_order_time}")
            return True
        except Exception as e:
            logger.error(f"Erro ao verificar atividade de ordens: {e}")
            return True  # Retorna True em caso de erro para evitar falsos positivos
    
    def get_account_info(self) -> Dict:
        """Obtém informações da conta"""
        try:
            if not self.connection_status:
                if not self.check_connection():
                    logger.error("Não é possível obter informações da conta sem conexão com o MT5")
                    return {}
            
            account_info = mt5.account_info()
            
            if account_info is None:
                logger.error("Não foi possível obter informações da conta")
                return {}
            
            # Converte para dicionário
            info = {
                "login": account_info.login,
                "server": account_info.server,
                "balance": account_info.balance,
                "equity": account_info.equity,
                "margin": account_info.margin,
                "margin_free": account_info.margin_free,
                "margin_level": account_info.margin_level,
                "currency": account_info.currency
            }
            
            return info
        except Exception as e:
            logger.error(f"Erro ao obter informações da conta: {e}")
            return {}
    
    def get_positions(self) -> List[Dict]:
        """Obtém posições abertas"""
        try:
            if not self.connection_status:
                if not self.check_connection():
                    logger.error("Não é possível obter posições sem conexão com o MT5")
                    return []
            
            positions = mt5.positions_get()
            
            if positions is None:
                return []
            
            # Converte para lista de dicionários
            positions_list = []
            for position in positions:
                pos = {
                    "ticket": position.ticket,
                    "symbol": position.symbol,
                    "type": "BUY" if position.type == 0 else "SELL",
                    "volume": position.volume,
                    "open_price": position.price_open,
                    "current_price": position.price_current,
                    "sl": position.sl,
                    "tp": position.tp,
                    "profit": position.profit,
                    "swap": position.swap,
                    "time": datetime.datetime.fromtimestamp(position.time).strftime("%Y-%m-%d %H:%M:%S")
                }
                positions_list.append(pos)
            
            return positions_list
        except Exception as e:
            logger.error(f"Erro ao obter posições: {e}")
            return []
    
    def get_orders(self) -> List[Dict]:
        """Obtém ordens pendentes"""
        try:
            if not self.connection_status:
                if not self.check_connection():
                    logger.error("Não é possível obter ordens sem conexão com o MT5")
                    return []
            
            orders = mt5.orders_get()
            
            if orders is None:
                return []
            
            # Converte para lista de dicionários
            orders_list = []
            for order in orders:
                ord = {
                    "ticket": order.ticket,
                    "symbol": order.symbol,
                    "type": order.type,
                    "volume": order.volume_initial,
                    "price": order.price_open,
                    "sl": order.sl,
                    "tp": order.tp,
                    "time_setup": datetime.datetime.fromtimestamp(order.time_setup).strftime("%Y-%m-%d %H:%M:%S")
                }
                orders_list.append(ord)
            
            return orders_list
        except Exception as e:
            logger.error(f"Erro ao obter ordens: {e}")
            return []
    
    def get_history(self, days: int = 7) -> List[Dict]:
        """Obtém histórico de ordens"""
        try:
            if not self.connection_status:
                if not self.check_connection():
                    logger.error("Não é possível obter histórico sem conexão com o MT5")
                    return []
            
            from_date = datetime.datetime.now() - datetime.timedelta(days=days)
            history = mt5.history_orders_get(from_date, datetime.datetime.now())
            
            if history is None:
                return []
            
            # Converte para lista de dicionários
            history_list = []
            for order in history:
                hist = {
                    "ticket": order.ticket,
                    "symbol": order.symbol,
                    "type": order.type,
                    "volume": order.volume_initial,
                    "price_open": order.price_open,
                    "price_close": order.price_current,
                    "sl": order.sl,
                    "tp": order.tp,
                    "profit": order.profit,
                    "time_setup": datetime.datetime.fromtimestamp(order.time_setup).strftime("%Y-%m-%d %H:%M:%S"),
                    "time_done": datetime.datetime.fromtimestamp(order.time_done).strftime("%Y-%m-%d %H:%M:%S") if order.time_done else None,
                    "state": order.state
                }
                history_list.append(hist)
            
            return history_list
        except Exception as e:
            logger.error(f"Erro ao obter histórico: {e}")
            return []
    
    def shutdown(self) -> None:
        """Encerra a conexão com o MT5"""
        try:
            mt5.shutdown()
            logger.info("Conexão com o MT5 encerrada")
        except Exception as e:
            logger.error(f"Erro ao encerrar conexão com o MT5: {e}")

class SystemMonitor:
    """Classe para monitorar recursos do sistema"""
    
    def __init__(self, config: Dict):
        """Inicializa o monitor do sistema"""
        self.config = config
        self.system_config = config["monitoring"]["system"]
        self.enabled = self.system_config["enabled"]
        self.last_check_time = datetime.datetime.now()
        
    def check_cpu(self) -> Tuple[bool, float]:
        """Verifica o uso de CPU"""
        if not self.enabled or not self.system_config["cpu_check"]["enabled"]:
            return True, 0.0
        
        try:
            # Obtém o uso de CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            threshold = self.system_config["cpu_check"]["threshold"]
            
            if cpu_percent > threshold:
                logger.warning(f"Uso de CPU alto: {cpu_percent}% (limite: {threshold}%)")
                return False, cpu_percent
            
            logger.info(f"Uso de CPU: {cpu_percent}%")
            return True, cpu_percent
        except Exception as e:
            logger.error(f"Erro ao verificar uso de CPU: {e}")
            return True, 0.0
    
    def check_memory(self) -> Tuple[bool, float]:
        """Verifica o uso de memória"""
        if not self.enabled or not self.system_config["memory_check"]["enabled"]:
            return True, 0.0
        
        try:
            # Obtém o uso de memória
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            threshold = self.system_config["memory_check"]["threshold"]
            
            if memory_percent > threshold:
                logger.warning(f"Uso de memória alto: {memory_percent}% (limite: {threshold}%)")
                return False, memory_percent
            
            logger.info(f"Uso de memória: {memory_percent}%")
            return True, memory_percent
        except Exception as e:
            logger.error(f"Erro ao verificar uso de memória: {e}")
            return True, 0.0
    
    def check_disk(self) -> Tuple[bool, float]:
        """Verifica o uso de disco"""
        if not self.enabled or not self.system_config["disk_check"]["enabled"]:
            return True, 0.0
        
        try:
            # Obtém o uso de disco
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            threshold = self.system_config["disk_check"]["threshold"]
            
            if disk_percent > threshold:
                logger.warning(f"Uso de disco alto: {disk_percent}% (limite: {threshold}%)")
                return False, disk_percent
            
            logger.info(f"Uso de disco: {disk_percent}%")
            return True, disk_percent
        except Exception as e:
            logger.error(f"Erro ao verificar uso de disco: {e}")
            return True, 0.0
    
    def check_network(self) -> Tuple[bool, Dict]:
        """Verifica a conectividade de rede"""
        if not self.enabled or not self.system_config["network_check"]["enabled"]:
            return True, {}
        
        try:
            hosts = self.system_config["network_check"]["hosts"]
            results = {}
            all_ok = True
            
            for host in hosts:
                try:
                    # Ping o host
                    response = subprocess.run(
                        ["ping", "-c", "1", "-W", "2", host],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False
                    )
                    
                    if response.returncode == 0:
                        # Extrai o tempo de resposta
                        import re
                        match = re.search(r"time=(\d+\.\d+)", response.stdout)
                        if match:
                            ping_time = float(match.group(1))
                        else:
                            ping_time = 0.0
                        
                        results[host] = {
                            "status": "ok",
                            "ping": ping_time
                        }
                    else:
                        results[host] = {
                            "status": "failed",
                            "ping": None
                        }
                        all_ok = False
                except Exception as e:
                    results[host] = {
                        "status": "error",
                        "ping": None,
                        "error": str(e)
                    }
                    all_ok = False
            
            if not all_ok:
                logger.warning(f"Problemas de conectividade de rede detectados: {results}")
            else:
                logger.info(f"Conectividade de rede OK")
            
            return all_ok, results
        except Exception as e:
            logger.error(f"Erro ao verificar conectividade de rede: {e}")
            return True, {}
    
    def check_processes(self) -> Tuple[bool, Dict]:
        """Verifica se os processos necessários estão em execução"""
        if not self.config["monitoring"]["process_check"]["enabled"]:
            return True, {}
        
        try:
            processes = self.config["monitoring"]["process_check"]["processes"]
            results = {}
            all_ok = True
            
            for proc_name in processes:
                found = False
                
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        # Verifica se o nome do processo corresponde
                        if proc_name.lower() in proc.info['name'].lower():
                            found = True
                            results[proc_name] = {
                                "status": "running",
                                "pid": proc.info['pid']
                            }
                            break
                        
                        # Verifica se o processo está na linha de comando
                        if proc.info['cmdline']:
                            cmdline = ' '.join(proc.info['cmdline']).lower()
                            if proc_name.lower() in cmdline:
                                found = True
                                results[proc_name] = {
                                    "status": "running",
                                    "pid": proc.info['pid']
                                }
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
                
                if not found:
                    results[proc_name] = {
                        "status": "not_running",
                        "pid": None
                    }
                    all_ok = False
            
            if not all_ok:
                logger.warning(f"Alguns processos necessários não estão em execução: {results}")
            else:
                logger.info(f"Todos os processos necessários estão em execução")
            
            return all_ok, results
        except Exception as e:
            logger.error(f"Erro ao verificar processos: {e}")
            return True, {}
    
    def get_system_info(self) -> Dict:
        """Obtém informações do sistema"""
        try:
            # Informações de CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            
            # Informações de memória
            memory = psutil.virtual_memory()
            
            # Informações de disco
            disk = psutil.disk_usage('/')
            
            # Informações de rede
            net_io = psutil.net_io_counters()
            
            # Informações do sistema
            boot_time = datetime.datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
            
            # Monta o dicionário de informações
            info = {
                "cpu": {
                    "percent": cpu_percent,
                    "count": cpu_count,
                    "freq_current": cpu_freq.current if cpu_freq else None,
                    "freq_max": cpu_freq.max if cpu_freq else None
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "used": memory.used,
                    "percent": memory.percent
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                },
                "network": {
                    "bytes_sent": net_io.bytes_sent,
                    "bytes_recv": net_io.bytes_recv,
                    "packets_sent": net_io.packets_sent,
                    "packets_recv": net_io.packets_recv
                },
                "system": {
                    "boot_time": boot_time,
                    "uptime": (datetime.datetime.now() - datetime.datetime.fromtimestamp(psutil.boot_time())).total_seconds()
                }
            }
            
            return info
        except Exception as e:
            logger.error(f"Erro ao obter informações do sistema: {e}")
            return {}

class AlertManager:
    """Classe para gerenciar alertas"""
    
    def __init__(self, config: Dict):
        """Inicializa o gerenciador de alertas"""
        self.config = config
        self.alerts_config = config["alerts"]
        self.enabled = self.alerts_config["enabled"]
        self.last_alerts = {}
        self.alert_count = {}
        self.last_hour = datetime.datetime.now().hour
        
    def send_alert(self, message: str, level: str = "warning", source: str = "system") -> bool:
        """Envia um alerta"""
        if not self.enabled:
            return False
        
        try:
            # Verifica throttling
            if self.alerts_config["throttling"]["enabled"]:
                # Verifica intervalo mínimo entre alertas do mesmo tipo
                alert_key = f"{source}:{level}"
                current_time = datetime.datetime.now()
                
                if alert_key in self.last_alerts:
                    time_diff = (current_time - self.last_alerts[alert_key]).total_seconds()
                    min_interval = self.alerts_config["throttling"]["min_interval"]
                    
                    if time_diff < min_interval:
                        logger.info(f"Alerta ignorado devido ao throttling (intervalo mínimo): {message}")
                        return False
                
                # Verifica número máximo de alertas por hora
                current_hour = current_time.hour
                
                if current_hour != self.last_hour:
                    # Hora mudou, reseta contadores
                    self.alert_count = {}
                    self.last_hour = current_hour
                
                if alert_key not in self.alert_count:
                    self.alert_count[alert_key] = 0
                
                self.alert_count[alert_key] += 1
                max_alerts = self.alerts_config["throttling"]["max_alerts_per_hour"]
                
                if self.alert_count[alert_key] > max_alerts:
                    logger.info(f"Alerta ignorado devido ao throttling (máximo por hora): {message}")
                    return False
                
                # Atualiza o timestamp do último alerta
                self.last_alerts[alert_key] = current_time
            
            # Formata a mensagem
            formatted_message = f"[{level.upper()}] {source}: {message}"
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            full_message = f"{timestamp} - {formatted_message}"
            
            # Envia alertas pelos canais configurados
            success = False
            
            if self.alerts_config["email"]["enabled"]:
                email_success = self._send_email_alert(full_message, level)
                success = success or email_success
            
            if self.alerts_config["telegram"]["enabled"]:
                telegram_success = self._send_telegram_alert(full_message, level)
                success = success or telegram_success
            
            if self.alerts_config["sms"]["enabled"]:
                sms_success = self._send_sms_alert(full_message, level)
                success = success or sms_success
            
            if self.alerts_config["webhook"]["enabled"]:
                webhook_success = self._send_webhook_alert(full_message, level, source)
                success = success or webhook_success
            
            if success:
                logger.info(f"Alerta enviado: {formatted_message}")
            else:
                logger.warning(f"Falha ao enviar alerta: {formatted_message}")
            
            return success
        except Exception as e:
            logger.error(f"Erro ao enviar alerta: {e}")
            return False
    
    def _send_email_alert(self, message: str, level: str) -> bool:
        """Envia alerta por e-mail"""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        email_config = self.alerts_config["email"]
        
        smtp_server = email_config["smtp_server"]
        smtp_port = email_config["smtp_port"]
        username = email_config["username"]
        password = email_config["password"]
        sender = email_config["from"]
        recipients = email_config["to"]
        
        if not smtp_server or not username or not password or not sender or not recipients:
            logger.error("Configuração de e-mail incompleta")
            return False
        
        try:
            # Cria a mensagem
            msg = MIMEMultipart()
            msg['From'] = sender
            msg['To'] = ', '.join(recipients)
            
            if level.lower() == "critical":
                msg['Subject'] = "ALERTA CRÍTICO - MT5 Tape Reading EA"
            elif level.lower() == "error":
                msg['Subject'] = "ERRO - MT5 Tape Reading EA"
            elif level.lower() == "warning":
                msg['Subject'] = "Aviso - MT5 Tape Reading EA"
            else:
                msg['Subject'] = "Informação - MT5 Tape Reading EA"
            
            msg.attach(MIMEText(message, 'plain'))
            
            # Envia o e-mail
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
            
            logger.info(f"Alerta por e-mail enviado para {', '.join(recipients)}")
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar alerta por e-mail: {e}")
            return False
    
    def _send_telegram_alert(self, message: str, level: str) -> bool:
        """Envia alerta pelo Telegram"""
        telegram_config = self.alerts_config["telegram"]
        
        token = telegram_config["token"]
        chat_id = telegram_config["chat_id"]
        
        if not token or not chat_id:
            logger.error("Configuração do Telegram incompleta")
            return False
        
        try:
            # Formata a mensagem
            if level.lower() == "critical":
                formatted_message = f"🚨 *ALERTA CRÍTICO*\n\n{message}"
            elif level.lower() == "error":
                formatted_message = f"❌ *ERRO*\n\n{message}"
            elif level.lower() == "warning":
                formatted_message = f"⚠️ *AVISO*\n\n{message}"
            else:
                formatted_message = f"ℹ️ *INFORMAÇÃO*\n\n{message}"
            
            # Envia a mensagem
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": formatted_message,
                "parse_mode": "Markdown"
            }
            
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            logger.info(f"Alerta pelo Telegram enviado para chat_id {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar alerta pelo Telegram: {e}")
            return False
    
    def _send_sms_alert(self, message: str, level: str) -> bool:
        """Envia alerta por SMS"""
        sms_config = self.alerts_config["sms"]
        
        provider = sms_config["provider"]
        
        if provider.lower() == "twilio":
            return self._send_twilio_sms(message, level)
        else:
            logger.error(f"Provedor de SMS não suportado: {provider}")
            return False
    
    def _send_twilio_sms(self, message: str, level: str) -> bool:
        """Envia SMS via Twilio"""
        try:
            from twilio.rest import Client
            
            sms_config = self.alerts_config["sms"]
            
            account_sid = sms_config["account_sid"]
            auth_token = sms_config["auth_token"]
            from_number = sms_config["from_number"]
            to_numbers = sms_config["to_numbers"]
            
            if not account_sid or not auth_token or not from_number or not to_numbers:
                logger.error("Configuração do Twilio incompleta")
                return False
            
            # Cria o cliente Twilio
            client = Client(account_sid, auth_token)
            
            # Limita o tamanho da mensagem para SMS
            if len(message) > 160:
                message = message[:157] + "..."
            
            # Envia SMS para cada número
            success = False
            
            for to_number in to_numbers:
                try:
                    sms = client.messages.create(
                        body=message,
                        from_=from_number,
                        to=to_number
                    )
                    
                    logger.info(f"SMS enviado para {to_number}, SID: {sms.sid}")
                    success = True
                except Exception as e:
                    logger.error(f"Erro ao enviar SMS para {to_number}: {e}")
            
            return success
        except Exception as e:
            logger.error(f"Erro ao enviar SMS via Twilio: {e}")
            return False
    
    def _send_webhook_alert(self, message: str, level: str, source: str) -> bool:
        """Envia alerta via webhook"""
        webhook_config = self.alerts_config["webhook"]
        
        url = webhook_config["url"]
        method = webhook_config["method"]
        headers = webhook_config["headers"]
        
        if not url:
            logger.error("URL do webhook não configurada")
            return False
        
        try:
            # Prepara o payload
            payload = {
                "message": message,
                "level": level,
                "source": source,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            # Envia a requisição
            if method.upper() == "POST":
                response = requests.post(url, json=payload, headers=headers)
            elif method.upper() == "PUT":
                response = requests.put(url, json=payload, headers=headers)
            else:
                logger.error(f"Método HTTP não suportado: {method}")
                return False
            
            response.raise_for_status()
            
            logger.info(f"Alerta enviado via webhook para {url}")
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar alerta via webhook: {e}")
            return False

class ActionManager:
    """Classe para gerenciar ações automáticas"""
    
    def __init__(self, config: Dict):
        """Inicializa o gerenciador de ações"""
        self.config = config
        self.actions_config = config["actions"]
        self.auto_restart_enabled = self.actions_config["auto_restart"]["enabled"]
        self.auto_recovery_enabled = self.actions_config["auto_recovery"]["enabled"]
        self.restart_count = 0
        self.last_restart_day = datetime.datetime.now().day
        
    def handle_issue(self, issue_type: str, details: Dict = None) -> bool:
        """Trata um problema detectado"""
        if details is None:
            details = {}
        
        try:
            # Verifica se o dia mudou para resetar o contador de reinicializações
            current_day = datetime.datetime.now().day
            if current_day != self.last_restart_day:
                self.restart_count = 0
                self.last_restart_day = current_day
            
            # Verifica se o auto-restart está habilitado para este tipo de problema
            if self.auto_restart_enabled:
                conditions = self.actions_config["auto_restart"]["conditions"]
                
                if issue_type in conditions and conditions[issue_type]:
                    # Verifica se não excedeu o número máximo de reinicializações por dia
                    max_restarts = self.actions_config["auto_restart"]["max_restarts_per_day"]
                    
                    if self.restart_count >= max_restarts:
                        logger.warning(f"Número máximo de reinicializações por dia atingido ({max_restarts})")
                        return False
                    
                    # Executa a ação de recuperação
                    success = self._execute_recovery_action(issue_type, details)
                    
                    if success:
                        self.restart_count += 1
                        logger.info(f"Ação de recuperação executada com sucesso para {issue_type}")
                    else:
                        logger.error(f"Falha ao executar ação de recuperação para {issue_type}")
                    
                    return success
            
            return False
        except Exception as e:
            logger.error(f"Erro ao tratar problema {issue_type}: {e}")
            return False
    
    def _execute_recovery_action(self, issue_type: str, details: Dict) -> bool:
        """Executa uma ação de recuperação"""
        if not self.auto_recovery_enabled:
            return False
        
        try:
            scripts = self.actions_config["auto_recovery"]["scripts"]
            
            if issue_type == "connection_lost":
                script = scripts.get("restart_mt5")
                if script:
                    return self._run_script(script, details)
            elif issue_type == "ea_not_running":
                script = scripts.get("restart_ea")
                if script:
                    return self._run_script(script, details)
            elif issue_type == "high_cpu_usage" or issue_type == "high_memory_usage":
                # Tenta primeiro reiniciar o EA
                script = scripts.get("restart_ea")
                if script:
                    success = self._run_script(script, details)
                    if success:
                        return True
                
                # Se falhar, tenta reiniciar o MT5
                script = scripts.get("restart_mt5")
                if script:
                    return self._run_script(script, details)
            
            logger.warning(f"Nenhuma ação de recuperação definida para {issue_type}")
            return False
        except Exception as e:
            logger.error(f"Erro ao executar ação de recuperação: {e}")
            return False
    
    def _run_script(self, script_path: str, details: Dict) -> bool:
        """Executa um script de recuperação"""
        try:
            if not os.path.exists(script_path):
                logger.error(f"Script não encontrado: {script_path}")
                return False
            
            # Torna o script executável
            os.chmod(script_path, 0o755)
            
            # Executa o script
            process = subprocess.run(
                [script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if process.returncode == 0:
                logger.info(f"Script executado com sucesso: {script_path}")
                logger.debug(f"Saída: {process.stdout}")
                return True
            else:
                logger.error(f"Erro ao executar script {script_path}: {process.stderr}")
                return False
        except Exception as e:
            logger.error(f"Erro ao executar script {script_path}: {e}")
            return False

class MonitoringSystem:
    """Classe principal do sistema de monitoramento"""
    
    def __init__(self):
        """Inicializa o sistema de monitoramento"""
        self.config_manager = MonitoringConfig()
        self.config = self.config_manager.get_config()
        self.mt5_monitor = MT5Monitor(self.config)
        self.system_monitor = SystemMonitor(self.config)
        self.alert_manager = AlertManager(self.config)
        self.action_manager = ActionManager(self.config)
        self.monitoring_queue = queue.Queue()
        self.worker_thread = None
        self.running = False
        self.history_data = {
            "mt5": {
                "connection_status": [],
                "ea_status": [],
                "account_info": []
            },
            "system": {
                "cpu": [],
                "memory": [],
                "disk": []
            },
            "alerts": []
        }
        self.dashboard_app = None
        self.socketio = None
    
    def start(self) -> None:
        """Inicia o sistema de monitoramento"""
        if self.running:
            logger.warning("Sistema de monitoramento já está em execução")
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop)
        self.worker_thread.daemon = True
        self.worker_thread.start()
        
        self._schedule_checks()
        
        # Inicia o dashboard se estiver habilitado
        if self.config["dashboard"]["enabled"]:
            self._start_dashboard()
        
        logger.info("Sistema de monitoramento iniciado")
    
    def stop(self) -> None:
        """Para o sistema de monitoramento"""
        if not self.running:
            logger.warning("Sistema de monitoramento não está em execução")
            return
        
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5.0)
        
        # Encerra a conexão com o MT5
        self.mt5_monitor.shutdown()
        
        logger.info("Sistema de monitoramento parado")
    
    def _worker_loop(self) -> None:
        """Loop principal do worker thread"""
        while self.running:
            try:
                # Executa tarefas agendadas
                schedule.run_pending()
                
                # Processa tarefas da fila
                try:
                    task = self.monitoring_queue.get(block=False)
                    self._process_monitoring_task(task)
                    self.monitoring_queue.task_done()
                except queue.Empty:
                    pass
                
                # Aguarda um pouco para não consumir CPU
                time.sleep(1)
            except Exception as e:
                logger.error(f"Erro no worker loop: {e}")
    
    def _schedule_checks(self) -> None:
        """Agenda verificações periódicas"""
        # Verificação de conexão com o MT5
        if self.config["monitoring"]["mt5"]["enabled"] and self.config["monitoring"]["mt5"]["connection_check"]["enabled"]:
            interval = self.config["monitoring"]["mt5"]["connection_check"]["interval"]
            schedule.every(interval).seconds.do(self._check_mt5_connection)
            logger.info(f"Verificação de conexão com o MT5 agendada a cada {interval} segundos")
        
        # Verificação do EA
        if self.config["monitoring"]["mt5"]["enabled"] and self.config["monitoring"]["mt5"]["ea_check"]["enabled"]:
            interval = self.config["monitoring"]["mt5"]["ea_check"]["interval"]
            schedule.every(interval).seconds.do(self._check_ea_running)
            logger.info(f"Verificação do EA agendada a cada {interval} segundos")
        
        # Verificação de atividade de ordens
        if self.config["monitoring"]["mt5"]["enabled"] and self.config["monitoring"]["mt5"]["order_check"]["enabled"]:
            interval = self.config["monitoring"]["mt5"]["order_check"]["interval"]
            schedule.every(interval).seconds.do(self._check_order_activity)
            logger.info(f"Verificação de atividade de ordens agendada a cada {interval} segundos")
        
        # Verificação de CPU
        if self.config["monitoring"]["system"]["enabled"] and self.config["monitoring"]["system"]["cpu_check"]["enabled"]:
            interval = self.config["monitoring"]["system"]["cpu_check"]["interval"]
            schedule.every(interval).seconds.do(self._check_cpu)
            logger.info(f"Verificação de CPU agendada a cada {interval} segundos")
        
        # Verificação de memória
        if self.config["monitoring"]["system"]["enabled"] and self.config["monitoring"]["system"]["memory_check"]["enabled"]:
            interval = self.config["monitoring"]["system"]["memory_check"]["interval"]
            schedule.every(interval).seconds.do(self._check_memory)
            logger.info(f"Verificação de memória agendada a cada {interval} segundos")
        
        # Verificação de disco
        if self.config["monitoring"]["system"]["enabled"] and self.config["monitoring"]["system"]["disk_check"]["enabled"]:
            interval = self.config["monitoring"]["system"]["disk_check"]["interval"]
            schedule.every(interval).seconds.do(self._check_disk)
            logger.info(f"Verificação de disco agendada a cada {interval} segundos")
        
        # Verificação de rede
        if self.config["monitoring"]["system"]["enabled"] and self.config["monitoring"]["system"]["network_check"]["enabled"]:
            interval = self.config["monitoring"]["system"]["network_check"]["interval"]
            schedule.every(interval).seconds.do(self._check_network)
            logger.info(f"Verificação de rede agendada a cada {interval} segundos")
        
        # Verificação de processos
        if self.config["monitoring"]["process_check"]["enabled"]:
            interval = self.config["monitoring"]["process_check"]["interval"]
            schedule.every(interval).seconds.do(self._check_processes)
            logger.info(f"Verificação de processos agendada a cada {interval} segundos")
    
    def _process_monitoring_task(self, task: Dict) -> None:
        """Processa uma tarefa de monitoramento"""
        task_type = task.get("type")
        
        if task_type == "mt5_connection":
            self._process_mt5_connection_task(task)
        elif task_type == "ea_running":
            self._process_ea_running_task(task)
        elif task_type == "order_activity":
            self._process_order_activity_task(task)
        elif task_type == "cpu_check":
            self._process_cpu_check_task(task)
        elif task_type == "memory_check":
            self._process_memory_check_task(task)
        elif task_type == "disk_check":
            self._process_disk_check_task(task)
        elif task_type == "network_check":
            self._process_network_check_task(task)
        elif task_type == "process_check":
            self._process_process_check_task(task)
        else:
            logger.warning(f"Tipo de tarefa desconhecido: {task_type}")
    
    def _check_mt5_connection(self) -> None:
        """Verifica a conexão com o MT5"""
        task = {
            "type": "mt5_connection",
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.monitoring_queue.put(task)
    
    def _process_mt5_connection_task(self, task: Dict) -> None:
        """Processa uma tarefa de verificação de conexão com o MT5"""
        try:
            connection_ok = self.mt5_monitor.check_connection()
            
            # Registra o status no histórico
            self.history_data["mt5"]["connection_status"].append({
                "timestamp": task["timestamp"],
                "status": connection_ok
            })
            
            # Limita o tamanho do histórico
            max_history = 1000
            if len(self.history_data["mt5"]["connection_status"]) > max_history:
                self.history_data["mt5"]["connection_status"] = self.history_data["mt5"]["connection_status"][-max_history:]
            
            # Atualiza o dashboard
            if self.socketio:
                self.socketio.emit('mt5_connection_update', {
                    "timestamp": task["timestamp"],
                    "status": connection_ok
                })
            
            # Se a conexão falhou, envia alerta e tenta recuperação
            if not connection_ok:
                self.alert_manager.send_alert(
                    "Conexão com o MT5 perdida",
                    level="error",
                    source="mt5_monitor"
                )
                
                self.action_manager.handle_issue("connection_lost", {
                    "timestamp": task["timestamp"]
                })
        except Exception as e:
            logger.error(f"Erro ao processar verificação de conexão com o MT5: {e}")
    
    def _check_ea_running(self) -> None:
        """Verifica se o EA está em execução"""
        task = {
            "type": "ea_running",
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.monitoring_queue.put(task)
    
    def _process_ea_running_task(self, task: Dict) -> None:
        """Processa uma tarefa de verificação do EA"""
        try:
            ea_running = self.mt5_monitor.check_ea_running()
            
            # Registra o status no histórico
            self.history_data["mt5"]["ea_status"].append({
                "timestamp": task["timestamp"],
                "status": ea_running
            })
            
            # Limita o tamanho do histórico
            max_history = 1000
            if len(self.history_data["mt5"]["ea_status"]) > max_history:
                self.history_data["mt5"]["ea_status"] = self.history_data["mt5"]["ea_status"][-max_history:]
            
            # Atualiza o dashboard
            if self.socketio:
                self.socketio.emit('ea_status_update', {
                    "timestamp": task["timestamp"],
                    "status": ea_running
                })
            
            # Se o EA não está em execução, envia alerta e tenta recuperação
            if not ea_running:
                self.alert_manager.send_alert(
                    "EA não está em execução",
                    level="warning",
                    source="mt5_monitor"
                )
                
                self.action_manager.handle_issue("ea_not_running", {
                    "timestamp": task["timestamp"]
                })
        except Exception as e:
            logger.error(f"Erro ao processar verificação do EA: {e}")
    
    def _check_order_activity(self) -> None:
        """Verifica a atividade de ordens"""
        task = {
            "type": "order_activity",
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.monitoring_queue.put(task)
    
    def _process_order_activity_task(self, task: Dict) -> None:
        """Processa uma tarefa de verificação de atividade de ordens"""
        try:
            activity_ok = self.mt5_monitor.check_order_activity()
            
            # Atualiza o dashboard
            if self.socketio:
                self.socketio.emit('order_activity_update', {
                    "timestamp": task["timestamp"],
                    "status": activity_ok
                })
            
            # Se não há atividade recente, envia alerta
            if not activity_ok:
                self.alert_manager.send_alert(
                    "Nenhuma atividade de ordens recente",
                    level="warning",
                    source="mt5_monitor"
                )
        except Exception as e:
            logger.error(f"Erro ao processar verificação de atividade de ordens: {e}")
    
    def _check_cpu(self) -> None:
        """Verifica o uso de CPU"""
        task = {
            "type": "cpu_check",
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.monitoring_queue.put(task)
    
    def _process_cpu_check_task(self, task: Dict) -> None:
        """Processa uma tarefa de verificação de CPU"""
        try:
            cpu_ok, cpu_percent = self.system_monitor.check_cpu()
            
            # Registra o valor no histórico
            self.history_data["system"]["cpu"].append({
                "timestamp": task["timestamp"],
                "value": cpu_percent
            })
            
            # Limita o tamanho do histórico
            max_history = 1000
            if len(self.history_data["system"]["cpu"]) > max_history:
                self.history_data["system"]["cpu"] = self.history_data["system"]["cpu"][-max_history:]
            
            # Atualiza o dashboard
            if self.socketio:
                self.socketio.emit('cpu_update', {
                    "timestamp": task["timestamp"],
                    "value": cpu_percent,
                    "status": cpu_ok
                })
            
            # Se o uso de CPU está alto, envia alerta e tenta recuperação
            if not cpu_ok:
                self.alert_manager.send_alert(
                    f"Uso de CPU alto: {cpu_percent:.1f}%",
                    level="warning",
                    source="system_monitor"
                )
                
                self.action_manager.handle_issue("high_cpu_usage", {
                    "timestamp": task["timestamp"],
                    "value": cpu_percent
                })
        except Exception as e:
            logger.error(f"Erro ao processar verificação de CPU: {e}")
    
    def _check_memory(self) -> None:
        """Verifica o uso de memória"""
        task = {
            "type": "memory_check",
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.monitoring_queue.put(task)
    
    def _process_memory_check_task(self, task: Dict) -> None:
        """Processa uma tarefa de verificação de memória"""
        try:
            memory_ok, memory_percent = self.system_monitor.check_memory()
            
            # Registra o valor no histórico
            self.history_data["system"]["memory"].append({
                "timestamp": task["timestamp"],
                "value": memory_percent
            })
            
            # Limita o tamanho do histórico
            max_history = 1000
            if len(self.history_data["system"]["memory"]) > max_history:
                self.history_data["system"]["memory"] = self.history_data["system"]["memory"][-max_history:]
            
            # Atualiza o dashboard
            if self.socketio:
                self.socketio.emit('memory_update', {
                    "timestamp": task["timestamp"],
                    "value": memory_percent,
                    "status": memory_ok
                })
            
            # Se o uso de memória está alto, envia alerta e tenta recuperação
            if not memory_ok:
                self.alert_manager.send_alert(
                    f"Uso de memória alto: {memory_percent:.1f}%",
                    level="warning",
                    source="system_monitor"
                )
                
                self.action_manager.handle_issue("high_memory_usage", {
                    "timestamp": task["timestamp"],
                    "value": memory_percent
                })
        except Exception as e:
            logger.error(f"Erro ao processar verificação de memória: {e}")
    
    def _check_disk(self) -> None:
        """Verifica o uso de disco"""
        task = {
            "type": "disk_check",
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.monitoring_queue.put(task)
    
    def _process_disk_check_task(self, task: Dict) -> None:
        """Processa uma tarefa de verificação de disco"""
        try:
            disk_ok, disk_percent = self.system_monitor.check_disk()
            
            # Registra o valor no histórico
            self.history_data["system"]["disk"].append({
                "timestamp": task["timestamp"],
                "value": disk_percent
            })
            
            # Limita o tamanho do histórico
            max_history = 1000
            if len(self.history_data["system"]["disk"]) > max_history:
                self.history_data["system"]["disk"] = self.history_data["system"]["disk"][-max_history:]
            
            # Atualiza o dashboard
            if self.socketio:
                self.socketio.emit('disk_update', {
                    "timestamp": task["timestamp"],
                    "value": disk_percent,
                    "status": disk_ok
                })
            
            # Se o uso de disco está alto, envia alerta
            if not disk_ok:
                self.alert_manager.send_alert(
                    f"Uso de disco alto: {disk_percent:.1f}%",
                    level="warning",
                    source="system_monitor"
                )
        except Exception as e:
            logger.error(f"Erro ao processar verificação de disco: {e}")
    
    def _check_network(self) -> None:
        """Verifica a conectividade de rede"""
        task = {
            "type": "network_check",
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.monitoring_queue.put(task)
    
    def _process_network_check_task(self, task: Dict) -> None:
        """Processa uma tarefa de verificação de rede"""
        try:
            network_ok, network_results = self.system_monitor.check_network()
            
            # Atualiza o dashboard
            if self.socketio:
                self.socketio.emit('network_update', {
                    "timestamp": task["timestamp"],
                    "results": network_results,
                    "status": network_ok
                })
            
            # Se há problemas de rede, envia alerta
            if not network_ok:
                self.alert_manager.send_alert(
                    f"Problemas de conectividade de rede detectados",
                    level="warning",
                    source="system_monitor"
                )
        except Exception as e:
            logger.error(f"Erro ao processar verificação de rede: {e}")
    
    def _check_processes(self) -> None:
        """Verifica os processos necessários"""
        task = {
            "type": "process_check",
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.monitoring_queue.put(task)
    
    def _process_process_check_task(self, task: Dict) -> None:
        """Processa uma tarefa de verificação de processos"""
        try:
            processes_ok, process_results = self.system_monitor.check_processes()
            
            # Atualiza o dashboard
            if self.socketio:
                self.socketio.emit('process_update', {
                    "timestamp": task["timestamp"],
                    "results": process_results,
                    "status": processes_ok
                })
            
            # Se algum processo necessário não está em execução, envia alerta
            if not processes_ok:
                missing_processes = [proc for proc, info in process_results.items() if info["status"] == "not_running"]
                self.alert_manager.send_alert(
                    f"Processos necessários não estão em execução: {', '.join(missing_processes)}",
                    level="warning",
                    source="system_monitor"
                )
                
                # Tenta recuperar o EA se ele for um dos processos faltantes
                if "mt5_tape_reading_ea.py" in missing_processes:
                    self.action_manager.handle_issue("ea_not_running", {
                        "timestamp": task["timestamp"],
                        "missing_processes": missing_processes
                    })
        except Exception as e:
            logger.error(f"Erro ao processar verificação de processos: {e}")
    
    def _start_dashboard(self) -> None:
        """Inicia o dashboard web"""
        try:
            # Cria a aplicação Flask
            app = Flask(__name__)
            socketio = SocketIO(app, cors_allowed_origins="*")
            
            self.dashboard_app = app
            self.socketio = socketio
            
            # Define as rotas
            @app.route('/')
            def index():
                return render_template('index.html')
            
            @app.route('/api/status')
            def get_status():
                return jsonify({
                    "mt5": {
                        "connection": self.mt5_monitor.connection_status,
                        "ea_running": self.mt5_monitor.ea_status,
                        "account_info": self.mt5_monitor.get_account_info()
                    },
                    "system": self.system_monitor.get_system_info()
                })
            
            @app.route('/api/positions')
            def get_positions():
                return jsonify(self.mt5_monitor.get_positions())
            
            @app.route('/api/orders')
            def get_orders():
                return jsonify(self.mt5_monitor.get_orders())
            
            @app.route('/api/history')
            def get_history():
                days = request.args.get('days', default=7, type=int)
                return jsonify(self.mt5_monitor.get_history(days))
            
            @app.route('/api/history_data')
            def get_history_data():
                return jsonify(self.history_data)
            
            @app.route('/api/config', methods=['GET'])
            def get_config():
                return jsonify(self.config)
            
            @app.route('/api/config', methods=['POST'])
            def update_config():
                try:
                    new_config = request.json
                    self.config_manager.update_config(new_config)
                    self.config = new_config
                    return jsonify({"status": "success"})
                except Exception as e:
                    return jsonify({"status": "error", "message": str(e)}), 400
            
            # Inicia o servidor em uma thread separada
            dashboard_thread = threading.Thread(
                target=socketio.run,
                kwargs={
                    "app": app,
                    "host": self.config["dashboard"]["host"],
                    "port": self.config["dashboard"]["port"],
                    "debug": False,
                    "use_reloader": False
                }
            )
            dashboard_thread.daemon = True
            dashboard_thread.start()
            
            logger.info(f"Dashboard iniciado em http://{self.config['dashboard']['host']}:{self.config['dashboard']['port']}")
        except Exception as e:
            logger.error(f"Erro ao iniciar dashboard: {e}")

def main():
    """Função principal"""
    try:
        # Inicializa o sistema de monitoramento
        monitoring_system = MonitoringSystem()
        
        # Inicia o sistema de monitoramento
        monitoring_system.start()
        
        # Mantém o programa em execução
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Interrupção do usuário recebida")
        finally:
            # Para o sistema de monitoramento
            monitoring_system.stop()
    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
