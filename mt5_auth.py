#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de autenticação segura para o MetaTrader 5.
Este módulo fornece funções para autenticação segura e gerenciamento de credenciais.
"""

import os
import json
import base64
import logging
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_auth.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5Auth")

class MT5Auth:
    """
    Classe para gerenciar autenticação segura com o MetaTrader 5.
    Fornece métodos para criptografar e descriptografar credenciais.
    """
    
    def __init__(self, key_file=None):
        """
        Inicializa a classe MT5Auth.
        
        Args:
            key_file (str, optional): Caminho para o arquivo de chave
        """
        self.key_file = key_file or os.path.expanduser("~/.mt5_key")
        self.key = None
        self.cipher_suite = None
        self._initialize_key()
    
    def _initialize_key(self):
        """Inicializa a chave de criptografia."""
        try:
            if os.path.exists(self.key_file):
                # Carregar chave existente
                with open(self.key_file, "rb") as f:
                    self.key = f.read()
            else:
                # Gerar nova chave
                self.key = Fernet.generate_key()
                # Salvar chave em arquivo com permissões restritas
                with open(self.key_file, "wb") as f:
                    f.write(self.key)
                os.chmod(self.key_file, 0o600)  # Somente o usuário pode ler/escrever
                logger.info(f"Nova chave de criptografia gerada e salva em {self.key_file}")
            
            # Inicializar cipher suite
            self.cipher_suite = Fernet(self.key)
            
        except Exception as e:
            logger.error(f"Erro ao inicializar chave de criptografia: {e}")
            raise
    
    def encrypt_password(self, password):
        """
        Criptografa uma senha.
        
        Args:
            password (str): Senha a ser criptografada
            
        Returns:
            str: Senha criptografada em formato base64
        """
        if not self.cipher_suite:
            raise ValueError("Cipher suite não inicializada")
        
        try:
            encrypted = self.cipher_suite.encrypt(password.encode())
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Erro ao criptografar senha: {e}")
            raise
    
    def decrypt_password(self, encrypted_password):
        """
        Descriptografa uma senha.
        
        Args:
            encrypted_password (str): Senha criptografada em formato base64
            
        Returns:
            str: Senha descriptografada
        """
        if not self.cipher_suite:
            raise ValueError("Cipher suite não inicializada")
        
        try:
            encrypted = base64.b64decode(encrypted_password)
            decrypted = self.cipher_suite.decrypt(encrypted)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Erro ao descriptografar senha: {e}")
            raise
    
    def create_credentials_file(self, file_path, master_password):
        """
        Cria um arquivo de credenciais protegido por senha mestra.
        
        Args:
            file_path (str): Caminho para o arquivo de credenciais
            master_password (str): Senha mestra para proteger o arquivo
            
        Returns:
            bool: True se o arquivo for criado com sucesso, False caso contrário
        """
        try:
            # Derivar chave da senha mestra
            salt = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
            
            # Criar cipher suite com a chave derivada
            cipher = Fernet(key)
            
            # Criar estrutura inicial de credenciais
            credentials = {
                "salt": base64.b64encode(salt).decode(),
                "accounts": []
            }
            
            # Salvar arquivo
            with open(file_path, "w") as f:
                json.dump(credentials, f)
            
            # Definir permissões restritas
            os.chmod(file_path, 0o600)
            
            logger.info(f"Arquivo de credenciais criado em {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao criar arquivo de credenciais: {e}")
            return False
    
    def add_account_to_credentials(self, file_path, master_password, account_info):
        """
        Adiciona informações de conta ao arquivo de credenciais.
        
        Args:
            file_path (str): Caminho para o arquivo de credenciais
            master_password (str): Senha mestra para proteger o arquivo
            account_info (dict): Informações da conta (login, senha, servidor, tipo)
            
        Returns:
            bool: True se a conta for adicionada com sucesso, False caso contrário
        """
        try:
            # Verificar se o arquivo existe
            if not os.path.exists(file_path):
                logger.error(f"Arquivo de credenciais não encontrado: {file_path}")
                return False
            
            # Carregar credenciais
            with open(file_path, "r") as f:
                credentials = json.load(f)
            
            # Obter salt e derivar chave
            salt = base64.b64decode(credentials["salt"])
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
            
            # Criar cipher suite com a chave derivada
            cipher = Fernet(key)
            
            # Criptografar senha da conta
            encrypted_password = cipher.encrypt(account_info["password"].encode()).decode()
            
            # Criar entrada da conta
            account_entry = {
                "login": account_info["login"],
                "server": account_info["server"],
                "password": encrypted_password,
                "type": account_info.get("type", "DEMO"),
                "name": account_info.get("name", f"Conta {account_info['login']}"),
                "enabled": account_info.get("enabled", True)
            }
            
            # Verificar se a conta já existe
            for i, account in enumerate(credentials["accounts"]):
                if account["login"] == account_info["login"] and account["server"] == account_info["server"]:
                    # Atualizar conta existente
                    credentials["accounts"][i] = account_entry
                    logger.info(f"Conta {account_info['login']} atualizada")
                    break
            else:
                # Adicionar nova conta
                credentials["accounts"].append(account_entry)
                logger.info(f"Conta {account_info['login']} adicionada")
            
            # Salvar arquivo atualizado
            with open(file_path, "w") as f:
                json.dump(credentials, f)
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao adicionar conta ao arquivo de credenciais: {e}")
            return False
    
    def get_account_from_credentials(self, file_path, master_password, login, server):
        """
        Obtém informações de uma conta do arquivo de credenciais.
        
        Args:
            file_path (str): Caminho para o arquivo de credenciais
            master_password (str): Senha mestra para proteger o arquivo
            login (str): Login da conta
            server (str): Servidor da conta
            
        Returns:
            dict: Informações da conta ou None em caso de erro
        """
        try:
            # Verificar se o arquivo existe
            if not os.path.exists(file_path):
                logger.error(f"Arquivo de credenciais não encontrado: {file_path}")
                return None
            
            # Carregar credenciais
            with open(file_path, "r") as f:
                credentials = json.load(f)
            
            # Obter salt e derivar chave
            salt = base64.b64decode(credentials["salt"])
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
            
            # Criar cipher suite com a chave derivada
            cipher = Fernet(key)
            
            # Buscar conta
            for account in credentials["accounts"]:
                if str(account["login"]) == str(login) and account["server"] == server:
                    # Descriptografar senha
                    try:
                        decrypted_password = cipher.decrypt(account["password"].encode()).decode()
                        
                        # Retornar informações da conta
                        return {
                            "login": account["login"],
                            "server": account["server"],
                            "password": decrypted_password,
                            "type": account.get("type", "DEMO"),
                            "name": account.get("name", f"Conta {account['login']}"),
                            "enabled": account.get("enabled", True)
                        }
                    except Exception as e:
                        logger.error(f"Erro ao descriptografar senha: {e}")
                        return None
            
            logger.warning(f"Conta {login} no servidor {server} não encontrada")
            return None
            
        except Exception as e:
            logger.error(f"Erro ao obter conta do arquivo de credenciais: {e}")
            return None
    
    def list_accounts_from_credentials(self, file_path, master_password):
        """
        Lista todas as contas do arquivo de credenciais.
        
        Args:
            file_path (str): Caminho para o arquivo de credenciais
            master_password (str): Senha mestra para proteger o arquivo
            
        Returns:
            list: Lista de contas (sem senhas) ou None em caso de erro
        """
        try:
            # Verificar se o arquivo existe
            if not os.path.exists(file_path):
                logger.error(f"Arquivo de credenciais não encontrado: {file_path}")
                return None
            
            # Carregar credenciais
            with open(file_path, "r") as f:
                credentials = json.load(f)
            
            # Obter salt e derivar chave para verificar a senha mestra
            salt = base64.b64decode(credentials["salt"])
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
            
            # Criar cipher suite com a chave derivada
            cipher = Fernet(key)
            
            # Verificar se a senha mestra está correta tentando descriptografar a primeira senha
            if credentials["accounts"]:
                try:
                    cipher.decrypt(credentials["accounts"][0]["password"].encode())
                except Exception:
                    logger.error("Senha mestra incorreta")
                    return None
            
            # Retornar lista de contas sem senhas
            accounts = []
            for account in credentials["accounts"]:
                accounts.append({
                    "login": account["login"],
                    "server": account["server"],
                    "type": account.get("type", "DEMO"),
                    "name": account.get("name", f"Conta {account['login']}"),
                    "enabled": account.get("enabled", True)
                })
            
            return accounts
            
        except Exception as e:
            logger.error(f"Erro ao listar contas do arquivo de credenciais: {e}")
            return None
    
    def remove_account_from_credentials(self, file_path, master_password, login, server):
        """
        Remove uma conta do arquivo de credenciais.
        
        Args:
            file_path (str): Caminho para o arquivo de credenciais
            master_password (str): Senha mestra para proteger o arquivo
            login (str): Login da conta
            server (str): Servidor da conta
            
        Returns:
            bool: True se a conta for removida com sucesso, False caso contrário
        """
        try:
            # Verificar se o arquivo existe
            if not os.path.exists(file_path):
                logger.error(f"Arquivo de credenciais não encontrado: {file_path}")
                return False
            
            # Carregar credenciais
            with open(file_path, "r") as f:
                credentials = json.load(f)
            
            # Obter salt e derivar chave
            salt = base64.b64decode(credentials["salt"])
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
            
            # Criar cipher suite com a chave derivada
            cipher = Fernet(key)
            
            # Verificar se a senha mestra está correta tentando descriptografar a primeira senha
            if credentials["accounts"]:
                try:
                    cipher.decrypt(credentials["accounts"][0]["password"].encode())
                except Exception:
                    logger.error("Senha mestra incorreta")
                    return False
            
            # Buscar e remover conta
            initial_count = len(credentials["accounts"])
            credentials["accounts"] = [
                account for account in credentials["accounts"]
                if not (str(account["login"]) == str(login) and account["server"] == server)
            ]
            
            if len(credentials["accounts"]) < initial_count:
                # Salvar arquivo atualizado
                with open(file_path, "w") as f:
                    json.dump(credentials, f)
                
                logger.info(f"Conta {login} no servidor {server} removida")
                return True
            else:
                logger.warning(f"Conta {login} no servidor {server} não encontrada")
                return False
            
        except Exception as e:
            logger.error(f"Erro ao remover conta do arquivo de credenciais: {e}")
            return False


# Exemplo de uso
if __name__ == "__main__":
    # Exemplo de uso da classe MT5Auth
    auth = MT5Auth()
    
    # Criptografar senha
    encrypted = auth.encrypt_password("minha_senha_secreta")
    print(f"Senha criptografada: {encrypted}")
    
    # Descriptografar senha
    decrypted = auth.decrypt_password(encrypted)
    print(f"Senha descriptografada: {decrypted}")
    
    # Criar arquivo de credenciais
    credentials_file = "mt5_credentials.json"
    auth.create_credentials_file(credentials_file, "senha_mestra")
    
    # Adicionar conta
    account_info = {
        "login": "12345678",
        "password": "senha_da_conta",
        "server": "MetaQuotes-Demo",
        "type": "DEMO",
        "name": "Minha Conta Demo"
    }
    auth.add_account_to_credentials(credentials_file, "senha_mestra", account_info)
    
    # Listar contas
    accounts = auth.list_accounts_from_credentials(credentials_file, "senha_mestra")
    print(f"Contas: {accounts}")
    
    # Obter conta
    account = auth.get_account_from_credentials(credentials_file, "senha_mestra", "12345678", "MetaQuotes-Demo")
    print(f"Conta: {account}")
