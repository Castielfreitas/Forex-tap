#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de configuração de servidor VPS para o EA de Tape Reading.
Este módulo implementa a configuração de um servidor VPS dedicado para hospedar o EA.
"""

import os
import sys
import json
import time
import logging
import subprocess
import argparse
from datetime import datetime
import requests
import paramiko
import docker
import boto3
from botocore.exceptions import ClientError
import digitalocean
import google.cloud.compute_v1 as compute_v1

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_cloud_setup.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5CloudSetup")

class MT5CloudSetup:
    """
    Classe para configurar um servidor VPS dedicado para o EA de Tape Reading.
    """
    
    def __init__(self, config_file=None):
        """
        Inicializa o configurador de servidor VPS.
        
        Args:
            config_file (str, optional): Caminho para o arquivo de configuração
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.ssh_client = None
        self.docker_client = None
        self.cloud_client = None
        self.server_ip = None
        self.server_id = None
        self.server_status = "not_created"
        self.mt5_container_id = None
        self.web_container_id = None
        self.db_container_id = None
    
    def _load_config(self):
        """
        Carrega a configuração do configurador de servidor VPS.
        
        Returns:
            dict: Configuração do configurador de servidor VPS
        """
        default_config = {
            "cloud": {
                "provider": "digitalocean",  # "aws", "digitalocean", "gcp", "azure"
                "region": "nyc1",
                "size": "s-2vcpu-4gb",
                "image": "docker-20-04",
                "ssh_key_name": "mt5_ea_key",
                "api_token": "",
                "aws_access_key": "",
                "aws_secret_key": "",
                "gcp_project_id": "",
                "azure_subscription_id": ""
            },
            "server": {
                "hostname": "mt5-ea-server",
                "username": "root",
                "ssh_key_path": "~/.ssh/id_rsa",
                "ssh_port": 22,
                "firewall": {
                    "allow_ssh": true,
                    "allow_http": true,
                    "allow_https": true,
                    "allow_mt5": true,
                    "allow_custom_ports": [8080, 8443, 5900]
                }
            },
            "docker": {
                "mt5_image": "mt5:latest",
                "web_image": "nginx:latest",
                "db_image": "postgres:13",
                "network_name": "mt5_network",
                "volume_name": "mt5_data",
                "mt5_container_name": "mt5_ea",
                "web_container_name": "mt5_web",
                "db_container_name": "mt5_db"
            },
            "mt5": {
                "version": "5.0.0.0",
                "terminal_path": "/opt/mt5",
                "wine_version": "stable",
                "account_server": "",
                "account_login": 0,
                "account_password": "",
                "account_type": "demo",  # "demo" ou "real"
                "ea_path": "/opt/mt5/MQL5/Experts/TapeReadingEA",
                "symbols": ["EURUSD", "GBPUSD", "USDJPY"],
                "timeframes": ["M1", "M5", "M15"]
            },
            "web": {
                "domain": "",
                "ssl": true,
                "port": 443,
                "auth_enabled": true,
                "username": "admin",
                "password": "admin",
                "jwt_secret": "",
                "session_timeout": 3600
            },
            "backup": {
                "enabled": true,
                "interval_hours": 24,
                "retention_days": 7,
                "s3_bucket": "",
                "s3_region": "us-east-1",
                "local_path": "/backup"
            },
            "monitoring": {
                "enabled": true,
                "interval_minutes": 5,
                "alert_email": "",
                "alert_sms": "",
                "metrics": {
                    "cpu": true,
                    "memory": true,
                    "disk": true,
                    "network": true,
                    "mt5_status": true,
                    "ea_status": true,
                    "trading_status": true
                }
            },
            "security": {
                "fail2ban_enabled": true,
                "ufw_enabled": true,
                "ssh_key_only": true,
                "disable_root": false,
                "auto_updates": true,
                "ssl_grade": "A+"
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
        Salva a configuração do configurador de servidor VPS em um arquivo JSON.
        
        Args:
            file_path (str, optional): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for salva com sucesso, False caso contrário
        """
        if not file_path:
            file_path = self.config_file or "mt5_cloud_setup_config.json"
        
        try:
            # Remover informações sensíveis antes de salvar
            config_to_save = self.config.copy()
            if "cloud" in config_to_save:
                if "api_token" in config_to_save["cloud"]:
                    config_to_save["cloud"]["api_token"] = ""
                if "aws_access_key" in config_to_save["cloud"]:
                    config_to_save["cloud"]["aws_access_key"] = ""
                if "aws_secret_key" in config_to_save["cloud"]:
                    config_to_save["cloud"]["aws_secret_key"] = ""
            
            if "mt5" in config_to_save:
                if "account_password" in config_to_save["mt5"]:
                    config_to_save["mt5"]["account_password"] = ""
            
            if "web" in config_to_save:
                if "password" in config_to_save["web"]:
                    config_to_save["web"]["password"] = ""
                if "jwt_secret" in config_to_save["web"]:
                    config_to_save["web"]["jwt_secret"] = ""
            
            with open(file_path, "w") as f:
                json.dump(config_to_save, f, indent=4)
            
            logger.info(f"Configuração salva em {file_path}")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}")
            return False
    
    def create_server(self):
        """
        Cria um servidor VPS na nuvem.
        
        Returns:
            bool: True se o servidor for criado com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            cloud_config = self.config["cloud"]
            provider = cloud_config["provider"]
            
            logger.info(f"Criando servidor VPS no provedor: {provider}")
            
            # Criar servidor de acordo com o provedor
            if provider == "digitalocean":
                return self._create_digitalocean_server()
            elif provider == "aws":
                return self._create_aws_server()
            elif provider == "gcp":
                return self._create_gcp_server()
            elif provider == "azure":
                return self._create_azure_server()
            else:
                logger.error(f"Provedor de nuvem não suportado: {provider}")
                return False
        except Exception as e:
            logger.error(f"Erro ao criar servidor VPS: {e}")
            return False
    
    def _create_digitalocean_server(self):
        """
        Cria um servidor VPS no DigitalOcean.
        
        Returns:
            bool: True se o servidor for criado com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            cloud_config = self.config["cloud"]
            server_config = self.config["server"]
            
            # Verificar token de API
            if not cloud_config["api_token"]:
                logger.error("Token de API do DigitalOcean não configurado")
                return False
            
            # Criar cliente do DigitalOcean
            manager = digitalocean.Manager(token=cloud_config["api_token"])
            
            # Verificar chave SSH
            ssh_keys = manager.get_all_sshkeys()
            ssh_key_id = None
            
            for key in ssh_keys:
                if key.name == cloud_config["ssh_key_name"]:
                    ssh_key_id = key.id
                    break
            
            if not ssh_key_id:
                # Criar nova chave SSH
                ssh_key_path = os.path.expanduser(server_config["ssh_key_path"])
                public_key_path = f"{ssh_key_path}.pub"
                
                if not os.path.exists(public_key_path):
                    logger.error(f"Chave pública SSH não encontrada: {public_key_path}")
                    return False
                
                with open(public_key_path, "r") as f:
                    public_key = f.read().strip()
                
                key = digitalocean.SSHKey(
                    token=cloud_config["api_token"],
                    name=cloud_config["ssh_key_name"],
                    public_key=public_key
                )
                key.create()
                ssh_key_id = key.id
            
            # Criar droplet
            droplet = digitalocean.Droplet(
                token=cloud_config["api_token"],
                name=server_config["hostname"],
                region=cloud_config["region"],
                image=cloud_config["image"],
                size_slug=cloud_config["size"],
                ssh_keys=[ssh_key_id],
                backups=False,
                ipv6=True,
                private_networking=True,
                monitoring=True
            )
            
            # Criar droplet
            droplet.create()
            
            # Aguardar criação do droplet
            logger.info("Aguardando criação do servidor...")
            
            # Aguardar até 5 minutos
            for _ in range(30):
                # Atualizar status do droplet
                actions = droplet.get_actions()
                for action in actions:
                    action.load()
                    if action.status == "completed":
                        # Obter informações do droplet
                        droplet.load()
                        self.server_ip = droplet.ip_address
                        self.server_id = droplet.id
                        self.server_status = "created"
                        
                        logger.info(f"Servidor criado com sucesso: {self.server_ip}")
                        return True
                
                # Aguardar 10 segundos
                time.sleep(10)
            
            logger.error("Timeout ao aguardar criação do servidor")
            return False
        except Exception as e:
            logger.error(f"Erro ao criar servidor no DigitalOcean: {e}")
            return False
    
    def _create_aws_server(self):
        """
        Cria um servidor VPS na AWS.
        
        Returns:
            bool: True se o servidor for criado com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            cloud_config = self.config["cloud"]
            server_config = self.config["server"]
            
            # Verificar credenciais da AWS
            if not cloud_config["aws_access_key"] or not cloud_config["aws_secret_key"]:
                logger.error("Credenciais da AWS não configuradas")
                return False
            
            # Criar cliente EC2
            ec2 = boto3.resource(
                'ec2',
                region_name=cloud_config["region"],
                aws_access_key_id=cloud_config["aws_access_key"],
                aws_secret_access_key=cloud_config["aws_secret_key"]
            )
            
            # Verificar chave SSH
            try:
                key_pair = ec2.KeyPair(cloud_config["ssh_key_name"])
                key_pair.load()
            except ClientError:
                # Criar nova chave SSH
                ssh_key_path = os.path.expanduser(server_config["ssh_key_path"])
                public_key_path = f"{ssh_key_path}.pub"
                
                if not os.path.exists(public_key_path):
                    logger.error(f"Chave pública SSH não encontrada: {public_key_path}")
                    return False
                
                with open(public_key_path, "r") as f:
                    public_key = f.read().strip()
                
                ec2.import_key_pair(
                    KeyName=cloud_config["ssh_key_name"],
                    PublicKeyMaterial=public_key
                )
            
            # Criar grupo de segurança
            try:
                security_group = ec2.create_security_group(
                    GroupName=f"{server_config['hostname']}-sg",
                    Description=f"Security group for {server_config['hostname']}"
                )
                
                # Configurar regras de firewall
                firewall_config = server_config["firewall"]
                
                if firewall_config["allow_ssh"]:
                    security_group.authorize_ingress(
                        IpProtocol="tcp",
                        FromPort=server_config["ssh_port"],
                        ToPort=server_config["ssh_port"],
                        CidrIp="0.0.0.0/0"
                    )
                
                if firewall_config["allow_http"]:
                    security_group.authorize_ingress(
                        IpProtocol="tcp",
                        FromPort=80,
                        ToPort=80,
                        CidrIp="0.0.0.0/0"
                    )
                
                if firewall_config["allow_https"]:
                    security_group.authorize_ingress(
                        IpProtocol="tcp",
                        FromPort=443,
                        ToPort=443,
                        CidrIp="0.0.0.0/0"
                    )
                
                if firewall_config["allow_mt5"]:
                    security_group.authorize_ingress(
                        IpProtocol="tcp",
                        FromPort=443,
                        ToPort=443,
                        CidrIp="0.0.0.0/0"
                    )
                
                for port in firewall_config["allow_custom_ports"]:
                    security_group.authorize_ingress(
                        IpProtocol="tcp",
                        FromPort=port,
                        ToPort=port,
                        CidrIp="0.0.0.0/0"
                    )
                
                security_group_id = security_group.id
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidGroup.Duplicate':
                    # Grupo de segurança já existe
                    security_groups = list(ec2.security_groups.filter(
                        Filters=[{'Name': 'group-name', 'Values': [f"{server_config['hostname']}-sg"]}]
                    ))
                    if security_groups:
                        security_group_id = security_groups[0].id
                    else:
                        logger.error("Grupo de segurança duplicado, mas não encontrado")
                        return False
                else:
                    raise
            
            # Criar instância EC2
            instances = ec2.create_instances(
                ImageId=cloud_config["image"],
                MinCount=1,
                MaxCount=1,
                InstanceType=cloud_config["size"],
                KeyName=cloud_config["ssh_key_name"],
                SecurityGroupIds=[security_group_id],
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': [
                            {
                                'Key': 'Name',
                                'Value': server_config["hostname"]
                            }
                        ]
                    }
                ]
            )
            
            instance = instances[0]
            
            # Aguardar inicialização da instância
            logger.info("Aguardando inicialização do servidor...")
            instance.wait_until_running()
            
            # Recarregar instância para obter IP público
            instance.reload()
            
            # Obter IP público
            self.server_ip = instance.public_ip_address
            self.server_id = instance.id
            self.server_status = "created"
            
            logger.info(f"Servidor criado com sucesso: {self.server_ip}")
            return True
        except Exception as e:
            logger.error(f"Erro ao criar servidor na AWS: {e}")
            return False
    
    def _create_gcp_server(self):
        """
        Cria um servidor VPS no Google Cloud Platform.
        
        Returns:
            bool: True se o servidor for criado com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            cloud_config = self.config["cloud"]
            server_config = self.config["server"]
            
            # Verificar projeto do GCP
            if not cloud_config["gcp_project_id"]:
                logger.error("ID do projeto do GCP não configurado")
                return False
            
            # Criar cliente de instâncias
            instance_client = compute_v1.InstancesClient()
            
            # Criar instância
            instance = compute_v1.Instance()
            instance.name = server_config["hostname"]
            instance.machine_type = f"zones/{cloud_config['region']}/machineTypes/{cloud_config['size']}"
            
            # Configurar disco de inicialização
            disk = compute_v1.AttachedDisk()
            disk.auto_delete = True
            disk.boot = True
            
            initialize_params = compute_v1.AttachedDiskInitializeParams()
            initialize_params.source_image = f"projects/debian-cloud/global/images/family/{cloud_config['image']}"
            initialize_params.disk_size_gb = 20
            
            disk.initialize_params = initialize_params
            instance.disks = [disk]
            
            # Configurar rede
            network_interface = compute_v1.NetworkInterface()
            network_interface.name = "global/networks/default"
            
            access_config = compute_v1.AccessConfig()
            access_config.name = "External NAT"
            access_config.type_ = "ONE_TO_ONE_NAT"
            access_config.network_tier = "PREMIUM"
            
            network_interface.access_configs = [access_config]
            instance.network_interfaces = [network_interface]
            
            # Configurar metadados
            ssh_key_path = os.path.expanduser(server_config["ssh_key_path"])
            public_key_path = f"{ssh_key_path}.pub"
            
            if not os.path.exists(public_key_path):
                logger.error(f"Chave pública SSH não encontrada: {public_key_path}")
                return False
            
            with open(public_key_path, "r") as f:
                public_key = f.read().strip()
            
            metadata = compute_v1.Metadata()
            metadata.items = [
                compute_v1.Items(
                    key="ssh-keys",
                    value=f"{server_config['username']}:{public_key}"
                )
            ]
            instance.metadata = metadata
            
            # Criar instância
            operation = instance_client.insert(
                project=cloud_config["gcp_project_id"],
                zone=cloud_config["region"],
                instance_resource=instance
            )
            
            # Aguardar criação da instância
            logger.info("Aguardando criação do servidor...")
            
            # Aguardar conclusão da operação
            while not operation.status == "DONE":
                time.sleep(5)
                operation = instance_client.get(
                    project=cloud_config["gcp_project_id"],
                    zone=cloud_config["region"],
                    operation=operation.name
                )
            
            # Obter instância criada
            instance = instance_client.get(
                project=cloud_config["gcp_project_id"],
                zone=cloud_config["region"],
                instance=server_config["hostname"]
            )
            
            # Obter IP público
            self.server_ip = instance.network_interfaces[0].access_configs[0].nat_ip
            self.server_id = instance.id
            self.server_status = "created"
            
            logger.info(f"Servidor criado com sucesso: {self.server_ip}")
            return True
        except Exception as e:
            logger.error(f"Erro ao criar servidor no GCP: {e}")
            return False
    
    def _create_azure_server(self):
        """
        Cria um servidor VPS no Microsoft Azure.
        
        Returns:
            bool: True se o servidor for criado com sucesso, False caso contrário
        """
        # Implementação simplificada para Azure
        # Em um sistema real, seria necessário implementar a criação de VM no Azure
        logger.error("Criação de servidor no Azure não implementada")
        return False
    
    def connect_to_server(self):
        """
        Conecta ao servidor VPS via SSH.
        
        Returns:
            bool: True se a conexão for estabelecida com sucesso, False caso contrário
        """
        try:
            # Verificar se o servidor foi criado
            if not self.server_ip:
                logger.error("Servidor não criado")
                return False
            
            # Obter configuração
            server_config = self.config["server"]
            
            # Expandir caminho da chave SSH
            ssh_key_path = os.path.expanduser(server_config["ssh_key_path"])
            
            # Verificar se a chave SSH existe
            if not os.path.exists(ssh_key_path):
                logger.error(f"Chave SSH não encontrada: {ssh_key_path}")
                return False
            
            # Criar cliente SSH
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Aguardar servidor estar pronto para conexão SSH
            logger.info(f"Aguardando servidor estar pronto para conexão SSH: {self.server_ip}")
            
            # Tentar conectar várias vezes (até 5 minutos)
            for attempt in range(30):
                try:
                    self.ssh_client.connect(
                        hostname=self.server_ip,
                        port=server_config["ssh_port"],
                        username=server_config["username"],
                        key_filename=ssh_key_path,
                        timeout=10
                    )
                    
                    logger.info(f"Conexão SSH estabelecida com sucesso: {self.server_ip}")
                    return True
                except Exception as e:
                    logger.warning(f"Tentativa {attempt+1} falhou: {e}")
                    time.sleep(10)
            
            logger.error(f"Falha ao conectar ao servidor após várias tentativas: {self.server_ip}")
            return False
        except Exception as e:
            logger.error(f"Erro ao conectar ao servidor: {e}")
            return False
    
    def setup_server(self):
        """
        Configura o servidor VPS.
        
        Returns:
            bool: True se o servidor for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            logger.info("Configurando servidor...")
            
            # Atualizar pacotes
            self._run_ssh_command("apt-get update")
            self._run_ssh_command("apt-get upgrade -y")
            
            # Instalar dependências
            self._run_ssh_command("apt-get install -y apt-transport-https ca-certificates curl software-properties-common")
            
            # Instalar Docker
            self._run_ssh_command("curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -")
            self._run_ssh_command('add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"')
            self._run_ssh_command("apt-get update")
            self._run_ssh_command("apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose")
            
            # Configurar firewall
            self._configure_firewall()
            
            # Configurar segurança
            self._configure_security()
            
            # Criar diretórios
            self._run_ssh_command("mkdir -p /opt/mt5-ea")
            self._run_ssh_command("mkdir -p /opt/mt5-ea/config")
            self._run_ssh_command("mkdir -p /opt/mt5-ea/data")
            self._run_ssh_command("mkdir -p /opt/mt5-ea/logs")
            self._run_ssh_command("mkdir -p /opt/mt5-ea/backup")
            
            # Criar rede Docker
            self._run_ssh_command(f"docker network create {self.config['docker']['network_name']}")
            
            logger.info("Servidor configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar servidor: {e}")
            return False
    
    def _configure_firewall(self):
        """
        Configura o firewall do servidor.
        
        Returns:
            bool: True se o firewall for configurado com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            server_config = self.config["server"]
            firewall_config = server_config["firewall"]
            
            # Instalar UFW
            self._run_ssh_command("apt-get install -y ufw")
            
            # Configurar regras de firewall
            self._run_ssh_command("ufw default deny incoming")
            self._run_ssh_command("ufw default allow outgoing")
            
            if firewall_config["allow_ssh"]:
                self._run_ssh_command(f"ufw allow {server_config['ssh_port']}/tcp")
            
            if firewall_config["allow_http"]:
                self._run_ssh_command("ufw allow 80/tcp")
            
            if firewall_config["allow_https"]:
                self._run_ssh_command("ufw allow 443/tcp")
            
            if firewall_config["allow_mt5"]:
                self._run_ssh_command("ufw allow 443/tcp")
            
            for port in firewall_config["allow_custom_ports"]:
                self._run_ssh_command(f"ufw allow {port}/tcp")
            
            # Habilitar UFW
            self._run_ssh_command("echo 'y' | ufw enable")
            
            logger.info("Firewall configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar firewall: {e}")
            return False
    
    def _configure_security(self):
        """
        Configura a segurança do servidor.
        
        Returns:
            bool: True se a segurança for configurada com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            security_config = self.config["security"]
            
            # Instalar fail2ban
            if security_config["fail2ban_enabled"]:
                self._run_ssh_command("apt-get install -y fail2ban")
                self._run_ssh_command("systemctl enable fail2ban")
                self._run_ssh_command("systemctl start fail2ban")
            
            # Configurar atualizações automáticas
            if security_config["auto_updates"]:
                self._run_ssh_command("apt-get install -y unattended-upgrades")
                self._run_ssh_command("dpkg-reconfigure -plow unattended-upgrades")
            
            # Desabilitar login como root via SSH
            if security_config["disable_root"]:
                self._run_ssh_command("sed -i 's/PermitRootLogin yes/PermitRootLogin no/g' /etc/ssh/sshd_config")
                self._run_ssh_command("systemctl restart sshd")
            
            # Configurar autenticação por chave SSH apenas
            if security_config["ssh_key_only"]:
                self._run_ssh_command("sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/g' /etc/ssh/sshd_config")
                self._run_ssh_command("systemctl restart sshd")
            
            logger.info("Segurança configurada com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar segurança: {e}")
            return False
    
    def deploy_mt5(self):
        """
        Implanta o MetaTrader 5 no servidor.
        
        Returns:
            bool: True se o MT5 for implantado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            logger.info("Implantando MetaTrader 5...")
            
            # Obter configuração
            mt5_config = self.config["mt5"]
            docker_config = self.config["docker"]
            
            # Criar Dockerfile para MT5
            dockerfile_content = f"""FROM ubuntu:20.04

# Instalar dependências
RUN apt-get update && apt-get install -y \\
    wget \\
    unzip \\
    xvfb \\
    x11vnc \\
    xdotool \\
    wine \\
    wine32 \\
    winetricks \\
    && rm -rf /var/lib/apt/lists/*

# Configurar ambiente Wine
ENV WINEARCH=win32
ENV WINEPREFIX=/root/.wine
ENV DISPLAY=:1

# Baixar e instalar MetaTrader 5
RUN mkdir -p {mt5_config["terminal_path"]}
WORKDIR {mt5_config["terminal_path"]}
RUN wget -q https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe
RUN xvfb-run -a wine mt5setup.exe /auto

# Copiar arquivos do EA
RUN mkdir -p {mt5_config["ea_path"]}
COPY ./mt5_tape_reading_ea.py {mt5_config["ea_path"]}/
COPY ./mt5_risk_manager.py {mt5_config["ea_path"]}/
COPY ./mt5_replicator.py {mt5_config["ea_path"]}/
COPY ./mt5_integration.py {mt5_config["ea_path"]}/
COPY ./mt5_performance.py {mt5_config["ea_path"]}/
COPY ./mt5_auth.py {mt5_config["ea_path"]}/
COPY ./mt5_test.py {mt5_config["ea_path"]}/
COPY ./requirements.txt {mt5_config["ea_path"]}/

# Instalar dependências Python
RUN apt-get update && apt-get install -y python3 python3-pip
RUN pip3 install -r {mt5_config["ea_path"]}/requirements.txt

# Script de inicialização
COPY ./start_mt5.sh /start_mt5.sh
RUN chmod +x /start_mt5.sh

# Expor portas
EXPOSE 5900

# Comando de inicialização
CMD ["/start_mt5.sh"]
"""
            
            # Criar script de inicialização
            start_script_content = f"""#!/bin/bash
# Iniciar Xvfb
Xvfb :1 -screen 0 1280x1024x16 &

# Iniciar VNC server
x11vnc -display :1 -forever -nopw -quiet &

# Iniciar MetaTrader 5
cd {mt5_config["terminal_path"]}
wine terminal.exe /portable

# Manter container em execução
tail -f /dev/null
"""
            
            # Criar arquivos no servidor
            self._run_ssh_command(f"cat > /opt/mt5-ea/Dockerfile << 'EOL'\n{dockerfile_content}\nEOL")
            self._run_ssh_command(f"cat > /opt/mt5-ea/start_mt5.sh << 'EOL'\n{start_script_content}\nEOL")
            
            # Copiar arquivos para o servidor
            self._upload_files()
            
            # Construir imagem Docker
            self._run_ssh_command("cd /opt/mt5-ea && docker build -t mt5-ea .")
            
            # Executar container
            self._run_ssh_command(f"""
                docker run -d \\
                --name {docker_config["mt5_container_name"]} \\
                --network {docker_config["network_name"]} \\
                -p 5900:5900 \\
                -v /opt/mt5-ea/data:/data \\
                -v /opt/mt5-ea/logs:/logs \\
                mt5-ea
            """)
            
            # Obter ID do container
            stdout, stderr = self._run_ssh_command(f"docker ps -q -f name={docker_config['mt5_container_name']}")
            self.mt5_container_id = stdout.strip()
            
            if not self.mt5_container_id:
                logger.error("Falha ao obter ID do container MT5")
                return False
            
            logger.info(f"MetaTrader 5 implantado com sucesso: {self.mt5_container_id}")
            return True
        except Exception as e:
            logger.error(f"Erro ao implantar MetaTrader 5: {e}")
            return False
    
    def _upload_files(self):
        """
        Faz upload dos arquivos necessários para o servidor.
        
        Returns:
            bool: True se os arquivos forem enviados com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            logger.info("Enviando arquivos para o servidor...")
            
            # Abrir conexão SFTP
            sftp = self.ssh_client.open_sftp()
            
            # Enviar arquivos
            files_to_upload = [
                "mt5_tape_reading_ea.py",
                "mt5_risk_manager.py",
                "mt5_replicator.py",
                "mt5_integration.py",
                "mt5_performance.py",
                "mt5_auth.py",
                "mt5_test.py",
                "requirements.txt",
                "index.html"
            ]
            
            for file in files_to_upload:
                local_path = os.path.join(os.getcwd(), file)
                remote_path = f"/opt/mt5-ea/{file}"
                
                if os.path.exists(local_path):
                    sftp.put(local_path, remote_path)
                    logger.info(f"Arquivo enviado: {file}")
                else:
                    logger.warning(f"Arquivo não encontrado: {local_path}")
            
            # Fechar conexão SFTP
            sftp.close()
            
            logger.info("Arquivos enviados com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar arquivos: {e}")
            return False
    
    def deploy_web_interface(self):
        """
        Implanta a interface web no servidor.
        
        Returns:
            bool: True se a interface web for implantada com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            logger.info("Implantando interface web...")
            
            # Obter configuração
            web_config = self.config["web"]
            docker_config = self.config["docker"]
            
            # Criar Dockerfile para interface web
            dockerfile_content = """FROM nginx:alpine

# Copiar arquivos da interface web
COPY ./index.html /usr/share/nginx/html/
COPY ./assets /usr/share/nginx/html/assets

# Configurar Nginx
COPY ./nginx.conf /etc/nginx/conf.d/default.conf

# Expor portas
EXPOSE 80 443

# Comando de inicialização
CMD ["nginx", "-g", "daemon off;"]
"""
            
            # Criar configuração do Nginx
            nginx_config = f"""server {{
    listen 80;
    server_name _;
    
    location / {{
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }}
    
    location /api/ {{
        proxy_pass http://{docker_config["mt5_container_name"]}:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
            
            # Criar diretório para assets
            self._run_ssh_command("mkdir -p /opt/mt5-ea/web/assets")
            
            # Criar arquivos no servidor
            self._run_ssh_command(f"cat > /opt/mt5-ea/web/Dockerfile << 'EOL'\n{dockerfile_content}\nEOL")
            self._run_ssh_command(f"cat > /opt/mt5-ea/web/nginx.conf << 'EOL'\n{nginx_config}\nEOL")
            
            # Copiar index.html para o servidor
            sftp = self.ssh_client.open_sftp()
            local_path = os.path.join(os.getcwd(), "index.html")
            remote_path = "/opt/mt5-ea/web/index.html"
            
            if os.path.exists(local_path):
                sftp.put(local_path, remote_path)
                logger.info("Arquivo index.html enviado")
            else:
                logger.warning(f"Arquivo não encontrado: {local_path}")
            
            sftp.close()
            
            # Construir imagem Docker
            self._run_ssh_command("cd /opt/mt5-ea/web && docker build -t mt5-web .")
            
            # Executar container
            self._run_ssh_command(f"""
                docker run -d \\
                --name {docker_config["web_container_name"]} \\
                --network {docker_config["network_name"]} \\
                -p 80:80 \\
                -p 443:443 \\
                mt5-web
            """)
            
            # Obter ID do container
            stdout, stderr = self._run_ssh_command(f"docker ps -q -f name={docker_config['web_container_name']}")
            self.web_container_id = stdout.strip()
            
            if not self.web_container_id:
                logger.error("Falha ao obter ID do container Web")
                return False
            
            # Configurar SSL se habilitado
            if web_config["ssl"]:
                self._configure_ssl()
            
            logger.info(f"Interface web implantada com sucesso: {self.web_container_id}")
            return True
        except Exception as e:
            logger.error(f"Erro ao implantar interface web: {e}")
            return False
    
    def _configure_ssl(self):
        """
        Configura SSL para a interface web.
        
        Returns:
            bool: True se o SSL for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            web_config = self.config["web"]
            
            # Verificar se o domínio está configurado
            if not web_config["domain"]:
                logger.warning("Domínio não configurado, SSL não será configurado")
                return False
            
            logger.info(f"Configurando SSL para domínio: {web_config['domain']}")
            
            # Instalar Certbot
            self._run_ssh_command("apt-get install -y certbot python3-certbot-nginx")
            
            # Obter certificado SSL
            self._run_ssh_command(f"certbot --nginx -d {web_config['domain']} --non-interactive --agree-tos --email admin@{web_config['domain']}")
            
            logger.info("SSL configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar SSL: {e}")
            return False
    
    def setup_database(self):
        """
        Configura o banco de dados.
        
        Returns:
            bool: True se o banco de dados for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            logger.info("Configurando banco de dados...")
            
            # Obter configuração
            docker_config = self.config["docker"]
            
            # Executar container PostgreSQL
            self._run_ssh_command(f"""
                docker run -d \\
                --name {docker_config["db_container_name"]} \\
                --network {docker_config["network_name"]} \\
                -e POSTGRES_PASSWORD=postgres \\
                -e POSTGRES_USER=postgres \\
                -e POSTGRES_DB=mt5 \\
                -v /opt/mt5-ea/data/postgres:/var/lib/postgresql/data \\
                postgres:13
            """)
            
            # Obter ID do container
            stdout, stderr = self._run_ssh_command(f"docker ps -q -f name={docker_config['db_container_name']}")
            self.db_container_id = stdout.strip()
            
            if not self.db_container_id:
                logger.error("Falha ao obter ID do container PostgreSQL")
                return False
            
            # Aguardar inicialização do banco de dados
            time.sleep(10)
            
            # Criar tabelas
            self._run_ssh_command(f"""
                docker exec {docker_config["db_container_name"]} psql -U postgres -d mt5 -c "
                CREATE TABLE IF NOT EXISTS accounts (
                    id SERIAL PRIMARY KEY,
                    login INTEGER NOT NULL,
                    server VARCHAR(255) NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    type VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    ticket BIGINT NOT NULL,
                    account_id INTEGER REFERENCES accounts(id),
                    symbol VARCHAR(50) NOT NULL,
                    type INTEGER NOT NULL,
                    volume REAL NOT NULL,
                    price REAL NOT NULL,
                    sl REAL,
                    tp REAL,
                    profit REAL,
                    comment VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY,
                    ticket BIGINT NOT NULL,
                    account_id INTEGER REFERENCES accounts(id),
                    symbol VARCHAR(50) NOT NULL,
                    type INTEGER NOT NULL,
                    volume REAL NOT NULL,
                    open_price REAL NOT NULL,
                    current_price REAL,
                    sl REAL,
                    tp REAL,
                    profit REAL,
                    swap REAL,
                    comment VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS performance (
                    id SERIAL PRIMARY KEY,
                    account_id INTEGER REFERENCES accounts(id),
                    balance REAL,
                    equity REAL,
                    margin REAL,
                    free_margin REAL,
                    margin_level REAL,
                    profit REAL,
                    drawdown REAL,
                    win_rate REAL,
                    profit_factor REAL,
                    expectancy REAL,
                    sharpe_ratio REAL,
                    sortino_ratio REAL,
                    max_consecutive_wins INTEGER,
                    max_consecutive_losses INTEGER,
                    average_win REAL,
                    average_loss REAL,
                    largest_win REAL,
                    largest_loss REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                "
            """)
            
            logger.info("Banco de dados configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar banco de dados: {e}")
            return False
    
    def setup_monitoring(self):
        """
        Configura o monitoramento do sistema.
        
        Returns:
            bool: True se o monitoramento for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            monitoring_config = self.config["monitoring"]
            
            # Verificar se o monitoramento está habilitado
            if not monitoring_config["enabled"]:
                logger.info("Monitoramento desabilitado")
                return True
            
            logger.info("Configurando monitoramento...")
            
            # Criar script de monitoramento
            monitoring_script = f"""#!/bin/bash
# Script de monitoramento para o EA de Tape Reading

# Configuração
INTERVAL={monitoring_config["interval_minutes"]}
ALERT_EMAIL="{monitoring_config["alert_email"]}"
ALERT_SMS="{monitoring_config["alert_sms"]}"

# Função para enviar alerta
send_alert() {{
    local subject="$1"
    local message="$2"
    
    # Enviar e-mail
    if [ ! -z "$ALERT_EMAIL" ]; then
        echo "$message" | mail -s "$subject" "$ALERT_EMAIL"
    fi
    
    # Enviar SMS (implementação simplificada)
    if [ ! -z "$ALERT_SMS" ]; then
        echo "SMS alert would be sent to $ALERT_SMS: $subject"
    fi
    
    # Registrar alerta
    echo "$(date): $subject - $message" >> /opt/mt5-ea/logs/alerts.log
}}

# Loop principal
while true; do
    # Verificar CPU
    if [ "{monitoring_config["metrics"]["cpu"]}" = "true" ]; then
        CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\\([0-9.]*\\)%* id.*/\\1/" | awk '{{ print 100 - $1 }}')
        if (( $(echo "$CPU_USAGE > 90" | bc -l) )); then
            send_alert "CPU Usage Alert" "CPU usage is high: $CPU_USAGE%"
        fi
    fi
    
    # Verificar memória
    if [ "{monitoring_config["metrics"]["memory"]}" = "true" ]; then
        MEM_USAGE=$(free | grep Mem | awk '{{ print $3/$2 * 100.0 }}')
        if (( $(echo "$MEM_USAGE > 90" | bc -l) )); then
            send_alert "Memory Usage Alert" "Memory usage is high: $MEM_USAGE%"
        fi
    fi
    
    # Verificar disco
    if [ "{monitoring_config["metrics"]["disk"]}" = "true" ]; then
        DISK_USAGE=$(df -h / | awk '{{ print $5 }}' | tail -n 1 | sed 's/%//')
        if [ "$DISK_USAGE" -gt 90 ]; then
            send_alert "Disk Usage Alert" "Disk usage is high: $DISK_USAGE%"
        fi
    fi
    
    # Verificar status do MT5
    if [ "{monitoring_config["metrics"]["mt5_status"]}" = "true" ]; then
        MT5_RUNNING=$(docker ps -q -f name=mt5_ea)
        if [ -z "$MT5_RUNNING" ]; then
            send_alert "MT5 Status Alert" "MT5 container is not running"
            
            # Tentar reiniciar
            docker start mt5_ea
        fi
    fi
    
    # Verificar status do EA
    if [ "{monitoring_config["metrics"]["ea_status"]}" = "true" ]; then
        # Implementação simplificada
        EA_RUNNING=$(docker exec mt5_ea ps aux | grep python | grep -v grep | wc -l)
        if [ "$EA_RUNNING" -eq 0 ]; then
            send_alert "EA Status Alert" "EA is not running"
            
            # Tentar reiniciar
            docker exec mt5_ea python3 /opt/mt5/MQL5/Experts/TapeReadingEA/mt5_tape_reading_ea.py &
        fi
    fi
    
    # Verificar status de negociação
    if [ "{monitoring_config["metrics"]["trading_status"]}" = "true" ]; then
        # Implementação simplificada
        LAST_ORDER_TIME=$(docker exec mt5_db psql -U postgres -d mt5 -t -c "SELECT MAX(created_at) FROM orders")
        CURRENT_TIME=$(date +%s)
        LAST_ORDER_TIMESTAMP=$(date -d "$LAST_ORDER_TIME" +%s 2>/dev/null || echo 0)
        
        # Se não houver ordens nas últimas 24 horas e for dia útil
        if [ $((CURRENT_TIME - LAST_ORDER_TIMESTAMP)) -gt 86400 ]; then
            # Verificar se é dia útil (1-5, segunda a sexta)
            DAY_OF_WEEK=$(date +%u)
            if [ "$DAY_OF_WEEK" -ge 1 ] && [ "$DAY_OF_WEEK" -le 5 ]; then
                # Verificar hora do dia (horário de mercado, simplificado)
                HOUR_OF_DAY=$(date +%H)
                if [ "$HOUR_OF_DAY" -ge 9 ] && [ "$HOUR_OF_DAY" -le 17 ]; then
                    send_alert "Trading Status Alert" "No orders in the last 24 hours during market hours"
                fi
            fi
        fi
    fi
    
    # Aguardar próxima verificação
    sleep $((INTERVAL * 60))
done
"""
            
            # Criar arquivo no servidor
            self._run_ssh_command(f"cat > /opt/mt5-ea/monitoring.sh << 'EOL'\n{monitoring_script}\nEOL")
            self._run_ssh_command("chmod +x /opt/mt5-ea/monitoring.sh")
            
            # Instalar dependências
            self._run_ssh_command("apt-get install -y bc mailutils")
            
            # Configurar serviço systemd
            systemd_service = """[Unit]
Description=MT5 EA Monitoring Service
After=docker.service

[Service]
ExecStart=/opt/mt5-ea/monitoring.sh
Restart=always
User=root
Group=root
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
"""
            
            self._run_ssh_command(f"cat > /etc/systemd/system/mt5-monitoring.service << 'EOL'\n{systemd_service}\nEOL")
            self._run_ssh_command("systemctl daemon-reload")
            self._run_ssh_command("systemctl enable mt5-monitoring.service")
            self._run_ssh_command("systemctl start mt5-monitoring.service")
            
            logger.info("Monitoramento configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar monitoramento: {e}")
            return False
    
    def setup_backup(self):
        """
        Configura o backup automático.
        
        Returns:
            bool: True se o backup for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            backup_config = self.config["backup"]
            
            # Verificar se o backup está habilitado
            if not backup_config["enabled"]:
                logger.info("Backup desabilitado")
                return True
            
            logger.info("Configurando backup automático...")
            
            # Criar script de backup
            backup_script = f"""#!/bin/bash
# Script de backup para o EA de Tape Reading

# Configuração
BACKUP_DIR="{backup_config["local_path"]}"
RETENTION_DAYS={backup_config["retention_days"]}
S3_BUCKET="{backup_config["s3_bucket"]}"
S3_REGION="{backup_config["s3_region"]}"

# Criar diretório de backup
mkdir -p $BACKUP_DIR

# Data atual
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/mt5_backup_$DATE.tar.gz"

# Parar containers
docker stop mt5_ea mt5_web mt5_db

# Criar backup
tar -czf $BACKUP_FILE /opt/mt5-ea

# Iniciar containers
docker start mt5_db mt5_web mt5_ea

# Enviar para S3 se configurado
if [ ! -z "$S3_BUCKET" ]; then
    # Instalar AWS CLI se necessário
    if ! command -v aws &> /dev/null; then
        apt-get update
        apt-get install -y awscli
    fi
    
    # Enviar para S3
    aws s3 cp $BACKUP_FILE s3://$S3_BUCKET/backups/ --region $S3_REGION
fi

# Remover backups antigos
find $BACKUP_DIR -name "mt5_backup_*.tar.gz" -type f -mtime +$RETENTION_DAYS -delete

# Registrar backup
echo "$(date): Backup created: $BACKUP_FILE" >> /opt/mt5-ea/logs/backup.log
"""
            
            # Criar arquivo no servidor
            self._run_ssh_command(f"cat > /opt/mt5-ea/backup.sh << 'EOL'\n{backup_script}\nEOL")
            self._run_ssh_command("chmod +x /opt/mt5-ea/backup.sh")
            
            # Configurar cron job
            cron_job = f"0 0 */{backup_config['interval_hours'] // 24} * * /opt/mt5-ea/backup.sh > /dev/null 2>&1"
            self._run_ssh_command(f"(crontab -l 2>/dev/null; echo '{cron_job}') | crontab -")
            
            logger.info("Backup automático configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar backup automático: {e}")
            return False
    
    def _run_ssh_command(self, command):
        """
        Executa um comando SSH no servidor.
        
        Args:
            command (str): Comando a ser executado
            
        Returns:
            tuple: (stdout, stderr)
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return "", "Not connected"
            
            # Executar comando
            stdin, stdout, stderr = self.ssh_client.exec_command(command)
            
            # Obter saída
            stdout_str = stdout.read().decode("utf-8")
            stderr_str = stderr.read().decode("utf-8")
            
            # Registrar comando e saída
            logger.debug(f"Comando: {command}")
            if stdout_str:
                logger.debug(f"Saída: {stdout_str}")
            if stderr_str:
                logger.debug(f"Erro: {stderr_str}")
            
            return stdout_str, stderr_str
        except Exception as e:
            logger.error(f"Erro ao executar comando SSH: {e}")
            return "", str(e)
    
    def get_access_url(self):
        """
        Obtém a URL de acesso ao sistema.
        
        Returns:
            str: URL de acesso
        """
        try:
            # Verificar se o servidor foi criado
            if not self.server_ip:
                logger.error("Servidor não criado")
                return ""
            
            # Obter configuração
            web_config = self.config["web"]
            
            # Verificar se o domínio está configurado
            if web_config["domain"]:
                # Usar domínio
                if web_config["ssl"]:
                    return f"https://{web_config['domain']}"
                else:
                    return f"http://{web_config['domain']}"
            else:
                # Usar IP
                return f"http://{self.server_ip}"
        except Exception as e:
            logger.error(f"Erro ao obter URL de acesso: {e}")
            return ""
    
    def get_vnc_url(self):
        """
        Obtém a URL de acesso VNC ao MetaTrader 5.
        
        Returns:
            str: URL de acesso VNC
        """
        try:
            # Verificar se o servidor foi criado
            if not self.server_ip:
                logger.error("Servidor não criado")
                return ""
            
            # Retornar URL VNC
            return f"vnc://{self.server_ip}:5900"
        except Exception as e:
            logger.error(f"Erro ao obter URL de acesso VNC: {e}")
            return ""
    
    def get_server_status(self):
        """
        Obtém o status do servidor.
        
        Returns:
            dict: Status do servidor
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                return {
                    "server_ip": self.server_ip,
                    "server_id": self.server_id,
                    "server_status": self.server_status,
                    "connected": False,
                    "containers": {},
                    "system": {},
                    "timestamp": datetime.now().isoformat()
                }
            
            # Obter status dos containers
            stdout, stderr = self._run_ssh_command("docker ps -a --format '{{.Names}}:{{.Status}}'")
            
            containers = {}
            for line in stdout.strip().split("\n"):
                if line:
                    name, status = line.split(":", 1)
                    containers[name] = status
            
            # Obter status do sistema
            stdout, stderr = self._run_ssh_command("uptime")
            uptime = stdout.strip()
            
            stdout, stderr = self._run_ssh_command("free -m | grep Mem")
            memory = stdout.strip()
            
            stdout, stderr = self._run_ssh_command("df -h / | tail -n 1")
            disk = stdout.strip()
            
            # Obter URL de acesso
            access_url = self.get_access_url()
            vnc_url = self.get_vnc_url()
            
            return {
                "server_ip": self.server_ip,
                "server_id": self.server_id,
                "server_status": self.server_status,
                "connected": True,
                "containers": containers,
                "system": {
                    "uptime": uptime,
                    "memory": memory,
                    "disk": disk
                },
                "access_url": access_url,
                "vnc_url": vnc_url,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Erro ao obter status do servidor: {e}")
            return {
                "server_ip": self.server_ip,
                "server_id": self.server_id,
                "server_status": self.server_status,
                "connected": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def disconnect(self):
        """
        Desconecta do servidor.
        
        Returns:
            bool: True se a desconexão for bem-sucedida, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.info("Não conectado ao servidor")
                return True
            
            # Fechar conexão SSH
            self.ssh_client.close()
            self.ssh_client = None
            
            logger.info("Desconectado do servidor")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar do servidor: {e}")
            return False
    
    def destroy_server(self):
        """
        Destrói o servidor VPS.
        
        Returns:
            bool: True se o servidor for destruído com sucesso, False caso contrário
        """
        try:
            # Verificar se o servidor foi criado
            if not self.server_id:
                logger.error("Servidor não criado")
                return False
            
            # Obter configuração
            cloud_config = self.config["cloud"]
            provider = cloud_config["provider"]
            
            logger.info(f"Destruindo servidor VPS no provedor: {provider}")
            
            # Desconectar do servidor
            self.disconnect()
            
            # Destruir servidor de acordo com o provedor
            if provider == "digitalocean":
                return self._destroy_digitalocean_server()
            elif provider == "aws":
                return self._destroy_aws_server()
            elif provider == "gcp":
                return self._destroy_gcp_server()
            elif provider == "azure":
                return self._destroy_azure_server()
            else:
                logger.error(f"Provedor de nuvem não suportado: {provider}")
                return False
        except Exception as e:
            logger.error(f"Erro ao destruir servidor VPS: {e}")
            return False
    
    def _destroy_digitalocean_server(self):
        """
        Destrói um servidor VPS no DigitalOcean.
        
        Returns:
            bool: True se o servidor for destruído com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            cloud_config = self.config["cloud"]
            
            # Verificar token de API
            if not cloud_config["api_token"]:
                logger.error("Token de API do DigitalOcean não configurado")
                return False
            
            # Criar cliente do DigitalOcean
            manager = digitalocean.Manager(token=cloud_config["api_token"])
            
            # Obter droplet
            droplet = digitalocean.Droplet(
                token=cloud_config["api_token"],
                id=self.server_id
            )
            
            # Destruir droplet
            droplet.destroy()
            
            logger.info(f"Servidor destruído com sucesso: {self.server_id}")
            
            # Limpar variáveis
            self.server_ip = None
            self.server_id = None
            self.server_status = "destroyed"
            
            return True
        except Exception as e:
            logger.error(f"Erro ao destruir servidor no DigitalOcean: {e}")
            return False
    
    def _destroy_aws_server(self):
        """
        Destrói um servidor VPS na AWS.
        
        Returns:
            bool: True se o servidor for destruído com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            cloud_config = self.config["cloud"]
            
            # Verificar credenciais da AWS
            if not cloud_config["aws_access_key"] or not cloud_config["aws_secret_key"]:
                logger.error("Credenciais da AWS não configuradas")
                return False
            
            # Criar cliente EC2
            ec2 = boto3.resource(
                'ec2',
                region_name=cloud_config["region"],
                aws_access_key_id=cloud_config["aws_access_key"],
                aws_secret_access_key=cloud_config["aws_secret_key"]
            )
            
            # Obter instância
            instance = ec2.Instance(self.server_id)
            
            # Terminar instância
            instance.terminate()
            
            logger.info(f"Servidor destruído com sucesso: {self.server_id}")
            
            # Limpar variáveis
            self.server_ip = None
            self.server_id = None
            self.server_status = "destroyed"
            
            return True
        except Exception as e:
            logger.error(f"Erro ao destruir servidor na AWS: {e}")
            return False
    
    def _destroy_gcp_server(self):
        """
        Destrói um servidor VPS no Google Cloud Platform.
        
        Returns:
            bool: True se o servidor for destruído com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            cloud_config = self.config["cloud"]
            server_config = self.config["server"]
            
            # Verificar projeto do GCP
            if not cloud_config["gcp_project_id"]:
                logger.error("ID do projeto do GCP não configurado")
                return False
            
            # Criar cliente de instâncias
            instance_client = compute_v1.InstancesClient()
            
            # Excluir instância
            operation = instance_client.delete(
                project=cloud_config["gcp_project_id"],
                zone=cloud_config["region"],
                instance=server_config["hostname"]
            )
            
            # Aguardar conclusão da operação
            while not operation.status == "DONE":
                time.sleep(5)
                operation = instance_client.get(
                    project=cloud_config["gcp_project_id"],
                    zone=cloud_config["region"],
                    operation=operation.name
                )
            
            logger.info(f"Servidor destruído com sucesso: {self.server_id}")
            
            # Limpar variáveis
            self.server_ip = None
            self.server_id = None
            self.server_status = "destroyed"
            
            return True
        except Exception as e:
            logger.error(f"Erro ao destruir servidor no GCP: {e}")
            return False
    
    def _destroy_azure_server(self):
        """
        Destrói um servidor VPS no Microsoft Azure.
        
        Returns:
            bool: True se o servidor for destruído com sucesso, False caso contrário
        """
        # Implementação simplificada para Azure
        # Em um sistema real, seria necessário implementar a destruição de VM no Azure
        logger.error("Destruição de servidor no Azure não implementada")
        return False


# Função principal
def main():
    """
    Função principal para configurar um servidor VPS para o EA de Tape Reading.
    """
    # Verificar argumentos
    parser = argparse.ArgumentParser(description="Configurador de servidor VPS para o EA de Tape Reading")
    parser.add_argument("--config", help="Caminho para o arquivo de configuração")
    parser.add_argument("--create", action="store_true", help="Criar servidor VPS")
    parser.add_argument("--setup", action="store_true", help="Configurar servidor VPS")
    parser.add_argument("--deploy", action="store_true", help="Implantar EA de Tape Reading")
    parser.add_argument("--status", action="store_true", help="Obter status do servidor")
    parser.add_argument("--destroy", action="store_true", help="Destruir servidor VPS")
    args = parser.parse_args()
    
    # Criar configurador
    cloud_setup = MT5CloudSetup(args.config)
    
    try:
        # Criar servidor
        if args.create:
            if cloud_setup.create_server():
                print(f"Servidor criado com sucesso: {cloud_setup.server_ip}")
            else:
                print("Falha ao criar servidor")
                return 1
        
        # Configurar servidor
        if args.setup:
            # Conectar ao servidor
            if not cloud_setup.connect_to_server():
                print("Falha ao conectar ao servidor")
                return 1
            
            # Configurar servidor
            if not cloud_setup.setup_server():
                print("Falha ao configurar servidor")
                return 1
            
            print("Servidor configurado com sucesso")
        
        # Implantar EA
        if args.deploy:
            # Conectar ao servidor se necessário
            if not cloud_setup.ssh_client and not cloud_setup.connect_to_server():
                print("Falha ao conectar ao servidor")
                return 1
            
            # Implantar MetaTrader 5
            if not cloud_setup.deploy_mt5():
                print("Falha ao implantar MetaTrader 5")
                return 1
            
            # Implantar interface web
            if not cloud_setup.deploy_web_interface():
                print("Falha ao implantar interface web")
                return 1
            
            # Configurar banco de dados
            if not cloud_setup.setup_database():
                print("Falha ao configurar banco de dados")
                return 1
            
            # Configurar monitoramento
            if not cloud_setup.setup_monitoring():
                print("Falha ao configurar monitoramento")
                return 1
            
            # Configurar backup
            if not cloud_setup.setup_backup():
                print("Falha ao configurar backup")
                return 1
            
            # Obter URLs de acesso
            access_url = cloud_setup.get_access_url()
            vnc_url = cloud_setup.get_vnc_url()
            
            print(f"EA de Tape Reading implantado com sucesso")
            print(f"URL de acesso: {access_url}")
            print(f"URL de acesso VNC: {vnc_url}")
        
        # Obter status
        if args.status:
            # Conectar ao servidor se necessário
            if not cloud_setup.ssh_client:
                cloud_setup.connect_to_server()
            
            # Obter status
            status = cloud_setup.get_server_status()
            
            print(f"Status do servidor: {status['server_status']}")
            print(f"IP do servidor: {status['server_ip']}")
            
            if status['connected']:
                print("Containers:")
                for name, container_status in status['containers'].items():
                    print(f"  {name}: {container_status}")
                
                print("Sistema:")
                for key, value in status['system'].items():
                    print(f"  {key}: {value}")
                
                print(f"URL de acesso: {status['access_url']}")
                print(f"URL de acesso VNC: {status['vnc_url']}")
        
        # Destruir servidor
        if args.destroy:
            if cloud_setup.destroy_server():
                print("Servidor destruído com sucesso")
            else:
                print("Falha ao destruir servidor")
                return 1
        
        # Desconectar do servidor
        if cloud_setup.ssh_client:
            cloud_setup.disconnect()
        
        return 0
    except KeyboardInterrupt:
        print("Operação interrompida pelo usuário")
        
        # Desconectar do servidor
        if cloud_setup.ssh_client:
            cloud_setup.disconnect()
        
        return 1
    except Exception as e:
        print(f"Erro: {e}")
        
        # Desconectar do servidor
        if cloud_setup.ssh_client:
            cloud_setup.disconnect()
        
        return 1


# Executar se for o script principal
if __name__ == "__main__":
    sys.exit(main())
