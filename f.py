import time
import logging
import re
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from webdriver_manager.chrome import ChromeDriverManager
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import random
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    TELEGRAM_TOKEN = input("Введите токен Telegram бота:7809190658:AAEi_uG41kvEanBFohFJpDE43eMOEpUcBcI ")

CHAT_ID = os.getenv('CHAT_ID')
if not CHAT_ID:
    CHAT_ID = input("Введите ID чата Telegram:@salesbuyers ")

# Delivery address for Perekrestok
DEFAULT_ADDRESS = "ул. Земляной Вал, 29, Москва"

class FoodDeliveryParser:
    def __init__(self, token=None):
        self.setup_driver()
        if token:
            self.bot = Bot(token=token)
        else:
            self.bot = None
        
    def setup_driver(self):
        """Setup Chrome driver with anti-detection measures"""
        options = Options()
        
        # Anti-detection measures
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Performance options
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Uncomment to run in headless mode when deploying
        # options.add_argument("--headless")
        
        # Add a random user agent
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        ]
        options.add_argument(f"user-agent={random.choice(user_agents)}")
        
        # Create a new Chrome driver instance
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        
        # Execute CDP commands to prevent detection
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
        
    def set_delivery_address(self, address=DEFAULT_ADDRESS):
        """Set the delivery address on Perekrestok site"""
        try:
            logger.info("Setting delivery address...")
            
            # Wait for address input field to be available
            address_input = WebDriverWait(self.driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[placeholder*='улица']"))
            )
            
            # Clear and set address
            address_input.clear()
            address_input.send_keys(address)
            
            # Wait for suggestions to appear and click the first one
            suggestion = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".ymaps-2-1-79-search-suggest-item"))
            )
            suggestion.click()
            
            # Click OK button to confirm address
            ok_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'OK') or contains(text(), 'Ок')]"))
            )
            ok_button.click()
            
            # Wait for page to update with new address
            time.sleep(5)
            logger.info("Address set successfully")
            return True
            
        except (TimeoutException, NoSuchElementException, ElementClickInterceptedException) as e:
            logger.error(f"Error setting address: {str(e)}")
            # Take screenshot for debugging
            self.driver.save_screenshot("address_error.png")
            return False
    
    def parse_perekrestok(self, url="https://www.perekrestok.ru/catalog/moloko-syr-yaytsa/moloko"):
        """Parse Perekrestok website for discounted products"""
        try:
            logger.info(f"Starting to parse URL: {url}")
            
            # Open the URL
            self.driver.get(url)
            time.sleep(5)  # Initial waiting time for page to load
            
            # Check if address selection is needed and set it
            if "Укажите адрес доставки" in self.driver.page_source:
                if not self.set_delivery_address():
                    logger.error("Failed to set delivery address")
                    return []
            
            # Wait for product cards to load
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='product-card']"))
                )
            except TimeoutException:
                # Try alternative selector if data-testid is not found
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".product-card"))
                )
            
            # Scroll down to load all products
            self._scroll_page()
            
            # Find all product cards (try multiple selectors)
            product_cards = []
            for selector in ["[data-testid='product-card']", ".product-card", ".xf-product"]:
                try:
                    cards = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if cards:
                        product_cards = cards
                        logger.info(f"Found {len(product_cards)} product cards using selector: {selector}")
                        break
                except Exception:
                    continue
            
            if not product_cards:
                logger.error("No product cards found")
                self.driver.save_screenshot("no_products.png")
                return []
            
            results = []
            for card in product_cards:
                try:
                    # Extract product information
                    product_info = self._extract_product_info(card)
                    
                    # Filter products by criteria (price < 50₽ or discount ≥ 50%)
                    if (product_info['current_price'] < 50 or 
                        (product_info['discount_percent'] and product_info['discount_percent'] >= 50)):
                        results.append(product_info)
                        logger.info(f"Found matching product: {product_info['name']} - {product_info['current_price']}₽")
                        
                except Exception as e:
                    logger.error(f"Error processing product card: {str(e)}")
                    continue
            
            return results
            
        except Exception as e:
            logger.error(f"Error in parse_perekrestok: {str(e)}")
            # Take screenshot for debugging
            self.driver.save_screenshot("parse_error.png")
            return []
    
    def _extract_product_info(self, card):
        """Extract product information from a card element"""
        try:
            # Try multiple selectors for each element to improve robustness
            
            # Get product name
            name = None
            for selector in ["[data-testid='title']", ".xf-product-title", ".product-card__title"]:
                try:
                    name_elem = card.find_element(By.CSS_SELECTOR, selector)
                    name = name_elem.text.strip()
                    if name:
                        break
                except Exception:
                    continue
            
            if not name:
                # If all selectors failed, try to get the text content of the card
                name = card.text.split('\n')[0].strip()
            
            # Get current price
            current_price = None
            for selector in ["[data-testid='price-current']", ".xf-product-price", ".product-card__price-current"]:
                try:
                    price_elem = card.find_element(By.CSS_SELECTOR, selector)
                    current_price_text = price_elem.text.strip()
                    # Extract digits and decimal point from price text
                    current_price = float(re.sub(r'[^\d.,]', '', current_price_text).replace(',', '.'))
                    break
                except Exception:
                    continue
            
            if current_price is None:
                # Try to extract price from the text content using regex
                card_text = card.text
                price_match = re.search(r'(\d+[.,]?\d*)\s*[₽Р]', card_text)
                if price_match:
                    current_price = float(price_match.group(1).replace(',', '.'))
                else:
                    current_price = 0.0
            
            # Try to get original price (if discounted)
            original_price = None
            discount_percent = None
            for selector in ["[data-testid='price-old']", ".xf-product-old-price", ".product-card__price-old"]:
                try:
                    original_price_elem = card.find_element(By.CSS_SELECTOR, selector)
                    original_price_text = original_price_elem.text.strip()
                    original_price = float(re.sub(r'[^\d.,]', '', original_price_text).replace(',', '.'))
                    break
                except Exception:
                    continue
            
            # Look for discount percentage directly
            if original_price is None:
                for selector in [".discount-label", ".product-card__discount"]:
                    try:
                        discount_elem = card.find_element(By.CSS_SELECTOR, selector)
                        discount_text = discount_elem.text.strip()
                        discount_match = re.search(r'-(\d+)[%％]', discount_text)
                        if discount_match:
                            discount_percent = int(discount_match.group(1))
                            if current_price > 0 and discount_percent > 0:
                                # Calculate original price from discount
                                original_price = current_price / (1 - discount_percent/100)
                            break
                    except Exception:
                        continue
            elif original_price > 0 and current_price > 0:
                # Calculate discount percentage
                discount_percent = round(((original_price - current_price) / original_price) * 100)
            
            # Get product URL
            url = None
            try:
                url = card.find_element(By.CSS_SELECTOR, "a").get_attribute("href")
            except Exception:
                # If we can't find a direct link, try to construct one from the product name
                product_id_match = re.search(r'data-product-id="(\d+)"', card.get_attribute('outerHTML'))
                if product_id_match:
                    product_id = product_id_match.group(1)
                    url = f"https://www.perekrestok.ru/cat/{product_id}/p/"
                else:
                    url = "https://www.perekrestok.ru"
            
            return {
                'name': name,
                'current_price': current_price,
                'original_price': original_price,
                'discount_percent': discount_percent,
                'url': url
            }
        except Exception as e:
            logger.error(f"Error extracting product info: {str(e)}")
            raise
    
    def _scroll_page(self):
        """Scroll the page to load all products"""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        max_attempts = 5
        
        while scroll_attempts < max_attempts:
            # Scroll down
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            # Wait for new content to load
            time.sleep(2)
            
            # Calculate new scroll height
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            
            # Check if the page height has remained the same
            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
                
            last_height = new_height
            
            # Break if we've made multiple attempts with no height change
            if scroll_attempts >= max_attempts:
                break
    
    async def send_to_telegram(self, products, chat_id=CHAT_ID):
        """Send product information to Telegram"""
        if not self.bot:
            logger.warning("Telegram bot not initialized")
            return
            
        if not products:
            await self.bot.send_message(chat_id=chat_id, text="Товары со скидкой не найдены.")
            return
            
        for product in products:
            discount_info = ""
            if product['discount_percent']:
                discount_info = f"Скидка: {product['discount_percent']}% (Старая цена: {product['original_price']}₽)"
                
            message = (
                f"🔥 *{product['name']}*\n"
                f"💰 Цена: *{product['current_price']}₽*\n"
                f"{discount_info}\n"
                f"🏪 Магазин: Перекресток\n"
                f"📍 Адрес доставки: {DEFAULT_ADDRESS}\n"
                f"[Посмотреть товар]({product['url']})"
            )
            
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=False
            )
            
            # Avoid Telegram rate limits
            time.sleep(1)
    
    def run_parser(self, categories=None):
        """Run the parser for multiple categories"""
        if categories is None:
            categories = [
                "https://www.perekrestok.ru/catalog/moloko-syr-yaytsa",
                "https://www.perekrestok.ru/catalog/ovoshchi-i-frukty",
                "https://www.perekrestok.ru/catalog/gotovaya-eda"
            ]
            
        all_products = []
        for category_url in categories:
            try:
                logger.info(f"Processing category: {category_url}")
                products = self.parse_perekrestok(category_url)
                all_products.extend(products)
            except Exception as e:
                logger.error(f"Error processing category {category_url}: {str(e)}")
        
        # Close the browser
        self.driver.quit()
        
        return all_products

# Telegram bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    await update.message.reply_text('Привет! Я бот для поиска выгодных продуктов. Используй /find для поиска скидок.')

async def find_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find deals command handler"""
    await update.message.reply_text('Начинаю поиск скидок в Перекрестке...')
    
    parser = FoodDeliveryParser(token=TELEGRAM_TOKEN)
    products = parser.run_parser()
    
    if not products:
        await update.message.reply_text('К сожалению, не удалось найти товары со скидкой.')
    else:
        await update.message.reply_text(f'Найдено {len(products)} товаров. Отправляю информацию...')
        
        for product in products:
            discount_info = ""
            if product['discount_percent']:
                discount_info = f"Скидка: {product['discount_percent']}% (Старая цена: {product['original_price']}₽)"
                
            message = (
                f"🔥 *{product['name']}*\n"
                f"💰 Цена: *{product['current_price']}₽*\n"
                f"{discount_info}\n"
                f"🏪 Магазин: Перекресток\n"
                f"📍 Адрес доставки: {DEFAULT_ADDRESS}\n"
                f"[Посмотреть товар]({product['url']})"
            )
            
            await update.message.reply_text(
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=False
            )
            
            # Avoid Telegram rate limits
            time.sleep(1)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors caused by updates"""
    logger.error(f'Update {update} caused error {context.error}')

async def main():
    """Run the bot"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("find", find_deals))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    await application.run_polling()

if __name__ == "__main__":
    try:
        # Тестовый режим без телеграма
        print("Запуск в режиме тестирования без отправки в Telegram")
        parser = FoodDeliveryParser()
        products = parser.parse_perekrestok("https://www.perekrestok.ru/catalog/moloko-syr-yaytsa/moloko")
        
        print(f"Найдено {len(products)} товаров, соответствующих критериям")
        for product in products:
            print(f"{product['name']} - {product['current_price']}₽")
        
        # Раскомментируй следующие строки для запуска бота
        # import asyncio
        # asyncio.run(main())
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        input("Нажмите Enter для выхода...")