#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de monitoramento de desempenho para o MetaTrader 5.
Este módulo fornece funções para calcular e visualizar métricas de desempenho de negociação.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import MetaTrader5 as mt5
import io
import base64

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mt5_performance.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MT5Performance")

class MT5Performance:
    """
    Classe para monitorar o desempenho de negociação no MetaTrader 5.
    Fornece métodos para calcular métricas de desempenho e gerar visualizações.
    """
    
    def __init__(self, mt5_backend=None):
        """
        Inicializa a classe MT5Performance.
        
        Args:
            mt5_backend: Instância de MT5Backend para comunicação com o MT5
        """
        self.mt5_backend = mt5_backend
        self.performance_data = {}
        self.daily_performance = {}
        self.equity_history = []
        self.max_drawdown = 0.0
        self.win_rate = 0.0
        self.trades_today = 0
        self.profit_today = 0.0
    
    def update_performance_data(self):
        """
        Atualiza os dados de desempenho a partir do MT5.
        
        Returns:
            dict: Dados de desempenho atualizados
        """
        if not self.mt5_backend or not self.mt5_backend.check_connection():
            logger.error("Não conectado ao MT5")
            return None
        
        try:
            # Obter informações da conta
            account_info = self.mt5_backend.get_account_info()
            if not account_info:
                logger.error("Falha ao obter informações da conta")
                return None
            
            # Obter posições abertas
            positions = self.mt5_backend.get_positions()
            if positions is None:
                positions = []
            
            # Obter histórico de negociações
            deals_history = self.mt5_backend.get_deals_history(30)  # Últimos 30 dias
            if deals_history is None:
                deals_history = []
            
            # Calcular métricas de desempenho
            self._calculate_performance_metrics(account_info, positions, deals_history)
            
            return self.performance_data
            
        except Exception as e:
            logger.error(f"Erro ao atualizar dados de desempenho: {e}")
            return None
    
    def _calculate_performance_metrics(self, account_info, positions, deals_history):
        """
        Calcula métricas de desempenho a partir dos dados do MT5.
        
        Args:
            account_info (dict): Informações da conta
            positions (list): Lista de posições abertas
            deals_history (list): Histórico de negociações
        """
        try:
            # Resumo da conta
            self.performance_data["account_summary"] = {
                "balance": account_info["balance"],
                "equity": account_info["equity"],
                "margin": account_info["margin"],
                "free_margin": account_info["margin_free"],
                "margin_level": account_info["margin_level"],
                "currency": account_info["currency"]
            }
            
            # Calcular lucro/prejuízo das posições abertas
            open_positions_profit = sum(position["profit"] for position in positions)
            
            # Atualizar histórico de patrimônio
            current_time = datetime.now()
            self.equity_history.append({
                "date": current_time,
                "equity": account_info["equity"]
            })
            
            # Manter apenas os últimos 30 dias de histórico
            cutoff_date = current_time - timedelta(days=30)
            self.equity_history = [entry for entry in self.equity_history if entry["date"] >= cutoff_date]
            
            # Calcular drawdown
            if self.equity_history:
                max_equity = max(entry["equity"] for entry in self.equity_history)
                current_equity = account_info["equity"]
                current_drawdown = max_equity - current_equity
                self.max_drawdown = max(self.max_drawdown, current_drawdown)
            
            # Processar histórico de negociações
            if deals_history:
                # Converter para DataFrame para facilitar a análise
                df_deals = pd.DataFrame(deals_history)
                
                # Converter timestamp para datetime
                df_deals["datetime"] = pd.to_datetime(df_deals["time"], unit="s")
                
                # Filtrar negociações de hoje
                today = datetime.now().date()
                df_today = df_deals[df_deals["datetime"].dt.date == today]
                
                # Calcular lucro/prejuízo do dia
                self.profit_today = df_today["profit"].sum() if not df_today.empty else 0.0
                
                # Contar operações do dia
                self.trades_today = len(df_today) if not df_today.empty else 0
                
                # Calcular taxa de acerto (últimos 30 dias)
                total_trades = len(df_deals)
                winning_trades = len(df_deals[df_deals["profit"] > 0])
                self.win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
                
                # Agrupar por dia para análise diária
                df_deals["date"] = df_deals["datetime"].dt.date
                daily_profit = df_deals.groupby("date")["profit"].sum()
                
                # Atualizar desempenho diário
                for date, profit in daily_profit.items():
                    self.daily_performance[str(date)] = profit
            
            # Atualizar dados de desempenho
            self.performance_data["trading_performance"] = {
                "equity_history": self.equity_history,
                "daily_performance": self.daily_performance,
                "profit_today": self.profit_today,
                "trades_today": self.trades_today,
                "win_rate": self.win_rate,
                "max_drawdown": self.max_drawdown
            }
            
        except Exception as e:
            logger.error(f"Erro ao calcular métricas de desempenho: {e}")
            raise
    
    def get_equity_chart(self, width=800, height=400, days=30):
        """
        Gera um gráfico de evolução do patrimônio.
        
        Args:
            width (int): Largura do gráfico em pixels
            height (int): Altura do gráfico em pixels
            days (int): Número de dias para exibir
            
        Returns:
            str: Imagem do gráfico em formato base64
        """
        try:
            # Verificar se há dados suficientes
            if not self.equity_history:
                logger.warning("Sem dados de histórico de patrimônio para gerar gráfico")
                return None
            
            # Criar figura
            fig = Figure(figsize=(width/100, height/100), dpi=100)
            canvas = FigureCanvas(fig)
            ax = fig.add_subplot(111)
            
            # Preparar dados
            dates = [entry["date"] for entry in self.equity_history]
            equity = [entry["equity"] for entry in self.equity_history]
            
            # Plotar gráfico
            ax.plot(dates, equity, marker='o', linestyle='-', color='#3b82f6', linewidth=2, markersize=4)
            
            # Configurar eixos
            ax.set_title("Evolução do Patrimônio", fontsize=14)
            ax.set_xlabel("Data", fontsize=12)
            ax.set_ylabel("Patrimônio", fontsize=12)
            
            # Formatar eixo x para datas
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates)//10)))
            
            # Adicionar grade
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # Ajustar layout
            fig.tight_layout()
            
            # Converter para base64
            buf = io.BytesIO()
            canvas.print_png(buf)
            data = base64.b64encode(buf.getbuffer()).decode("ascii")
            
            return f"data:image/png;base64,{data}"
            
        except Exception as e:
            logger.error(f"Erro ao gerar gráfico de patrimônio: {e}")
            return None
    
    def get_daily_profit_chart(self, width=800, height=400, days=30):
        """
        Gera um gráfico de lucro/prejuízo diário.
        
        Args:
            width (int): Largura do gráfico em pixels
            height (int): Altura do gráfico em pixels
            days (int): Número de dias para exibir
            
        Returns:
            str: Imagem do gráfico em formato base64
        """
        try:
            # Verificar se há dados suficientes
            if not self.daily_performance:
                logger.warning("Sem dados de desempenho diário para gerar gráfico")
                return None
            
            # Criar figura
            fig = Figure(figsize=(width/100, height/100), dpi=100)
            canvas = FigureCanvas(fig)
            ax = fig.add_subplot(111)
            
            # Preparar dados
            dates = list(self.daily_performance.keys())
            profits = list(self.daily_performance.values())
            
            # Limitar aos últimos 'days' dias
            if len(dates) > days:
                dates = dates[-days:]
                profits = profits[-days:]
            
            # Converter strings de data para objetos datetime
            dates = [datetime.strptime(date, "%Y-%m-%d") for date in dates]
            
            # Definir cores com base no lucro/prejuízo
            colors = ['#4ade80' if profit >= 0 else '#f87171' for profit in profits]
            
            # Plotar gráfico de barras
            ax.bar(dates, profits, color=colors, width=0.7)
            
            # Configurar eixos
            ax.set_title("Lucro/Prejuízo Diário", fontsize=14)
            ax.set_xlabel("Data", fontsize=12)
            ax.set_ylabel("Lucro/Prejuízo", fontsize=12)
            
            # Formatar eixo x para datas
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates)//10)))
            
            # Adicionar linha horizontal em y=0
            ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
            
            # Adicionar grade
            ax.grid(True, linestyle='--', alpha=0.7, axis='y')
            
            # Ajustar layout
            fig.tight_layout()
            
            # Converter para base64
            buf = io.BytesIO()
            canvas.print_png(buf)
            data = base64.b64encode(buf.getbuffer()).decode("ascii")
            
            return f"data:image/png;base64,{data}"
            
        except Exception as e:
            logger.error(f"Erro ao gerar gráfico de lucro diário: {e}")
            return None
    
    def get_win_loss_chart(self, width=400, height=400):
        """
        Gera um gráfico de pizza de ganhos vs perdas.
        
        Args:
            width (int): Largura do gráfico em pixels
            height (int): Altura do gráfico em pixels
            
        Returns:
            str: Imagem do gráfico em formato base64
        """
        try:
            # Verificar se há dados suficientes
            if self.win_rate <= 0:
                logger.warning("Sem dados de taxa de acerto para gerar gráfico")
                return None
            
            # Criar figura
            fig = Figure(figsize=(width/100, height/100), dpi=100)
            canvas = FigureCanvas(fig)
            ax = fig.add_subplot(111)
            
            # Preparar dados
            win_rate = self.win_rate
            loss_rate = 100 - win_rate
            
            # Plotar gráfico de pizza
            ax.pie([win_rate, loss_rate], labels=['Ganhos', 'Perdas'], 
                   colors=['#4ade80', '#f87171'], autopct='%1.1f%%', 
                   startangle=90, shadow=False)
            
            # Configurar título
            ax.set_title("Ganhos vs Perdas", fontsize=14)
            
            # Ajustar layout
            fig.tight_layout()
            
            # Converter para base64
            buf = io.BytesIO()
            canvas.print_png(buf)
            data = base64.b64encode(buf.getbuffer()).decode("ascii")
            
            return f"data:image/png;base64,{data}"
            
        except Exception as e:
            logger.error(f"Erro ao gerar gráfico de ganhos vs perdas: {e}")
            return None
    
    def get_performance_summary(self):
        """
        Retorna um resumo do desempenho de negociação.
        
        Returns:
            dict: Resumo do desempenho
        """
        if not self.performance_data:
            logger.warning("Sem dados de desempenho para gerar resumo")
            return None
        
        try:
            account_summary = self.performance_data.get("account_summary", {})
            trading_performance = self.performance_data.get("trading_performance", {})
            
            summary = {
                "balance": account_summary.get("balance", 0),
                "equity": account_summary.get("equity", 0),
                "free_margin": account_summary.get("free_margin", 0),
                "margin_level": account_summary.get("margin_level", 0),
                "currency": account_summary.get("currency", "USD"),
                "profit_today": trading_performance.get("profit_today", 0),
                "trades_today": trading_performance.get("trades_today", 0),
                "win_rate": trading_performance.get("win_rate", 0),
                "max_drawdown": trading_performance.get("max_drawdown", 0)
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Erro ao gerar resumo de desempenho: {e}")
            return None
    
    def save_performance_data(self, file_path):
        """
        Salva os dados de desempenho em um arquivo JSON.
        
        Args:
            file_path (str): Caminho para o arquivo
            
        Returns:
            bool: True se os dados forem salvos com sucesso, False caso contrário
        """
        if not self.performance_data:
            logger.warning("Sem dados de desempenho para salvar")
            return False
        
        try:
            # Converter dados para formato serializável
            serializable_data = self.performance_data.copy()
            
            # Converter objetos datetime para strings
            if "trading_performance" in serializable_data and "equity_history" in serializable_data["trading_performance"]:
                for entry in serializable_data["trading_performance"]["equity_history"]:
                    if isinstance(entry["date"], datetime):
                        entry["date"] = entry["date"].isoformat()
            
            # Salvar em arquivo JSON
            with open(file_path, "w") as f:
                json.dump(serializable_data, f, indent=4)
            
            logger.info(f"Dados de desempenho salvos em {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao salvar dados de desempenho: {e}")
            return False
    
    def load_performance_data(self, file_path):
        """
        Carrega os dados de desempenho de um arquivo JSON.
        
        Args:
            file_path (str): Caminho para o arquivo
            
        Returns:
            bool: True se os dados forem carregados com sucesso, False caso contrário
        """
        if not os.path.exists(file_path):
            logger.warning(f"Arquivo de dados de desempenho não encontrado: {file_path}")
            return False
        
        try:
            # Carregar dados do arquivo JSON
            with open(file_path, "r") as f:
                loaded_data = json.load(f)
            
            # Converter strings de data para objetos datetime
            if "trading_performance" in loaded_data and "equity_history" in loaded_data["trading_performance"]:
                for entry in loaded_data["trading_performance"]["equity_history"]:
                    if isinstance(entry["date"], str):
                        entry["date"] = datetime.fromisoformat(entry["date"])
            
            # Atualizar dados de desempenho
            self.performance_data = loaded_data
            
            # Extrair dados importantes
            if "trading_performance" in loaded_data:
                trading_performance = loaded_data["trading_performance"]
                self.equity_history = trading_performance.get("equity_history", [])
                self.daily_performance = trading_performance.get("daily_performance", {})
                self.win_rate = trading_performance.get("win_rate", 0.0)
                self.max_drawdown = trading_performance.get("max_drawdown", 0.0)
                self.profit_today = trading_performance.get("profit_today", 0.0)
                self.trades_today = trading_performance.get("trades_today", 0)
            
            logger.info(f"Dados de desempenho carregados de {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao carregar dados de desempenho: {e}")
            return False


class MT5PerformanceMonitor:
    """
    Classe para monitorar continuamente o desempenho de negociação no MetaTrader 5.
    """
    
    def __init__(self, mt5_backend, data_dir=None):
        """
        Inicializa a classe MT5PerformanceMonitor.
        
        Args:
            mt5_backend: Instância de MT5Backend para comunicação com o MT5
            data_dir (str, optional): Diretório para armazenar dados de desempenho
        """
        self.mt5_backend = mt5_backend
        self.performance = MT5Performance(mt5_backend)
        self.data_dir = data_dir or os.path.expanduser("~/mt5_performance_data")
        self.running = False
        
        # Criar diretório de dados se não existir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
    
    def start_monitoring(self, interval=60):
        """
        Inicia o monitoramento contínuo de desempenho.
        
        Args:
            interval (int): Intervalo em segundos entre atualizações
            
        Returns:
            bool: True se o monitoramento for iniciado com sucesso, False caso contrário
        """
        if not self.mt5_backend or not self.mt5_backend.check_connection():
            logger.error("Não conectado ao MT5")
            return False
        
        if self.running:
            logger.warning("Monitoramento já está em execução")
            return True
        
        self.running = True
        
        try:
            # Carregar dados existentes, se houver
            today = datetime.now().strftime("%Y-%m-%d")
            data_file = os.path.join(self.data_dir, f"performance_{today}.json")
            
            if os.path.exists(data_file):
                self.performance.load_performance_data(data_file)
            
            # Iniciar loop de monitoramento em uma thread separada
            import threading
            self.monitor_thread = threading.Thread(
                target=self._monitoring_loop,
                args=(interval, data_file),
                daemon=True
            )
            self.monitor_thread.start()
            
            logger.info(f"Monitoramento de desempenho iniciado com intervalo de {interval} segundos")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao iniciar monitoramento: {e}")
            self.running = False
            return False
    
    def stop_monitoring(self):
        """
        Para o monitoramento contínuo de desempenho.
        
        Returns:
            bool: True se o monitoramento for parado com sucesso, False caso contrário
        """
        if not self.running:
            logger.warning("Monitoramento não está em execução")
            return True
        
        self.running = False
        logger.info("Monitoramento de desempenho parado")
        return True
    
    def _monitoring_loop(self, interval, data_file):
        """
        Loop de monitoramento contínuo.
        
        Args:
            interval (int): Intervalo em segundos entre atualizações
            data_file (str): Caminho para o arquivo de dados
        """
        import time
        
        while self.running:
            try:
                # Atualizar dados de desempenho
                self.performance.update_performance_data()
                
                # Salvar dados atualizados
                self.performance.save_performance_data(data_file)
                
                # Aguardar próxima atualização
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"Erro no loop de monitoramento: {e}")
                time.sleep(interval)
    
    def get_current_performance(self):
        """
        Retorna os dados de desempenho atuais.
        
        Returns:
            dict: Dados de desempenho atuais
        """
        return self.performance.get_performance_summary()
    
    def generate_performance_report(self, output_dir=None):
        """
        Gera um relatório de desempenho completo.
        
        Args:
            output_dir (str, optional): Diretório para salvar o relatório
            
        Returns:
            str: Caminho para o relatório gerado ou None em caso de erro
        """
        if not output_dir:
            output_dir = self.data_dir
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        try:
            # Atualizar dados de desempenho
            self.performance.update_performance_data()
            
            # Gerar gráficos
            equity_chart = self.performance.get_equity_chart()
            daily_profit_chart = self.performance.get_daily_profit_chart()
            win_loss_chart = self.performance.get_win_loss_chart()
            
            # Obter resumo de desempenho
            summary = self.performance.get_performance_summary()
            
            # Gerar relatório HTML
            report_file = os.path.join(output_dir, f"performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
            
            with open(report_file, "w") as f:
                f.write(f"""
                <!DOCTYPE html>
                <html lang="pt-BR">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Relatório de Desempenho MT5</title>
                    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
                </head>
                <body class="bg-gray-100 min-h-screen">
                    <div class="container mx-auto px-4 py-8">
                        <header class="mb-8 text-center">
                            <h1 class="text-3xl font-bold text-gray-800">Relatório de Desempenho MT5</h1>
                            <p class="text-gray-600">Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
                        </header>
                        
                        <div class="bg-white rounded-lg shadow p-4 mb-6">
                            <h2 class="text-xl font-semibold mb-4">Resumo da Conta</h2>
                            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                                <div class="bg-blue-50 p-3 rounded-lg text-center">
                                    <div class="text-sm text-blue-600 font-medium">Saldo</div>
                                    <div class="text-2xl font-bold">${summary['balance']:.2f}</div>
                                </div>
                                <div class="bg-green-50 p-3 rounded-lg text-center">
                                    <div class="text-sm text-green-600 font-medium">Patrimônio</div>
                                    <div class="text-2xl font-bold">${summary['equity']:.2f}</div>
                                </div>
                                <div class="bg-purple-50 p-3 rounded-lg text-center">
                                    <div class="text-sm text-purple-600 font-medium">Margem Livre</div>
                                    <div class="text-2xl font-bold">${summary['free_margin']:.2f}</div>
                                </div>
                                <div class="bg-yellow-50 p-3 rounded-lg text-center">
                                    <div class="text-sm text-yellow-600 font-medium">Nível de Margem</div>
                                    <div class="text-2xl font-bold">{summary['margin_level']:.1f}%</div>
                                </div>
                            </div>
                        </div>
                        
                        <div class="bg-white rounded-lg shadow p-4 mb-6">
                            <h2 class="text-xl font-semibold mb-4">Desempenho de Negociação</h2>
                            
                            <div class="mb-6">
                                <h3 class="text-lg font-medium mb-2">Evolução do Patrimônio</h3>
                                <div class="h-64 bg-gray-50 rounded-lg p-2">
                                    <img src="{equity_chart}" alt="Evolução do Patrimônio" class="w-full h-full object-contain">
                                </div>
                            </div>
                            
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                                <div>
                                    <h3 class="text-lg font-medium mb-2">Lucro/Prejuízo Diário</h3>
                                    <div class="h-64 bg-gray-50 rounded-lg p-2">
                                        <img src="{daily_profit_chart}" alt="Lucro/Prejuízo Diário" class="w-full h-full object-contain">
                                    </div>
                                </div>
                                <div>
                                    <h3 class="text-lg font-medium mb-2">Ganhos vs Perdas</h3>
                                    <div class="h-64 bg-gray-50 rounded-lg p-2">
                                        <img src="{win_loss_chart}" alt="Ganhos vs Perdas" class="w-full h-full object-contain">
                                    </div>
                                </div>
                            </div>
                            
                            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                                <div class="bg-green-50 p-3 rounded-lg text-center">
                                    <div class="text-sm text-green-600 font-medium">Lucro/Prejuízo Hoje</div>
                                    <div class="text-2xl font-bold">${summary['profit_today']:.2f}</div>
                                </div>
                                <div class="bg-blue-50 p-3 rounded-lg text-center">
                                    <div class="text-sm text-blue-600 font-medium">Operações Hoje</div>
                                    <div class="text-2xl font-bold">{summary['trades_today']}</div>
                                </div>
                                <div class="bg-purple-50 p-3 rounded-lg text-center">
                                    <div class="text-sm text-purple-600 font-medium">Taxa de Acerto</div>
                                    <div class="text-2xl font-bold">{summary['win_rate']:.1f}%</div>
                                </div>
                                <div class="bg-red-50 p-3 rounded-lg text-center">
                                    <div class="text-sm text-red-600 font-medium">Drawdown Máximo</div>
                                    <div class="text-2xl font-bold">-${summary['max_drawdown']:.2f}</div>
                                </div>
                            </div>
                        </div>
                        
                        <footer class="text-center text-gray-500 text-sm mt-8">
                            <p>Relatório gerado pelo Sistema de Tape Reading para MT5</p>
                        </footer>
                    </div>
                </body>
                </html>
                """)
            
            logger.info(f"Relatório de desempenho gerado em {report_file}")
            return report_file
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório de desempenho: {e}")
            return None


# Exemplo de uso
if __name__ == "__main__":
    # Importar backend MT5
    import sys
    sys.path.append('.')
    from mt5_backend import MT5Backend
    
    # Criar instância do backend
    mt5_backend = MT5Backend()
    
    # Conectar ao MT5
    if mt5_backend.connect(12345678, "senha", "MetaQuotes-Demo", "DEMO"):
        print("Conectado com sucesso!")
        
        # Criar monitor de desempenho
        monitor = MT5PerformanceMonitor(mt5_backend)
        
        # Iniciar monitoramento
        monitor.start_monitoring(interval=60)
        
        # Gerar relatório após alguns minutos
        import time
        time.sleep(300)  # Aguardar 5 minutos
        
        report_file = monitor.generate_performance_report()
        print(f"Relatório gerado: {report_file}")
        
        # Parar monitoramento
        monitor.stop_monitoring()
        
        # Desconectar
        mt5_backend.disconnect()
    else:
        print("Falha ao conectar!")
