import yfinance as yf
from alpaca_trade_api.rest import REST
from src.config import Config

class YahooLoader:
    @staticmethod
    def get_data(symbol, period='1y', interval='1d'):
        return yf.download(symbol, period=period, interval=interval)

class AlpacaLoader:
    def __init__(self):
        self.api = REST(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)

    def get_data(self, symbol, timeframe='day', limit=100):
        barset = self.api.get_bars(symbol, timeframe, limit=limit)
        return barset.df 