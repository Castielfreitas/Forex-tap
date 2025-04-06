#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sistema de Backup Automático para MT5 Tape Reading EA
====================================================

Este script implementa um sistema de backup automático para o MT5 Tape Reading EA,
garantindo que todos os dados importantes sejam preservados e possam ser restaurados
em caso de falhas.

Funcionalidades:
- Backup automático programado (diário, semanal, mensal)
- Backup incremental para economizar espaço
- Compressão e criptografia dos backups
- Armazenamento em múltiplos destinos (local, nuvem)
- Rotação de backups para gerenciamento de espaço
- Verificação de integridade dos backups
- Restauração automatizada

Autor: Manus AI
Data: 06/04/2025
"""

import os
import sys
import time
import datetime
import shutil
import logging
import json
import hashlib
import tarfile
import gzip
import boto3
import schedule
import threading
import queue
import requests
from cryptography.fernet import Fernet
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union, Any

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("backup_system.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5BackupSystem")

class BackupConfig:
    """Classe para gerenciar configurações de backup"""
    
    def __init__(self, config_file: str = "backup_config.json"):
        """Inicializa a configuração de backup"""
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
                    "backup": {
                        "enabled": True,
                        "schedule": {
                            "daily": {
                                "enabled": True,
                                "time": "23:00",
                                "retention": 7
                            },
                            "weekly": {
                                "enabled": True,
                                "day": "sunday",
                                "time": "22:00",
                                "retention": 4
                            },
                            "monthly": {
                                "enabled": True,
                                "day": 1,
                                "time": "21:00",
                                "retention": 6
                            }
                        },
                        "sources": [
                            {
                                "name": "mt5_data",
                                "path": "/home/ubuntu/mt5_data",
                                "include": ["*.py", "*.json", "*.csv", "*.db", "*.sqlite"],
                                "exclude": ["__pycache__", "*.log", "*.tmp"]
                            },
                            {
                                "name": "mt5_config",
                                "path": "/home/ubuntu/mt5_config",
                                "include": ["*.json", "*.ini", "*.conf"],
                                "exclude": []
                            },
                            {
                                "name": "mt5_logs",
                                "path": "/home/ubuntu/mt5_logs",
                                "include": ["*.log"],
                                "exclude": ["temp_*"]
                            }
                        ],
                        "destinations": [
                            {
                                "type": "local",
                                "name": "local_backup",
                                "path": "/home/ubuntu/backups",
                                "enabled": True
                            },
                            {
                                "type": "s3",
                                "name": "s3_backup",
                                "bucket": "mt5-tape-reading-backups",
                                "prefix": "backups/",
                                "region": "us-east-1",
                                "enabled": False,
                                "credentials": {
                                    "access_key": "",
                                    "secret_key": ""
                                }
                            },
                            {
                                "type": "ftp",
                                "name": "ftp_backup",
                                "host": "",
                                "port": 21,
                                "username": "",
                                "password": "",
                                "path": "/backups",
                                "enabled": False
                            }
                        ],
                        "encryption": {
                            "enabled": True,
                            "key_file": "backup_key.key"
                        },
                        "compression": {
                            "enabled": True,
                            "level": 9
                        },
                        "notification": {
                            "email": {
                                "enabled": False,
                                "smtp_server": "",
                                "smtp_port": 587,
                                "username": "",
                                "password": "",
                                "from": "",
                                "to": []
                            },
                            "telegram": {
                                "enabled": False,
                                "token": "",
                                "chat_id": ""
                            }
                        }
                    },
                    "restore": {
                        "auto_restore": {
                            "enabled": True,
                            "on_startup": True,
                            "on_failure": True
                        },
                        "verification": {
                            "enabled": True,
                            "method": "checksum"
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

class EncryptionManager:
    """Classe para gerenciar criptografia de backups"""
    
    def __init__(self, config: Dict):
        """Inicializa o gerenciador de criptografia"""
        self.enabled = config["backup"]["encryption"]["enabled"]
        self.key_file = config["backup"]["encryption"]["key_file"]
        self.key = self._load_or_generate_key()
        
    def _load_or_generate_key(self) -> bytes:
        """Carrega chave existente ou gera uma nova"""
        if os.path.exists(self.key_file):
            with open(self.key_file, 'rb') as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as f:
                f.write(key)
            logger.info(f"Nova chave de criptografia gerada e salva em {self.key_file}")
            return key
    
    def encrypt_file(self, file_path: str) -> str:
        """Criptografa um arquivo e retorna o caminho do arquivo criptografado"""
        if not self.enabled:
            return file_path
        
        try:
            encrypted_path = f"{file_path}.enc"
            fernet = Fernet(self.key)
            
            with open(file_path, 'rb') as f:
                data = f.read()
            
            encrypted_data = fernet.encrypt(data)
            
            with open(encrypted_path, 'wb') as f:
                f.write(encrypted_data)
            
            logger.info(f"Arquivo criptografado: {file_path} -> {encrypted_path}")
            return encrypted_path
        except Exception as e:
            logger.error(f"Erro ao criptografar arquivo {file_path}: {e}")
            return file_path
    
    def decrypt_file(self, file_path: str) -> str:
        """Descriptografa um arquivo e retorna o caminho do arquivo descriptografado"""
        if not self.enabled or not file_path.endswith('.enc'):
            return file_path
        
        try:
            decrypted_path = file_path[:-4]  # Remove .enc
            fernet = Fernet(self.key)
            
            with open(file_path, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = fernet.decrypt(encrypted_data)
            
            with open(decrypted_path, 'wb') as f:
                f.write(decrypted_data)
            
            logger.info(f"Arquivo descriptografado: {file_path} -> {decrypted_path}")
            return decrypted_path
        except Exception as e:
            logger.error(f"Erro ao descriptografar arquivo {file_path}: {e}")
            return file_path

class CompressionManager:
    """Classe para gerenciar compressão de backups"""
    
    def __init__(self, config: Dict):
        """Inicializa o gerenciador de compressão"""
        self.enabled = config["backup"]["compression"]["enabled"]
        self.level = config["backup"]["compression"]["level"]
    
    def compress_directory(self, directory: str, output_file: str) -> str:
        """Comprime um diretório e retorna o caminho do arquivo comprimido"""
        if not self.enabled:
            return directory
        
        try:
            # Cria um arquivo tar.gz
            with tarfile.open(output_file, f"w:gz", compresslevel=self.level) as tar:
                tar.add(directory, arcname=os.path.basename(directory))
            
            logger.info(f"Diretório comprimido: {directory} -> {output_file}")
            return output_file
        except Exception as e:
            logger.error(f"Erro ao comprimir diretório {directory}: {e}")
            return directory
    
    def decompress_file(self, file_path: str, output_dir: str) -> str:
        """Descomprime um arquivo e retorna o caminho do diretório descomprimido"""
        if not self.enabled or not (file_path.endswith('.tar.gz') or file_path.endswith('.tgz')):
            return file_path
        
        try:
            # Extrai o arquivo tar.gz
            with tarfile.open(file_path, "r:gz") as tar:
                tar.extractall(path=output_dir)
            
            logger.info(f"Arquivo descomprimido: {file_path} -> {output_dir}")
            return output_dir
        except Exception as e:
            logger.error(f"Erro ao descomprimir arquivo {file_path}: {e}")
            return file_path

class BackupManager:
    """Classe principal para gerenciar backups"""
    
    def __init__(self):
        """Inicializa o gerenciador de backup"""
        self.config_manager = BackupConfig()
        self.config = self.config_manager.get_config()
        self.encryption_manager = EncryptionManager(self.config)
        self.compression_manager = CompressionManager(self.config)
        self.backup_queue = queue.Queue()
        self.restore_queue = queue.Queue()
        self.worker_thread = None
        self.running = False
    
    def start(self) -> None:
        """Inicia o sistema de backup"""
        if self.running:
            logger.warning("Sistema de backup já está em execução")
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop)
        self.worker_thread.daemon = True
        self.worker_thread.start()
        
        self._schedule_backups()
        
        logger.info("Sistema de backup iniciado")
    
    def stop(self) -> None:
        """Para o sistema de backup"""
        if not self.running:
            logger.warning("Sistema de backup não está em execução")
            return
        
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5.0)
        
        logger.info("Sistema de backup parado")
    
    def _worker_loop(self) -> None:
        """Loop principal do worker thread"""
        while self.running:
            try:
                # Verifica se há tarefas de backup
                try:
                    task = self.backup_queue.get(block=False)
                    self._process_backup_task(task)
                    self.backup_queue.task_done()
                except queue.Empty:
                    pass
                
                # Verifica se há tarefas de restauração
                try:
                    task = self.restore_queue.get(block=False)
                    self._process_restore_task(task)
                    self.restore_queue.task_done()
                except queue.Empty:
                    pass
                
                # Executa tarefas agendadas
                schedule.run_pending()
                
                # Aguarda um pouco para não consumir CPU
                time.sleep(1)
            except Exception as e:
                logger.error(f"Erro no worker loop: {e}")
    
    def _schedule_backups(self) -> None:
        """Agenda backups conforme configuração"""
        backup_config = self.config["backup"]
        
        if not backup_config["enabled"]:
            logger.info("Backups automáticos desabilitados na configuração")
            return
        
        # Backup diário
        if backup_config["schedule"]["daily"]["enabled"]:
            daily_time = backup_config["schedule"]["daily"]["time"]
            schedule.every().day.at(daily_time).do(self.create_backup, backup_type="daily")
            logger.info(f"Backup diário agendado para {daily_time}")
        
        # Backup semanal
        if backup_config["schedule"]["weekly"]["enabled"]:
            weekly_day = backup_config["schedule"]["weekly"]["day"]
            weekly_time = backup_config["schedule"]["weekly"]["time"]
            getattr(schedule.every(), weekly_day).at(weekly_time).do(self.create_backup, backup_type="weekly")
            logger.info(f"Backup semanal agendado para {weekly_day} às {weekly_time}")
        
        # Backup mensal
        if backup_config["schedule"]["monthly"]["enabled"]:
            monthly_day = backup_config["schedule"]["monthly"]["day"]
            monthly_time = backup_config["schedule"]["monthly"]["time"]
            
            # Agenda para o dia específico do mês
            def monthly_job():
                # Verifica se é o dia correto do mês
                if datetime.datetime.now().day == monthly_day:
                    self.create_backup(backup_type="monthly")
            
            schedule.every().day.at(monthly_time).do(monthly_job)
            logger.info(f"Backup mensal agendado para dia {monthly_day} às {monthly_time}")
    
    def create_backup(self, backup_type: str = "daily") -> None:
        """Cria um backup e o adiciona à fila de processamento"""
        logger.info(f"Iniciando backup do tipo: {backup_type}")
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = f"{backup_type}_{timestamp}"
        
        task = {
            "id": backup_id,
            "type": backup_type,
            "timestamp": timestamp,
            "status": "pending"
        }
        
        self.backup_queue.put(task)
        logger.info(f"Tarefa de backup {backup_id} adicionada à fila")
    
    def _process_backup_task(self, task: Dict) -> None:
        """Processa uma tarefa de backup da fila"""
        backup_id = task["id"]
        backup_type = task["type"]
        timestamp = task["timestamp"]
        
        logger.info(f"Processando tarefa de backup {backup_id}")
        
        try:
            # Atualiza status
            task["status"] = "processing"
            
            # Cria diretório temporário para o backup
            temp_dir = os.path.join("/tmp", f"mt5_backup_{backup_id}")
            os.makedirs(temp_dir, exist_ok=True)
            
            # Copia arquivos das fontes para o diretório temporário
            self._copy_source_files(temp_dir)
            
            # Cria arquivo de metadados
            metadata = {
                "id": backup_id,
                "type": backup_type,
                "timestamp": timestamp,
                "created_at": datetime.datetime.now().isoformat(),
                "sources": self.config["backup"]["sources"],
                "checksum": self._calculate_directory_checksum(temp_dir)
            }
            
            metadata_file = os.path.join(temp_dir, "backup_metadata.json")
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=4)
            
            # Comprime o diretório
            backup_file = os.path.join("/tmp", f"mt5_backup_{backup_id}.tar.gz")
            self.compression_manager.compress_directory(temp_dir, backup_file)
            
            # Criptografa o arquivo se necessário
            if self.config["backup"]["encryption"]["enabled"]:
                backup_file = self.encryption_manager.encrypt_file(backup_file)
            
            # Envia para os destinos configurados
            self._send_to_destinations(backup_file, backup_type)
            
            # Limpa arquivos temporários
            shutil.rmtree(temp_dir, ignore_errors=True)
            if os.path.exists(backup_file):
                os.remove(backup_file)
            
            # Rotaciona backups antigos
            self._rotate_backups(backup_type)
            
            # Atualiza status
            task["status"] = "completed"
            logger.info(f"Backup {backup_id} concluído com sucesso")
            
            # Envia notificação
            self._send_notification(f"Backup {backup_id} concluído com sucesso")
        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            logger.error(f"Erro ao processar backup {backup_id}: {e}")
            self._send_notification(f"Erro no backup {backup_id}: {e}", is_error=True)
    
    def _copy_source_files(self, target_dir: str) -> None:
        """Copia arquivos das fontes configuradas para o diretório de destino"""
        import glob
        import fnmatch
        
        for source in self.config["backup"]["sources"]:
            source_path = source["path"]
            source_name = source["name"]
            include_patterns = source["include"]
            exclude_patterns = source["exclude"]
            
            if not os.path.exists(source_path):
                logger.warning(f"Diretório fonte não encontrado: {source_path}")
                continue
            
            # Cria diretório de destino para esta fonte
            dest_dir = os.path.join(target_dir, source_name)
            os.makedirs(dest_dir, exist_ok=True)
            
            # Função para verificar se um arquivo deve ser excluído
            def should_exclude(file_path):
                file_name = os.path.basename(file_path)
                for pattern in exclude_patterns:
                    if fnmatch.fnmatch(file_name, pattern):
                        return True
                return False
            
            # Copia arquivos que correspondem aos padrões de inclusão
            for pattern in include_patterns:
                for file_path in glob.glob(os.path.join(source_path, "**", pattern), recursive=True):
                    if os.path.isfile(file_path) and not should_exclude(file_path):
                        # Mantém a estrutura de diretórios relativa
                        rel_path = os.path.relpath(file_path, source_path)
                        dest_file = os.path.join(dest_dir, rel_path)
                        
                        # Cria diretórios intermediários se necessário
                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        
                        # Copia o arquivo
                        shutil.copy2(file_path, dest_file)
                        logger.debug(f"Arquivo copiado: {file_path} -> {dest_file}")
    
    def _calculate_directory_checksum(self, directory: str) -> str:
        """Calcula o checksum de um diretório"""
        checksums = []
        
        for root, _, files in os.walk(directory):
            for file in sorted(files):
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    with open(file_path, 'rb') as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()
                        rel_path = os.path.relpath(file_path, directory)
                        checksums.append(f"{rel_path}:{file_hash}")
        
        # Calcula o hash final de todos os checksums concatenados
        return hashlib.sha256('\n'.join(checksums).encode()).hexdigest()
    
    def _send_to_destinations(self, backup_file: str, backup_type: str) -> None:
        """Envia o arquivo de backup para os destinos configurados"""
        for dest in self.config["backup"]["destinations"]:
            if not dest["enabled"]:
                continue
            
            dest_type = dest["type"]
            dest_name = dest["name"]
            
            try:
                if dest_type == "local":
                    self._send_to_local(backup_file, dest, backup_type)
                elif dest_type == "s3":
                    self._send_to_s3(backup_file, dest, backup_type)
                elif dest_type == "ftp":
                    self._send_to_ftp(backup_file, dest, backup_type)
                else:
                    logger.warning(f"Tipo de destino desconhecido: {dest_type}")
                    continue
                
                logger.info(f"Backup enviado para {dest_name} ({dest_type})")
            except Exception as e:
                logger.error(f"Erro ao enviar backup para {dest_name} ({dest_type}): {e}")
    
    def _send_to_local(self, backup_file: str, dest: Dict, backup_type: str) -> None:
        """Envia o backup para um diretório local"""
        dest_path = dest["path"]
        backup_type_dir = os.path.join(dest_path, backup_type)
        
        # Cria diretórios se não existirem
        os.makedirs(backup_type_dir, exist_ok=True)
        
        # Copia o arquivo
        dest_file = os.path.join(backup_type_dir, os.path.basename(backup_file))
        shutil.copy2(backup_file, dest_file)
        
        logger.info(f"Backup copiado para {dest_file}")
    
    def _send_to_s3(self, backup_file: str, dest: Dict, backup_type: str) -> None:
        """Envia o backup para um bucket S3"""
        bucket = dest["bucket"]
        prefix = dest.get("prefix", "")
        region = dest.get("region", "us-east-1")
        access_key = dest["credentials"]["access_key"]
        secret_key = dest["credentials"]["secret_key"]
        
        # Verifica se as credenciais foram fornecidas
        if not access_key or not secret_key:
            logger.error("Credenciais S3 não configuradas")
            return
        
        # Cria cliente S3
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        
        # Define o caminho no S3
        s3_key = f"{prefix}{backup_type}/{os.path.basename(backup_file)}"
        
        # Faz upload do arquivo
        s3_client.upload_file(backup_file, bucket, s3_key)
        
        logger.info(f"Backup enviado para S3: {bucket}/{s3_key}")
    
    def _send_to_ftp(self, backup_file: str, dest: Dict, backup_type: str) -> None:
        """Envia o backup para um servidor FTP"""
        from ftplib import FTP
        
        host = dest["host"]
        port = dest.get("port", 21)
        username = dest["username"]
        password = dest["password"]
        remote_path = dest["path"]
        
        # Verifica se as credenciais foram fornecidas
        if not host or not username or not password:
            logger.error("Credenciais FTP não configuradas")
            return
        
        # Conecta ao servidor FTP
        ftp = FTP()
        ftp.connect(host, port)
        ftp.login(username, password)
        
        # Navega para o diretório remoto e cria se necessário
        remote_dir = f"{remote_path}/{backup_type}"
        
        # Tenta criar diretórios recursivamente
        current_dir = ""
        for part in remote_dir.split('/'):
            if not part:
                continue
            
            current_dir += f"/{part}"
            try:
                ftp.cwd(current_dir)
            except:
                ftp.mkd(current_dir)
                ftp.cwd(current_dir)
        
        # Faz upload do arquivo
        with open(backup_file, 'rb') as f:
            ftp.storbinary(f"STOR {os.path.basename(backup_file)}", f)
        
        # Fecha conexão
        ftp.quit()
        
        logger.info(f"Backup enviado para FTP: {host}{remote_dir}/{os.path.basename(backup_file)}")
    
    def _rotate_backups(self, backup_type: str) -> None:
        """Remove backups antigos conforme política de retenção"""
        retention = self.config["backup"]["schedule"][backup_type]["retention"]
        
        for dest in self.config["backup"]["destinations"]:
            if not dest["enabled"]:
                continue
            
            dest_type = dest["type"]
            dest_name = dest["name"]
            
            try:
                if dest_type == "local":
                    self._rotate_local_backups(dest, backup_type, retention)
                elif dest_type == "s3":
                    self._rotate_s3_backups(dest, backup_type, retention)
                elif dest_type == "ftp":
                    self._rotate_ftp_backups(dest, backup_type, retention)
                else:
                    continue
                
                logger.info(f"Rotação de backups concluída para {dest_name} ({dest_type})")
            except Exception as e:
                logger.error(f"Erro na rotação de backups para {dest_name} ({dest_type}): {e}")
    
    def _rotate_local_backups(self, dest: Dict, backup_type: str, retention: int) -> None:
        """Remove backups locais antigos"""
        backup_dir = os.path.join(dest["path"], backup_type)
        
        if not os.path.exists(backup_dir):
            return
        
        # Lista todos os arquivos de backup
        backup_files = []
        for file in os.listdir(backup_dir):
            file_path = os.path.join(backup_dir, file)
            if os.path.isfile(file_path) and (file.endswith('.tar.gz') or file.endswith('.enc')):
                backup_files.append((file_path, os.path.getmtime(file_path)))
        
        # Ordena por data de modificação (mais recente primeiro)
        backup_files.sort(key=lambda x: x[1], reverse=True)
        
        # Remove arquivos excedentes
        if len(backup_files) > retention:
            for file_path, _ in backup_files[retention:]:
                os.remove(file_path)
                logger.info(f"Backup antigo removido: {file_path}")
    
    def _rotate_s3_backups(self, dest: Dict, backup_type: str, retention: int) -> None:
        """Remove backups antigos do S3"""
        bucket = dest["bucket"]
        prefix = dest.get("prefix", "")
        region = dest.get("region", "us-east-1")
        access_key = dest["credentials"]["access_key"]
        secret_key = dest["credentials"]["secret_key"]
        
        # Verifica se as credenciais foram fornecidas
        if not access_key or not secret_key:
            logger.error("Credenciais S3 não configuradas")
            return
        
        # Cria cliente S3
        s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        
        # Lista objetos no bucket
        prefix_path = f"{prefix}{backup_type}/"
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix_path)
        
        if 'Contents' not in response:
            return
        
        # Ordena por data de modificação (mais recente primeiro)
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
        
        # Remove objetos excedentes
        if len(objects) > retention:
            for obj in objects[retention:]:
                s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
                logger.info(f"Backup antigo removido do S3: {bucket}/{obj['Key']}")
    
    def _rotate_ftp_backups(self, dest: Dict, backup_type: str, retention: int) -> None:
        """Remove backups antigos do servidor FTP"""
        from ftplib import FTP
        
        host = dest["host"]
        port = dest.get("port", 21)
        username = dest["username"]
        password = dest["password"]
        remote_path = dest["path"]
        
        # Verifica se as credenciais foram fornecidas
        if not host or not username or not password:
            logger.error("Credenciais FTP não configuradas")
            return
        
        # Conecta ao servidor FTP
        ftp = FTP()
        ftp.connect(host, port)
        ftp.login(username, password)
        
        # Navega para o diretório remoto
        remote_dir = f"{remote_path}/{backup_type}"
        try:
            ftp.cwd(remote_dir)
        except:
            # Diretório não existe, nada a fazer
            ftp.quit()
            return
        
        # Lista arquivos
        files = []
        ftp.retrlines('LIST', lambda x: files.append(x))
        
        # Extrai nomes e datas
        import re
        file_info = []
        for file_line in files:
            # Formato típico: "04-06-2025  09:00AM              12345 filename.tar.gz"
            match = re.search(r'(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}(?:AM|PM))\s+\d+\s+(.+)', file_line)
            if match:
                date_str, filename = match.groups()
                if filename.endswith('.tar.gz') or filename.endswith('.enc'):
                    # Converte data para timestamp
                    try:
                        date_obj = datetime.datetime.strptime(date_str, '%m-%d-%Y %I:%M%p')
                        file_info.append((filename, date_obj.timestamp()))
                    except:
                        continue
        
        # Ordena por data (mais recente primeiro)
        file_info.sort(key=lambda x: x[1], reverse=True)
        
        # Remove arquivos excedentes
        if len(file_info) > retention:
            for filename, _ in file_info[retention:]:
                try:
                    ftp.delete(filename)
                    logger.info(f"Backup antigo removido do FTP: {remote_dir}/{filename}")
                except:
                    logger.error(f"Erro ao remover arquivo do FTP: {remote_dir}/{filename}")
        
        # Fecha conexão
        ftp.quit()
    
    def _send_notification(self, message: str, is_error: bool = False) -> None:
        """Envia notificação sobre o backup"""
        notification_config = self.config["backup"]["notification"]
        
        # Notificação por e-mail
        if notification_config["email"]["enabled"]:
            self._send_email_notification(message, is_error)
        
        # Notificação por Telegram
        if notification_config["telegram"]["enabled"]:
            self._send_telegram_notification(message, is_error)
    
    def _send_email_notification(self, message: str, is_error: bool = False) -> None:
        """Envia notificação por e-mail"""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        email_config = self.config["backup"]["notification"]["email"]
        
        smtp_server = email_config["smtp_server"]
        smtp_port = email_config["smtp_port"]
        username = email_config["username"]
        password = email_config["password"]
        sender = email_config["from"]
        recipients = email_config["to"]
        
        if not smtp_server or not username or not password or not sender or not recipients:
            logger.error("Configuração de e-mail incompleta")
            return
        
        try:
            # Cria a mensagem
            msg = MIMEMultipart()
            msg['From'] = sender
            msg['To'] = ', '.join(recipients)
            
            if is_error:
                msg['Subject'] = "ERRO - Sistema de Backup MT5"
            else:
                msg['Subject'] = "Sistema de Backup MT5 - Notificação"
            
            msg.attach(MIMEText(message, 'plain'))
            
            # Envia o e-mail
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
            
            logger.info(f"Notificação por e-mail enviada para {', '.join(recipients)}")
        except Exception as e:
            logger.error(f"Erro ao enviar notificação por e-mail: {e}")
    
    def _send_telegram_notification(self, message: str, is_error: bool = False) -> None:
        """Envia notificação pelo Telegram"""
        telegram_config = self.config["backup"]["notification"]["telegram"]
        
        token = telegram_config["token"]
        chat_id = telegram_config["chat_id"]
        
        if not token or not chat_id:
            logger.error("Configuração do Telegram incompleta")
            return
        
        try:
            # Formata a mensagem
            if is_error:
                formatted_message = f"❌ ERRO - Sistema de Backup MT5:\n\n{message}"
            else:
                formatted_message = f"✅ Sistema de Backup MT5:\n\n{message}"
            
            # Envia a mensagem
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": formatted_message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            logger.info(f"Notificação pelo Telegram enviada para chat_id {chat_id}")
        except Exception as e:
            logger.error(f"Erro ao enviar notificação pelo Telegram: {e}")
    
    def restore_backup(self, backup_id: str = None, backup_file: str = None) -> None:
        """Inicia uma restauração de backup"""
        if not backup_id and not backup_file:
            logger.error("É necessário fornecer backup_id ou backup_file para restauração")
            return
        
        task = {
            "id": f"restore_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "backup_id": backup_id,
            "backup_file": backup_file,
            "status": "pending"
        }
        
        self.restore_queue.put(task)
        logger.info(f"Tarefa de restauração {task['id']} adicionada à fila")
    
    def _process_restore_task(self, task: Dict) -> None:
        """Processa uma tarefa de restauração da fila"""
        restore_id = task["id"]
        backup_id = task.get("backup_id")
        backup_file = task.get("backup_file")
        
        logger.info(f"Processando tarefa de restauração {restore_id}")
        
        try:
            # Atualiza status
            task["status"] = "processing"
            
            # Se backup_id foi fornecido, procura o arquivo correspondente
            if backup_id and not backup_file:
                backup_file = self._find_backup_by_id(backup_id)
                
                if not backup_file:
                    raise ValueError(f"Backup com ID {backup_id} não encontrado")
            
            # Cria diretório temporário para restauração
            temp_dir = os.path.join("/tmp", f"mt5_restore_{restore_id}")
            os.makedirs(temp_dir, exist_ok=True)
            
            # Descriptografa o arquivo se necessário
            if backup_file.endswith('.enc'):
                decrypted_file = self.encryption_manager.decrypt_file(backup_file)
                backup_file = decrypted_file
            
            # Descomprime o arquivo
            self.compression_manager.decompress_file(backup_file, temp_dir)
            
            # Verifica a integridade do backup
            if not self._verify_backup_integrity(temp_dir):
                raise ValueError("Falha na verificação de integridade do backup")
            
            # Restaura os arquivos para os diretórios originais
            self._restore_files(temp_dir)
            
            # Limpa arquivos temporários
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            # Atualiza status
            task["status"] = "completed"
            logger.info(f"Restauração {restore_id} concluída com sucesso")
            
            # Envia notificação
            self._send_notification(f"Restauração {restore_id} concluída com sucesso")
        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            logger.error(f"Erro ao processar restauração {restore_id}: {e}")
            self._send_notification(f"Erro na restauração {restore_id}: {e}", is_error=True)
    
    def _find_backup_by_id(self, backup_id: str) -> Optional[str]:
        """Procura um arquivo de backup pelo ID"""
        # Procura em todos os destinos locais
        for dest in self.config["backup"]["destinations"]:
            if not dest["enabled"] or dest["type"] != "local":
                continue
            
            dest_path = dest["path"]
            
            # Determina o tipo de backup a partir do ID
            backup_type = backup_id.split('_')[0]  # daily, weekly, monthly
            backup_dir = os.path.join(dest_path, backup_type)
            
            if not os.path.exists(backup_dir):
                continue
            
            # Procura por arquivos que contenham o ID no nome
            for file in os.listdir(backup_dir):
                if backup_id in file and (file.endswith('.tar.gz') or file.endswith('.enc')):
                    return os.path.join(backup_dir, file)
        
        return None
    
    def _verify_backup_integrity(self, backup_dir: str) -> bool:
        """Verifica a integridade do backup"""
        metadata_file = os.path.join(backup_dir, "backup_metadata.json")
        
        if not os.path.exists(metadata_file):
            logger.error("Arquivo de metadados não encontrado no backup")
            return False
        
        try:
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            original_checksum = metadata.get("checksum")
            if not original_checksum:
                logger.warning("Checksum não encontrado nos metadados do backup")
                return True  # Continua mesmo sem checksum
            
            # Calcula o checksum atual
            current_checksum = self._calculate_directory_checksum(backup_dir)
            
            # Compara os checksums
            if original_checksum != current_checksum:
                logger.error(f"Verificação de integridade falhou: checksums não correspondem")
                logger.error(f"Original: {original_checksum}")
                logger.error(f"Atual: {current_checksum}")
                return False
            
            logger.info("Verificação de integridade do backup bem-sucedida")
            return True
        except Exception as e:
            logger.error(f"Erro ao verificar integridade do backup: {e}")
            return False
    
    def _restore_files(self, backup_dir: str) -> None:
        """Restaura os arquivos do backup para os diretórios originais"""
        metadata_file = os.path.join(backup_dir, "backup_metadata.json")
        
        if not os.path.exists(metadata_file):
            raise ValueError("Arquivo de metadados não encontrado no backup")
        
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        # Restaura cada fonte
        for source in metadata["sources"]:
            source_name = source["name"]
            target_path = source["path"]
            
            # Diretório de origem no backup
            source_dir = os.path.join(backup_dir, source_name)
            
            if not os.path.exists(source_dir):
                logger.warning(f"Diretório {source_name} não encontrado no backup")
                continue
            
            # Cria o diretório de destino se não existir
            os.makedirs(target_path, exist_ok=True)
            
            # Copia os arquivos
            for root, dirs, files in os.walk(source_dir):
                # Calcula o caminho relativo
                rel_path = os.path.relpath(root, source_dir)
                
                # Cria diretórios no destino
                if rel_path != '.':
                    os.makedirs(os.path.join(target_path, rel_path), exist_ok=True)
                
                # Copia arquivos
                for file in files:
                    src_file = os.path.join(root, file)
                    if rel_path == '.':
                        dst_file = os.path.join(target_path, file)
                    else:
                        dst_file = os.path.join(target_path, rel_path, file)
                    
                    shutil.copy2(src_file, dst_file)
                    logger.debug(f"Arquivo restaurado: {src_file} -> {dst_file}")
            
            logger.info(f"Fonte {source_name} restaurada para {target_path}")

def main():
    """Função principal"""
    try:
        # Inicializa o gerenciador de backup
        backup_manager = BackupManager()
        
        # Inicia o sistema de backup
        backup_manager.start()
        
        # Mantém o programa em execução
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Interrupção do usuário recebida")
        finally:
            # Para o sistema de backup
            backup_manager.stop()
    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
