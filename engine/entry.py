import asyncio
import datetime
from api.chart import fn_ka10080
from api.account import fn_kt00004, fn_kt00001
from api.order import fn_kt10000
from api.market import fn_ka10001, fn_get_market_index
from util.market_hour import MarketHour
from util.get_setting import get_setting
from util.tel_send import tel_send
from util.logger import get_logger


class EntryMixin:
	async def _check_charts_and_trade(self):
		"""1분봉 기준 고점 돌파 진입 / 데드크로스+RSI 청산 (phase 기반)"""
		max_retries = 5
		retry_delay = 1  # 1초

		for attempt in range(max_retries):
			try:
				chart_short      = get_setting('chart_short', 5)
				chart_long       = get_setting('chart_long', 20)
				rsi_period       = 14
				cooldown_minutes = 20
				needed = max(chart_long + 1, rsi_period + 2)

				# ── Phase별 고점 돌파 기준 ───────────────────────
				phase = MarketHour.get_market_phase()
				breakout_bars = 3 if phase == 'early' else 5

				# 보유 종목 확인
				my_stocks, _, _ = await asyncio.get_event_loop().run_in_executor(
					None, fn_kt00004, False, 'N', '', self.token
				)
				if my_stocks is None:
					# API 실패 시 보유 종목 확인 불가 → 이중 매수 방지를 위해 이번 회차 스킵
					get_logger().warning('[차트체크] fn_kt00004 실패 — 이번 회차 스킵')
					await asyncio.sleep(5)
					continue
				held_stock_codes = [stock['stk_cd'].replace('A', '') for stock in my_stocks]

				# 체크할 종목 (선정된 종목 + 보유 종목)
				stocks_to_check = list(set(self.selected_stocks + held_stock_codes))

				for stk_cd in stocks_to_check:
					# 1분봉 데이터 조회 (needed개, 최신순) - 종가 + 거래량 + 시가 + 고가
					prices, volumes, open_prices, highs = await asyncio.get_event_loop().run_in_executor(
						None, fn_ka10080, stk_cd, needed, 'N', '', self.token
					)
					await asyncio.sleep(0.3)  # API 호출 간격

					# 데이터 유효성 검사
					if len(prices) < needed or any(p == 0.0 for p in prices):
						print(f"{stk_cd}: 데이터 부족 또는 유효하지 않음 ({len(prices)}/{needed}개)")
						continue

					current_price = prices[0]

					# ── 데드크로스 감지 (청산용) ──────────────────────────
					ma_short_curr = self._calc_ma(prices, chart_short)
					ma_long_curr  = self._calc_ma(prices, chart_long)
					ma_short_prev = self._calc_ma(prices[1:], chart_short)
					ma_long_prev  = self._calc_ma(prices[1:], chart_long)

					if None in (ma_short_curr, ma_long_curr, ma_short_prev, ma_long_prev):
						continue

					dead_cross = (ma_short_prev >= ma_long_prev) and (ma_short_curr < ma_long_curr)

					print(
						f"{stk_cd} | 현재가: {current_price:.0f} "
						f"| MA{chart_short}: {ma_short_curr:.1f} MA{chart_long}: {ma_long_curr:.1f}"
					)

					# ── 청산: 데드크로스 AND RSI < 45 ────────────────────
					if dead_cross and stk_cd in held_stock_codes:
						rsi_exit = self._calc_rsi(prices, rsi_period)
						if rsi_exit is not None and rsi_exit < 45:
							signal_info = (
								f"📉 데드크로스+RSI 청산\n"
								f"   MA{chart_short}: {ma_short_curr:.1f} < MA{chart_long}: {ma_long_curr:.1f}\n"
								f"   RSI: {rsi_exit:.1f} < 45"
							)
							await self._sell_stock(stk_cd, '데드크로스', signal_info=signal_info)
						else:
							print(f"{stk_cd}: 데드크로스 감지 but RSI {f'{rsi_exit:.1f}' if rsi_exit else 'N/A'} >= 45 - 청산 보류")

					# ── 진입 (phase별 조건) ──────────────────────────
					if stk_cd in self.selected_stocks and stk_cd not in held_stock_codes:

						breakout_high = max(prices[1:breakout_bars + 1])
						if current_price <= breakout_high:
							continue

						# 추격매수 방지: 돌파 기준점 대비 1% 초과 시 진입 금지
						if current_price > breakout_high * 1.01:
							continue

						# 쿨다운: 매도 후 20분 이내 재매수 금지
						last_sell = self.sell_cooldown.get(stk_cd)
						if last_sell:
							elapsed = (datetime.datetime.now() - last_sell).total_seconds() / 60
							if elapsed < cooldown_minutes:
								print(f"{stk_cd}: 쿨다운 중 ({elapsed:.0f}/{cooldown_minutes}분) - 매수 스킵")
								continue

						curr_vol = volumes[0] if len(volumes) > 0 else 0
						prev_vol = volumes[1] if len(volumes) > 1 else 0
						rsi      = self._calc_rsi(prices, rsi_period)
						rsi_str  = f"{rsi:.1f}" if rsi is not None else "N/A"

						if phase == 'early':
							# 최대 5회 진입 제한
							if self.early_buy_count >= 5:
								print(f"{stk_cd}: 장초반 최대 매수 5회 초과 - 매수 스킵")
								continue
							# 거래량 > 직전봉
							if prev_vol == 0 or curr_vol <= prev_vol:
								print(f"{stk_cd}: 거래량 미달 (현재 {curr_vol:.0f} <= 직전봉 {prev_vol:.0f}) - 매수 스킵")
								continue
							# 현재가 > 시가
							today_open = open_prices[-1] if open_prices and open_prices[-1] > 0 else 0
							if today_open > 0 and current_price <= today_open:
								print(f"{stk_cd}: 현재가({current_price:.0f}) <= 시가({today_open:.0f}) - 매수 스킵")
								continue
							# RSI > 50
							if rsi is None or rsi <= 50:
								print(f"{stk_cd}: RSI {rsi_str} <= 50 - 매수 스킵")
								continue

						elif phase == 'mid':
							# 거래량 > 직전봉
							if prev_vol == 0 or curr_vol <= prev_vol:
								print(f"{stk_cd}: 거래량 미달 (현재 {curr_vol:.0f} <= 직전봉 {prev_vol:.0f}) - 매수 스킵")
								continue
							# RSI > 55 OR 현재가 > MA20
							rsi_ok = rsi is not None and rsi > 55
							ma_ok  = current_price > ma_long_curr
							if not (rsi_ok or ma_ok):
								print(f"{stk_cd}: RSI {rsi_str} <= 55 AND 현재가({current_price:.0f}) <= MA{chart_long}({ma_long_curr:.1f}) - 매수 스킵")
								continue

						else:  # late
							# 거래량 > 직전봉
							if prev_vol == 0 or curr_vol <= prev_vol:
								print(f"{stk_cd}: 거래량 미달 (현재 {curr_vol:.0f} <= 직전봉 {prev_vol:.0f}) - 매수 스킵")
								continue
							# RSI > 60
							if rsi is None or rsi <= 60:
								print(f"{stk_cd}: RSI {rsi_str} <= 60 - 매수 스킵")
								continue
							# 현재가 > MA20
							if current_price <= ma_long_curr:
								print(f"{stk_cd}: 현재가({current_price:.0f}) <= MA{chart_long}({ma_long_curr:.1f}) - 매수 스킵")
								continue

						# ── 당일 2회 손실 종목 진입 금지 ────────────────
						if self.daily_loss_count.get(stk_cd, 0) >= 2:
							print(f"{stk_cd}: 당일 손실 {self.daily_loss_count[stk_cd]}회 - 금일 거래 금지")
							continue

						# ── 과열 종목 조건부 허용 (3개 중 2개 이상) ────────
						flu_rt = self.selected_stocks_meta.get(stk_cd, {}).get('flu_rt', 0)
						if flu_rt > 25:
							overheat_score = (
								(1 if curr_vol > prev_vol * 1.5 else 0) +
								(1 if current_price > ma_long_curr else 0) +
								(1 if rsi is not None and rsi > 65 else 0)
							)
							if overheat_score < 2:
								print(f"{stk_cd}: 과열(flu_rt={flu_rt:.1f}%) 예외조건 {overheat_score}/3 미달 - 매수 스킵")
								continue

						# ── 고점 근접 필터 (ka10001 당일 최고가 기준) ──────
						stk_info = await asyncio.get_event_loop().run_in_executor(
							None, fn_ka10001, stk_cd, 'N', '', self.token
						)
						if stk_info:
							intraday_high = stk_info.get('high_pric')
							if intraday_high and intraday_high > 0:
								if current_price >= intraday_high * 0.98:
									if curr_vol <= prev_vol * 1.7:
										print(f"{stk_cd}: 고점({intraday_high:.0f}) 근접+거래량 미달 - 매수 스킵")
										continue

						# ── 진입 스냅샷 빌드 ────────────────────────────
						meta = self.selected_stocks_meta.get(stk_cd, {})
						kospi_flu, kosdaq_flu = await asyncio.get_event_loop().run_in_executor(
							None, fn_get_market_index, self.token
						)
						entry_snapshot = {
							'entry_price':     current_price,
							'entry_rsi':       round(rsi, 2) if rsi is not None else None,
							'entry_flu_rt':    meta.get('flu_rt', 0),
							'entry_vol_ratio': round(curr_vol / prev_vol, 2) if prev_vol > 0 else None,
							'entry_score':     round(meta.get('score', 0), 4),
							'is_foreign':      meta.get('is_foreign', False),
							'kospi_flu':       kospi_flu,
							'kosdaq_flu':      kosdaq_flu,
						}

						signal_info = (
							f"📈 [{self._phase_name(phase)}] 고점 돌파 진입: {stk_cd}\n"
							f"   현재가: {current_price:.0f} > 직전{breakout_bars}봉 고점: {breakout_high:.0f}\n"
							f"   RSI: {rsi_str} | 거래량: {curr_vol:.0f} (직전봉: {prev_vol:.0f})"
						)
						bought = await self._buy_stock(stk_cd, current_price, signal_info=signal_info, snapshot=entry_snapshot)
						if bought and phase == 'early':
							self.early_buy_count += 1

				# 성공적으로 완료되면 루프 종료
				return

			except Exception as e:
				get_logger().error(f'[차트체크 오류] 시도 {attempt + 1}/{max_retries}: {e}', exc_info=True)
				if attempt < max_retries - 1:
					await asyncio.sleep(retry_delay)
				else:
					get_logger().error(f'[차트체크 실패] 최대 재시도 횟수({max_retries}) 초과')

	async def _buy_stock(self, stk_cd, current_price, signal_info='', snapshot=None):
		"""종목 매수. 성공 시 True, 실패 시 False 반환"""
		log = get_logger()
		try:
			entry = await asyncio.get_event_loop().run_in_executor(
				None, fn_kt00001, 'N', '', self.token
			)
			if not entry:
				log.warning(f'[매수] {stk_cd} 예수금 조회 실패 - 매수 취소')
				tel_send(f"❌ 매수 취소: {stk_cd} (예수금 조회 실패)")
				return False

			my_stk, aset_evlt_amt, _ = await asyncio.get_event_loop().run_in_executor(
				None, fn_kt00004, False, 'N', '', self.token
			)
			if my_stk is None:
				total_assets = float(entry)
			else:
				stk_evlt_sum = sum(float(s.get('evlt_amt', '0') or '0') for s in my_stk) if my_stk else 0
				cash_val = float(aset_evlt_amt) if aset_evlt_amt and aset_evlt_amt != '0' else float(entry)
				total_assets = cash_val + stk_evlt_sum

			buy_ratio  = get_setting('buy_ratio', 8.0)
			buy_amount = total_assets * (buy_ratio / 100.0)
			ord_qty    = int(buy_amount / current_price)

			log.info(f'[매수 시도] {stk_cd} | 현재가={current_price:.0f} | 총자산={total_assets:,.0f} | 매수금액={buy_amount:,.0f} | 수량={ord_qty}')

			if ord_qty <= 0:
				log.warning(f'[매수] {stk_cd} 수량 0 - 매수 취소 (총자산={total_assets:,.0f}, 현재가={current_price:.0f})')
				tel_send(f"❌ 매수 취소: {stk_cd} (수량 0 — 총자산 {total_assets:,.0f}원 / 현재가 {int(current_price):,}원)")
				return False

			result = await asyncio.get_event_loop().run_in_executor(
				None, fn_kt10000, stk_cd, str(ord_qty), '', 'N', '', self.token
			)

			if result == 0:
				stk_nm = self.selected_stocks_names.get(stk_cd, stk_cd)
				self.entry_time[stk_cd] = datetime.datetime.now()
				if snapshot:
					self.entry_snapshot[stk_cd] = snapshot
				log.info(f'[매수 완료] {stk_nm}({stk_cd}) {ord_qty}주')
				msg = f"{signal_info}\n🟢 {stk_nm}({stk_cd}) {ord_qty}주 매수 완료\n   가격: {int(current_price):,}원 | 총자산: {int(total_assets):,}원 기준"
				tel_send(msg)
				return True
			else:
				log.error(f'[매수 실패] {stk_cd} API 결과={result}')
				tel_send(f"{signal_info}\n❌ 매수 실패: {stk_cd} (API 결과={result})")
				return False

		except Exception as e:
			log.error(f'[매수 오류] {stk_cd}: {e}', exc_info=True)
			return False
