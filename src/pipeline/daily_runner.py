from src.config import Config
from src.data.loader import YahooLoader
from src.strategies.sma_crossover import SMACrossover
from src.utils.logging import get_logger

logger = get_logger()

def run():
    Config.validate()
    data = YahooLoader.get_data(Config.YAHOO_SYMBOL)
    strategy = SMACrossover()
    signals = strategy.generate_signals(data)
    logger.info(f"Señales generadas:\n{signals.tail()}")

if __name__ == "__main__":
    run() 