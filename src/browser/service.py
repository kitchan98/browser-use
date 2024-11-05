"""
Selenium browser on steroids.
"""

import base64
import os
import tempfile
import time
from typing import Literal

from main_content_extractor import MainContentExtractor
from Screenshot import Screenshot
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from src.browser.views import BrowserState
from src.dom.service import DomService
from src.utils import time_execution_sync


class BrowserService:
	def __init__(self, headless: bool = False):
		self.headless = headless
		self.driver: webdriver.Chrome | None = None
		self._ob = Screenshot.Screenshot()
		self.MINIMUM_WAIT_TIME = 0.5
		self.MAXIMUM_WAIT_TIME = 5

	def init(self) -> webdriver.Chrome:
		"""
		Sets up and returns a Selenium WebDriver instance with anti-detection measures.

		Returns:
		    webdriver.Chrome: Configured Chrome WebDriver instance
		"""
		chrome_options = Options()
		if self.headless:
			chrome_options.add_argument('--headless')

		# Anti-detection measures
		chrome_options.add_argument('--disable-blink-features=AutomationControlled')
		chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
		chrome_options.add_experimental_option('useAutomationExtension', False)

		# Additional stealth settings
		chrome_options.add_argument('--window-size=1024,1024')
		chrome_options.add_argument('--disable-extensions')
		chrome_options.add_argument('--no-sandbox')
		chrome_options.add_argument('--disable-infobars')

		# Initialize the Chrome driver
		driver = webdriver.Chrome(
			service=Service(ChromeDriverManager().install()), options=chrome_options
		)

		# Execute stealth scripts
		driver.execute_cdp_cmd(
			'Page.addScriptToEvaluateOnNewDocument',
			{
				'source': """
				Object.defineProperty(navigator, 'webdriver', {
					get: () => undefined
				});
				
				Object.defineProperty(navigator, 'languages', {
					get: () => ['en-US', 'en']
				});
				
				Object.defineProperty(navigator, 'plugins', {
					get: () => [1, 2, 3, 4, 5]
				});
				
				window.chrome = {
					runtime: {}
				};
				
				Object.defineProperty(navigator, 'permissions', {
					get: () => ({
						query: Promise.resolve.bind(Promise)
					})
				});
			"""
			},
		)

		self.driver = driver
		return driver

	def _get_driver(self) -> webdriver.Chrome:
		if self.driver is None:
			self.driver = self.init()
		return self.driver

	def wait_for_page_load(self):
		"""
		Ensures page is fully loaded before continuing.
		Waits for either document.readyState to be complete or minimum WAIT_TIME, whichever is longer.
		"""
		driver = self._get_driver()

		# Start timing
		start_time = time.time()

		# Wait for page load
		try:
			WebDriverWait(driver, 5).until(
				lambda d: d.execute_script('return document.readyState') == 'complete'
			)
		except Exception:
			pass

		# Calculate remaining time to meet minimum WAIT_TIME
		elapsed = time.time() - start_time
		remaining = max(self.MINIMUM_WAIT_TIME - elapsed, 0)

		print(
			f'Page loaded in {elapsed:.2f} seconds, waiting for additional {remaining:.2f} seconds'
		)

		# Sleep remaining time if needed
		if remaining > 0:
			time.sleep(remaining)

	def get_updated_state(self) -> BrowserState:
		"""
		Update and return state.
		"""
		driver = self._get_driver()
		dom_service = DomService(driver)
		content = dom_service.get_clickable_elements()
		self.current_state = BrowserState(
			items=content.items,
			selector_map=content.selector_map,
			url=driver.current_url,
			title=driver.title,
		)

		return self.current_state

	def close(self):
		driver = self._get_driver()
		driver.quit()
		self.driver = None

	def __del__(self):
		"""
		Close the browser driver when instance is destroyed.
		"""
		if self.driver is not None:
			self.close()

	# region - Browser Actions

	def search_google(self, query: str):
		"""
		@dev TODO: add serp api call here
		"""
		driver = self._get_driver()
		driver.get(f'https://www.google.com/search?q={query}')
		self.wait_for_page_load()

	def go_to_url(self, url: str):
		driver = self._get_driver()
		driver.get(url)
		self.wait_for_page_load()

	def go_back(self):
		driver = self._get_driver()
		driver.back()
		self.wait_for_page_load()

	def refresh(self):
		driver = self._get_driver()
		driver.refresh()
		self.wait_for_page_load()

	def extract_page_content(self, value: Literal['text', 'markdown'] = 'markdown') -> str:
		"""
		TODO: switch to a better parser/extractor
		"""
		driver = self._get_driver()
		content = MainContentExtractor.extract(driver.page_source, output_format=value)  # type: ignore TODO
		return content

	def done(self, text: str):
		"""
		Ends the task and waits for further instructions.
		"""
		print(f'Done on page {self.current_state.url}\n\n: {text}')
		return text

	def take_screenshot(self, full_page: bool = False) -> str:
		"""
		Returns a base64 encoded screenshot of the current page.
		"""
		driver = self._get_driver()
		if full_page:
			# Create temp directory
			temp_dir = tempfile.mkdtemp()
			screenshot = self._ob.full_screenshot(
				driver,
				save_path=temp_dir,
				image_name='temp.png',
				is_load_at_runtime=True,
				load_wait_time=1,
			)

			# Read file as base64
			with open(os.path.join(temp_dir, 'temp.png'), 'rb') as img:
				screenshot = base64.b64encode(img.read()).decode('utf-8')

			# Cleanup temp directory
			os.remove(os.path.join(temp_dir, 'temp.png'))
			os.rmdir(temp_dir)
		else:
			screenshot = driver.get_screenshot_as_base64()
		return screenshot

	# endregion

	# region - User Actions
	def _webdriver_wait(self):
		driver = self._get_driver()
		return WebDriverWait(driver, 10)

	def _input_text_by_xpath(self, xpath: str, text: str):
		driver = self._get_driver()

		try:
			# Wait for element to be both present and interactable
			element = self._webdriver_wait().until(EC.element_to_be_clickable((By.XPATH, xpath)))

			# Scroll element into view using ActionChains for smoother scrolling
			actions = ActionChains(driver)
			actions.move_to_element(element).perform()

			# Try to clear using JavaScript first
			driver.execute_script("arguments[0].value = '';", element)

			# Then send keys
			element.send_keys(text)

			self.wait_for_page_load()

		except Exception as e:
			raise Exception(
				f'Failed to input text into element with xpath: {xpath}. Error: {str(e)}'
			)

	def input_text_by_index(self, index: int, text: str, state: BrowserState):
		if index not in state.selector_map:
			raise Exception(f'Element index {index} not found in selector map')

		xpath = state.selector_map[index]
		self._input_text_by_xpath(xpath, text)

	def _click_element_by_xpath(self, xpath: str):
		"""
		Optimized method to click an element using xpath.
		"""
		driver = self._get_driver()
		wait = self._webdriver_wait()

		try:
			# First try the direct approach with a shorter timeout
			try:
				element = wait.until(
					EC.element_to_be_clickable((By.XPATH, xpath)),
					message=f'Element not clickable: {xpath}',
				)
				driver.execute_script('arguments[0].click();', element)
				self.wait_for_page_load()
				return
			except Exception:
				pass

			# If that fails, try a simplified approach
			try:
				# Try with ID if present in xpath
				if 'id=' in xpath:
					id_value = xpath.split('id=')[-1].split(']')[0]
					element = driver.find_element(By.ID, id_value)
					if element.is_displayed() and element.is_enabled():
						driver.execute_script('arguments[0].click();', element)
						self.wait_for_page_load()
						return
			except Exception:
				pass

			# Last resort: force click with JavaScript
			try:
				element = driver.find_element(By.XPATH, xpath)
				driver.execute_script(
					"""
					arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});
					arguments[0].click();
				""",
					element,
				)
				self.wait_for_page_load()
				return
			except Exception as e:
				raise Exception(f'Failed to click element: {str(e)}')

		except Exception as e:
			raise Exception(f'Failed to click element with xpath: {xpath}. Error: {str(e)}')

	@time_execution_sync('click')
	def click_element_by_index(self, index: int, state: BrowserState):
		"""
		Clicks an element using its index from the selector map.
		"""
		if index not in state.selector_map:
			raise Exception(f'Element index {index} not found in selector map')

		xpath = state.selector_map[index]
		self._click_element_by_xpath(xpath)

	# endregion
