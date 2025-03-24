import logging
import time
import random
import requests
from bs4 import BeautifulSoup
import re
import json
from fake_useragent import UserAgent
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='food_parser.log'
)
logger = logging.getLogger(__name__)

# Настройки Telegram бота
TELEGRAM_TOKEN = '7809190658:AAEi_uG41kvEanBFohFJpDE43eMOEpUcBcI'
CHAT_ID = '@salesbuyers'

# Настройки для запросов
MAX_RETRIES = 3
RETRY_DELAY = 5  # Задержка между повторными запросами в секундах
DEFAULT_TIMEOUT = 10  # Таймаут для запросов

# Генератор случайных User-Agent
ua = UserAgent()

def get_random_headers():
    """Генерирует случайные заголовки для HTTP-запроса"""
    return {
        'User-Agent': ua.random,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
    }

def make_request(url, session=None, proxies=None):
    """Выполняет HTTP-запрос с обработкой ошибок и повторными попытками"""
    if session is None:
        session = requests.Session()
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            headers = get_random_headers()
            response = session.get(
                url, 
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
                proxies=proxies,
                allow_redirects=True
            )
            
            # Проверка статуса ответа
            if response.status_code == 200:
                return response
            else:
                logger.warning(f"Попытка {attempt} для {url} завершилась с кодом: {response.status_code}")
                
                # Если это ошибка 403 или 503, возможно нас обнаружили как бота
                if response.status_code in [403, 503]:
                    logger.info(f"Сайт обнаружил бота, увеличиваем задержку и меняем заголовки")
                    time.sleep(RETRY_DELAY * 2)  # Увеличенная задержка
                else:
                    time.sleep(RETRY_DELAY)
                    
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к {url}: {e}")
            time.sleep(RETRY_DELAY)
    
    logger.error(f"Не удалось получить доступ к {url} после {MAX_RETRIES} попыток")
    return None

# Парсер для Перекрестка на Яндекс.Еде
def parse_perekrestok_yandex(region="Москва", max_price=50, min_discount=50):
    """Парсер для Перекрёстка через Яндекс.Еду"""
    products = []
    base_url = "https://eda.yandex.ru/retail/perekrestok"
    
    try:
        session = requests.Session()
        
        # Имитируем установку местоположения
        session.cookies.set("location", region)
        session.cookies.set("deliveryRegion", "213")  # Код региона Москвы в Яндексе
        
        # Устанавливаем более достоверные заголовки запроса
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://eda.yandex.ru/',
        }
        
        # Делаем запрос к API для получения данных
        api_url = f"{base_url}/catalog/promo-goods?placeSlug=perekrestok_vkbp"
        
        response = session.get(api_url, headers=headers, timeout=DEFAULT_TIMEOUT)
        
        if response.status_code == 200:
            try:
                # Пытаемся разобрать JSON
                data = response.json()
                
                # Обрабатываем данные о товарах из JSON
                if 'products' in data:
                    for item in data['products']:
                        try:
                            name = item.get('name', '')
                            
                            # Получаем цены
                            current_price = item.get('price', {}).get('value', 0) / 100  # Часто цены хранятся в копейках
                            
                            # Проверяем, есть ли скидка
                            old_price = item.get('oldPrice', {}).get('value', 0) / 100 if 'oldPrice' in item else current_price
                            
                            # Рассчитываем скидку
                            if old_price > current_price:
                                discount = round((1 - current_price / old_price) * 100)
                            else:
                                discount = 0
                            
                            # Проверяем условия поиска
                            if current_price <= max_price or discount >= min_discount:
                                # Формируем URL товара
                                product_id = item.get('id', '')
                                product_url = f"{base_url}/product?product_id={product_id}&placeSlug=perekrestok_vkbp"
                                
                                products.append({
                                    'name': name,
                                    'current_price': current_price,
                                    'old_price': old_price,
                                    'discount': discount,
                                    'url': product_url,
                                    'shop': 'Перекрёсток (Яндекс.Еда)',
                                    'region': region
                                })
                        except Exception as e:
                            logger.error(f"Ошибка при обработке товара: {e}")
                            continue
            except json.JSONDecodeError:
                # Если JSON невалидный, пробуем парсить как HTML
                logger.warning("Не удалось разобрать JSON, пробуем парсить HTML")
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Находим карточки товаров
                # Адаптируем селекторы на основе скриншотов
                product_cards = soup.select('article')
                
                for product in product_cards:
                    try:
                        # Ищем название товара
                        name_element = product.select_one('[data-testid="product-title"]')
                        if not name_element:
                            continue
                        
                        name = name_element.text.strip()
                        
                        # Ищем текущую цену
                        price_element = product.select_one('[data-testid="product-price"]')
                        if not price_element:
                            continue
                        
                        price_text = price_element.text.strip()
                        current_price = float(re.sub(r'[^\d.]', '', price_text))
                        
                        # Ищем старую цену (если есть скидка)
                        old_price_element = product.select_one('[data-testid="product-old-price"]')
                        if old_price_element:
                            old_price_text = old_price_element.text.strip()
                            old_price = float(re.sub(r'[^\d.]', '', old_price_text))
                            discount = round((1 - current_price / old_price) * 100)
                        else:
                            old_price = current_price
                            discount = 0
                        
                        # Проверяем условия
                        if current_price <= max_price or discount >= min_discount:
                            # Ищем ссылку на товар
                            link_element = product.select_one('a')
                            if link_element:
                                product_url = link_element.get('href', '')
                                if product_url and not product_url.startswith('http'):
                                    product_url = base_url + product_url
                                
                                products.append({
                                    'name': name,
                                    'current_price': current_price,
                                    'old_price': old_price,
                                    'discount': discount,
                                    'url': product_url,
                                    'shop': 'Перекрёсток (Яндекс.Еда)',
                                    'region': region
                                })
                    except Exception as e:
                        logger.error(f"Ошибка при парсинге HTML для товара: {e}")
                        continue
        else:
            logger.error(f"Ошибка при запросе к API: {response.status_code}")
    
    except Exception as e:
        logger.error(f"Ошибка при парсинге Перекрёсток через Яндекс.Еду: {e}")
    
    return products

# Обработчики команд Telegram
async def start(update, context):
    """Обработчик команды /start"""
    user = update.effective_user
    await update.message.reply_text(
        f'Привет, {user.first_name}! Я бот для поиска товаров со скидками.\n'
        f'Используйте /parse для запуска поиска.'
    )

async def parse_command(update, context):
    """Обработчик команды /parse"""
    chat_id = update.effective_chat.id
    
    await update.message.reply_text("Начинаю поиск товаров со скидками. Это может занять некоторое время...")
    
    region = "Москва"  # По умолчанию или можно получать из контекста пользователя
    
    # Собираем товары из всех сервисов
    all_products = []
    
    # Парсим Перекрёсток через Яндекс.Еду
    await update.message.reply_text("Проверяю Перекрёсток...")
    perekrestok_products = parse_perekrestok_yandex(region)
    all_products.extend(perekrestok_products)
    
    # Отправляем результаты в Telegram
    await send_to_telegram(context.bot, all_products, chat_id)

async def send_to_telegram(bot, products, chat_id):
    """Отправляет информацию о найденных товарах в Telegram"""
    if not products:
        await bot.send_message(chat_id=chat_id, text="Товары по заданным критериям не найдены.")
        return
        
    await bot.send_message(chat_id=chat_id, text=f"Найдено {len(products)} товаров со скидками:")
    
    for product in products[:20]:  # Ограничиваем количество сообщений
        discount_text = f" (скидка {product['discount']}%)" if product['discount'] > 0 else ""
        message = (
            f"🛒 {product['name']}\n"
            f"💰 Цена: {product['current_price']} руб{discount_text}\n"
            f"🏪 Магазин: {product['shop']}\n"
            f"📍 Регион: {product['region']}\n"
            f"🔗 {product['url']}"
        )
        await bot.send_message(chat_id=chat_id, text=message, disable_web_page_preview=False)
        time.sleep(0.5)  # Задержка между сообщениями

def main():
    """Основная функция для запуска бота"""
    # Создаем экземпляр приложения
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("parse", parse_command))
    
    # Запускаем бота до прерывания пользователем
    application.run_polling()

if __name__ == "__main__":
    main()