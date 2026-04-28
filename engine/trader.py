import asyncio
import datetime
from util.market_hour import MarketHour
from util.get_setting import update_setting
from util.tel_send import tel_send
from util.login import fn_au10001


class TraderMixin:
	async def _wait_for_market_start_plus_one_minute(self):
		"""장 시작 후 1분까지 대기"""
		now          = datetime.datetime.now()
		market_start = now.replace(hour=MarketHour.MARKET_START_HOUR, minute=MarketHour.MARKET_START_MINUTE, second=0, microsecond=0)
		wait_until   = market_start + datetime.timedelta(minutes=1)

		if now < wait_until:
			wait_seconds = (wait_until - now).total_seconds()
			print(f"장 시작 1분 후까지 {wait_seconds}초 대기...")
			await asyncio.sleep(wait_seconds)

	async def _trading_loop(self):
		"""트레이딩 로직을 실행하는 백그라운드 루프"""
		try:
			await self._wait_for_market_start_plus_one_minute()

			# ORB 전용 후보 선정 (09:01, 1회 고정 — 이후 갱신 없음)
			await self._get_orb_candidates()

			# 모멘텀 후보 선정 (실패해도 루프는 유지 - 다음 갱신 주기에 재시도)
			await self._select_initial_stocks()

			last_refresh_time = datetime.datetime.now()
			self.current_phase = MarketHour.get_market_phase()

			while self.is_running and MarketHour.is_market_open_time():
				now   = datetime.datetime.now()
				phase = MarketHour.get_market_phase()

				# ── 구간 전환 감지 ──────────────────────────────
				if phase != self.current_phase:
					tel_send(f"🕐 구간 전환: {self._phase_name(self.current_phase)} → {self._phase_name(phase)}")
					self.current_phase = phase
					# 장 후반 전환 시에는 신규 선정 없음 (기존 유지)
					if phase != 'late':
						await self._select_initial_stocks()
					last_refresh_time = now

				# ── 주기 갱신 (장 초반 2분 / 장 중반·후반 10분) ──
				else:
					refresh_interval = self.EARLY_STOCK_REFRESH_INTERVAL if phase == 'early' else self.STOCK_REFRESH_INTERVAL
					if (now - last_refresh_time).total_seconds() >= refresh_interval:
						await self._refresh_selected_stocks(phase=phase)
						last_refresh_time = now

				await self._check_charts_and_trade()
				self.last_chart_check_time = now
				await asyncio.sleep(60)

		except asyncio.CancelledError:
			print("트레이딩 루프가 중지되었습니다")
		except Exception as e:
			print(f"트레이딩 루프 오류: {e}")
			tel_send(f"❌ 트레이딩 루프 오류: {e}")

	def get_token(self):
		"""새로운 토큰을 발급받습니다."""
		try:
			token = fn_au10001()
			if token:
				self.token = token
				print(f"새로운 토큰 발급 완료: {token[:10]}...")
				return token
			else:
				print("토큰 발급 실패")
				return None
		except Exception as e:
			print(f"토큰 발급 중 오류: {e}")
			return None

	async def start(self):
		"""start 명령어를 처리합니다."""
		try:
			if self.is_running:
				tel_send("⚠️ 이미 실행 중입니다")
				return False

			# 새로운 토큰 발급
			token = self.get_token()
			if not token:
				tel_send("❌ 토큰 발급에 실패했습니다")
				return False

			# auto_start를 true로 설정
			if not update_setting('auto_start', True):
				tel_send("❌ 설정 파일 업데이트 실패")
				return False

			# 장이 열리지 않았을 때는 auto_start만 설정하고 메시지 전송
			if not MarketHour.is_market_open_time():
				tel_send(f"⏰ 장이 열리지 않았습니다. 장 시작 시간({MarketHour.MARKET_START_HOUR:02d}:{MarketHour.MARKET_START_MINUTE:02d})에 자동으로 시작됩니다.")
				return True

			# 프로세스 시작
			self.is_running = True
			self.selected_stocks = []
			self.selected_stocks_names = {}
			self.last_chart_check_time = None
			self.orb_candidates = []

			# 백그라운드 태스크 시작
			self.trading_task      = asyncio.create_task(self._trading_loop())
			self.profit_check_task = asyncio.create_task(self._profit_check_loop())

			tel_send("✅ 트레이딩 프로세스가 시작되었습니다")
			return True

		except Exception as e:
			tel_send(f"❌ start 명령어 실행 중 오류: {e}")
			return False

	async def stop(self, set_auto_start_false=True):
		"""stop 명령어를 처리합니다."""
		try:
			# auto_start 설정 (사용자 명령일 때만 false로 설정)
			if set_auto_start_false:
				if not update_setting('auto_start', False):
					tel_send("❌ 설정 파일 업데이트 실패")
					return False

			# 프로세스 중지
			self.is_running = False

			# 백그라운드 태스크 정지
			if self.trading_task and not self.trading_task.done():
				self.trading_task.cancel()
				try:
					await self.trading_task
				except asyncio.CancelledError:
					pass

			if self.profit_check_task and not self.profit_check_task.done():
				self.profit_check_task.cancel()
				try:
					await self.profit_check_task
				except asyncio.CancelledError:
					pass

			self.selected_stocks = []
			self.selected_stocks_names = {}
			self.last_chart_check_time = None
			self.orb_data = {}
			self.orb_buy_count = 0
			self.orb_candidates = []

			tel_send("✅ 트레이딩 프로세스가 중지되었습니다")
			return True

		except Exception as e:
			tel_send(f"❌ stop 명령어 실행 중 오류: {e}")
			return False
