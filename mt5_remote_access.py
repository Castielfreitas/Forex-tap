#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de configuração de acesso remoto seguro para o EA de Tape Reading.
Este módulo implementa a configuração de acesso remoto seguro para o servidor VPS.
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
        logging.FileHandler("mt5_remote_access.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5RemoteAccess")

class MT5RemoteAccess:
    """
    Classe para configurar acesso remoto seguro para o EA de Tape Reading.
    """
    
    def __init__(self, config_file=None):
        """
        Inicializa o configurador de acesso remoto.
        
        Args:
            config_file (str, optional): Caminho para o arquivo de configuração
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.ssh_client = None
        self.server_ip = None
        self.server_id = None
    
    def _load_config(self):
        """
        Carrega a configuração do configurador de acesso remoto.
        
        Returns:
            dict: Configuração do configurador de acesso remoto
        """
        default_config = {
            "server": {
                "ip": "",
                "hostname": "mt5-ea-server",
                "username": "root",
                "ssh_key_path": "~/.ssh/id_rsa",
                "ssh_port": 22
            },
            "remote_access": {
                "vpn": {
                    "enabled": True,
                    "type": "wireguard",  # "wireguard", "openvpn"
                    "port": 51820,
                    "clients": [
                        {
                            "name": "client1",
                            "email": ""
                        }
                    ]
                },
                "ssh": {
                    "enabled": True,
                    "port": 22,
                    "key_only": True,
                    "allowed_users": ["admin"],
                    "fail2ban": True
                },
                "web": {
                    "enabled": True,
                    "domain": "",
                    "ssl": True,
                    "port": 443,
                    "basic_auth": True,
                    "username": "admin",
                    "password": "admin",
                    "jwt": True,
                    "jwt_secret": "",
                    "rate_limit": True,
                    "max_requests": 100,
                    "cors": True,
                    "allowed_origins": ["*"]
                },
                "vnc": {
                    "enabled": True,
                    "port": 5900,
                    "password": "",
                    "ssl": True,
                    "web_client": True,
                    "web_port": 6080
                },
                "api": {
                    "enabled": True,
                    "port": 8080,
                    "ssl": True,
                    "auth": True,
                    "rate_limit": True,
                    "max_requests": 100,
                    "cors": True,
                    "allowed_origins": ["*"]
                }
            },
            "security": {
                "firewall": {
                    "enabled": True,
                    "default_policy": "deny",
                    "allowed_ips": [],
                    "allowed_ports": [22, 80, 443, 51820, 5900, 6080, 8080]
                },
                "ssl": {
                    "provider": "letsencrypt",
                    "email": "",
                    "auto_renew": True
                },
                "fail2ban": {
                    "enabled": True,
                    "max_retries": 5,
                    "ban_time": 3600,
                    "services": ["ssh", "web", "api"]
                },
                "updates": {
                    "enabled": True,
                    "auto_update": True,
                    "update_time": "03:00"
                }
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
        Salva a configuração do configurador de acesso remoto em um arquivo JSON.
        
        Args:
            file_path (str, optional): Caminho para o arquivo
            
        Returns:
            bool: True se a configuração for salva com sucesso, False caso contrário
        """
        if not file_path:
            file_path = self.config_file or "mt5_remote_access_config.json"
        
        try:
            # Remover informações sensíveis antes de salvar
            config_to_save = self.config.copy()
            
            if "remote_access" in config_to_save:
                if "web" in config_to_save["remote_access"]:
                    if "password" in config_to_save["remote_access"]["web"]:
                        config_to_save["remote_access"]["web"]["password"] = ""
                    if "jwt_secret" in config_to_save["remote_access"]["web"]:
                        config_to_save["remote_access"]["web"]["jwt_secret"] = ""
                
                if "vnc" in config_to_save["remote_access"]:
                    if "password" in config_to_save["remote_access"]["vnc"]:
                        config_to_save["remote_access"]["vnc"]["password"] = ""
            
            with open(file_path, "w") as f:
                json.dump(config_to_save, f, indent=4)
            
            logger.info(f"Configuração salva em {file_path}")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar configuração: {e}")
            return False
    
    def connect_to_server(self):
        """
        Conecta ao servidor VPS via SSH.
        
        Returns:
            bool: True se a conexão for estabelecida com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            server_config = self.config["server"]
            
            # Verificar se o IP do servidor está configurado
            if not server_config["ip"]:
                logger.error("IP do servidor não configurado")
                return False
            
            # Armazenar IP do servidor
            self.server_ip = server_config["ip"]
            
            # Expandir caminho da chave SSH
            ssh_key_path = os.path.expanduser(server_config["ssh_key_path"])
            
            # Verificar se a chave SSH existe
            if not os.path.exists(ssh_key_path):
                logger.error(f"Chave SSH não encontrada: {ssh_key_path}")
                return False
            
            # Criar cliente SSH
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Conectar ao servidor
            logger.info(f"Conectando ao servidor: {self.server_ip}")
            
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
            logger.error(f"Erro ao conectar ao servidor: {e}")
            return False
    
    def setup_vpn(self):
        """
        Configura VPN para acesso remoto seguro.
        
        Returns:
            bool: True se a VPN for configurada com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            vpn_config = self.config["remote_access"]["vpn"]
            
            # Verificar se a VPN está habilitada
            if not vpn_config["enabled"]:
                logger.info("VPN desabilitada")
                return True
            
            logger.info("Configurando VPN...")
            
            # Configurar VPN de acordo com o tipo
            if vpn_config["type"] == "wireguard":
                return self._setup_wireguard()
            elif vpn_config["type"] == "openvpn":
                return self._setup_openvpn()
            else:
                logger.error(f"Tipo de VPN não suportado: {vpn_config['type']}")
                return False
        except Exception as e:
            logger.error(f"Erro ao configurar VPN: {e}")
            return False
    
    def _setup_wireguard(self):
        """
        Configura WireGuard para acesso remoto seguro.
        
        Returns:
            bool: True se o WireGuard for configurado com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            vpn_config = self.config["remote_access"]["vpn"]
            
            logger.info("Configurando WireGuard...")
            
            # Instalar WireGuard
            self._run_ssh_command("apt-get update")
            self._run_ssh_command("apt-get install -y wireguard")
            
            # Criar diretório para configuração
            self._run_ssh_command("mkdir -p /etc/wireguard/clients")
            
            # Gerar chave privada do servidor
            self._run_ssh_command("wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key")
            
            # Obter chaves do servidor
            stdout, stderr = self._run_ssh_command("cat /etc/wireguard/server_private.key")
            server_private_key = stdout.strip()
            
            stdout, stderr = self._run_ssh_command("cat /etc/wireguard/server_public.key")
            server_public_key = stdout.strip()
            
            # Criar configuração do servidor
            server_config = f"""[Interface]
PrivateKey = {server_private_key}
Address = 10.0.0.1/24
ListenPort = {vpn_config['port']}
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
"""
            
            # Criar configurações dos clientes
            client_configs = {}
            
            for i, client in enumerate(vpn_config["clients"]):
                # Gerar chave privada do cliente
                self._run_ssh_command(f"wg genkey | tee /etc/wireguard/clients/{client['name']}_private.key | wg pubkey > /etc/wireguard/clients/{client['name']}_public.key")
                
                # Obter chaves do cliente
                stdout, stderr = self._run_ssh_command(f"cat /etc/wireguard/clients/{client['name']}_private.key")
                client_private_key = stdout.strip()
                
                stdout, stderr = self._run_ssh_command(f"cat /etc/wireguard/clients/{client['name']}_public.key")
                client_public_key = stdout.strip()
                
                # Adicionar cliente à configuração do servidor
                server_config += f"""
[Peer]
PublicKey = {client_public_key}
AllowedIPs = 10.0.0.{i+2}/32
"""
                
                # Criar configuração do cliente
                client_config = f"""[Interface]
PrivateKey = {client_private_key}
Address = 10.0.0.{i+2}/24
DNS = 8.8.8.8, 8.8.4.4

[Peer]
PublicKey = {server_public_key}
Endpoint = {self.server_ip}:{vpn_config['port']}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
                
                client_configs[client["name"]] = client_config
                
                # Salvar configuração do cliente
                self._run_ssh_command(f"echo '{client_config}' > /etc/wireguard/clients/{client['name']}.conf")
                
                # Gerar QR code para configuração do cliente
                self._run_ssh_command(f"apt-get install -y qrencode")
                self._run_ssh_command(f"qrencode -t ansiutf8 < /etc/wireguard/clients/{client['name']}.conf > /etc/wireguard/clients/{client['name']}.qr")
            
            # Salvar configuração do servidor
            self._run_ssh_command(f"echo '{server_config}' > /etc/wireguard/wg0.conf")
            
            # Configurar encaminhamento de pacotes
            self._run_ssh_command("echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf")
            self._run_ssh_command("sysctl -p")
            
            # Iniciar WireGuard
            self._run_ssh_command("systemctl enable wg-quick@wg0")
            self._run_ssh_command("systemctl start wg-quick@wg0")
            
            # Verificar status
            stdout, stderr = self._run_ssh_command("systemctl status wg-quick@wg0")
            
            if "Active: active" in stdout:
                logger.info("WireGuard configurado com sucesso")
                
                # Retornar configurações dos clientes
                return True
            else:
                logger.error(f"Falha ao iniciar WireGuard: {stdout}")
                return False
        except Exception as e:
            logger.error(f"Erro ao configurar WireGuard: {e}")
            return False
    
    def _setup_openvpn(self):
        """
        Configura OpenVPN para acesso remoto seguro.
        
        Returns:
            bool: True se o OpenVPN for configurado com sucesso, False caso contrário
        """
        try:
            logger.info("Configurando OpenVPN...")
            
            # Instalar OpenVPN
            self._run_ssh_command("apt-get update")
            self._run_ssh_command("apt-get install -y openvpn easy-rsa")
            
            # Configurar OpenVPN
            self._run_ssh_command("mkdir -p /etc/openvpn/easy-rsa")
            self._run_ssh_command("cp -r /usr/share/easy-rsa/* /etc/openvpn/easy-rsa/")
            
            # Configurar variáveis
            vars_content = """export EASYRSA_KEY_SIZE=2048
export EASYRSA_REQ_COUNTRY="US"
export EASYRSA_REQ_PROVINCE="California"
export EASYRSA_REQ_CITY="San Francisco"
export EASYRSA_REQ_ORG="MT5 EA"
export EASYRSA_REQ_EMAIL="admin@example.com"
export EASYRSA_REQ_OU="MT5 EA VPN"
export EASYRSA_CA_EXPIRE=3650
export EASYRSA_CERT_EXPIRE=3650
"""
            
            self._run_ssh_command(f"echo '{vars_content}' > /etc/openvpn/easy-rsa/vars")
            
            # Inicializar PKI
            self._run_ssh_command("cd /etc/openvpn/easy-rsa && ./easyrsa init-pki")
            
            # Construir CA
            self._run_ssh_command("cd /etc/openvpn/easy-rsa && ./easyrsa build-ca nopass")
            
            # Gerar certificado e chave do servidor
            self._run_ssh_command("cd /etc/openvpn/easy-rsa && ./easyrsa gen-req server nopass")
            self._run_ssh_command("cd /etc/openvpn/easy-rsa && ./easyrsa sign-req server server")
            
            # Gerar parâmetros Diffie-Hellman
            self._run_ssh_command("cd /etc/openvpn/easy-rsa && ./easyrsa gen-dh")
            
            # Gerar chave TLS Auth
            self._run_ssh_command("openvpn --genkey --secret /etc/openvpn/ta.key")
            
            # Copiar arquivos para diretório do OpenVPN
            self._run_ssh_command("cp /etc/openvpn/easy-rsa/pki/ca.crt /etc/openvpn/")
            self._run_ssh_command("cp /etc/openvpn/easy-rsa/pki/issued/server.crt /etc/openvpn/")
            self._run_ssh_command("cp /etc/openvpn/easy-rsa/pki/private/server.key /etc/openvpn/")
            self._run_ssh_command("cp /etc/openvpn/easy-rsa/pki/dh.pem /etc/openvpn/")
            
            # Criar configuração do servidor
            server_config = """port 1194
proto udp
dev tun
ca ca.crt
cert server.crt
key server.key
dh dh.pem
auth SHA256
cipher AES-256-CBC
tls-auth ta.key 0
server 10.8.0.0 255.255.255.0
ifconfig-pool-persist ipp.txt
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 8.8.8.8"
push "dhcp-option DNS 8.8.4.4"
keepalive 10 120
user nobody
group nogroup
persist-key
persist-tun
status openvpn-status.log
verb 3
"""
            
            self._run_ssh_command(f"echo '{server_config}' > /etc/openvpn/server.conf")
            
            # Configurar encaminhamento de pacotes
            self._run_ssh_command("echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf")
            self._run_ssh_command("sysctl -p")
            
            # Configurar NAT
            self._run_ssh_command("iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE")
            self._run_ssh_command("iptables-save > /etc/iptables.rules")
            
            # Criar script para restaurar regras de iptables
            iptables_script = """#!/bin/sh
iptables-restore < /etc/iptables.rules
exit 0
"""
            
            self._run_ssh_command(f"echo '{iptables_script}' > /etc/network/if-up.d/iptables")
            self._run_ssh_command("chmod +x /etc/network/if-up.d/iptables")
            
            # Iniciar OpenVPN
            self._run_ssh_command("systemctl enable openvpn@server")
            self._run_ssh_command("systemctl start openvpn@server")
            
            # Verificar status
            stdout, stderr = self._run_ssh_command("systemctl status openvpn@server")
            
            if "Active: active" in stdout:
                logger.info("OpenVPN configurado com sucesso")
                
                # Gerar configurações dos clientes
                self._generate_openvpn_clients()
                
                return True
            else:
                logger.error(f"Falha ao iniciar OpenVPN: {stdout}")
                return False
        except Exception as e:
            logger.error(f"Erro ao configurar OpenVPN: {e}")
            return False
    
    def _generate_openvpn_clients(self):
        """
        Gera configurações de clientes OpenVPN.
        
        Returns:
            bool: True se as configurações forem geradas com sucesso, False caso contrário
        """
        try:
            # Obter configuração
            vpn_config = self.config["remote_access"]["vpn"]
            
            # Criar diretório para configurações dos clientes
            self._run_ssh_command("mkdir -p /etc/openvpn/clients")
            
            # Criar script para gerar configurações dos clientes
            client_script = """#!/bin/bash
# Script para gerar configurações de clientes OpenVPN

# Verificar argumentos
if [ $# -ne 1 ]; then
    echo "Uso: $0 <nome_cliente>"
    exit 1
fi

# Variáveis
CLIENT=$1
OUTPUT_DIR="/etc/openvpn/clients"
EASYRSA_DIR="/etc/openvpn/easy-rsa"
CA_DIR="/etc/openvpn"

# Gerar certificado e chave do cliente
cd $EASYRSA_DIR
./easyrsa gen-req $CLIENT nopass
./easyrsa sign-req client $CLIENT

# Criar configuração do cliente
cat > $OUTPUT_DIR/$CLIENT.ovpn << EOF
client
dev tun
proto udp
remote SERVER_IP 1194
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
auth SHA256
cipher AES-256-CBC
key-direction 1
verb 3
EOF

# Adicionar certificados e chaves
echo "<ca>" >> $OUTPUT_DIR/$CLIENT.ovpn
cat $CA_DIR/ca.crt >> $OUTPUT_DIR/$CLIENT.ovpn
echo "</ca>" >> $OUTPUT_DIR/$CLIENT.ovpn

echo "<cert>" >> $OUTPUT_DIR/$CLIENT.ovpn
cat $EASYRSA_DIR/pki/issued/$CLIENT.crt >> $OUTPUT_DIR/$CLIENT.ovpn
echo "</cert>" >> $OUTPUT_DIR/$CLIENT.ovpn

echo "<key>" >> $OUTPUT_DIR/$CLIENT.ovpn
cat $EASYRSA_DIR/pki/private/$CLIENT.key >> $OUTPUT_DIR/$CLIENT.ovpn
echo "</key>" >> $OUTPUT_DIR/$CLIENT.ovpn

echo "<tls-auth>" >> $OUTPUT_DIR/$CLIENT.ovpn
cat $CA_DIR/ta.key >> $OUTPUT_DIR/$CLIENT.ovpn
echo "</tls-auth>" >> $OUTPUT_DIR/$CLIENT.ovpn

# Substituir IP do servidor
sed -i "s/SERVER_IP/$SERVER_IP/g" $OUTPUT_DIR/$CLIENT.ovpn

# Gerar QR code
apt-get install -y qrencode
qrencode -t ansiutf8 -o $OUTPUT_DIR/$CLIENT.qr < $OUTPUT_DIR/$CLIENT.ovpn

echo "Configuração do cliente $CLIENT gerada com sucesso!"
"""
            
            # Substituir IP do servidor
            client_script = client_script.replace("SERVER_IP", self.server_ip)
            
            # Salvar script
            self._run_ssh_command(f"echo '{client_script}' > /etc/openvpn/generate_client.sh")
            self._run_ssh_command("chmod +x /etc/openvpn/generate_client.sh")
            
            # Gerar configurações para cada cliente
            for client in vpn_config["clients"]:
                self._run_ssh_command(f"/etc/openvpn/generate_client.sh {client['name']}")
            
            logger.info("Configurações dos clientes OpenVPN geradas com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao gerar configurações dos clientes OpenVPN: {e}")
            return False
    
    def setup_ssh_access(self):
        """
        Configura acesso SSH seguro.
        
        Returns:
            bool: True se o acesso SSH for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            ssh_config = self.config["remote_access"]["ssh"]
            
            # Verificar se o acesso SSH está habilitado
            if not ssh_config["enabled"]:
                logger.info("Acesso SSH desabilitado")
                return True
            
            logger.info("Configurando acesso SSH seguro...")
            
            # Configurar SSH
            sshd_config = """# Configuração do SSH
Port {port}
Protocol 2
HostKey /etc/ssh/ssh_host_rsa_key
HostKey /etc/ssh/ssh_host_ecdsa_key
HostKey /etc/ssh/ssh_host_ed25519_key
UsePrivilegeSeparation yes
KeyRegenerationInterval 3600
ServerKeyBits 1024
SyslogFacility AUTH
LogLevel INFO
LoginGraceTime 120
PermitRootLogin {permit_root}
StrictModes yes
RSAAuthentication yes
PubkeyAuthentication yes
IgnoreRhosts yes
RhostsRSAAuthentication no
HostbasedAuthentication no
PermitEmptyPasswords no
ChallengeResponseAuthentication no
PasswordAuthentication {password_auth}
X11Forwarding yes
X11DisplayOffset 10
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
AcceptEnv LANG LC_*
Subsystem sftp /usr/lib/openssh/sftp-server
UsePAM yes
AllowUsers {allowed_users}
"""
            
            # Substituir valores
            sshd_config = sshd_config.format(
                port=ssh_config["port"],
                permit_root="without-password" if ssh_config["key_only"] else "yes",
                password_auth="no" if ssh_config["key_only"] else "yes",
                allowed_users=" ".join(ssh_config["allowed_users"])
            )
            
            # Salvar configuração
            self._run_ssh_command(f"echo '{sshd_config}' > /etc/ssh/sshd_config")
            
            # Configurar fail2ban se habilitado
            if ssh_config["fail2ban"]:
                self._run_ssh_command("apt-get install -y fail2ban")
                
                fail2ban_config = """[sshd]
enabled = true
port = {port}
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 3600
"""
                
                # Substituir valores
                fail2ban_config = fail2ban_config.format(port=ssh_config["port"])
                
                # Salvar configuração
                self._run_ssh_command(f"echo '{fail2ban_config}' > /etc/fail2ban/jail.d/ssh.conf")
                
                # Reiniciar fail2ban
                self._run_ssh_command("systemctl restart fail2ban")
            
            # Reiniciar SSH
            self._run_ssh_command("systemctl restart sshd")
            
            logger.info("Acesso SSH configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar acesso SSH: {e}")
            return False
    
    def setup_web_access(self):
        """
        Configura acesso web seguro.
        
        Returns:
            bool: True se o acesso web for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            web_config = self.config["remote_access"]["web"]
            
            # Verificar se o acesso web está habilitado
            if not web_config["enabled"]:
                logger.info("Acesso web desabilitado")
                return True
            
            logger.info("Configurando acesso web seguro...")
            
            # Instalar Nginx
            self._run_ssh_command("apt-get install -y nginx")
            
            # Configurar Nginx
            nginx_config = """server {
    listen {port};
    server_name {domain};
    
    {ssl_config}
    
    {auth_config}
    
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
        
        {cors_config}
        {rate_limit_config}
    }
    
    location /api/ {
        proxy_pass http://localhost:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        {cors_config}
        {rate_limit_config}
    }
    
    location /vnc/ {
        proxy_pass http://localhost:6080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        {cors_config}
        {rate_limit_config}
    }
}
"""
            
            # Configurar SSL
            ssl_config = ""
            if web_config["ssl"]:
                # Verificar se o domínio está configurado
                if not web_config["domain"]:
                    logger.warning("Domínio não configurado, SSL não será configurado")
                else:
                    # Instalar Certbot
                    self._run_ssh_command("apt-get install -y certbot python3-certbot-nginx")
                    
                    # Configurar SSL
                    ssl_config = """ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-SHA384;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload";
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";""".format(domain=web_config["domain"])
            
            # Configurar autenticação básica
            auth_config = ""
            if web_config["basic_auth"]:
                # Instalar apache2-utils
                self._run_ssh_command("apt-get install -y apache2-utils")
                
                # Criar arquivo de senha
                self._run_ssh_command(f"htpasswd -bc /etc/nginx/.htpasswd {web_config['username']} {web_config['password']}")
                
                # Configurar autenticação básica
                auth_config = """auth_basic "Restricted Area";
    auth_basic_user_file /etc/nginx/.htpasswd;"""
            
            # Configurar CORS
            cors_config = ""
            if web_config["cors"]:
                allowed_origins = " ".join(web_config["allowed_origins"])
                
                cors_config = f"""add_header 'Access-Control-Allow-Origin' '{allowed_origins}';
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS, PUT, DELETE';
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
        add_header 'Access-Control-Expose-Headers' 'Content-Length,Content-Range';
        
        if ($request_method = 'OPTIONS') {{
            add_header 'Access-Control-Allow-Origin' '{allowed_origins}';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS, PUT, DELETE';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
            add_header 'Access-Control-Max-Age' 1728000;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }}"""
            
            # Configurar limite de taxa
            rate_limit_config = ""
            if web_config["rate_limit"]:
                rate_limit_config = f"""limit_req_zone $binary_remote_addr zone=api_limit:10m rate={web_config['max_requests']}r/m;
        limit_req zone=api_limit burst=20 nodelay;"""
            
            # Substituir valores
            nginx_config = nginx_config.format(
                port=web_config["port"],
                domain=web_config["domain"] or "_",
                ssl_config=ssl_config,
                auth_config=auth_config,
                cors_config=cors_config,
                rate_limit_config=rate_limit_config
            )
            
            # Salvar configuração
            self._run_ssh_command(f"echo '{nginx_config}' > /etc/nginx/sites-available/default")
            
            # Obter certificado SSL se configurado
            if web_config["ssl"] and web_config["domain"]:
                self._run_ssh_command(f"certbot --nginx -d {web_config['domain']} --non-interactive --agree-tos --email admin@{web_config['domain']}")
            
            # Reiniciar Nginx
            self._run_ssh_command("systemctl restart nginx")
            
            logger.info("Acesso web configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar acesso web: {e}")
            return False
    
    def setup_vnc_access(self):
        """
        Configura acesso VNC seguro.
        
        Returns:
            bool: True se o acesso VNC for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            vnc_config = self.config["remote_access"]["vnc"]
            
            # Verificar se o acesso VNC está habilitado
            if not vnc_config["enabled"]:
                logger.info("Acesso VNC desabilitado")
                return True
            
            logger.info("Configurando acesso VNC seguro...")
            
            # Verificar se o container MT5 está em execução
            stdout, stderr = self._run_ssh_command("docker ps -q -f name=mt5_ea")
            mt5_container_id = stdout.strip()
            
            if not mt5_container_id:
                logger.error("Container MT5 não encontrado")
                return False
            
            # Configurar VNC no container MT5
            self._run_ssh_command(f"docker exec {mt5_container_id} apt-get update")
            self._run_ssh_command(f"docker exec {mt5_container_id} apt-get install -y x11vnc")
            
            # Configurar senha VNC
            if vnc_config["password"]:
                self._run_ssh_command(f"docker exec {mt5_container_id} x11vnc -storepasswd {vnc_config['password']} /root/.vnc/passwd")
            
            # Criar script de inicialização VNC
            vnc_script = f"""#!/bin/bash
# Script de inicialização do VNC

# Iniciar VNC
x11vnc -display :1 -forever -rfbport {vnc_config['port']} {'-rfbauth /root/.vnc/passwd' if vnc_config['password'] else '-nopw'} -quiet &

# Manter script em execução
tail -f /dev/null
"""
            
            # Salvar script no container
            self._run_ssh_command(f"docker exec {mt5_container_id} bash -c \"echo '{vnc_script}' > /start_vnc.sh\"")
            self._run_ssh_command(f"docker exec {mt5_container_id} chmod +x /start_vnc.sh")
            
            # Iniciar VNC
            self._run_ssh_command(f"docker exec -d {mt5_container_id} /start_vnc.sh")
            
            # Configurar cliente web VNC se habilitado
            if vnc_config["web_client"]:
                # Instalar noVNC
                self._run_ssh_command("apt-get install -y git")
                self._run_ssh_command("git clone https://github.com/novnc/noVNC.git /opt/novnc")
                self._run_ssh_command("git clone https://github.com/novnc/websockify /opt/novnc/utils/websockify")
                
                # Criar script de inicialização noVNC
                novnc_script = f"""#!/bin/bash
# Script de inicialização do noVNC

# Iniciar websockify
/opt/novnc/utils/websockify/run --web /opt/novnc {vnc_config['web_port']} localhost:{vnc_config['port']}
"""
                
                # Salvar script
                self._run_ssh_command(f"echo '{novnc_script}' > /opt/start_novnc.sh")
                self._run_ssh_command("chmod +x /opt/start_novnc.sh")
                
                # Criar serviço systemd
                novnc_service = """[Unit]
Description=noVNC Service
After=network.target

[Service]
ExecStart=/opt/start_novnc.sh
Restart=always
User=root
Group=root
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
"""
                
                # Salvar serviço
                self._run_ssh_command(f"echo '{novnc_service}' > /etc/systemd/system/novnc.service")
                
                # Iniciar serviço
                self._run_ssh_command("systemctl daemon-reload")
                self._run_ssh_command("systemctl enable novnc.service")
                self._run_ssh_command("systemctl start novnc.service")
            
            logger.info("Acesso VNC configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar acesso VNC: {e}")
            return False
    
    def setup_api_access(self):
        """
        Configura acesso API seguro.
        
        Returns:
            bool: True se o acesso API for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            api_config = self.config["remote_access"]["api"]
            
            # Verificar se o acesso API está habilitado
            if not api_config["enabled"]:
                logger.info("Acesso API desabilitado")
                return True
            
            logger.info("Configurando acesso API seguro...")
            
            # Verificar se o container MT5 está em execução
            stdout, stderr = self._run_ssh_command("docker ps -q -f name=mt5_ea")
            mt5_container_id = stdout.strip()
            
            if not mt5_container_id:
                logger.error("Container MT5 não encontrado")
                return False
            
            # Instalar dependências no container MT5
            self._run_ssh_command(f"docker exec {mt5_container_id} pip3 install flask flask-restful flask-cors flask-jwt-extended")
            
            # Criar API Flask
            api_script = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-

\"\"\"
API REST para o EA de Tape Reading.
\"\"\"

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_restful import Api, Resource
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/logs/api.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5API")

# Criar aplicação Flask
app = Flask(__name__)
api = Api(app)

# Configurar CORS
CORS(app, resources={r"/*": {"origins": "*"}})

# Configurar JWT
app.config["JWT_SECRET_KEY"] = "{jwt_secret}"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
jwt = JWTManager(app)

# Dados de usuários (em um sistema real, seria um banco de dados)
users = {{
    "{username}": {{
        "password": "{password}",
        "role": "admin"
    }}
}}

# Classe para autenticação
class Auth(Resource):
    def post(self):
        try:
            username = request.json.get("username", None)
            password = request.json.get("password", None)
            
            if not username or not password:
                return {{"message": "Credenciais inválidas"}}, 401
            
            user = users.get(username)
            
            if not user or user["password"] != password:
                return {{"message": "Credenciais inválidas"}}, 401
            
            access_token = create_access_token(identity=username)
            
            return {{"access_token": access_token}}, 200
        except Exception as e:
            logger.error(f"Erro na autenticação: {{e}}")
            return {{"message": "Erro interno"}}, 500

# Classe para status do sistema
class Status(Resource):
    @jwt_required()
    def get(self):
        try:
            # Obter status do sistema
            status = {{
                "server": {{
                    "uptime": os.popen("uptime").read().strip(),
                    "memory": os.popen("free -m | grep Mem").read().strip(),
                    "disk": os.popen("df -h / | tail -n 1").read().strip()
                }},
                "mt5": {{
                    "running": True,
                    "version": "5.0.0.0",
                    "connected": True,
                    "account": {{
                        "server": "MetaQuotes-Demo",
                        "login": 12345678,
                        "name": "Demo Account",
                        "balance": 10000.0,
                        "equity": 10000.0,
                        "margin": 0.0,
                        "free_margin": 10000.0,
                        "margin_level": 0.0
                    }}
                }},
                "ea": {{
                    "running": True,
                    "version": "1.0.0",
                    "status": "running",
                    "last_update": datetime.now().isoformat()
                }}
            }}
            
            return status, 200
        except Exception as e:
            logger.error(f"Erro ao obter status: {{e}}")
            return {{"message": "Erro interno"}}, 500

# Classe para ordens
class Orders(Resource):
    @jwt_required()
    def get(self):
        try:
            # Obter ordens (simulado)
            orders = [
                {{
                    "ticket": 1234567,
                    "symbol": "EURUSD",
                    "type": "BUY",
                    "volume": 0.1,
                    "open_price": 1.1000,
                    "close_price": 1.1050,
                    "sl": 1.0950,
                    "tp": 1.1100,
                    "profit": 50.0,
                    "comment": "Tape Reading EA",
                    "open_time": "2023-01-01T12:00:00",
                    "close_time": "2023-01-01T14:00:00"
                }},
                {{
                    "ticket": 1234568,
                    "symbol": "GBPUSD",
                    "type": "SELL",
                    "volume": 0.2,
                    "open_price": 1.3000,
                    "close_price": 1.2950,
                    "sl": 1.3050,
                    "tp": 1.2900,
                    "profit": 100.0,
                    "comment": "Tape Reading EA",
                    "open_time": "2023-01-02T10:00:00",
                    "close_time": "2023-01-02T12:00:00"
                }}
            ]
            
            return orders, 200
        except Exception as e:
            logger.error(f"Erro ao obter ordens: {{e}}")
            return {{"message": "Erro interno"}}, 500
    
    @jwt_required()
    def post(self):
        try:
            # Obter dados da ordem
            data = request.json
            
            # Validar dados
            required_fields = ["symbol", "type", "volume"]
            
            for field in required_fields:
                if field not in data:
                    return {{"message": f"Campo obrigatório: {{field}}"}}, 400
            
            # Criar ordem (simulado)
            order = {{
                "ticket": int(time.time()),
                "symbol": data["symbol"],
                "type": data["type"],
                "volume": data["volume"],
                "open_price": data.get("price", 0.0),
                "sl": data.get("sl", 0.0),
                "tp": data.get("tp", 0.0),
                "comment": data.get("comment", "API Order"),
                "open_time": datetime.now().isoformat()
            }}
            
            return order, 201
        except Exception as e:
            logger.error(f"Erro ao criar ordem: {{e}}")
            return {{"message": "Erro interno"}}, 500

# Classe para posições
class Positions(Resource):
    @jwt_required()
    def get(self):
        try:
            # Obter posições (simulado)
            positions = [
                {{
                    "ticket": 1234569,
                    "symbol": "EURUSD",
                    "type": "BUY",
                    "volume": 0.1,
                    "open_price": 1.1000,
                    "current_price": 1.1020,
                    "sl": 1.0950,
                    "tp": 1.1100,
                    "profit": 20.0,
                    "swap": 0.0,
                    "comment": "Tape Reading EA",
                    "open_time": "2023-01-03T10:00:00"
                }},
                {{
                    "ticket": 1234570,
                    "symbol": "USDJPY",
                    "type": "SELL",
                    "volume": 0.3,
                    "open_price": 110.00,
                    "current_price": 109.80,
                    "sl": 110.50,
                    "tp": 109.00,
                    "profit": 60.0,
                    "swap": -1.5,
                    "comment": "Tape Reading EA",
                    "open_time": "2023-01-03T11:00:00"
                }}
            ]
            
            return positions, 200
        except Exception as e:
            logger.error(f"Erro ao obter posições: {{e}}")
            return {{"message": "Erro interno"}}, 500

# Classe para desempenho
class Performance(Resource):
    @jwt_required()
    def get(self):
        try:
            # Obter desempenho (simulado)
            performance = {{
                "balance": 10000.0,
                "equity": 10080.0,
                "margin": 200.0,
                "free_margin": 9880.0,
                "margin_level": 5040.0,
                "profit": 80.0,
                "drawdown": 2.5,
                "win_rate": 65.0,
                "profit_factor": 1.8,
                "expectancy": 0.5,
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.5,
                "max_consecutive_wins": 5,
                "max_consecutive_losses": 2,
                "average_win": 50.0,
                "average_loss": -30.0,
                "largest_win": 100.0,
                "largest_loss": -85.0,
                "history": [
                    {{
                        "date": "2023-01-01",
                        "balance": 10000.0,
                        "equity": 10000.0,
                        "profit": 0.0
                    }},
                    {{
                        "date": "2023-01-02",
                        "balance": 10050.0,
                        "equity": 10050.0,
                        "profit": 50.0
                    }},
                    {{
                        "date": "2023-01-03",
                        "balance": 10080.0,
                        "equity": 10080.0,
                        "profit": 30.0
                    }}
                ]
            }}
            
            return performance, 200
        except Exception as e:
            logger.error(f"Erro ao obter desempenho: {{e}}")
            return {{"message": "Erro interno"}}, 500

# Classe para configuração
class Config(Resource):
    @jwt_required()
    def get(self):
        try:
            # Obter configuração (simulado)
            config = {{
                "ea": {{
                    "enabled": True,
                    "symbols": ["EURUSD", "GBPUSD", "USDJPY"],
                    "timeframes": ["M1", "M5", "M15"],
                    "magic_number": 123456,
                    "max_spread_points": 10,
                    "slippage_points": 5,
                    "comment": "Tape Reading EA"
                }},
                "tape_reading": {{
                    "volume_imbalance": {{
                        "enabled": True,
                        "threshold": 2.0,
                        "lookback_bars": 10,
                        "min_volume": 100
                    }},
                    "footprint": {{
                        "enabled": True,
                        "lookback_bars": 20,
                        "delta_threshold": 0.6
                    }},
                    "price_levels": {{
                        "enabled": True,
                        "volume_threshold": 1000,
                        "lookback_bars": 50
                    }},
                    "market_profile": {{
                        "enabled": True,
                        "lookback_bars": 100,
                        "value_area_percent": 70
                    }}
                }},
                "trading": {{
                    "enabled": True,
                    "max_positions": 5,
                    "max_positions_per_symbol": 2,
                    "default_volume": 0.01,
                    "use_risk_manager": True,
                    "entry_confirmation": {{
                        "required_signals": 2,
                        "min_score": 7
                    }}
                }},
                "risk_manager": {{
                    "max_daily_loss_percent": 3.0,
                    "max_weekly_loss_percent": 7.0,
                    "max_monthly_loss_percent": 15.0,
                    "max_drawdown_percent": 20.0,
                    "max_open_positions": 5,
                    "max_positions_per_symbol": 2,
                    "max_risk_per_trade_percent": 1.0,
                    "max_risk_per_symbol_percent": 3.0,
                    "max_daily_trades": 10,
                    "max_consecutive_losses": 3
                }},
                "replication": {{
                    "enabled": True,
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
                }}
            }}
            
            return config, 200
        except Exception as e:
            logger.error(f"Erro ao obter configuração: {{e}}")
            return {{"message": "Erro interno"}}, 500
    
    @jwt_required()
    def put(self):
        try:
            # Obter dados da configuração
            data = request.json
            
            # Validar dados (simplificado)
            if not isinstance(data, dict):
                return {{"message": "Dados inválidos"}}, 400
            
            # Atualizar configuração (simulado)
            return {{"message": "Configuração atualizada com sucesso"}}, 200
        except Exception as e:
            logger.error(f"Erro ao atualizar configuração: {{e}}")
            return {{"message": "Erro interno"}}, 500

# Classe para controle do EA
class Control(Resource):
    @jwt_required()
    def post(self):
        try:
            # Obter comando
            data = request.json
            command = data.get("command")
            
            if not command:
                return {{"message": "Comando não especificado"}}, 400
            
            # Executar comando (simulado)
            if command == "start":
                return {{"message": "EA iniciado com sucesso"}}, 200
            elif command == "stop":
                return {{"message": "EA parado com sucesso"}}, 200
            elif command == "restart":
                return {{"message": "EA reiniciado com sucesso"}}, 200
            else:
                return {{"message": f"Comando desconhecido: {{command}}"}}, 400
        except Exception as e:
            logger.error(f"Erro ao executar comando: {{e}}")
            return {{"message": "Erro interno"}}, 500

# Registrar recursos
api.add_resource(Auth, "/auth")
api.add_resource(Status, "/status")
api.add_resource(Orders, "/orders")
api.add_resource(Positions, "/positions")
api.add_resource(Performance, "/performance")
api.add_resource(Config, "/config")
api.add_resource(Control, "/control")

# Rota principal
@app.route("/")
def index():
    return jsonify({{"message": "MT5 Tape Reading EA API", "version": "1.0.0"}})

# Iniciar aplicação
if __name__ == "__main__":
    app.run(host="0.0.0.0", port={port}, debug=False)
"""
            
            # Substituir valores
            api_script = api_script.format(
                port=api_config["port"],
                jwt_secret=api_config.get("jwt_secret", "secret"),
                username=self.config["remote_access"]["web"]["username"],
                password=self.config["remote_access"]["web"]["password"]
            )
            
            # Salvar script no container
            self._run_ssh_command(f"docker exec {mt5_container_id} bash -c \"echo '{api_script}' > /api.py\"")
            self._run_ssh_command(f"docker exec {mt5_container_id} chmod +x /api.py")
            
            # Criar script de inicialização da API
            api_start_script = """#!/bin/bash
# Script de inicialização da API

# Iniciar API
python3 /api.py > /logs/api.log 2>&1 &

# Manter script em execução
tail -f /dev/null
"""
            
            # Salvar script no container
            self._run_ssh_command(f"docker exec {mt5_container_id} bash -c \"echo '{api_start_script}' > /start_api.sh\"")
            self._run_ssh_command(f"docker exec {mt5_container_id} chmod +x /start_api.sh")
            
            # Iniciar API
            self._run_ssh_command(f"docker exec -d {mt5_container_id} /start_api.sh")
            
            logger.info("Acesso API configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar acesso API: {e}")
            return False
    
    def setup_firewall(self):
        """
        Configura firewall para acesso remoto seguro.
        
        Returns:
            bool: True se o firewall for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            firewall_config = self.config["security"]["firewall"]
            
            # Verificar se o firewall está habilitado
            if not firewall_config["enabled"]:
                logger.info("Firewall desabilitado")
                return True
            
            logger.info("Configurando firewall...")
            
            # Instalar UFW
            self._run_ssh_command("apt-get install -y ufw")
            
            # Configurar política padrão
            self._run_ssh_command(f"ufw default {firewall_config['default_policy']} incoming")
            self._run_ssh_command("ufw default allow outgoing")
            
            # Permitir portas específicas
            for port in firewall_config["allowed_ports"]:
                self._run_ssh_command(f"ufw allow {port}/tcp")
            
            # Permitir IPs específicos
            for ip in firewall_config["allowed_ips"]:
                self._run_ssh_command(f"ufw allow from {ip}")
            
            # Habilitar UFW
            self._run_ssh_command("echo 'y' | ufw enable")
            
            logger.info("Firewall configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar firewall: {e}")
            return False
    
    def setup_ssl(self):
        """
        Configura SSL para acesso remoto seguro.
        
        Returns:
            bool: True se o SSL for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            ssl_config = self.config["security"]["ssl"]
            web_config = self.config["remote_access"]["web"]
            
            # Verificar se o domínio está configurado
            if not web_config["domain"]:
                logger.warning("Domínio não configurado, SSL não será configurado")
                return False
            
            logger.info(f"Configurando SSL para domínio: {web_config['domain']}")
            
            # Configurar SSL de acordo com o provedor
            if ssl_config["provider"] == "letsencrypt":
                # Instalar Certbot
                self._run_ssh_command("apt-get install -y certbot python3-certbot-nginx")
                
                # Obter certificado SSL
                self._run_ssh_command(f"certbot --nginx -d {web_config['domain']} --non-interactive --agree-tos --email {ssl_config['email']}")
                
                # Configurar renovação automática
                if ssl_config["auto_renew"]:
                    self._run_ssh_command("systemctl enable certbot.timer")
                    self._run_ssh_command("systemctl start certbot.timer")
            else:
                logger.error(f"Provedor de SSL não suportado: {ssl_config['provider']}")
                return False
            
            logger.info("SSL configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar SSL: {e}")
            return False
    
    def setup_fail2ban(self):
        """
        Configura Fail2Ban para acesso remoto seguro.
        
        Returns:
            bool: True se o Fail2Ban for configurado com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            fail2ban_config = self.config["security"]["fail2ban"]
            
            # Verificar se o Fail2Ban está habilitado
            if not fail2ban_config["enabled"]:
                logger.info("Fail2Ban desabilitado")
                return True
            
            logger.info("Configurando Fail2Ban...")
            
            # Instalar Fail2Ban
            self._run_ssh_command("apt-get install -y fail2ban")
            
            # Configurar Fail2Ban
            jail_local = f"""[DEFAULT]
bantime = {fail2ban_config['ban_time']}
maxretry = {fail2ban_config['max_retries']}
"""
            
            # Adicionar configuração para cada serviço
            if "ssh" in fail2ban_config["services"]:
                jail_local += """
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
"""
            
            if "web" in fail2ban_config["services"]:
                jail_local += """
[nginx-http-auth]
enabled = true
port = http,https
filter = nginx-http-auth
logpath = /var/log/nginx/error.log
"""
            
            if "api" in fail2ban_config["services"]:
                jail_local += """
[nginx-limit-req]
enabled = true
port = http,https
filter = nginx-limit-req
logpath = /var/log/nginx/error.log
"""
            
            # Salvar configuração
            self._run_ssh_command(f"echo '{jail_local}' > /etc/fail2ban/jail.local")
            
            # Reiniciar Fail2Ban
            self._run_ssh_command("systemctl restart fail2ban")
            
            logger.info("Fail2Ban configurado com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar Fail2Ban: {e}")
            return False
    
    def setup_auto_updates(self):
        """
        Configura atualizações automáticas para acesso remoto seguro.
        
        Returns:
            bool: True se as atualizações automáticas forem configuradas com sucesso, False caso contrário
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return False
            
            # Obter configuração
            updates_config = self.config["security"]["updates"]
            
            # Verificar se as atualizações automáticas estão habilitadas
            if not updates_config["enabled"]:
                logger.info("Atualizações automáticas desabilitadas")
                return True
            
            logger.info("Configurando atualizações automáticas...")
            
            # Instalar unattended-upgrades
            self._run_ssh_command("apt-get install -y unattended-upgrades apt-listchanges")
            
            # Configurar unattended-upgrades
            unattended_upgrades_config = """Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}";
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
    "${distro_id}:${distro_codename}-updates";
};

Unattended-Upgrade::Package-Blacklist {
};

Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "{update_time}";
"""
            
            # Substituir valores
            unattended_upgrades_config = unattended_upgrades_config.format(
                update_time=updates_config["update_time"]
            )
            
            # Salvar configuração
            self._run_ssh_command(f"echo '{unattended_upgrades_config}' > /etc/apt/apt.conf.d/50unattended-upgrades")
            
            # Habilitar unattended-upgrades
            auto_upgrades_config = """APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
"""
            
            # Salvar configuração
            self._run_ssh_command(f"echo '{auto_upgrades_config}' > /etc/apt/apt.conf.d/20auto-upgrades")
            
            logger.info("Atualizações automáticas configuradas com sucesso")
            return True
        except Exception as e:
            logger.error(f"Erro ao configurar atualizações automáticas: {e}")
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
    
    def get_access_info(self):
        """
        Obtém informações de acesso remoto.
        
        Returns:
            dict: Informações de acesso remoto
        """
        try:
            # Verificar se está conectado ao servidor
            if not self.ssh_client:
                logger.error("Não conectado ao servidor")
                return {}
            
            # Obter configuração
            remote_access_config = self.config["remote_access"]
            
            # Obter informações de acesso
            access_info = {
                "server": {
                    "ip": self.server_ip,
                    "hostname": self.config["server"]["hostname"]
                },
                "ssh": {
                    "enabled": remote_access_config["ssh"]["enabled"],
                    "port": remote_access_config["ssh"]["port"],
                    "username": self.config["server"]["username"],
                    "key_path": self.config["server"]["ssh_key_path"]
                },
                "web": {
                    "enabled": remote_access_config["web"]["enabled"],
                    "url": f"https://{remote_access_config['web']['domain']}" if remote_access_config["web"]["ssl"] else f"http://{self.server_ip}",
                    "username": remote_access_config["web"]["username"],
                    "password": "********"
                },
                "vpn": {
                    "enabled": remote_access_config["vpn"]["enabled"],
                    "type": remote_access_config["vpn"]["type"],
                    "clients": []
                },
                "vnc": {
                    "enabled": remote_access_config["vnc"]["enabled"],
                    "url": f"vnc://{self.server_ip}:{remote_access_config['vnc']['port']}",
                    "web_url": f"https://{remote_access_config['web']['domain']}/vnc/" if remote_access_config["web"]["ssl"] else f"http://{self.server_ip}/vnc/",
                    "password": "********"
                },
                "api": {
                    "enabled": remote_access_config["api"]["enabled"],
                    "url": f"https://{remote_access_config['web']['domain']}/api/" if remote_access_config["web"]["ssl"] else f"http://{self.server_ip}:{remote_access_config['api']['port']}",
                    "username": remote_access_config["web"]["username"],
                    "password": "********"
                }
            }
            
            # Obter configurações dos clientes VPN
            if remote_access_config["vpn"]["enabled"]:
                if remote_access_config["vpn"]["type"] == "wireguard":
                    # Obter configurações dos clientes WireGuard
                    for client in remote_access_config["vpn"]["clients"]:
                        # Obter configuração do cliente
                        stdout, stderr = self._run_ssh_command(f"cat /etc/wireguard/clients/{client['name']}.conf")
                        
                        # Obter QR code
                        qr_stdout, qr_stderr = self._run_ssh_command(f"cat /etc/wireguard/clients/{client['name']}.qr")
                        
                        access_info["vpn"]["clients"].append({
                            "name": client["name"],
                            "config": stdout,
                            "qr_code": qr_stdout
                        })
                elif remote_access_config["vpn"]["type"] == "openvpn":
                    # Obter configurações dos clientes OpenVPN
                    for client in remote_access_config["vpn"]["clients"]:
                        # Obter configuração do cliente
                        stdout, stderr = self._run_ssh_command(f"cat /etc/openvpn/clients/{client['name']}.ovpn")
                        
                        # Obter QR code
                        qr_stdout, qr_stderr = self._run_ssh_command(f"cat /etc/openvpn/clients/{client['name']}.qr")
                        
                        access_info["vpn"]["clients"].append({
                            "name": client["name"],
                            "config": stdout,
                            "qr_code": qr_stdout
                        })
            
            return access_info
        except Exception as e:
            logger.error(f"Erro ao obter informações de acesso: {e}")
            return {}
    
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


# Função principal
def main():
    """
    Função principal para configurar acesso remoto seguro para o EA de Tape Reading.
    """
    # Verificar argumentos
    parser = argparse.ArgumentParser(description="Configurador de acesso remoto seguro para o EA de Tape Reading")
    parser.add_argument("--config", help="Caminho para o arquivo de configuração")
    parser.add_argument("--server", help="IP do servidor")
    parser.add_argument("--setup-vpn", action="store_true", help="Configurar VPN")
    parser.add_argument("--setup-ssh", action="store_true", help="Configurar acesso SSH")
    parser.add_argument("--setup-web", action="store_true", help="Configurar acesso web")
    parser.add_argument("--setup-vnc", action="store_true", help="Configurar acesso VNC")
    parser.add_argument("--setup-api", action="store_true", help="Configurar acesso API")
    parser.add_argument("--setup-all", action="store_true", help="Configurar todos os acessos")
    parser.add_argument("--get-access-info", action="store_true", help="Obter informações de acesso")
    args = parser.parse_args()
    
    # Criar configurador
    remote_access = MT5RemoteAccess(args.config)
    
    # Definir IP do servidor
    if args.server:
        remote_access.config["server"]["ip"] = args.server
    
    try:
        # Conectar ao servidor
        if not remote_access.connect_to_server():
            print("Falha ao conectar ao servidor")
            return 1
        
        # Configurar VPN
        if args.setup_vpn or args.setup_all:
            if remote_access.setup_vpn():
                print("VPN configurada com sucesso")
            else:
                print("Falha ao configurar VPN")
        
        # Configurar acesso SSH
        if args.setup_ssh or args.setup_all:
            if remote_access.setup_ssh_access():
                print("Acesso SSH configurado com sucesso")
            else:
                print("Falha ao configurar acesso SSH")
        
        # Configurar acesso web
        if args.setup_web or args.setup_all:
            if remote_access.setup_web_access():
                print("Acesso web configurado com sucesso")
            else:
                print("Falha ao configurar acesso web")
        
        # Configurar acesso VNC
        if args.setup_vnc or args.setup_all:
            if remote_access.setup_vnc_access():
                print("Acesso VNC configurado com sucesso")
            else:
                print("Falha ao configurar acesso VNC")
        
        # Configurar acesso API
        if args.setup_api or args.setup_all:
            if remote_access.setup_api_access():
                print("Acesso API configurado com sucesso")
            else:
                print("Falha ao configurar acesso API")
        
        # Configurar firewall
        if args.setup_all:
            if remote_access.setup_firewall():
                print("Firewall configurado com sucesso")
            else:
                print("Falha ao configurar firewall")
        
        # Configurar SSL
        if args.setup_all:
            if remote_access.setup_ssl():
                print("SSL configurado com sucesso")
            else:
                print("Falha ao configurar SSL")
        
        # Configurar Fail2Ban
        if args.setup_all:
            if remote_access.setup_fail2ban():
                print("Fail2Ban configurado com sucesso")
            else:
                print("Falha ao configurar Fail2Ban")
        
        # Configurar atualizações automáticas
        if args.setup_all:
            if remote_access.setup_auto_updates():
                print("Atualizações automáticas configuradas com sucesso")
            else:
                print("Falha ao configurar atualizações automáticas")
        
        # Obter informações de acesso
        if args.get_access_info:
            access_info = remote_access.get_access_info()
            
            print("\nInformações de acesso:")
            print(f"Servidor: {access_info['server']['ip']} ({access_info['server']['hostname']})")
            
            if access_info["ssh"]["enabled"]:
                print(f"\nAcesso SSH:")
                print(f"  URL: ssh://{access_info['ssh']['username']}@{access_info['server']['ip']}:{access_info['ssh']['port']}")
                print(f"  Chave: {access_info['ssh']['key_path']}")
            
            if access_info["web"]["enabled"]:
                print(f"\nAcesso Web:")
                print(f"  URL: {access_info['web']['url']}")
                print(f"  Usuário: {access_info['web']['username']}")
                print(f"  Senha: {access_info['web']['password']}")
            
            if access_info["vpn"]["enabled"]:
                print(f"\nAcesso VPN ({access_info['vpn']['type']}):")
                for client in access_info["vpn"]["clients"]:
                    print(f"  Cliente: {client['name']}")
                    print(f"  Configuração: Salva em /etc/wireguard/clients/{client['name']}.conf" if access_info["vpn"]["type"] == "wireguard" else f"  Configuração: Salva em /etc/openvpn/clients/{client['name']}.ovpn")
                    print(f"  QR Code: Disponível")
            
            if access_info["vnc"]["enabled"]:
                print(f"\nAcesso VNC:")
                print(f"  URL: {access_info['vnc']['url']}")
                print(f"  URL Web: {access_info['vnc']['web_url']}")
                print(f"  Senha: {access_info['vnc']['password']}")
            
            if access_info["api"]["enabled"]:
                print(f"\nAcesso API:")
                print(f"  URL: {access_info['api']['url']}")
                print(f"  Usuário: {access_info['api']['username']}")
                print(f"  Senha: {access_info['api']['password']}")
        
        # Desconectar do servidor
        remote_access.disconnect()
        
        return 0
    except KeyboardInterrupt:
        print("Operação interrompida pelo usuário")
        
        # Desconectar do servidor
        remote_access.disconnect()
        
        return 1
    except Exception as e:
        print(f"Erro: {e}")
        
        # Desconectar do servidor
        remote_access.disconnect()
        
        return 1


# Executar se for o script principal
if __name__ == "__main__":
    sys.exit(main())
