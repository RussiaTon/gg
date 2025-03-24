import requests
from bs4 import BeautifulSoup
import re
import time
import logging
import json
import os
import random
from datetime import datetime
from urllib.parse import urljoin
import telegram

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parser_log.txt"),
        logging.StreamHandler()
    ]
)

# Настройки
MAX_PRICE = 50  # Максимальная цена в рублях
MIN_DISCOUNT_PERCENT = 50  # Минимальный процент скидки
CHECK_INTERVAL = 1800  # Интервал проверки в секундах (30 минут)
CONFIG_FILE = "parser_config.json"

# Настройки телеграм-бота (добавьте свой токен)
TELEGRAM_TOKEN = "7809190658:AAEi_uG41kvEanBFohFJpDE43eMOEpUcBcI"
CHAT_ID = "@salesbuyers"

# Список магазинов для парсинга с их базовыми URL и селекторами
STORES = {
    "Перекрёсток": {
        "base_url": "https://www.vprok.ru",
        "catalog_url": "/catalog/sladkoe-i-sneki/",  # Более конкретный каталог
        "item_selector": ".xf-product-new",  # Обновлено на основе скриншота
        "name_selector": ".xf-product-new__title",
        "price_selector": ".xf-price__rouble",
        "old_price_selector": ".xf-price__old",
        "discount_selector": ".xf-product-new__discount"
    },
    "Магнит": {
        "base_url": "https://magnit.ru",
        "catalog_url": "/catalog/sladosti-i-konditerskie-izdeliya/",
        "item_selector": ".product-card",
        "name_selector": ".product-card__title",
        "price_selector": ".product-card__price",
        "old_price_selector": ".product-card__old-price",
        "discount_selector": ".product-card__discount"
    },
    "Вкусвилл": {
        "base_url": "https://vkusvill.ru",
        "catalog_url": "/goods/gotovaya-eda/",
        "item_selector": ".ProductCards__item",
        "name_selector": ".ProductCard__title",
        "price_selector": ".ProductCard__price",
        "old_price_selector": ".ProductCard__oldPrice",
        "discount_selector": ".ProductCard__discount"
    }
}

class FoodDeliveryParser:
    def __init__(self):
        self.config = self.load_config()
        self.bot = None
        if TELEGRAM_TOKEN != "YOUR_TELEGRAM_TOKEN" and CHAT_ID != "YOUR_CHAT_ID":
            self.bot = telegram.Bot(token=TELEGRAM_TOKEN)
        self.found_products = set()  # Для отслеживания уже найденных товаров
        
        # Расширенные заголовки запросов для имитации реального браузера
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "TE": "Trailers",
            "DNT": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1"
        }
        
        # Список популярных User-Agents для ротации
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:98.0) Gecko/20100101 Firefox/98.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36"
        ]
        
        # Словарь для cookies по доменам
        self.cookies = {}

    def load_config(self):
        """Загрузка конфигурации из файла или создание нового файла конфигурации"""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            default_config = {
                "address": "Курский вокзал, Москва",  # Адрес по умолчанию
                "region": "Москва",
                "last_check": None,
                "max_price": MAX_PRICE,
                "min_discount": MIN_DISCOUNT_PERCENT,
                "check_interval": CHECK_INTERVAL
            }
            self.save_config(default_config)
            return default_config

    def save_config(self, config):
        """Сохранение конфигурации в файл"""
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def update_address(self, address, region):
        """Обновление адреса доставки"""
        self.config["address"] = address
        self.config["region"] = region
        self.save_config(self.config)
        logging.info(f"Адрес доставки обновлен: {address}, регион: {region}")

    def get_random_user_agent(self):
        """Получение случайного User-Agent"""
        return random.choice(self.user_agents)

    def get_session_with_cookies(self, domain):
        """Получение сессии с сохраненными cookies для домена"""
        session = requests.Session()
        session.headers.update(self.headers)
        session.headers["User-Agent"] = self.get_random_user_agent()
        
        if domain in self.cookies:
            session.cookies.update(self.cookies[domain])
            
        return session

    def save_cookies(self, domain, cookies):
        """Сохранение cookies для домена"""
        self.cookies[domain] = cookies

    def parse_perekrestok(self):
        """Специализированный парсер для Перекрестка (из-за проблем с доступом)"""
        store_name = "Перекрёсток"
        store_info = STORES[store_name]
        logging.info(f"Проверка магазина: {store_name} с прямым подходом")
        
        try:
            # Извлечение домена из URL
            domain = store_info["base_url"].split("//")[1].split("/")[0]
            session = self.get_session_with_cookies(domain)
            
            # Сначала получаем главную страницу, чтобы получить cookies
            main_response = session.get(
                store_info["base_url"], 
                timeout=15, 
                allow_redirects=True
            )
            
            if main_response.status_code != 200:
                logging.error(f"Ошибка доступа к главной странице {store_name}: {main_response.status_code}")
                return []
                
            # Сохраняем cookies
            self.save_cookies(domain, session.cookies)
            
            # Делаем паузу между запросами
            time.sleep(random.uniform(2, 4))
            
            # Теперь получаем страницу каталога
            url = urljoin(store_info["base_url"], store_info["catalog_url"])
            logging.info(f"Переход к URL: {url}")
            
            # Делаем несколько попыток с разными заголовками
            for attempt in range(3):
                # Обновляем User-Agent для каждой попытки
                session.headers["User-Agent"] = self.get_random_user_agent()
                
                response = session.get(
                    url, 
                    timeout=15, 
                    allow_redirects=True
                )
                
                if response.status_code == 200:
                    break
                    
                logging.warning(f"Попытка {attempt+1} для {store_name} завершилась с кодом: {response.status_code}")
                time.sleep(random.uniform(3, 6))
            
            if response.status_code != 200:
                logging.error(f"Ошибка доступа к сайту {store_name}: {response.status_code}")
                return []
            
            # Сохраняем HTML для отладки (можно закомментировать в продакшене)
            with open(f"{store_name.lower()}_debug.html", 'w', encoding='utf-8') as f:
                f.write(response.text)
                
            # Парсим HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Проверяем наличие каптчи или блокировки
            if "captcha" in response.text.lower() or "проверка" in response.text.lower():
                logging.error(f"Обнаружена капча или защита от ботов на сайте {store_name}")
                return []
                
            # Находим товары на странице
            items = soup.select(store_info["item_selector"])
            logging.info(f"Найдено {len(items)} товаров на странице {store_name}")
            
            good_deals = []
            for item in items:
                try:
                    # Ищем название товара
                    name_elem = item.select_one(store_info["name_selector"])
                    if not name_elem:
                        continue
                    name = name_elem.get_text().strip()
                    
                    # Ищем текущую цену
                    price_elem = item.select_one(store_info["price_selector"])
                    if not price_elem:
                        continue
                        
                    # Извлекаем цену, удаляя нечисловые символы
                    price_text = price_elem.get_text().strip()
                    price_match = re.search(r'(\d+[.,]?\d*)', price_text.replace(' ', ''))
                    if not price_match:
                        continue
                    price = float(price_match.group(1).replace(',', '.'))
                    
                    # Ищем старую цену и скидку
                    discount_percent = 0
                    old_price_elem = item.select_one(store_info["old_price_selector"])
                    if old_price_elem:
                        old_price_text = old_price_elem.get_text().strip()
                        old_price_match = re.search(r'(\d+[.,]?\d*)', old_price_text.replace(' ', ''))
                        if old_price_match:
                            old_price = float(old_price_match.group(1).replace(',', '.'))
                            discount_percent = round((old_price - price) / old_price * 100)
                    
                    # Проверяем, есть ли элемент скидки
                    discount_elem = item.select_one(store_info["discount_selector"])
                    if discount_elem and discount_percent == 0:
                        discount_text = discount_elem.get_text().strip()
                        discount_match = re.search(r'(\d+)[%]?', discount_text)
                        if discount_match:
                            discount_percent = int(discount_match.group(1))
                    
                    # Формируем ссылку на товар
                    product_link = ""
                    link_elem = item.select_one('a')
                    if link_elem and link_elem.has_attr('href'):
                        product_link = urljoin(store_info["base_url"], link_elem['href'])
                    
                    # Проверяем, соответствует ли товар критериям
                    product_id = f"{store_name}_{name}_{price}"
                    if (price <= self.config["max_price"] or discount_percent >= self.config["min_discount"]) and product_id not in self.found_products:
                        good_deals.append({
                            "store": store_name,
                            "name": name,
                            "price": price,
                            "discount": discount_percent,
                            "link": product_link
                        })
                        self.found_products.add(product_id)
                        logging.info(f"Найден подходящий товар: {name}, цена: {price}₽, скидка: {discount_percent}%")
                        
                except Exception as e:
                    logging.error(f"Ошибка при обработке товара в {store_name}: {str(e)}")
            
            logging.info(f"Найдено {len(good_deals)} товаров со скидкой или дешевле {self.config['max_price']}₽ в {store_name}")
            return good_deals
            
        except Exception as e:
            logging.error(f"Ошибка при парсинге {store_name}: {str(e)}")
            return []

    def parse_store(self, store_name, store_info):
        """Парсинг отдельного магазина"""
        logging.info(f"Проверка магазина: {store_name}")
        
        # Специальная обработка для Перекрестка
        if store_name == "Перекрёсток":
            return self.parse_perekrestok()
        
        try:
            # Извлечение домена из URL
            domain = store_info["base_url"].split("//")[1].split("/")[0]
            session = self.get_session_with_cookies(domain)
            
            # Получаем страницу каталога
            url = urljoin(store_info["base_url"], store_info["catalog_url"])
            
            # Делаем несколько попыток с разными заголовками
            for attempt in range(3):
                # Обновляем User-Agent для каждой попытки
                session.headers["User-Agent"] = self.get_random_user_agent()
                
                try:
                    response = session.get(
                        url, 
                        timeout=15, 
                        allow_redirects=True
                    )
                    
                    if response.status_code == 200:
                        break
                        
                    logging.warning(f"Попытка {attempt+1} для {store_name} завершилась с кодом: {response.status_code}")
                    time.sleep(random.uniform(3, 6))
                except requests.exceptions.RequestException as e:
                    logging.warning(f"Попытка {attempt+1} для {store_name} вызвала исключение: {str(e)}")
                    time.sleep(random.uniform(3, 6))
            
            if response.status_code != 200:
                logging.error(f"Ошибка доступа к сайту {store_name}: {response.status_code}")
                return []
            
            # Сохраняем cookies
            self.save_cookies(domain, session.cookies)
            
            # Обрабатываем HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            items = soup.select(store_info["item_selector"])
            
            good_deals = []
            for item in items:
                try:
                    name_elem = item.select_one(store_info["name_selector"])
                    price_elem = item.select_one(store_info["price_selector"])
                    old_price_elem = item.select_one(store_info["old_price_selector"])
                    discount_elem = item.select_one(store_info["discount_selector"])
                    
                    if not name_elem or not price_elem:
                        continue
                    
                    name = name_elem.get_text().strip()
                    
                    # Извлечение цены с использованием регулярных выражений
                    price_text = price_elem.get_text().strip()
                    price_match = re.search(r'(\d+[.,]?\d*)', price_text.replace(' ', ''))
                    if not price_match:
                        continue
                    price = float(price_match.group(1).replace(',', '.'))
                    
                    # Определяем, есть ли скидка
                    discount_percent = 0
                    if old_price_elem:
                        old_price_text = old_price_elem.get_text().strip()
                        old_price_match = re.search(r'(\d+[.,]?\d*)', old_price_text.replace(' ', ''))
                        if old_price_match:
                            old_price = float(old_price_match.group(1).replace(',', '.'))
                            discount_percent = round((old_price - price) / old_price * 100)
                    elif discount_elem:
                        discount_text = discount_elem.get_text().strip()
                        discount_match = re.search(r'(\d+)[%]?', discount_text)
                        if discount_match:
                            discount_percent = int(discount_match.group(1))
                    
                    # Формируем ссылку на товар
                    product_link = ""
                    link_elem = item.select_one('a')
                    if link_elem and link_elem.has_attr('href'):
                        product_link = urljoin(store_info["base_url"], link_elem['href'])
                    
                    # Проверяем, соответствует ли товар критериям
                    product_id = f"{store_name}_{name}_{price}"
                    if (price <= self.config["max_price"] or discount_percent >= self.config["min_discount"]) and product_id not in self.found_products:
                        good_deals.append({
                            "store": store_name,
                            "name": name,
                            "price": price,
                            "discount": discount_percent,
                            "link": product_link
                        })
                        self.found_products.add(product_id)
                        logging.info(f"Найден подходящий товар: {name}, цена: {price}₽, скидка: {discount_percent}%")
                
                except Exception as e:
                    logging.error(f"Ошибка при обработке товара в {store_name}: {str(e)}")
            
            logging.info(f"Найдено {len(good_deals)} товаров со скидкой или дешевле {self.config['max_price']}₽ в {store_name}")
            return good_deals
            
        except Exception as e:
            logging.error(f"Ошибка при парсинге {store_name}: {str(e)}")
            return []

    def send_notification(self, product):
        """Отправка уведомления о найденном товаре в Telegram"""
        if not self.bot:
            logging.info(f"Телеграм-бот не настроен, пропуск отправки уведомления для товара: {product['name']}")
            return
            
        discount_info = f", скидка: {product['discount']}%" if product['discount'] > 0 else ""
        message = (
            f"💥 *Найден товар по вашим критериям!*\n\n"
            f"🏪 *Магазин:* {product['store']}\n"
            f"🛒 *Товар:* {product['name']}\n"
            f"💰 *Цена:* {product['price']} ₽{discount_info}\n"
            f"📍 *Адрес:* {self.config['address']}\n"
            f"🔗 [Перейти к товару]({product['link']})"
        )
        
        try:
            self.bot.send_message(
                chat_id=CHAT_ID,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=False
            )
            logging.info(f"Уведомление отправлено: {product['name']}")
        except Exception as e:
            logging.error(f"Ошибка при отправке уведомления: {str(e)}")

    def monitor(self):
        """Основной метод мониторинга"""
        while True:
            logging.info("Запуск парсера по магазинам...")
            self.config["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.save_config(self.config)
            
            found_any = False
            for store_name, store_info in STORES.items():
                deals = self.parse_store(store_name, store_info)
                
                if deals:
                    found_any = True
                    for deal in deals:
                        self.send_notification(deal)
                
                # Случайная пауза между запросами к разным магазинам для имитации человеческого поведения
                time.sleep(random.uniform(5, 15))
            
            if not found_any:
                logging.info("Не найдено товаров, соответствующих критериям")
            
            next_check = self.config["check_interval"]
            logging.info(f"Ждем {next_check // 60} минут до следующей проверки...")
            
            try:
                # Разбиваем большой таймер на маленькие интервалы для возможности прерывания
                interval = 30  # 30 секунд
                for _ in range(next_check // interval):
                    time.sleep(interval)
                    # Проверяем наличие сигнала для остановки (можно реализовать через файл)
                    if os.path.exists("stop_parser.signal"):
                        logging.info("Обнаружен сигнал остановки парсера")
                        os.remove("stop_parser.signal")
                        return
                
                # Остаток времени
                time.sleep(next_check % interval)
            except KeyboardInterrupt:
                logging.info("Парсер остановлен пользователем")
                break

def manual_test():
    """Функция для ручного тестирования парсера на одном магазине"""
    parser = FoodDeliveryParser()
    
    # Выбираем магазин для тестирования
    store_name = "Перекрёсток"
    store_info = STORES[store_name]
    
    logging.info(f"Запуск тестового парсинга для {store_name}...")
    deals = parser.parse_store(store_name, store_info)
    
    if deals:
        logging.info(f"Найдено {len(deals)} подходящих товаров:")
        for i, deal in enumerate(deals, 1):
            logging.info(f"{i}. {deal['name']} - {deal['price']}₽ (скидка: {deal['discount']}%)")
            # Можно раскомментировать для тестирования отправки в Telegram
            # parser.send_notification(deal)
    else:
        logging.info(f"Не найдено подходящих товаров в {store_name}")

if __name__ == "__main__":
    # Раскомментируйте для тестирования одного магазина
    # manual_test()
    
    # Запуск полного мониторинга
    parser = FoodDeliveryParser()
    parser.monitor()