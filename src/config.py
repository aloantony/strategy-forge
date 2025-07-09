import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../env/.env.example'))

class Config:
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
    YAHOO_SYMBOL = os.getenv('YAHOO_SYMBOL')

    @classmethod
    def validate(cls):
        missing = [k for k in ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'YAHOO_SYMBOL'] if not getattr(cls, k)]
        if missing:
            raise ValueError(f"Faltan variables de entorno: {', '.join(missing)}") 