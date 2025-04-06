import sys
import os

# Adiciona o diretório da aplicação ao path
path = '/home/mt5tapereading/mt5_tape_reading_ea'
if path not in sys.path:
    sys.path.append(path)

# Importa a aplicação Flask
from flask_app import app as application
