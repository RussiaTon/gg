import logging
import re
import time
import requests
from bs4 import BeautifulSoup
from telegram import Bot
import asyncio
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация Telegram
TELEGRAM_TOKEN = '7809190658:AAEi_uG41kvEanBFohFJpDE43eMOEpUcBcI'
CHAT_ID = '@salesbuyers'

# Параметры поиска
MIN_DISCOUNT_PERCENT = 50  # Минимальный процент скидки
MAX_PRICE = 50  # Максимальная цена в рублях
DELIVERY_ADDRESS = 'Москва, ул. Примерная, д. 1'  # Ваш адрес доставки

class FoodDeliveryParser:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_TOKEN)
        # Настройка Chrome для работы в фоновом режиме
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Инициализация WebDriver
        self.driver = webdriver.Chrome(options=chrome_options)
        
    def close(self):
        """Закрыть WebDriver после завершения работы"""
        if self.driver:
            self.driver.quit()
            
    def extract_price(self, price_text):
        """Извлечь числовую цену из текста"""
        if not price_text:
            return 0.0
        
        # Удалить все нецифровые символы, кроме десятичной точки
        price_match = re.search(r'(\d+[.,]?\d*)', price_text.replace(' ', ''))
        if price_match:
            return float(price_match.group(1).replace(',', '.'))
        return 0.0
        
    def extract_discount(self, discount_text):
        """Извлечь процент скидки из текста"""
        if not discount_text:
            return 0
            
        discount_match = re.search(r'-(\d+)%', discount_text)
        if discount_match:
            return int(discount_match.group(1))
        return 0
        
    async def send_telegram_message(self, message):
        """Отправить сообщение в Telegram"""
        await self.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='HTML')
        
    def parse_perekrestok_category(self, url):
        """Парсинг категории Перекрестка с использованием Selenium"""
        logger.info(f"Начинаем парсинг URL: {url}")
        
        self.driver.get(url)
        time.sleep(3)  # Даем время для загрузки страницы
        
        # Ждем загрузки карточек товаров
        try:
            # На основе скриншота, карточки товаров могут иметь другой класс
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-testid='Product']"))
            )
        except TimeoutException:
            logger.error("Истекло время ожидания загрузки страницы")
            return []
            
        # Прокрутка вниз для загрузки большего количества товаров
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        for _ in range(5):  # Прокручиваем несколько раз, чтобы загрузить больше товаров
            self.driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(2)  # Ждем загрузки контента
            
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            
        # Получаем исходный код страницы после выполнения JavaScript
        page_source = self.driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # Ищем все карточки товаров
        # Используем селектор, который подходит для товаров на странице
        product_cards = soup.select("article[data-testid='Product']")
        logger.info(f"Найдено {len(product_cards)} карточек товаров")
        
        matching_products = []
        
        for card in product_cards:
            try:
                # Извлекаем название товара
                title_element = card.select_one("h3")
                if not title_element:
                    continue
                    
                product_title = title_element.text.strip()
                
                # Извлекаем текущую цену
                # Ищем цены в разных форматах
                price_elements = card.select("span")
                current_price = 0
                original_price = 0
                
                for element in price_elements:
                    price_text = element.text.strip()
                    if '₽' in price_text:
                        # Проверяем, является ли это текущей или старой ценой
                        if 'старая' in element.get('class', []) or 'old' in element.get('class', []):
                            original_price = self.extract_price(price_text)
                        else:
                            current_price = self.extract_price(price_text)
                
                # Если мы все еще не нашли цену, ищем ее по формату
                if current_price == 0:
                    for element in price_elements:
                        price_text = element.text.strip()
                        if '₽' in price_text:
                            # Если мы еще не определили текущую цену, это она
                            current_price = self.extract_price(price_text)
                            break
                
                # Если мы все еще не нашли цену, проверим весь текст карточки
                if current_price == 0:
                    all_text = card.get_text().strip()
                    price_match = re.search(r'(\d+)\s*₽', all_text)
                    if price_match:
                        current_price = float(price_match.group(1))
                
                # Извлекаем процент скидки
                discount_element = card.select_one("div.discount")
                discount_percent = 0
                
                if discount_element:
                    discount_text = discount_element.text.strip()
                    discount_percent = self.extract_discount(discount_text)
                elif original_price > 0 and current_price > 0:
                    # Вычисляем скидку, если она не указана явно
                    discount_percent = int(((original_price - current_price) / original_price) * 100)
                
                # Определяем, есть ли скидка по тексту
                if discount_percent == 0:
                    discount_text = card.get_text()
                    discount_match = re.search(r'-(\d+)%', discount_text)
                    if discount_match:
                        discount_percent = int(discount_match.group(1))
                
                # Получаем URL товара
                product_link = card.find('a')
                product_url = ""
                if product_link and 'href' in product_link.attrs:
                    product_url = "https://eda.yandex.ru" + product_link['href']
                
                # Проверяем, соответствует ли товар нашим критериям
                if (current_price <= MAX_PRICE and current_price > 0) or (discount_percent >= MIN_DISCOUNT_PERCENT):
                    product_info = {
                        'title': product_title,
                        'current_price': current_price,
                        'original_price': original_price,
                        'discount_percent': discount_percent,
                        'url': product_url
                    }
                    matching_products.append(product_info)
                    
                    logger.info(f"Найден подходящий товар: {product_title} - {current_price}₽ (Скидка: {discount_percent}%)")
                    
            except Exception as e:
                logger.error(f"Ошибка при обработке карточки товара: {e}")
                
        return matching_products
    
    def get_category_urls(self, base_url):
        """Получить URLs всех категорий для Перекрестка"""
        self.driver.get(base_url)
        time.sleep(3)  # Ждем загрузку страницы
        
        # Сохраняем категории из боковой панели, которая видна на скриншоте
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        
        # Ищем все элементы навигации по категориям в боковом меню
        category_links = []
        
        # Пробуем найти категории в боковом меню
        side_menu_categories = soup.select("a.UiKitSideMenu__link")
        for category in side_menu_categories:
            href = category.get('href')
            if href and '/catalog/' in href:
                full_url = f"https://eda.yandex.ru{href}"
                category_links.append(full_url)
                logger.info(f"Найдена категория в боковом меню: {category.text.strip()} ({full_url})")
        
        # Если не найдено категорий в боковом меню, ищем другие категории
        if not category_links:
            all_links = soup.find_all('a')
            for link in all_links:
                href = link.get('href')
                if href and '/catalog/' in href and 'placeSlug=' in href:
                    full_url = f"https://eda.yandex.ru{href}"
                    if full_url not in category_links:
                        category_links.append(full_url)
                        logger.info(f"Найдена категория: {link.text.strip()} ({full_url})")
        
        # Если все еще не найдено категорий, используем ссылки из вашего сообщения
        if not category_links:
            logger.info("Категории не найдены, используем предоставленные ссылки")
            category_links = [
                "https://eda.yandex.ru/retail/perekrestok/catalog/44008?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/241010?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/290456?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/21857?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/21849?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/2873?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/158336?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/268686?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/2910?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/167?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/220376?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/222879?placeSlug=perekrestok_wjtsp",
                "https://eda.yandex.ru/retail/perekrestok/catalog/220380?placeSlug=perekrestok_wjtsp"
            ]
        
        logger.info(f"Всего найдено {len(category_links)} категорий для парсинга")
        return category_links
        
    async def run(self):
        """Основная функция для запуска парсера"""
        try:
            # Базовая URL для Перекрестка
            base_url = "https://eda.yandex.ru/retail/perekrestok/catalog?placeSlug=perekrestok_wjtsp"
            
            # Получаем URL категорий
            category_urls = self.get_category_urls(base_url)
            
            if not category_urls:
                logger.error("Не удалось найти категории для парсинга")
                await self.send_telegram_message("Не удалось найти категории для парсинга. Проверьте структуру сайта.")
                return
            
            all_matching_products = []
            
            # Парсим каждую категорию
            for category_url in category_urls:
                category_products = self.parse_perekrestok_category(category_url)
                if category_products:
                    all_matching_products.extend(category_products)
            
            if all_matching_products:
                # Отправляем результаты в Telegram
                message = f"Найдено {len(all_matching_products)} товаров в Перекрестке по вашим критериям:\n\n"
                
                for product in all_matching_products[:10]:  # Ограничиваем до 10 товаров на сообщение
                    discount_info = f" (Скидка: {product['discount_percent']}%)" if product['discount_percent'] > 0 else ""
                    message += f"• <b>{product['title']}</b>\n"
                    message += f"  Цена: {product['current_price']}₽{discount_info}\n"
                    if product['url']:
                        message += f"  <a href='{product['url']}'>Перейти к товару</a>\n\n"
                    else:
                        message += "\n"
                
                message += f"\nАдрес доставки: {DELIVERY_ADDRESS}"
                
                await self.send_telegram_message(message)
                
                # Если найдено больше 10 товаров, отправляем дополнительные сообщения
                if len(all_matching_products) > 10:
                    chunks = [all_matching_products[i:i+10] for i in range(10, len(all_matching_products), 10)]
                    
                    for chunk in chunks:
                        message = "Дополнительные товары в Перекрестке:\n\n"
                        
                        for product in chunk:
                            discount_info = f" (Скидка: {product['discount_percent']}%)" if product['discount_percent'] > 0 else ""
                            message += f"• <b>{product['title']}</b>\n"
                            message += f"  Цена: {product['current_price']}₽{discount_info}\n"
                            if product['url']:
                                message += f"  <a href='{product['url']}'>Перейти к товару</a>\n\n"
                            else:
                                message += "\n"
                        
                        await self.send_telegram_message(message)
            else:
                await self.send_telegram_message("В Перекрестке не найдено товаров, соответствующих критериям.")
                
        except Exception as e:
            logger.error(f"Ошибка в методе run: {e}")
            await self.send_telegram_message(f"Произошла ошибка при парсинге: {e}")
        finally:
            self.close()

async def main():
    parser = FoodDeliveryParser()
    await parser.run()

if __name__ == "__main__":
    asyncio.run(main())