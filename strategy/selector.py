import asyncio
from api.chart import fn_ka10080
from api.ranking import fn_ka10023, fn_ka10032
from api.foreign import fn_ka90009
from api.account import fn_kt00004
from util.market_hour import MarketHour
from util.get_setting import get_setting
from util.tel_send import tel_send
from util.logger import get_logger


class StockSelectorMixin:
	EXCLUDE_KEYWORDS = [
		'ETF', 'ETN', '레버리지', '인버스',
		'2X', '3X', '선물', '채권', 'TR',
		'액티브', '합성', '커버드콜',
		'스팩', 'SPAC', '미국', '차이나',
		'KODEX', 'TIGER', 'ARIRANG',
		'RISE', 'KBSTAR', 'SOL', 'HANARO', 'ACE',
	]

	STOCK_REFRESH_INTERVAL       =  5 * 60  # 장 중반/후반 종목 갱신 주기: 5분
	EARLY_STOCK_REFRESH_INTERVAL =  2 * 60  # 장 초반 종목 갱신 주기: 2분

	def _is_excluded(self, stk_nm):
		return any(kw in stk_nm for kw in self.EXCLUDE_KEYWORDS)

	def _phase_name(self, phase):
		return {'early': '장 초반', 'mid': '장 중반', 'late': '장 후반'}.get(phase, phase)

	def _fmt_stocks(self, stock_codes):
		"""종목 코드 리스트를 '종목명(코드)' 형식의 문자열로 변환"""
		return ', '.join(
			f"{self.selected_stocks_names.get(c, c)}({c})" for c in stock_codes
		)

	async def _get_exclusion_set(self):
		"""보유 종목 + 당일 2회 이상 손절 종목 코드 set 반환"""
		excluded = {cd for cd, cnt in self.daily_loss_count.items() if cnt >= 2}
		try:
			my_stk, _, _ = await asyncio.get_event_loop().run_in_executor(
				None, fn_kt00004, False, 'N', '', self.token
			)
			if my_stk:
				for s in my_stk:
					cd = s.get('stk_cd', '').replace('A', '').strip()
					if cd:
						excluded.add(cd)
		except Exception:
			pass
		return excluded

	async def _fetch_stocks_by_phase(self, phase):
		"""phase에 따라 종목 후보 리스트를 반환
		공통 흐름: API 대량 조회 → ETF/ETN 제거 → 1차 필터 → 차트 필터+스코어링 → top N (부족 시 fallback)
		"""
		stock_count = get_setting('stock_count', 10)
		chart_long  = get_setting('chart_long', 20)
		rsi_period  = 14
		needed      = max(chart_long + 1, rsi_period + 2)

		if phase == 'early':
			# ── 1. API 조회 (30개) ────────────────────────────
			raw = await asyncio.get_event_loop().run_in_executor(
				None, fn_ka10032, 30, 'N', '', self.token
			)
			if not raw:
				return []

			# ── 2. ETF/ETN 제거 + 과열 제외 ─────────────────────
			raw = [s for s in raw if not self._is_excluded(s.get('stk_nm', ''))]
			raw = [s for s in raw if s.get('flu_rt', 0) <= 25]

			# ── 3. 1차 필터: 거래대금 ≥ 700억, 등락률 ≥ -1.5% ──
			filtered = [
				s for s in raw
				if s.get('trde_prica', 0) >= 70000  # 백만원 단위, 700억
				and s.get('flu_rt', 0) >= -1.5
			]
			pool = filtered if filtered else raw

			# 거래대금 rank(1=최상위, 이미 정렬됨), 등락률 rank 계산
			n = len(pool)
			flu_sorted_idx = sorted(range(n), key=lambda i: pool[i].get('flu_rt', 0), reverse=True)
			flu_rank = {pool[i]['stk_cd']: rank + 1 for rank, i in enumerate(flu_sorted_idx)}

			def early_score(stk_cd, trade_rank):
				# 선형 rank: 1등이 n-1점, n등이 0점 → 순위 차이 균등 반영
				r_flu = flu_rank.get(stk_cd, n)
				return (n - trade_rank) * 0.6 + (n - r_flu) * 0.4

			# ── 4. 차트: 현재가 > 시가 필터 + rank 기반 스코어링 ──
			scored = []
			for trade_rank, s in enumerate(pool, start=1):
				prices, _, open_prices, _ = await asyncio.get_event_loop().run_in_executor(
					None, fn_ka10080, s['stk_cd'], needed, 'N', '', self.token
				)
				await asyncio.sleep(0.3)
				if not prices or len(prices) < 2:
					continue
				today_open = open_prices[-1] if open_prices and open_prices[-1] > 0 else 0
				if today_open > 0 and prices[0] <= today_open * 0.99:
					continue
				scored.append({**s, 'score': early_score(s['stk_cd'], trade_rank)})

			if not scored:
				# fallback: 차트 없이 rank 기반 정렬 후 상위 반환
				fb = [{**s, 'score': early_score(s['stk_cd'], i + 1)} for i, s in enumerate(pool)]
				return sorted(fb, key=lambda x: x['score'], reverse=True)[:stock_count]

			scored.sort(key=lambda x: x['score'], reverse=True)
			return scored[:stock_count]

		else:  # mid / late
			# ── 1. API 조회 (50개) ────────────────────────────
			raw = await asyncio.get_event_loop().run_in_executor(
				None, fn_ka10023, 50, 'N', '', self.token
			)
			if not raw:
				return []

			# ── 2. ETF/ETN 제거 + 과열 제외 ─────────────────────
			raw = [s for s in raw if not self._is_excluded(s.get('stk_nm', ''))]
			raw = [s for s in raw if s.get('flu_rt', 0) <= 25]

			# ── 3. 1차 필터 (완화): 등락률 ≥ +0.3%, 거래량급증률 ≥ 120% ──
			filtered = [
				s for s in raw
				if s.get('flu_rt', 0) >= 0.3
				and s.get('sdnin_rt', 0) >= 120
			]
			pool = filtered if filtered else raw

			# ── 4. 기관/외인 조회 ────────────────────────────
			buy_stocks = await asyncio.get_event_loop().run_in_executor(
				None, fn_ka90009, 'N', '', self.token
			)

			# ── 5. 차트: MA20 필터(late만 적용) → 후보 수집 ─────────
			candidates = []
			for s in pool:
				prices, _, _, _ = await asyncio.get_event_loop().run_in_executor(
					None, fn_ka10080, s['stk_cd'], needed, 'N', '', self.token
				)
				await asyncio.sleep(0.3)
				if not prices or len(prices) < needed:
					continue

				current_price = prices[0]
				ma20 = self._calc_ma(prices, chart_long)
				rsi  = self._calc_rsi(prices, rsi_period)

				if phase == 'late' and (ma20 is None or current_price <= ma20):
					continue

				candidates.append({
					**s,
					'rsi_val':    rsi if rsi is not None else 50.0,
					'is_foreign': bool(buy_stocks and s['stk_cd'] in buy_stocks),
				})

			# ── 6. 동적 정규화 후 스코어 계산 ────────────────────
			scored = []
			if candidates:
				sdnin_list = [c.get('sdnin_rt', 0) for c in candidates]
				flu_list   = [c.get('flu_rt', 0)   for c in candidates]
				max_sdnin  = max(sdnin_list) or 1
				max_flu    = max(flu_list)
				min_flu    = min(flu_list)
				flu_range  = (max_flu - min_flu) or 1

				for c in candidates:
					volume_norm   = c.get('sdnin_rt', 0) / max_sdnin
					flu_norm      = (c.get('flu_rt', 0) - min_flu) / flu_range
					rsi_norm      = c['rsi_val'] / 100
					foreign_score = 1.0 if c['is_foreign'] else 0.0

					score = (
						volume_norm   * 0.4 +
						flu_norm      * 0.3 +
						rsi_norm      * 0.2 +
						foreign_score * 0.1
					)
					scored.append({
						**{k: v for k, v in c.items() if k not in ('rsi_val',)},
						'score': score,
						'rsi':   round(c['rsi_val'], 1),
					})

			scored.sort(key=lambda x: x['score'], reverse=True)

			# scored가 stock_count 미달이면 fallback으로 보충 (최소 조건: 상승 종목만)
			if len(scored) < stock_count:
				scored_cds = {s['stk_cd'] for s in scored}
				fb_pool = [
					s for s in pool
					if s['stk_cd'] not in scored_cds and s.get('flu_rt', 0) > 0
				]
				if fb_pool:
					fb_sdnin     = [s.get('sdnin_rt', 0) for s in fb_pool]
					fb_flu       = [s.get('flu_rt', 0)   for s in fb_pool]
					fb_max_sdnin = max(fb_sdnin) or 1
					fb_max_flu   = max(fb_flu)
					fb_min_flu   = min(fb_flu)
					fb_flu_range = (fb_max_flu - fb_min_flu) or 1

					fb = []
					for s in fb_pool:
						volume_norm = s.get('sdnin_rt', 0) / fb_max_sdnin
						flu_norm    = (s.get('flu_rt', 0) - fb_min_flu) / fb_flu_range
						score = volume_norm * 0.6 + flu_norm * 0.4
						fb.append({**s, 'score': score})
					fb.sort(key=lambda x: x['score'], reverse=True)
					scored += fb[:stock_count - len(scored)]

			return scored[:stock_count]

	async def _select_initial_stocks(self):
		"""장 시작 후 최초 종목 선정 (phase 기반)"""
		phase = MarketHour.get_market_phase()
		# 장 후반에 start된 경우 mid 로직으로 1회 선정
		if phase == 'late':
			phase = 'mid'

		ranked_stocks = await self._fetch_stocks_by_phase(phase)
		if not ranked_stocks:
			tel_send(f"⚠️ [{self._phase_name(phase)}] 종목 선정 실패 - 다음 갱신 주기에 재시도합니다")
			return False

		exclusion_set = await self._get_exclusion_set()
		if exclusion_set:
			before = len(ranked_stocks)
			ranked_stocks = [s for s in ranked_stocks if s['stk_cd'] not in exclusion_set]
			if len(ranked_stocks) < before:
				get_logger().info(f'[종목선정] 제외: {exclusion_set} ({before}→{len(ranked_stocks)}개)')

		self.selected_stocks = [s['stk_cd'] for s in ranked_stocks]
		self.selected_stocks_names = {s['stk_cd']: s.get('stk_nm', s['stk_cd']) for s in ranked_stocks}
		self.selected_stocks_meta = {
			s['stk_cd']: {
				'flu_rt':     s.get('flu_rt', 0),
				'score':      s.get('score', 0),
				'is_foreign': s.get('is_foreign', False),
			} for s in ranked_stocks
		}

		chart_long  = get_setting('chart_long', 20)
		phase_strategy = {
			'early': f"직전 3봉 고점 돌파 확인(2.5초) + 거래량≥1.5x + 시가×0.99↑ + RSI 40~70 | 손절 -2% / 트레일링 2%",
			'mid':   f"직전 5봉 고점 돌파 확인(3초) + RSI 45~70 + RSI상승 | 손절 -3% / 트레일링 3.5%",
			'late':  f"직전 5봉 고점 돌파 확인(3초) + 거래량↑ + RSI 50~60 + RSI상승 + MA{chart_long}↑ | 손절 -3% / 트레일링 2.5%",
		}
		tel_send(
			f"✅ [{self._phase_name(phase)}] 초기 종목 선정 완료\n"
			f"   전략: {phase_strategy.get(phase, '')}\n"
			f"   종목: {self._fmt_stocks(self.selected_stocks)}"
		)
		return True

	async def _refresh_selected_stocks(self, phase=None):
		"""종목 갱신 (초반 2분 / 중반·후반 5분 주기) — 전 phase 점수 비교 후 선택적 교체"""
		try:
			if phase is None:
				phase = MarketHour.get_market_phase()

			ranked_stocks = await self._fetch_stocks_by_phase(phase)
			if not ranked_stocks:
				tel_send(f"⚠️ [{self._phase_name(phase)}] 종목 갱신 실패 - 기존 종목 유지")
				return

			exclusion_set = await self._get_exclusion_set()
			stock_count   = get_setting('stock_count', 10)

			# 새로 조회된 후보 맵 (제외 종목 필터링)
			new_map = {s['stk_cd']: s for s in ranked_stocks if s['stk_cd'] not in exclusion_set}

			# ── 점수 비교 기반 병합 ───────────────────────────────
			# 기존 선정 종목: 새 점수로 갱신 or 기존 점수 유지 (한 사이클 버팀)
			merged_pool = {}
			for cd in self.selected_stocks:
				if cd in exclusion_set:
					continue
				if cd in new_map:
					merged_pool[cd] = new_map[cd]           # 새 점수로 갱신
				else:
					old = self.selected_stocks_meta.get(cd, {})
					merged_pool[cd] = {                     # 기존 점수 유지
						'stk_cd':     cd,
						'stk_nm':     self.selected_stocks_names.get(cd, cd),
						'score':      old.get('score', 0),
						'flu_rt':     old.get('flu_rt', 0),
						'is_foreign': old.get('is_foreign', False),
					}

			# 신규 후보: 기존에 없던 종목만 추가
			for cd, s in new_map.items():
				if cd not in merged_pool:
					merged_pool[cd] = s

			# 점수 기준 상위 stock_count 선정
			final_stocks = sorted(merged_pool.values(), key=lambda x: x['score'], reverse=True)[:stock_count]
			new_stocks   = [s['stk_cd'] for s in final_stocks]
			new_names    = {s['stk_cd']: s.get('stk_nm', s['stk_cd']) for s in final_stocks}
			new_meta     = {
				s['stk_cd']: {
					'flu_rt':     s.get('flu_rt', 0),
					'score':      s.get('score', 0),
					'is_foreign': s.get('is_foreign', False),
				} for s in final_stocks
			}

			added   = [s for s in new_stocks if s not in self.selected_stocks]
			removed = [s for s in self.selected_stocks if s not in new_stocks]

			# state 업데이트 전에 메시지 빌드 (편출 종목의 old 점수 접근)
			final_map = {s['stk_cd']: s for s in final_stocks}

			def _with_score(codes, src):
				parts = []
				for cd in codes:
					nm    = src.get(cd, {}).get('stk_nm') or self.selected_stocks_names.get(cd, cd)
					score = src.get(cd, {}).get('score', 0)
					parts.append(f"{nm}({cd}, {score:.2f})")
				return ', '.join(parts)

			if added or removed:
				msg = f"🔄 [{self._phase_name(phase)}] 종목 갱신\n"
				if added:
					msg += f"   신규 편입: {_with_score(added, final_map)}\n"
				if removed:
					msg += f"   편출: {_with_score(removed, self.selected_stocks_meta)}\n"
				msg += f"   현재 선정: {self._fmt_stocks(new_stocks)}"
			else:
				msg = f"🔄 [{self._phase_name(phase)}] 종목 유지 (점수 기준 변경 없음)\n   선정 종목: {self._fmt_stocks(new_stocks)}"

			self.selected_stocks_names.update(new_names)
			self.selected_stocks_meta = new_meta
			self.selected_stocks      = new_stocks

			tel_send(msg)

		except Exception as e:
			print(f"종목 갱신 오류: {e}")
			tel_send(f"⚠️ 종목 갱신 중 오류: {e} - 기존 종목 유지")
